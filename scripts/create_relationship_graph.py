from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_DIR = ROOT / "backend" / "app" / "data" / "dummy_db"
SCHEMAS = ("clients", "content", "media", "analytics", "jx_bridge", "general", "world", "users", "organizations", "entity")


def connect(db_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_dir / "main.sqlite3")
    conn.row_factory = sqlite3.Row
    for schema in SCHEMAS:
        conn.execute(f"ATTACH DATABASE '{(db_dir / f'{schema}.sqlite3').as_posix()}' AS {schema}")
    return conn


def ensure_graph_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity.entity (
            id INTEGER PRIMARY KEY,
            entity_type TEXT NOT NULL,
            node_key TEXT NOT NULL UNIQUE,
            source_table TEXT NOT NULL,
            source_pk TEXT NOT NULL,
            client_id INTEGER,
            name TEXT,
            description TEXT,
            metadata TEXT,
            inserted_datetime TEXT,
            updated_datetime TEXT,
            deleted_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity.entity_relationship (
            id INTEGER PRIMARY KEY,
            from_entity_id INTEGER NOT NULL,
            to_entity_id INTEGER NOT NULL,
            relationship_type TEXT NOT NULL,
            source_table TEXT,
            source_pk TEXT,
            client_id INTEGER,
            weight REAL,
            metadata TEXT,
            inserted_datetime TEXT,
            deleted_at TEXT,
            UNIQUE(from_entity_id, to_entity_id, relationship_type, source_table, source_pk)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity.entity_facility_brand (
            id INTEGER PRIMARY KEY,
            entity_id INTEGER,
            client_id INTEGER,
            brand_name TEXT,
            deleted_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity.entity_facility_sub_brand (
            id INTEGER PRIMARY KEY,
            entity_id INTEGER,
            client_id INTEGER,
            sub_brand_name TEXT,
            deleted_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS entity.idx_entity_client_type ON entity(client_id, entity_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS entity.idx_relationship_client_type ON entity_relationship(client_id, relationship_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS entity.idx_relationship_from ON entity_relationship(from_entity_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS entity.idx_relationship_to ON entity_relationship(to_entity_id)")


def reset_graph(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM entity.entity_relationship")
    conn.execute("DELETE FROM entity.entity_facility_brand")
    conn.execute("DELETE FROM entity.entity_facility_sub_brand")
    conn.execute("DELETE FROM entity.entity")


class GraphBuilder:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.now = datetime.now(timezone.utc).isoformat()
        self.node_ids: dict[str, int] = {}

    def node(
        self,
        *,
        node_key: str,
        entity_type: str,
        source_table: str,
        source_pk: Any,
        name: str,
        client_id: int | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if node_key in self.node_ids:
            return self.node_ids[node_key]
        cursor = self.conn.execute(
            """
            INSERT INTO entity.entity
            (entity_type, node_key, source_table, source_pk, client_id, name, description, metadata,
             inserted_datetime, updated_datetime, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                entity_type,
                node_key,
                source_table,
                str(source_pk),
                client_id,
                name,
                description,
                json.dumps(metadata or {}, ensure_ascii=False),
                self.now,
                self.now,
            ),
        )
        entity_id = int(cursor.lastrowid)
        self.node_ids[node_key] = entity_id
        return entity_id

    def edge(
        self,
        from_entity_id: int,
        to_entity_id: int,
        relationship_type: str,
        *,
        client_id: int | None = None,
        source_table: str | None = None,
        source_pk: Any | None = None,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO entity.entity_relationship
            (from_entity_id, to_entity_id, relationship_type, source_table, source_pk, client_id, weight,
             metadata, inserted_datetime, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                from_entity_id,
                to_entity_id,
                relationship_type,
                source_table,
                str(source_pk) if source_pk is not None else None,
                client_id,
                weight,
                json.dumps(metadata or {}, ensure_ascii=False),
                self.now,
            ),
        )


def build_client_identity_graph(conn: sqlite3.Connection, graph: GraphBuilder) -> None:
    rows = conn.execute(
        """
        SELECT
          c.id AS client_id,
          c.name AS client_name,
          c.organization_id,
          o.name AS organization_name,
          c.world_city_id,
          wc.name AS city_name
        FROM clients.clients c
        LEFT JOIN organizations.organizations o ON o.id = c.organization_id
        LEFT JOIN world.cities wc ON wc.id = c.world_city_id
        WHERE c.deleted_at IS NULL
        """
    ).fetchall()
    for row in rows:
        client_id = int(row["client_id"])
        client_node = graph.node(
            node_key=f"client:{client_id}",
            entity_type="Client",
            source_table="clients.clients",
            source_pk=client_id,
            client_id=client_id,
            name=row["client_name"],
        )
        conn.execute(
            "INSERT INTO entity.entity_facility_brand (entity_id, client_id, brand_name, deleted_at) VALUES (?, ?, ?, NULL)",
            (client_node, client_id, row["client_name"]),
        )
        conn.execute(
            "INSERT INTO entity.entity_facility_sub_brand (entity_id, client_id, sub_brand_name, deleted_at) VALUES (?, ?, ?, NULL)",
            (client_node, client_id, f"{row['client_name']} dummy sub-brand"),
        )
        if row["organization_id"] is not None:
            org_id = int(row["organization_id"])
            org_node = graph.node(
                node_key=f"organization:{org_id}",
                entity_type="Organization",
                source_table="organizations.organizations",
                source_pk=org_id,
                name=row["organization_name"] or f"Organization {org_id}",
            )
            graph.edge(client_node, org_node, "BELONGS_TO_ORGANIZATION", client_id=client_id, source_table="clients.clients", source_pk=client_id)
        if row["world_city_id"] is not None:
            city_id = int(row["world_city_id"])
            city_node = graph.node(
                node_key=f"city:{city_id}",
                entity_type="City",
                source_table="world.cities",
                source_pk=city_id,
                name=row["city_name"] or f"City {city_id}",
            )
            graph.edge(client_node, city_node, "LOCATED_IN", client_id=client_id, source_table="clients.clients", source_pk=client_id)


def build_access_graph(conn: sqlite3.Connection, graph: GraphBuilder) -> None:
    rows = conn.execute(
        """
        SELECT cc.id, cc.client_id, cc.user_id, cc.access_level, u.full_name
        FROM clients.clients_collaborators cc
        JOIN users.users u ON u.id = cc.user_id
        WHERE cc.deleted_at IS NULL
          AND cc.enabled = 1
          AND u.deleted_at IS NULL
        """
    ).fetchall()
    for row in rows:
        client_id = int(row["client_id"])
        client_node = graph.node(node_key=f"client:{client_id}", entity_type="Client", source_table="clients.clients", source_pk=client_id, client_id=client_id, name=f"Client {client_id}")
        user_id = int(row["user_id"])
        user_node = graph.node(node_key=f"user:{user_id}", entity_type="User", source_table="users.users", source_pk=user_id, name=row["full_name"] or f"User {user_id}")
        graph.edge(client_node, user_node, "HAS_COLLABORATOR", client_id=client_id, source_table="clients.clients_collaborators", source_pk=row["id"], metadata={"access_level": row["access_level"]})

    rows = conn.execute(
        """
        SELECT ou.id, ou.organization_id, ou.user_id, ou.role, o.name AS organization_name, u.full_name, c.id AS client_id
        FROM organizations.organization_users ou
        JOIN organizations.organizations o ON o.id = ou.organization_id
        JOIN users.users u ON u.id = ou.user_id
        LEFT JOIN clients.clients c ON c.organization_id = ou.organization_id
        WHERE ou.deleted_at IS NULL
        """
    ).fetchall()
    for row in rows:
        org_id = int(row["organization_id"])
        user_id = int(row["user_id"])
        org_node = graph.node(node_key=f"organization:{org_id}", entity_type="Organization", source_table="organizations.organizations", source_pk=org_id, name=row["organization_name"] or f"Organization {org_id}")
        user_node = graph.node(node_key=f"user:{user_id}", entity_type="User", source_table="users.users", source_pk=user_id, name=row["full_name"] or f"User {user_id}")
        scoped_client_id = int(row["client_id"]) if row["client_id"] is not None else None
        graph.edge(org_node, user_node, "HAS_ORGANIZATION_MEMBER", client_id=scoped_client_id, source_table="organizations.organization_users", source_pk=row["id"], metadata={"role": row["role"]})


def build_market_comparable_graph(conn: sqlite3.Connection, graph: GraphBuilder) -> None:
    if not _table_exists(conn, "clients", "client_marketing_settings"):
        return

    rows = conn.execute(
        """
        WITH client_markets AS (
          SELECT
            c.id AS client_id,
            c.name AS client_name,
            c.organization_id,
            c.world_city_id,
            wc.name AS city_name,
            cms.id AS marketing_settings_id,
            cms.property_type,
            cms.average_default_rate,
            cms.conversion,
            cms.average_length_of_stay
          FROM clients.clients c
          LEFT JOIN world.cities wc ON wc.id = c.world_city_id
          LEFT JOIN clients.client_marketing_settings cms
            ON cms.client_id = c.id
           AND cms.deleted_at IS NULL
          WHERE c.deleted_at IS NULL
        )
        SELECT
          target.client_id,
          target.client_name,
          target.city_name,
          target.property_type,
          target.average_default_rate,
          competitor.client_id AS competitor_client_id,
          competitor.client_name AS competitor_name,
          competitor.city_name AS competitor_city_name,
          competitor.property_type AS competitor_property_type,
          competitor.average_default_rate AS competitor_average_default_rate,
          competitor.marketing_settings_id AS competitor_marketing_settings_id,
          CASE WHEN competitor.world_city_id = target.world_city_id THEN 1 ELSE 0 END AS same_city,
          CASE
            WHEN LOWER(COALESCE(competitor.property_type, '')) = LOWER(COALESCE(target.property_type, ''))
             AND COALESCE(target.property_type, '') <> ''
            THEN 1 ELSE 0
          END AS same_property_type,
          CASE
            WHEN target.average_default_rate IS NOT NULL
             AND competitor.average_default_rate IS NOT NULL
             AND target.average_default_rate > 0
             AND ABS(CAST(competitor.average_default_rate AS REAL) - CAST(target.average_default_rate AS REAL))
                 <= CAST(target.average_default_rate AS REAL) * 0.30
            THEN 1 ELSE 0
          END AS similar_rate_band,
          (
            CASE WHEN competitor.world_city_id = target.world_city_id THEN 45 ELSE 0 END
            + CASE
                WHEN LOWER(COALESCE(competitor.property_type, '')) = LOWER(COALESCE(target.property_type, ''))
                 AND COALESCE(target.property_type, '') <> ''
                THEN 30 ELSE 0
              END
            + CASE
                WHEN target.average_default_rate IS NOT NULL
                 AND competitor.average_default_rate IS NOT NULL
                 AND target.average_default_rate > 0
                 AND ABS(CAST(competitor.average_default_rate AS REAL) - CAST(target.average_default_rate AS REAL))
                     <= CAST(target.average_default_rate AS REAL) * 0.30
                THEN 20 ELSE 0
              END
            + CASE WHEN COALESCE(competitor.organization_id, -1) <> COALESCE(target.organization_id, -1) THEN 5 ELSE 0 END
          ) AS comparable_score
        FROM client_markets target
        JOIN client_markets competitor
          ON competitor.client_id <> target.client_id
        WHERE (
          competitor.world_city_id = target.world_city_id
          OR (
            LOWER(COALESCE(competitor.property_type, '')) = LOWER(COALESCE(target.property_type, ''))
            AND COALESCE(target.property_type, '') <> ''
          )
          OR (
            target.average_default_rate IS NOT NULL
            AND competitor.average_default_rate IS NOT NULL
            AND target.average_default_rate > 0
            AND ABS(CAST(competitor.average_default_rate AS REAL) - CAST(target.average_default_rate AS REAL))
                <= CAST(target.average_default_rate AS REAL) * 0.30
          )
        )
        ORDER BY target.client_id, comparable_score DESC
        """
    ).fetchall()

    for row in rows:
        client_id = int(row["client_id"])
        competitor_id = int(row["competitor_client_id"])
        client_node = graph.node(
            node_key=f"client:{client_id}",
            entity_type="Client",
            source_table="clients.clients",
            source_pk=client_id,
            client_id=client_id,
            name=row["client_name"] or f"Client {client_id}",
        )
        competitor_node = graph.node(
            node_key=f"client:{competitor_id}",
            entity_type="Client",
            source_table="clients.clients",
            source_pk=competitor_id,
            client_id=competitor_id,
            name=row["competitor_name"] or f"Client {competitor_id}",
        )
        score = float(row["comparable_score"] or 0)
        graph.edge(
            client_node,
            competitor_node,
            "HAS_COMPARABLE_CLIENT",
            client_id=client_id,
            source_table="clients.client_marketing_settings",
            source_pk=f"{client_id}:{competitor_id}",
            weight=round(score / 100, 3),
            metadata={
                "relationship_basis": "inferred comparable, not official competitor set",
                "same_city": bool(row["same_city"]),
                "same_property_type": bool(row["same_property_type"]),
                "similar_rate_band": bool(row["similar_rate_band"]),
                "target_city": row["city_name"],
                "target_property_type": row["property_type"],
                "target_average_default_rate": row["average_default_rate"],
                "competitor_city": row["competitor_city_name"],
                "competitor_property_type": row["competitor_property_type"],
                "competitor_average_default_rate": row["competitor_average_default_rate"],
                "comparable_score": score,
            },
        )


def build_client_knowledge_graph(conn: sqlite3.Connection, graph: GraphBuilder) -> None:
    note_rows = conn.execute(
        """
        SELECT cn.id, cn.client_id, cn.title, cn.note
        FROM clients.client_notes cn
        WHERE cn.deleted_at IS NULL
        """
    ).fetchall()
    for row in note_rows:
        client_id = int(row["client_id"])
        client_node = graph.node(node_key=f"client:{client_id}", entity_type="Client", source_table="clients.clients", source_pk=client_id, client_id=client_id, name=f"Client {client_id}")
        note_node = graph.node(
            node_key=f"client_note:{row['id']}",
            entity_type="ClientNote",
            source_table="clients.client_notes",
            source_pk=row["id"],
            client_id=client_id,
            name=row["title"] or f"Client note {row['id']}",
            description=row["note"],
        )
        graph.edge(client_node, note_node, "HAS_CLIENT_NOTE", client_id=client_id, source_table="clients.client_notes", source_pk=row["id"])

    detail_rows = conn.execute("SELECT id, client_id, overview FROM clients.property_details WHERE deleted_at IS NULL").fetchall()
    for row in detail_rows:
        client_id = int(row["client_id"])
        client_node = graph.node(node_key=f"client:{client_id}", entity_type="Client", source_table="clients.clients", source_pk=client_id, client_id=client_id, name=f"Client {client_id}")
        detail_node = graph.node(node_key=f"property_detail:{row['id']}", entity_type="PropertyDetail", source_table="clients.property_details", source_pk=row["id"], client_id=client_id, name=f"Property detail {row['id']}", description=row["overview"])
        graph.edge(client_node, detail_node, "HAS_PROPERTY_DETAIL", client_id=client_id, source_table="clients.property_details", source_pk=row["id"])

    rows = conn.execute("SELECT id, client_id, audience FROM clients.client_target_audience WHERE deleted_at IS NULL").fetchall()
    for row in rows:
        client_id = int(row["client_id"])
        client_node = graph.node(node_key=f"client:{client_id}", entity_type="Client", source_table="clients.clients", source_pk=client_id, client_id=client_id, name=f"Client {client_id}")
        audience_node = graph.node(node_key=f"audience:{row['id']}", entity_type="Audience", source_table="clients.client_target_audience", source_pk=row["id"], client_id=client_id, name=row["audience"])
        graph.edge(client_node, audience_node, "HAS_TARGET_AUDIENCE", client_id=client_id, source_table="clients.client_target_audience", source_pk=row["id"])


def build_content_media_analytics_graph(conn: sqlite3.Connection, graph: GraphBuilder) -> None:
    topic_rows = conn.execute("SELECT id, client_id, name FROM content.content_topic WHERE deleted_at IS NULL").fetchall()
    for row in topic_rows:
        client_id = int(row["client_id"])
        client_node = graph.node(node_key=f"client:{client_id}", entity_type="Client", source_table="clients.clients", source_pk=client_id, client_id=client_id, name=f"Client {client_id}")
        topic_node = graph.node(node_key=f"content_topic:{row['id']}", entity_type="ContentTopic", source_table="content.content_topic", source_pk=row["id"], client_id=client_id, name=row["name"] or f"Topic {row['id']}")
        graph.edge(client_node, topic_node, "HAS_CONTENT_TOPIC", client_id=client_id, source_table="content.content_topic", source_pk=row["id"])

    post_rows = conn.execute(
        """
        SELECT ctp.id, ct.client_id, ctp.content_topic_id, ctp.social_network_type_id, ctp.content_post_status_id,
               ctp.network_post_ref, ctp.post_datetime, ctp.post_text, snt.description AS network, cps.description AS status
        FROM content.content_topic_post ctp
        JOIN content.content_topic ct ON ct.id = ctp.content_topic_id
        LEFT JOIN general.social_network_type snt ON snt.id = ctp.social_network_type_id
        LEFT JOIN content.content_post_status cps ON cps.id = ctp.content_post_status_id
        WHERE ctp.deleted_at IS NULL
        """
    ).fetchall()
    for row in post_rows:
        client_id = int(row["client_id"])
        topic_node = graph.node(node_key=f"content_topic:{row['content_topic_id']}", entity_type="ContentTopic", source_table="content.content_topic", source_pk=row["content_topic_id"], client_id=client_id, name=f"Topic {row['content_topic_id']}")
        post_node = graph.node(node_key=f"post:{row['id']}", entity_type="Post", source_table="content.content_topic_post", source_pk=row["id"], client_id=client_id, name=f"{row['network'] or 'social'} post {row['id']}", description=row["post_text"], metadata={"post_datetime": row["post_datetime"], "network_post_ref": row["network_post_ref"], "status": row["status"]})
        graph.edge(topic_node, post_node, "HAS_POST", client_id=client_id, source_table="content.content_topic_post", source_pk=row["id"])
        if row["social_network_type_id"] is not None:
            network_id = int(row["social_network_type_id"])
            network_node = graph.node(node_key=f"network:{network_id}", entity_type="SocialNetwork", source_table="general.social_network_type", source_pk=network_id, name=row["network"] or f"Network {network_id}")
            graph.edge(post_node, network_node, "PUBLISHED_ON_NETWORK", client_id=client_id, source_table="content.content_topic_post", source_pk=row["id"])
        if row["content_post_status_id"] is not None:
            status_id = int(row["content_post_status_id"])
            status_node = graph.node(node_key=f"post_status:{status_id}", entity_type="PostStatus", source_table="content.content_post_status", source_pk=status_id, name=row["status"] or f"Status {status_id}")
            graph.edge(post_node, status_node, "HAS_POST_STATUS", client_id=client_id, source_table="content.content_topic_post", source_pk=row["id"])

    media_rows = conn.execute("SELECT id, client_id, name, description FROM media.media WHERE deleted_at IS NULL").fetchall()
    for row in media_rows:
        client_id = int(row["client_id"])
        client_node = graph.node(node_key=f"client:{client_id}", entity_type="Client", source_table="clients.clients", source_pk=client_id, client_id=client_id, name=f"Client {client_id}")
        media_node = graph.node(node_key=f"media:{row['id']}", entity_type="Media", source_table="media.media", source_pk=row["id"], client_id=client_id, name=row["name"] or f"Media {row['id']}", description=row["description"])
        graph.edge(client_node, media_node, "HAS_MEDIA_ASSET", client_id=client_id, source_table="media.media", source_pk=row["id"])

    rows = conn.execute(
        """
        SELECT ctpm.id, ct.client_id, ctpm.content_topic_post_id, ctpm.media_id, m.name AS media_name
        FROM content.content_topic_post_media ctpm
        JOIN content.content_topic_post ctp ON ctp.id = ctpm.content_topic_post_id
        JOIN content.content_topic ct ON ct.id = ctp.content_topic_id
        LEFT JOIN media.media m ON m.id = ctpm.media_id
        WHERE ctpm.deleted_at IS NULL
        """
    ).fetchall()
    for row in rows:
        client_id = int(row["client_id"])
        post_node = graph.node(node_key=f"post:{row['content_topic_post_id']}", entity_type="Post", source_table="content.content_topic_post", source_pk=row["content_topic_post_id"], client_id=client_id, name=f"Post {row['content_topic_post_id']}")
        media_node = graph.node(node_key=f"media:{row['media_id']}", entity_type="Media", source_table="media.media", source_pk=row["media_id"], client_id=client_id, name=row["media_name"] or f"Media {row['media_id']}")
        graph.edge(post_node, media_node, "USES_MEDIA", client_id=client_id, source_table="content.content_topic_post_media", source_pk=row["id"])

    rows = conn.execute("SELECT id, media_id, short_description FROM media.media_analysis_ai WHERE deleted_at IS NULL").fetchall()
    for row in rows:
        media_node = graph.node(node_key=f"media:{row['media_id']}", entity_type="Media", source_table="media.media", source_pk=row["media_id"], name=f"Media {row['media_id']}")
        analysis_node = graph.node(node_key=f"media_analysis:{row['id']}", entity_type="MediaAnalysis", source_table="media.media_analysis_ai", source_pk=row["id"], name=f"Media analysis {row['id']}", description=row["short_description"])
        graph.edge(media_node, analysis_node, "HAS_MEDIA_ANALYSIS", source_table="media.media_analysis_ai", source_pk=row["id"])

    rows = conn.execute(
        """
        SELECT asp.id, ct.client_id, ctp.id AS post_id, asp.post_ref, asp.identifier, asp.created_at
        FROM analytics.social_media_post asp
        JOIN content.content_topic_post ctp
          ON ctp.network_post_ref = asp.post_ref
          OR ctp.network_post_ref = asp.identifier
        JOIN content.content_topic ct ON ct.id = ctp.content_topic_id
        WHERE asp.deleted_at IS NULL
        """
    ).fetchall()
    for row in rows:
        client_id = int(row["client_id"])
        post_node = graph.node(node_key=f"post:{row['post_id']}", entity_type="Post", source_table="content.content_topic_post", source_pk=row["post_id"], client_id=client_id, name=f"Post {row['post_id']}")
        metric_node = graph.node(node_key=f"metric_snapshot:{row['id']}", entity_type="MetricSnapshot", source_table="analytics.social_media_post", source_pk=row["id"], client_id=client_id, name=f"Metric snapshot {row['post_ref'] or row['identifier']}", metadata={"created_at": row["created_at"]})
        graph.edge(post_node, metric_node, "HAS_ANALYTICS_SNAPSHOT", client_id=client_id, source_table="analytics.social_media_post", source_pk=row["id"])


def build_inbox_event_embedding_graph(conn: sqlite3.Connection, graph: GraphBuilder) -> None:
    rows = conn.execute("SELECT interaction_id, client_id, title FROM jx_bridge.interactions").fetchall()
    for row in rows:
        client_id = int(row["client_id"])
        client_node = graph.node(node_key=f"client:{client_id}", entity_type="Client", source_table="clients.clients", source_pk=client_id, client_id=client_id, name=f"Client {client_id}")
        interaction_node = graph.node(node_key=f"interaction:{row['interaction_id']}", entity_type="Interaction", source_table="jx_bridge.interactions", source_pk=row["interaction_id"], client_id=client_id, name=row["title"] or f"Interaction {row['interaction_id']}")
        graph.edge(client_node, interaction_node, "HAS_INTERACTION", client_id=client_id, source_table="jx_bridge.interactions", source_pk=row["interaction_id"])

    rows = conn.execute("SELECT message_id, client_id, interaction_id, content FROM jx_bridge.messages").fetchall()
    for row in rows:
        client_id = int(row["client_id"])
        interaction_node = graph.node(node_key=f"interaction:{row['interaction_id']}", entity_type="Interaction", source_table="jx_bridge.interactions", source_pk=row["interaction_id"], client_id=client_id, name=f"Interaction {row['interaction_id']}")
        message_node = graph.node(node_key=f"message:{row['message_id']}", entity_type="Message", source_table="jx_bridge.messages", source_pk=row["message_id"], client_id=client_id, name=f"Message {row['message_id']}", description=row["content"])
        graph.edge(interaction_node, message_node, "HAS_MESSAGE", client_id=client_id, source_table="jx_bridge.messages", source_pk=row["message_id"])

    rows = conn.execute(
        """
        SELECT e.id, e.world_city_id, e.name, e.date, c.id AS client_id
        FROM general.events e
        JOIN clients.clients c ON c.world_city_id = e.world_city_id
        WHERE e.deleted_at IS NULL
          AND c.deleted_at IS NULL
        """
    ).fetchall()
    for row in rows:
        client_id = int(row["client_id"])
        client_node = graph.node(node_key=f"client:{client_id}", entity_type="Client", source_table="clients.clients", source_pk=client_id, client_id=client_id, name=f"Client {client_id}")
        event_node = graph.node(node_key=f"event:{row['id']}", entity_type="Event", source_table="general.events", source_pk=row["id"], name=row["name"], metadata={"date": row["date"], "world_city_id": row["world_city_id"]})
        graph.edge(client_node, event_node, "HAS_NEARBY_EVENT", client_id=client_id, source_table="general.events", source_pk=row["id"])

    if _table_exists(conn, "general", "knowledge_embeddings"):
        rows = conn.execute("SELECT id, client_id, source_table, source_pk, source_kind, chunk_label FROM general.knowledge_embeddings").fetchall()
        for row in rows:
            client_id = int(row["client_id"])
            client_node = graph.node(node_key=f"client:{client_id}", entity_type="Client", source_table="clients.clients", source_pk=client_id, client_id=client_id, name=f"Client {client_id}")
            chunk_node = graph.node(node_key=f"knowledge_chunk:{row['id']}", entity_type="KnowledgeChunk", source_table="general.knowledge_embeddings", source_pk=row["id"], client_id=client_id, name=row["chunk_label"] or f"Knowledge chunk {row['id']}", metadata={"source_table": row["source_table"], "source_pk": row["source_pk"], "source_kind": row["source_kind"]})
            graph.edge(client_node, chunk_node, "HAS_KNOWLEDGE_CHUNK", client_id=client_id, source_table="general.knowledge_embeddings", source_pk=row["id"])

    if _table_exists(conn, "analytics", "metric_embeddings"):
        rows = conn.execute("SELECT id, client_id, source_pk, source_ref, source_kind FROM analytics.metric_embeddings").fetchall()
        for row in rows:
            client_id = int(row["client_id"])
            client_node = graph.node(node_key=f"client:{client_id}", entity_type="Client", source_table="clients.clients", source_pk=client_id, client_id=client_id, name=f"Client {client_id}")
            chunk_node = graph.node(node_key=f"metric_chunk:{row['id']}", entity_type="MetricChunk", source_table="analytics.metric_embeddings", source_pk=row["id"], client_id=client_id, name=f"Metric chunk {row['source_ref'] or row['source_pk']}", metadata={"source_pk": row["source_pk"], "source_ref": row["source_ref"], "source_kind": row["source_kind"]})
            graph.edge(client_node, chunk_node, "HAS_METRIC_CHUNK", client_id=client_id, source_table="analytics.metric_embeddings", source_pk=row["id"])


def _table_exists(conn: sqlite3.Connection, schema_name: str, table_name: str) -> bool:
    row = conn.execute(f"SELECT 1 FROM {schema_name}.sqlite_master WHERE type = 'table' AND name = ?", (table_name,)).fetchone()
    return row is not None


def main() -> int:
    conn = connect(DEFAULT_DB_DIR)
    ensure_graph_schema(conn)
    reset_graph(conn)
    graph = GraphBuilder(conn)
    build_client_identity_graph(conn, graph)
    build_access_graph(conn, graph)
    build_market_comparable_graph(conn, graph)
    build_client_knowledge_graph(conn, graph)
    build_content_media_analytics_graph(conn, graph)
    build_inbox_event_embedding_graph(conn, graph)
    conn.commit()
    node_count = conn.execute("SELECT COUNT(*) AS count FROM entity.entity").fetchone()["count"]
    edge_count = conn.execute("SELECT COUNT(*) AS count FROM entity.entity_relationship").fetchone()["count"]
    conn.close()
    print(f"Created relationship graph with {node_count} node(s) and {edge_count} relationship(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
