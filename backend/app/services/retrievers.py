from __future__ import annotations

from datetime import date
import json
import re
from typing import Any

from ..contracts import RetrievalResult, RoutingPayload, SourceTrace
from ..db import repository
from .embeddings import cosine_similarity, embed_texts, embedding_enabled, vector_from_json

JOIN_MAP_CATALOG: dict[str, dict[str, Any]] = {
    "client_access": {
        "label": "client access path",
        "path": [
            "clients.clients",
            "clients.clients_collaborators",
            "users.users",
            "organizations.organization_users",
        ],
    },
    "competitor_lookup": {
        "label": "inferred competitor comparable path",
        "path": [
            "clients.clients",
            "clients.client_marketing_settings",
            "clients.property_details",
            "clients.client_target_audience",
            "world.cities",
        ],
    },
    "entity_relationship_graph": {
        "label": "derived entity relationship graph",
        "path": [
            "clients.clients",
            "entity.entity",
            "entity.entity_relationship",
        ],
    },
    "content_schedule": {
        "label": "content workflow path",
        "path": [
            "clients.clients",
            "content.content_topic",
            "content.content_topic_post",
            "general.social_network_type",
        ],
    },
    "content_approval": {
        "label": "content approval path",
        "path": [
            "clients.clients",
            "content.content_topic",
            "content.content_topic_post",
            "content.content_topic_post_approval_status",
            "content.content_post_status",
        ],
    },
    "content_post_detail": {
        "label": "content post detail path",
        "path": [
            "clients.clients",
            "content.content_topic",
            "content.content_topic_post",
            "content.content_topic_post_media",
            "media.media",
            "media.media_analysis_ai",
            "general.social_network_type",
        ],
    },
    "content_performance": {
        "label": "content performance path",
        "path": [
            "clients.clients",
            "content.content_topic",
            "content.content_topic_post",
            "content.content_topic_post_media",
            "media.media",
            "media.media_analysis_ai",
            "analytics.social_media_post",
        ],
    },
    "inbox_threads": {
        "label": "inbox triage path",
        "path": [
            "clients.clients",
            "jx_bridge.interactions",
            "jx_bridge.messages",
            "jx_bridge.thread_triage",
            "jx_bridge.alerts",
            "jx_bridge.alert_replies",
        ],
    },
    "event_lookup": {
        "label": "event lookup path",
        "path": [
            "clients.clients",
            "world.cities",
            "general.events",
        ],
    },
    "property_knowledge": {
        "label": "property knowledge path",
        "path": [
            "clients.clients",
            "clients.client_notes",
            "clients.property_details",
            "clients.client_details",
        ],
    },
    "media_semantic": {
        "label": "media semantic path",
        "path": [
            "media.media",
            "media.media_analysis_ai",
            "content.content_topic_post_media",
        ],
    },
}

SQL_TEMPLATE_CATALOG: dict[str, dict[str, Any]] = {
    "client_access_lookup": {
        "tables": ["clients.clients", "clients.clients_collaborators", "users.users", "organizations.organization_users"],
        "join_path": "client_access",
        "description": "Explain active collaborator and organization-level access for a client.",
    },
    "competitor_lookup": {
        "tables": ["clients.clients", "clients.client_marketing_settings", "clients.property_details", "clients.client_target_audience", "world.cities"],
        "join_path": "competitor_lookup",
        "description": "Return likely comparable competitors inferred from client market settings, city, audience, and property detail context.",
    },
    "relationship_lookup": {
        "tables": ["entity.entity", "entity.entity_relationship", "clients.clients"],
        "join_path": "entity_relationship_graph",
        "description": "Explain connected entities for a client from the derived read-only relationship graph.",
    },
    "content_schedule_lookup": {
        "tables": ["content.content_topic_post", "content.content_topic", "content.content_post_status", "general.social_network_type"],
        "join_path": "content_schedule",
        "description": "Return scheduled and recent content posts in a time window.",
    },
    "content_approval_lookup": {
        "tables": ["content.content_topic_post", "content.content_topic", "content.content_topic_post_approval_status", "content.content_post_status"],
        "join_path": "content_approval",
        "description": "Return draft and approval workflow records for a client.",
    },
    "content_post_detail_lookup": {
        "tables": ["content.content_topic_post", "content.content_topic", "content.content_topic_post_media", "media.media", "media.media_analysis_ai", "general.social_network_type"],
        "join_path": "content_post_detail",
        "description": "Return the latest matching post copy and attached media details for a client.",
    },
    "post_performance_lookup": {
        "tables": ["content.content_topic_post", "content.content_topic", "analytics.social_media_post", "content.content_topic_post_media", "media.media", "media.media_analysis_ai"],
        "join_path": "content_performance",
        "description": "Return latest post plus available analytics snapshot and related media context.",
    },
    "inbox_lookup": {
        "tables": ["jx_bridge.messages", "jx_bridge.interactions", "jx_bridge.thread_triage", "jx_bridge.alerts", "jx_bridge.alert_replies"],
        "join_path": "inbox_threads",
        "description": "Return active or unresolved inbox threads with triage state.",
    },
    "event_lookup": {
        "tables": ["general.events", "clients.clients", "world.cities"],
        "join_path": "event_lookup",
        "description": "Return nearby or upcoming events relevant to a client location.",
    },
}

NETWORK_ALIASES = {
    "instagram": [3, 7],
    "facebook": [1],
    "linkedin": [6],
    "tiktok": [9],
    "twitter": [2],
}

KNOWLEDGE_CAPABILITY_DOMAINS = {
    "property_fact_lookup": ["property_knowledge"],
    "property_knowledge_summary": ["property_knowledge"],
    "tone_of_voice_lookup": ["tone", "audience"],
    "audience_lookup": ["audience"],
    "media_recommendation": ["media"],
}
YES_NO_QUERY_PREFIXES = ("do ", "does ", "is ", "is there ", "are there ", "has ", "have ")
FACT_TERM_STOPWORDS = {
    "about",
    "any",
    "are",
    "at",
    "available",
    "client",
    "detail",
    "details",
    "do",
    "does",
    "for",
    "has",
    "have",
    "hotel",
    "its",
    "property",
    "there",
    "this",
    "what",
}


def _normalize(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9\s\-']", " ", lowered)
    return " ".join(lowered.split())


def _query_tokens(query: str) -> list[str]:
    return [token for token in _normalize(query).split() if len(token) > 2]


def _fact_focus_terms(payload: RoutingPayload) -> list[str]:
    client_terms = set(_query_tokens(payload.entities.property_name or ""))
    terms = []
    for term in _query_tokens(payload.query):
        if term in FACT_TERM_STOPWORDS:
            continue
        if term in client_terms:
            continue
        if term not in terms:
            terms.append(term)
    return terms


def _strip_embedding_aliases(value: Any) -> str:
    raw = str(value or "").strip()
    if "Content:" in raw:
        raw = raw.split("Content:", 1)[1].strip()
    if ". Aliases:" in raw:
        raw = raw.split(". Aliases:", 1)[0].strip()
    return raw


def _chunk_contains_focus(chunk: dict[str, Any], focus_terms: list[str]) -> bool:
    if not focus_terms:
        return True
    haystack = _normalize(
        " ".join(
            str(value or "")
            for value in (
                chunk.get("title"),
                _strip_embedding_aliases(chunk.get("excerpt")),
                chunk.get("source_ref"),
                chunk.get("source_kind"),
                chunk.get("chunk_label"),
            )
        )
    )
    return any(term in haystack for term in focus_terms)


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed if str(item).strip()]
            except Exception:
                pass
        return [part.strip() for part in stripped.split(",") if part.strip()]
    return [str(value)]


def _execute_sql(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return repository.execute_query(sql, params)


def _source_trace(label: str, mode: str, tables: list[str], rows: list[dict[str, Any]], sql: str | None, join_path_key: str, scope_client_ids: list[int], notes: list[str] | None = None) -> SourceTrace:
    join_path = JOIN_MAP_CATALOG.get(join_path_key, {}).get("path", [])
    return SourceTrace(
        mode=mode,
        label=label,
        tables=tables,
        row_count=len(rows),
        sql=sql,
        join_path=join_path,
        scope_client_ids=scope_client_ids,
        notes=notes or [],
    )


def _network_ids_from_payload(payload: RoutingPayload) -> list[int]:
    channel = payload.entities.channel or ""
    return NETWORK_ALIASES.get(channel, [])


def _extract_total(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        for key in ("totalCount", "total_count", "count"):
            raw = value.get(key)
            if isinstance(raw, int):
                return raw
        summary = value.get("summary")
        if isinstance(summary, str):
            try:
                parsed = json.loads(summary)
                for key in ("total_count", "totalCount"):
                    raw = parsed.get(key)
                    if isinstance(raw, int):
                        return raw
            except Exception:
                return None
    return None


def extract_analytics_snapshot(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    raw_json = row.get("json_value") or {}
    if isinstance(raw_json, str):
        try:
            raw_json = json.loads(raw_json)
        except Exception:
            raw_json = {}
    likes = _extract_total(raw_json.get("likes"))
    comments = _extract_total(raw_json.get("comments"))
    reactions = _extract_total(raw_json.get("reactions"))
    shares = _extract_total(raw_json.get("shares"))
    if likes is None and isinstance(raw_json.get("like_count"), int):
        likes = raw_json.get("like_count")
    if comments is None and isinstance(raw_json.get("comments_count"), int):
        comments = raw_json.get("comments_count")
    reach = _extract_total(raw_json.get("reach"))
    impressions = _extract_total(raw_json.get("impressions"))
    return {
        "likes": likes,
        "comments": comments,
        "reactions": reactions,
        "shares": shares,
        "reach": reach,
        "impressions": impressions,
        "permalink_url": raw_json.get("permalink_url") or raw_json.get("permalink"),
        "created_time": raw_json.get("created_time") or raw_json.get("timestamp"),
    }


def execute_sql_capability(capability: str, payload: RoutingPayload) -> RetrievalResult:
    client_id = payload.entities.client_id
    scope_client_ids = payload.scope.client_ids
    if client_id is None:
        return RetrievalResult(
            mode="sql",
            template_key=capability,
            support_notes=["SQL retrieval needs a resolved client_id."],
            source_traces=[
                SourceTrace(
                    mode="sql",
                    label="missing client scope",
                    tables=SQL_TEMPLATE_CATALOG.get(capability, {}).get("tables", []),
                    row_count=0,
                    join_path=JOIN_MAP_CATALOG.get(SQL_TEMPLATE_CATALOG.get(capability, {}).get("join_path", ""), {}).get("path", []),
                    scope_client_ids=scope_client_ids,
                    notes=["client_id was not resolved during intake"],
                )
            ],
        )

    if capability == "client_access_lookup":
        sql = """
        SELECT DISTINCT
          u.id AS user_id,
          u.full_name,
          cc.access_level,
          c.name AS client_name
        FROM clients.clients c
        LEFT JOIN clients.clients_collaborators cc
          ON cc.client_id = c.id
         AND cc.deleted_at IS NULL
         AND cc.enabled IS TRUE
        LEFT JOIN users.users u
          ON u.id = cc.user_id
        WHERE c.id = :client_id
          AND c.deleted_at IS NULL
        ORDER BY u.full_name ASC NULLS LAST
        LIMIT 25
        """
        rows = _execute_sql(sql, {"client_id": client_id})
        return RetrievalResult(
            mode="sql",
            template_key=capability,
            tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
            rows=rows,
            sql=sql.strip(),
            source_traces=[_source_trace("client access lookup", "sql", SQL_TEMPLATE_CATALOG[capability]["tables"], rows, sql.strip(), SQL_TEMPLATE_CATALOG[capability]["join_path"], scope_client_ids)],
        )

    if capability == "competitor_lookup":
        if not repository.table_exists("clients", "client_marketing_settings"):
            return RetrievalResult(
                mode="sql",
                template_key=capability,
                tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
                rows=[],
                support_notes=[
                    "no official competitor-set table was found",
                    "clients.client_marketing_settings is not available, so comparable inference cannot run",
                ],
                source_traces=[
                    _source_trace(
                        "competitor comparable lookup",
                        "sql",
                        SQL_TEMPLATE_CATALOG[capability]["tables"],
                        [],
                        "",
                        SQL_TEMPLATE_CATALOG[capability]["join_path"],
                        scope_client_ids,
                        notes=["competitor evidence was unavailable in the approved schema"],
                    )
                ],
            )

        if repository.is_dummy():
            target_audiences_expr = """
              (
                SELECT GROUP_CONCAT(DISTINCT target_audience.audience)
                FROM clients.client_target_audience target_audience
                WHERE target_audience.client_id = target.id
                  AND target_audience.deleted_at IS NULL
              ) AS target_audiences
            """
            competitor_audiences_expr = """
              (
                SELECT GROUP_CONCAT(DISTINCT competitor_audience.audience)
                FROM clients.client_target_audience competitor_audience
                WHERE competitor_audience.client_id = competitor.id
                  AND competitor_audience.deleted_at IS NULL
              ) AS competitor_audiences
            """
        else:
            target_audiences_expr = """
              (
                SELECT STRING_AGG(DISTINCT target_audience.audience, ', ')
                FROM clients.client_target_audience target_audience
                WHERE target_audience.client_id = target.id
                  AND target_audience.deleted_at IS NULL
              ) AS target_audiences
            """
            competitor_audiences_expr = """
              (
                SELECT STRING_AGG(DISTINCT competitor_audience.audience, ', ')
                FROM clients.client_target_audience competitor_audience
                WHERE competitor_audience.client_id = competitor.id
                  AND competitor_audience.deleted_at IS NULL
              ) AS competitor_audiences
            """

        sql = f"""
        WITH target AS (
          SELECT
            c.id,
            c.name,
            c.organization_id,
            c.world_city_id,
            city.name AS city_name,
            cms.property_type,
            cms.conversion,
            cms.average_default_rate,
            cms.average_length_of_stay,
            pd.overview,
            pd.amenities
          FROM clients.clients c
          LEFT JOIN world.cities city
            ON city.id = c.world_city_id
          LEFT JOIN clients.client_marketing_settings cms
            ON cms.client_id = c.id
           AND cms.deleted_at IS NULL
          LEFT JOIN clients.property_details pd
            ON pd.client_id = c.id
           AND pd.deleted_at IS NULL
          WHERE c.id = :client_id
            AND c.deleted_at IS NULL
          ORDER BY cms.updated_datetime DESC
          LIMIT 1
        )
        SELECT
          target.id AS client_id,
          target.name AS client_name,
          target.city_name AS client_city,
          target.property_type AS target_property_type,
          target.average_default_rate AS target_average_default_rate,
          target.conversion AS target_conversion,
          target.average_length_of_stay AS target_average_length_of_stay,
          target.overview AS target_overview,
          {target_audiences_expr},
          competitor.id AS competitor_client_id,
          competitor.name AS competitor_name,
          competitor_city.name AS competitor_city,
          competitor_ms.property_type AS competitor_property_type,
          competitor_ms.average_default_rate AS competitor_average_default_rate,
          competitor_ms.conversion AS competitor_conversion,
          competitor_ms.average_length_of_stay AS competitor_average_length_of_stay,
          competitor_pd.overview AS competitor_overview,
          competitor_pd.amenities AS competitor_amenities,
          {competitor_audiences_expr},
          CASE WHEN competitor.world_city_id = target.world_city_id THEN 1 ELSE 0 END AS same_city,
          CASE
            WHEN LOWER(COALESCE(competitor_ms.property_type, '')) = LOWER(COALESCE(target.property_type, ''))
             AND COALESCE(target.property_type, '') <> ''
            THEN 1 ELSE 0
          END AS same_property_type,
          CASE
            WHEN target.average_default_rate IS NOT NULL
             AND competitor_ms.average_default_rate IS NOT NULL
             AND target.average_default_rate > 0
             AND ABS(CAST(competitor_ms.average_default_rate AS REAL) - CAST(target.average_default_rate AS REAL))
                 <= CAST(target.average_default_rate AS REAL) * 0.30
            THEN 1 ELSE 0
          END AS similar_rate_band,
          (
            CASE WHEN competitor.world_city_id = target.world_city_id THEN 45 ELSE 0 END
            + CASE
                WHEN LOWER(COALESCE(competitor_ms.property_type, '')) = LOWER(COALESCE(target.property_type, ''))
                 AND COALESCE(target.property_type, '') <> ''
                THEN 30 ELSE 0
              END
            + CASE
                WHEN target.average_default_rate IS NOT NULL
                 AND competitor_ms.average_default_rate IS NOT NULL
                 AND target.average_default_rate > 0
                 AND ABS(CAST(competitor_ms.average_default_rate AS REAL) - CAST(target.average_default_rate AS REAL))
                     <= CAST(target.average_default_rate AS REAL) * 0.30
                THEN 20 ELSE 0
              END
            + CASE WHEN COALESCE(competitor.organization_id, -1) <> COALESCE(target.organization_id, -1) THEN 5 ELSE 0 END
          ) AS comparable_score
        FROM target
        JOIN clients.clients competitor
          ON competitor.id <> target.id
         AND competitor.deleted_at IS NULL
        LEFT JOIN world.cities competitor_city
          ON competitor_city.id = competitor.world_city_id
        LEFT JOIN clients.client_marketing_settings competitor_ms
          ON competitor_ms.client_id = competitor.id
         AND competitor_ms.deleted_at IS NULL
        LEFT JOIN clients.property_details competitor_pd
          ON competitor_pd.client_id = competitor.id
         AND competitor_pd.deleted_at IS NULL
        WHERE (
          competitor.world_city_id = target.world_city_id
          OR (
            LOWER(COALESCE(competitor_ms.property_type, '')) = LOWER(COALESCE(target.property_type, ''))
            AND COALESCE(target.property_type, '') <> ''
          )
          OR (
            target.average_default_rate IS NOT NULL
            AND competitor_ms.average_default_rate IS NOT NULL
            AND target.average_default_rate > 0
            AND ABS(CAST(competitor_ms.average_default_rate AS REAL) - CAST(target.average_default_rate AS REAL))
                <= CAST(target.average_default_rate AS REAL) * 0.30
          )
        )
        ORDER BY comparable_score DESC, same_city DESC, same_property_type DESC, similar_rate_band DESC, competitor.name ASC
        LIMIT 8
        """
        rows = _execute_sql(sql, {"client_id": client_id})
        notes = [
            "no official competitor-set table was found in the live schema inspection",
            "competitors are inferred as likely comparables from city, property type, rate band, audience, and property context",
        ]
        if not rows:
            notes.append("the comparable inference query returned no candidates for the resolved client")
        return RetrievalResult(
            mode="sql",
            template_key=capability,
            tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
            rows=rows,
            sql=sql.strip(),
            support_notes=notes,
            source_traces=[
                _source_trace(
                    "competitor comparable lookup",
                    "sql",
                    SQL_TEMPLATE_CATALOG[capability]["tables"],
                    rows,
                    sql.strip(),
                    SQL_TEMPLATE_CATALOG[capability]["join_path"],
                    scope_client_ids,
                    notes=notes,
                )
            ],
        )

    if capability == "relationship_lookup":
        if not repository.table_exists("entity", "entity_relationship"):
            return RetrievalResult(
                mode="sql",
                template_key=capability,
                tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
                rows=[],
                support_notes=["derived relationship graph is not available"],
                source_traces=[
                    _source_trace(
                        "entity relationship graph lookup",
                        "sql",
                        SQL_TEMPLATE_CATALOG[capability]["tables"],
                        [],
                        "",
                        SQL_TEMPLATE_CATALOG[capability]["join_path"],
                        scope_client_ids,
                        notes=["entity.entity_relationship table was not found"],
                    )
                ],
            )
        normalized_query = payload.normalized_query
        type_filters: list[str] = []
        relationship_filters: list[str] = []
        if any(word in normalized_query for word in ("media", "asset", "visual", "photo", "image")):
            type_filters.extend(["Media", "MediaAnalysis"])
        if any(word in normalized_query for word in ("post", "posts", "content", "caption", "copy")):
            type_filters.extend(["ContentTopic", "Post", "PostStatus", "SocialNetwork"])
        if any(word in normalized_query for word in ("metric", "metrics", "analytics", "performance", "engagement")):
            type_filters.extend(["MetricSnapshot", "MetricChunk"])
        if any(word in normalized_query for word in ("event", "events", "nearby")):
            type_filters.append("Event")
        if any(word in normalized_query for word in ("competitor", "competitors", "competition", "competitive", "comp set", "compset", "comparable", "comparables", "similar hotel", "similar hotels")):
            relationship_filters.append("HAS_COMPARABLE_CLIENT")
        if any(word in normalized_query for word in ("inbox", "message", "messages", "thread", "interaction", "complaint")):
            type_filters.extend(["Interaction", "Message"])
        if any(word in normalized_query for word in ("access", "collaborator", "organization", "owner", "user", "role")):
            type_filters.extend(["Organization", "User"])

        params: dict[str, Any] = {"client_id": client_id}
        type_filter_sql = ""
        filter_clauses: list[str] = []
        if type_filters:
            unique_filters = []
            for entity_type in type_filters:
                if entity_type not in unique_filters:
                    unique_filters.append(entity_type)
            placeholders = []
            for index, entity_type in enumerate(unique_filters):
                key = f"entity_type_{index}"
                params[key] = entity_type
                placeholders.append(f":{key}")
            filter_clauses.append(f"(from_entity.entity_type IN ({', '.join(placeholders)}) OR to_entity.entity_type IN ({', '.join(placeholders)}))")
        if relationship_filters:
            rel_placeholders = []
            for index, relationship_type in enumerate(relationship_filters):
                key = f"relationship_type_{index}"
                params[key] = relationship_type
                rel_placeholders.append(f":{key}")
            filter_clauses.append(f"rel.relationship_type IN ({', '.join(rel_placeholders)})")
        if filter_clauses:
            type_filter_sql = f"AND ({' OR '.join(filter_clauses)})"

        sql = f"""
        SELECT
          rel.id AS relationship_id,
          rel.relationship_type,
          rel.source_table,
          rel.source_pk,
          rel.weight,
          from_entity.entity_type AS from_entity_type,
          from_entity.name AS from_entity_name,
          from_entity.source_table AS from_source_table,
          from_entity.source_pk AS from_source_pk,
          to_entity.entity_type AS to_entity_type,
          to_entity.name AS to_entity_name,
          to_entity.source_table AS to_source_table,
          to_entity.source_pk AS to_source_pk,
          rel.metadata
        FROM entity.entity_relationship rel
        JOIN entity.entity from_entity
          ON from_entity.id = rel.from_entity_id
        JOIN entity.entity to_entity
          ON to_entity.id = rel.to_entity_id
        WHERE rel.client_id = :client_id
          AND rel.deleted_at IS NULL
          AND from_entity.deleted_at IS NULL
          AND to_entity.deleted_at IS NULL
          {type_filter_sql}
        ORDER BY
          CASE rel.relationship_type
            WHEN 'BELONGS_TO_ORGANIZATION' THEN 1
            WHEN 'LOCATED_IN' THEN 2
            WHEN 'HAS_COLLABORATOR' THEN 3
            WHEN 'HAS_CONTENT_TOPIC' THEN 4
            WHEN 'HAS_POST' THEN 5
            WHEN 'USES_MEDIA' THEN 6
            WHEN 'HAS_ANALYTICS_SNAPSHOT' THEN 7
            ELSE 20
          END,
          rel.id ASC
        LIMIT 200
        """
        rows = _execute_sql(sql, params)
        notes = ["relationship graph is a derived read-only model built from dummy DB source tables"]
        if type_filters:
            notes.append(f"filtered relationship graph by requested entity families: {', '.join(sorted(set(type_filters)))}")
        if relationship_filters:
            notes.append(f"filtered relationship graph by requested relationship types: {', '.join(sorted(set(relationship_filters)))}")
        return RetrievalResult(
            mode="sql",
            template_key=capability,
            tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
            rows=rows,
            sql=sql.strip(),
            support_notes=notes,
            source_traces=[_source_trace("entity relationship graph lookup", "sql", SQL_TEMPLATE_CATALOG[capability]["tables"], rows, sql.strip(), SQL_TEMPLATE_CATALOG[capability]["join_path"], scope_client_ids, notes=notes)],
        )

    if capability == "content_schedule_lookup":
        params: dict[str, Any] = {"client_id": client_id}
        date_filter = "AND ctp.post_datetime >= CURRENT_DATE"
        notes: list[str] = []
        date_range = payload.entities.date_range
        if date_range and date_range.start and date_range.end:
            params["window_start"] = date_range.start
            params["window_end"] = date_range.end + date.resolution
            date_filter = "AND ctp.post_datetime >= :window_start AND ctp.post_datetime < :window_end"
            notes.append(f"time window {date_range.start.isoformat()} to {date_range.end.isoformat()}")
        sql = f"""
        SELECT
          ctp.id AS post_id,
          ct.name AS topic_name,
          cps.description AS status,
          snt.description AS social_network,
          ctp.post_datetime,
          ctp.network_post_ref,
          SUBSTR(ctp.post_text, 1, 160) AS post_preview
        FROM content.content_topic_post ctp
        JOIN content.content_topic ct
          ON ct.id = ctp.content_topic_id
        LEFT JOIN content.content_post_status cps
          ON cps.id = ctp.content_post_status_id
        LEFT JOIN general.social_network_type snt
          ON snt.id = ctp.social_network_type_id
        WHERE ct.client_id = :client_id
          AND ctp.deleted_at IS NULL
          {date_filter}
        ORDER BY ctp.post_datetime ASC
        LIMIT 25
        """
        rows = _execute_sql(sql, params)
        return RetrievalResult(
            mode="sql",
            template_key=capability,
            tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
            rows=rows,
            sql=sql.strip(),
            source_traces=[_source_trace("content schedule lookup", "sql", SQL_TEMPLATE_CATALOG[capability]["tables"], rows, sql.strip(), SQL_TEMPLATE_CATALOG[capability]["join_path"], scope_client_ids, notes=notes)],
        )

    if capability == "content_approval_lookup":
        sql = """
        SELECT
          ctp.id AS post_id,
          ct.name AS topic_name,
          cps.description AS current_status,
          snt.description AS social_network,
          cpas.valid_from_timestamp AS approval_recorded_at,
          cpas.approval_rejection_text,
          SUBSTR(ctp.post_text, 1, 160) AS post_preview
        FROM content.content_topic_post ctp
        JOIN content.content_topic ct
          ON ct.id = ctp.content_topic_id
        LEFT JOIN content.content_post_status cps
          ON cps.id = ctp.content_post_status_id
        LEFT JOIN content.content_topic_post_approval_status cpas
          ON cpas.content_topic_post_id = ctp.id
         AND cpas.deleted_at IS NULL
        LEFT JOIN general.social_network_type snt
          ON snt.id = ctp.social_network_type_id
        WHERE ct.client_id = :client_id
          AND ctp.deleted_at IS NULL
          AND COALESCE(cps.description, '') IN ('draft', 'sent_for_approval', 'sent_for_external_approval', 'rejected')
        ORDER BY ctp.post_datetime DESC NULLS LAST, cpas.valid_from_timestamp DESC NULLS LAST
        LIMIT 25
        """
        rows = _execute_sql(sql, {"client_id": client_id})
        return RetrievalResult(
            mode="sql",
            template_key=capability,
            tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
            rows=rows,
            sql=sql.strip(),
            source_traces=[_source_trace("content approval lookup", "sql", SQL_TEMPLATE_CATALOG[capability]["tables"], rows, sql.strip(), SQL_TEMPLATE_CATALOG[capability]["join_path"], scope_client_ids)],
        )

    if capability == "content_post_detail_lookup":
        network_ids = _network_ids_from_payload(payload)
        params: dict[str, Any] = {"client_id": client_id}
        network_filter = ""
        notes: list[str] = []
        if network_ids:
            network_placeholders = []
            for index, network_id in enumerate(network_ids):
                key = f"network_id_{index}"
                params[key] = network_id
                network_placeholders.append(f":{key}")
            network_filter = f"AND ctp.social_network_type_id IN ({', '.join(network_placeholders)})"
            notes.append(f"filtered to channel {payload.entities.channel}")

        if repository.is_dummy():
            media_ids_expr = "GROUP_CONCAT(m.id, ' ||| ') AS media_ids"
            media_names_expr = "GROUP_CONCAT(m.name, ' ||| ') AS media_names"
            media_context_expr = "GROUP_CONCAT(mai.short_description, ' ||| ') AS media_context"
            media_alt_text_expr = "GROUP_CONCAT(mai.alt_text, ' ||| ') AS media_alt_text"
            media_tags_expr = "GROUP_CONCAT(mai.visual_tags, ' ||| ') AS media_visual_tags"
        else:
            media_ids_expr = "STRING_AGG(DISTINCT m.id::text, ' ||| ') AS media_ids"
            media_names_expr = "STRING_AGG(DISTINCT m.name, ' ||| ') AS media_names"
            media_context_expr = "STRING_AGG(DISTINCT mai.short_description, ' ||| ') AS media_context"
            media_alt_text_expr = "STRING_AGG(DISTINCT mai.alt_text, ' ||| ') AS media_alt_text"
            media_tags_expr = "STRING_AGG(DISTINCT mai.visual_tags::text, ' ||| ') AS media_visual_tags"

        sql = f"""
        SELECT
          ctp.id AS post_id,
          ct.name AS topic_name,
          cps.description AS status,
          snt.description AS social_network,
          ctp.post_datetime,
          ctp.network_post_ref,
          ctp.post_text,
          {media_ids_expr},
          {media_names_expr},
          {media_context_expr},
          {media_alt_text_expr},
          {media_tags_expr}
        FROM content.content_topic_post ctp
        JOIN content.content_topic ct
          ON ct.id = ctp.content_topic_id
        LEFT JOIN content.content_post_status cps
          ON cps.id = ctp.content_post_status_id
        LEFT JOIN general.social_network_type snt
          ON snt.id = ctp.social_network_type_id
        LEFT JOIN content.content_topic_post_media ctpm
          ON ctpm.content_topic_post_id = ctp.id
         AND ctpm.deleted_at IS NULL
        LEFT JOIN media.media m
          ON m.id = ctpm.media_id
         AND m.deleted_at IS NULL
        LEFT JOIN media.media_analysis_ai mai
          ON mai.media_id = m.id
         AND mai.deleted_at IS NULL
        WHERE ct.client_id = :client_id
          AND ctp.deleted_at IS NULL
          AND ctp.post_datetime <= CURRENT_TIMESTAMP
          {network_filter}
        GROUP BY ctp.id, ct.name, cps.description, snt.description, ctp.post_datetime, ctp.network_post_ref, ctp.post_text
        ORDER BY ctp.post_datetime DESC, ctp.id DESC
        LIMIT 1
        """
        rows = _execute_sql(sql, params)
        return RetrievalResult(
            mode="sql",
            template_key=capability,
            tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
            rows=rows,
            sql=sql.strip(),
            support_notes=notes,
            source_traces=[_source_trace("content post detail lookup", "sql", SQL_TEMPLATE_CATALOG[capability]["tables"], rows, sql.strip(), SQL_TEMPLATE_CATALOG[capability]["join_path"], scope_client_ids, notes=notes)],
        )

    if capability == "post_performance_lookup":
        network_ids = _network_ids_from_payload(payload)
        params: dict[str, Any] = {"client_id": client_id}
        network_filter = ""
        notes: list[str] = ["analytics support is network-specific and may be incomplete"]
        if network_ids:
            network_placeholders = []
            for index, network_id in enumerate(network_ids):
                key = f"network_id_{index}"
                params[key] = network_id
                network_placeholders.append(f":{key}")
            network_filter = f"AND ctp.social_network_type_id IN ({', '.join(network_placeholders)})"
        if repository.is_dummy():
            media_ids_expr = "GROUP_CONCAT(ctpm.media_id, ' ||| ') AS media_ids"
            media_names_expr = "GROUP_CONCAT(m.name, ' ||| ') AS media_names"
            media_context_expr = "GROUP_CONCAT(mai.short_description, ' ||| ') AS media_context"
            media_alt_text_expr = "GROUP_CONCAT(mai.alt_text, ' ||| ') AS media_alt_text"
            media_tags_expr = "GROUP_CONCAT(mai.visual_tags, ' ||| ') AS media_visual_tags"
        else:
            media_ids_expr = "STRING_AGG(DISTINCT ctpm.media_id::text, ' ||| ') AS media_ids"
            media_names_expr = "STRING_AGG(DISTINCT m.name, ' ||| ') AS media_names"
            media_context_expr = "STRING_AGG(DISTINCT mai.short_description, ' ||| ') AS media_context"
            media_alt_text_expr = "STRING_AGG(DISTINCT mai.alt_text, ' ||| ') AS media_alt_text"
            media_tags_expr = "STRING_AGG(DISTINCT mai.visual_tags::text, ' ||| ') AS media_visual_tags"
 
        post_sql = f"""
        SELECT
          ctp.id AS post_id,
          ct.name AS topic_name,
          cps.description AS status,
          snt.description AS social_network,
          ctp.post_datetime,
          ctp.network_post_ref,
          ctp.post_text,
          {media_ids_expr},
          {media_names_expr},
          {media_context_expr},
          {media_alt_text_expr},
          {media_tags_expr}
        FROM content.content_topic_post ctp
        JOIN content.content_topic ct
          ON ct.id = ctp.content_topic_id
        LEFT JOIN content.content_post_status cps
          ON cps.id = ctp.content_post_status_id
        LEFT JOIN general.social_network_type snt
          ON snt.id = ctp.social_network_type_id
        LEFT JOIN content.content_topic_post_media ctpm
          ON ctpm.content_topic_post_id = ctp.id
         AND ctpm.deleted_at IS NULL
        LEFT JOIN media.media m
          ON m.id = ctpm.media_id
         AND m.deleted_at IS NULL
        LEFT JOIN media.media_analysis_ai mai
          ON mai.media_id = ctpm.media_id
         AND mai.deleted_at IS NULL
        WHERE ct.client_id = :client_id
          AND ctp.deleted_at IS NULL
          AND ctp.post_datetime <= CURRENT_TIMESTAMP
          AND ctp.network_post_ref IS NOT NULL
          {network_filter}
        GROUP BY ctp.id, ct.name, cps.description, snt.description, ctp.post_datetime, ctp.network_post_ref, ctp.post_text
        ORDER BY ctp.post_datetime DESC
        LIMIT 10
        """
        post_rows = _execute_sql(post_sql, params)
        if not post_rows:
            return RetrievalResult(
                mode="sql",
                template_key=capability,
                tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
                rows=[],
                sql=post_sql.strip(),
                support_notes=notes,
                source_traces=[_source_trace("post performance lookup", "sql", SQL_TEMPLATE_CATALOG[capability]["tables"], [], post_sql.strip(), SQL_TEMPLATE_CATALOG[capability]["join_path"], scope_client_ids, notes=notes)],
            )

        latest_post = post_rows[0]
        analytics_rows: list[dict[str, Any]] = []
        analytics_sql = """
        SELECT
          id,
          social_network_type_id,
          identifier,
          post_ref,
          json_value,
          created_at
        FROM analytics.social_media_post
        WHERE deleted_at IS NULL
          AND (post_ref = :post_ref OR identifier = :post_ref)
        ORDER BY created_at DESC NULLS LAST, id DESC
        LIMIT 1
        """
        for candidate in post_rows:
            network_post_ref = candidate.get("network_post_ref")
            if not network_post_ref:
                continue
            candidate_analytics_rows = _execute_sql(analytics_sql, {"post_ref": network_post_ref})
            if candidate_analytics_rows:
                latest_post = candidate
                analytics_rows = candidate_analytics_rows
                break
        snapshot = extract_analytics_snapshot(analytics_rows[0] if analytics_rows else None)
        latest_post["analytics_snapshot"] = snapshot
        return RetrievalResult(
            mode="sql",
            template_key=capability,
            tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
            rows=[latest_post],
            sql=post_sql.strip(),
            support_notes=notes,
            source_traces=[
                _source_trace("latest post lookup", "sql", SQL_TEMPLATE_CATALOG[capability]["tables"], post_rows, post_sql.strip(), SQL_TEMPLATE_CATALOG[capability]["join_path"], scope_client_ids, notes=notes),
                _source_trace("analytics snapshot lookup", "sql", ["analytics.social_media_post"], analytics_rows, "SELECT ... FROM analytics.social_media_post WHERE post_ref = :post_ref", "content_performance", scope_client_ids, notes=notes),
            ],
        )

    if capability == "inbox_lookup":
        filters: list[str] = []
        params: dict[str, Any] = {"client_id": client_id}
        normalized_query = payload.normalized_query
        if any(word in normalized_query for word in ("complaint", "complaints", "issue", "problem", "cancel")):
            filters.append(
                """
                AND (
                  LOWER(COALESCE(m.content, '')) LIKE '%complaint%'
                  OR LOWER(COALESCE(m.content, '')) LIKE '%issue%'
                  OR LOWER(COALESCE(m.content, '')) LIKE '%problem%'
                  OR LOWER(COALESCE(m.content, '')) LIKE '%cancel%'
                )
                """
            )
        sql = f"""
        SELECT
          COALESCE(CAST(m.interaction_id AS TEXT), CAST(i.interaction_id AS TEXT)) AS interaction_id,
          i.client_id,
          c.name AS client_name,
          i.title,
          MAX(m.source_timestamp) AS last_guest_message_at,
          COUNT(*) AS message_count,
          COALESCE(MAX(tt.triage), 'reply_now') AS triage,
          SUBSTR(MAX(COALESCE(m.content, '')), 1, 160) AS latest_preview
        FROM jx_bridge.interactions i
        JOIN clients.clients c
          ON c.id = i.client_id
        JOIN jx_bridge.messages m
          ON m.interaction_id = i.interaction_id
         AND m.client_id = i.client_id
        LEFT JOIN jx_bridge.thread_triage tt
          ON tt.interaction_id = i.interaction_id
        WHERE i.client_id = :client_id
          AND COALESCE(m.last_state, 'new') <> 'resolved'
          {' '.join(filters)}
        GROUP BY COALESCE(CAST(m.interaction_id AS TEXT), CAST(i.interaction_id AS TEXT)), i.client_id, c.name, i.title
        ORDER BY MAX(m.source_timestamp) DESC
        LIMIT 25
        """
        rows = _execute_sql(sql, params)
        return RetrievalResult(
            mode="sql",
            template_key=capability,
            tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
            rows=rows,
            sql=sql.strip(),
            source_traces=[_source_trace("inbox thread lookup", "sql", SQL_TEMPLATE_CATALOG[capability]["tables"], rows, sql.strip(), SQL_TEMPLATE_CATALOG[capability]["join_path"], scope_client_ids)],
        )

    if capability == "event_lookup":
        sql = """
        SELECT
          e.id,
          e.name,
          e.date,
          e.type,
          e.location,
          e.audience
        FROM clients.clients c
        JOIN general.events e
          ON e.world_city_id = c.world_city_id
        WHERE c.id = :client_id
          AND c.deleted_at IS NULL
          AND e.deleted_at IS NULL
          AND e.date >= CURRENT_DATE
        ORDER BY e.date ASC
        LIMIT 25
        """
        rows = _execute_sql(sql, {"client_id": client_id})
        return RetrievalResult(
            mode="sql",
            template_key=capability,
            tables=SQL_TEMPLATE_CATALOG[capability]["tables"],
            rows=rows,
            sql=sql.strip(),
            source_traces=[_source_trace("event lookup", "sql", SQL_TEMPLATE_CATALOG[capability]["tables"], rows, sql.strip(), SQL_TEMPLATE_CATALOG[capability]["join_path"], scope_client_ids)],
        )

    return RetrievalResult(mode="sql", template_key=capability, support_notes=["No approved SQL template matched this capability."])


def _score_text(query: str, text_value: str) -> float:
    normalized_text = _normalize(text_value)
    tokens = _query_tokens(query)
    if not normalized_text or not tokens:
        return 0.0
    token_hits = sum(1 for token in tokens if token in normalized_text)
    phrase_bonus = 1.0 if _normalize(query) in normalized_text else 0.0
    return token_hits + phrase_bonus


def _load_property_chunks(client_id: int) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for note in repository.get_client_notes(client_id):
        note_text = str(note.get("note") or "").strip()
        if not note_text:
            continue
        chunks.append(
            {
                "table": "clients.client_notes",
                "title": note.get("title") or note.get("note_type") or "Client note",
                "excerpt": note_text,
            }
        )
    for note in repository.get_property_detail_notes(client_id):
        note_text = str(note.get("note") or "").strip()
        if not note_text:
            continue
        chunks.append(
            {
                "table": "clients.property_details" if note.get("title") == "Property details" else "clients.client_details",
                "title": note.get("title") or "Property detail",
                "excerpt": note_text,
            }
        )
    tone_rows = repository.execute_query(
        """
        SELECT custom_guidelines, use_words, avoid_words
        FROM clients.client_tone_of_voice_settings
        WHERE client_id = :client_id
          AND deleted_at IS NULL
        ORDER BY updated_datetime DESC NULLS LAST
        LIMIT 1
        """,
        {"client_id": client_id},
    )
    if tone_rows:
        row = tone_rows[0]
        parts = [str(row.get("custom_guidelines") or "").strip()]
        use_words = _as_text_list(row.get("use_words"))
        avoid_words = _as_text_list(row.get("avoid_words"))
        if use_words:
            parts.append("Use words: " + ", ".join(use_words))
        if avoid_words:
            parts.append("Avoid words: " + ", ".join(avoid_words))
        excerpt = " ".join(part for part in parts if part)
        if excerpt:
            chunks.append(
                {
                    "table": "clients.client_tone_of_voice_settings",
                    "title": "Tone of voice settings",
                    "excerpt": excerpt,
                }
            )
    audience_rows = repository.execute_query(
        """
        SELECT audience, is_custom
        FROM clients.client_target_audience
        WHERE client_id = :client_id
          AND deleted_at IS NULL
        ORDER BY updated_datetime DESC NULLS LAST
        LIMIT 15
        """,
        {"client_id": client_id},
    )
    for row in audience_rows:
        audience = str(row.get("audience") or "").strip()
        if audience:
            chunks.append(
                {
                    "table": "clients.client_target_audience",
                    "title": "Custom audience" if row.get("is_custom") else "Audience",
                    "excerpt": audience,
                }
            )
    return chunks


def _load_media_chunks(client_id: int) -> list[dict[str, Any]]:
    rows = repository.execute_query(
        """
        SELECT
          m.id AS media_id,
          m.name,
          m.description,
          mai.short_description,
          mai.alt_text,
          mai.visual_tags,
          mai.descriptive_tags,
          mai.semantic_keywords,
          mai.post_copy
        FROM media.media m
        JOIN media.media_analysis_ai mai
          ON mai.media_id = m.id
        WHERE m.client_id = :client_id
          AND m.deleted_at IS NULL
          AND mai.deleted_at IS NULL
        ORDER BY mai.updated_datetime DESC NULLS LAST, mai.id DESC
        LIMIT 250
        """,
        {"client_id": client_id},
    )
    chunks: list[dict[str, Any]] = []
    for row in rows:
        parts = [
            str(row.get("name") or "").strip(),
            str(row.get("description") or "").strip(),
            str(row.get("short_description") or "").strip(),
            str(row.get("alt_text") or "").strip(),
            " ".join(_as_text_list(row.get("visual_tags"))),
            " ".join(_as_text_list(row.get("descriptive_tags"))),
            " ".join(_as_text_list(row.get("semantic_keywords"))),
            str(row.get("post_copy") or "").strip(),
        ]
        excerpt = " ".join(part for part in parts if part)
        if excerpt:
            chunks.append(
                {
                    "table": "media.media_analysis_ai",
                    "title": row.get("name") or f"media {row.get('media_id')}",
                    "excerpt": excerpt,
                    "media_id": row.get("media_id"),
                }
            )
    return chunks


def _load_knowledge_embedding_chunks(client_id: int, domains: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    if not repository.table_exists("general", "knowledge_embeddings"):
        return [], ["knowledge embedding table is not available; using source-table fallback retrieval"]

    params: dict[str, Any] = {"client_id": client_id}
    placeholders = []
    for index, domain in enumerate(domains):
        key = f"domain_{index}"
        params[key] = domain
        placeholders.append(f":{key}")
    domain_filter = f"AND knowledge_domain IN ({', '.join(placeholders)})" if placeholders else ""
    rows = repository.execute_query(
        f"""
        SELECT
          id,
          client_id,
          source_table,
          source_pk,
          source_ref,
          source_kind,
          knowledge_domain,
          chunk_label,
          knowledge_document,
          embedding_model,
          embedding_json,
          updated_datetime
        FROM general.knowledge_embeddings
        WHERE client_id = :client_id
          {domain_filter}
        ORDER BY updated_datetime DESC, id DESC
        LIMIT 500
        """,
        params,
    )
    chunks = []
    for row in rows:
        document = str(row.get("knowledge_document") or "").strip()
        if not document:
            continue
        chunks.append(
            {
                "table": row.get("source_table") or "general.knowledge_embeddings",
                "title": row.get("chunk_label") or row.get("source_ref") or row.get("source_kind") or "Knowledge chunk",
                "excerpt": document,
                "source_pk": row.get("source_pk"),
                "source_ref": row.get("source_ref"),
                "source_kind": row.get("source_kind"),
                "knowledge_domain": row.get("knowledge_domain"),
                "embedding_source_table": "general.knowledge_embeddings",
                "embedding_model": row.get("embedding_model"),
                "embedding_json": row.get("embedding_json"),
            }
        )
    if chunks:
        notes.append("knowledge embedding table was available and scoped by client_id")
    else:
        notes.append("knowledge embedding table exists but has no rows for the resolved client/domain")
    return chunks, notes


def _rank_semantic_chunks(
    chunks: list[dict[str, Any]],
    query: str,
    *,
    prefer_tables: dict[str, int] | None = None,
    fallback_summary_mode: bool = False,
) -> tuple[list[tuple[float, dict[str, Any]]], list[str]]:
    notes: list[str] = []
    ranked: list[tuple[float, dict[str, Any]]] = []
    embedded_chunks = [chunk for chunk in chunks if vector_from_json(chunk.get("embedding_json"))]

    if embedded_chunks and embedding_enabled():
        try:
            query_vector = embed_texts([query])[0]
            for chunk in embedded_chunks:
                score = cosine_similarity(query_vector, vector_from_json(chunk.get("embedding_json")))
                lexical_boost = min(_score_text(query, str(chunk.get("excerpt") or "")), 8.0) * 0.04
                table_boost = 0.0
                if prefer_tables:
                    table_rank = prefer_tables.get(str(chunk.get("table")), 99)
                    table_boost = max(0.0, (10 - min(table_rank, 10)) * 0.005)
                ranked.append((score + lexical_boost + table_boost, chunk))
            ranked.sort(key=lambda item: item[0], reverse=True)
            notes.append("ranked knowledge context with OpenAI query embedding against stored knowledge embeddings")
            return ranked, notes
        except Exception as exc:
            notes.append(f"knowledge embedding ranking unavailable, fell back to lexical ranking: {exc}")

    for chunk in chunks:
        score = _score_text(query, str(chunk.get("excerpt") or ""))
        if fallback_summary_mode and score == 0:
            score = 0.5
        if prefer_tables:
            table_rank = prefer_tables.get(str(chunk.get("table")), 99)
            score += max(0.0, (10 - min(table_rank, 10)) * 0.05)
        if score > 0:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    notes.append("ranked knowledge context with deterministic lexical fallback")
    return ranked, notes


def _knowledge_embedding_result(capability: str, payload: RoutingPayload, *, limit: int = 5) -> RetrievalResult | None:
    client_id = payload.entities.client_id
    if client_id is None:
        return None
    domains = KNOWLEDGE_CAPABILITY_DOMAINS.get(capability)
    if not domains:
        return None

    chunks, notes = _load_knowledge_embedding_chunks(client_id, domains)
    if not chunks:
        return None

    prefer_tables = {
        "clients.client_notes": 0,
        "clients.property_details": 1,
        "clients.client_details": 2,
        "clients.client_tone_of_voice_settings": 3,
        "clients.client_target_audience": 4,
        "media.media_analysis_ai": 5,
        "content.content_topic_post": 6,
    }
    ranked, ranking_notes = _rank_semantic_chunks(
        chunks,
        payload.query,
        prefer_tables=prefer_tables,
        fallback_summary_mode=capability == "property_knowledge_summary",
    )
    notes.extend(ranking_notes)

    if capability == "property_fact_lookup" and payload.normalized_query.startswith(YES_NO_QUERY_PREFIXES):
        focus_terms = _fact_focus_terms(payload)
        if focus_terms:
            focused_ranked = [(score, chunk) for score, chunk in ranked if _chunk_contains_focus(chunk, focus_terms)]
            if focused_ranked:
                ranked = focused_ranked
                notes.append(f"filtered property fact evidence to chunks containing requested fact terms: {', '.join(focus_terms)}")
            else:
                notes.append(f"no direct property fact evidence found for requested terms: {', '.join(focus_terms)}")
                return RetrievalResult(
                    mode="vector",
                    template_key=capability,
                    tables=["general.knowledge_embeddings"],
                    matches=[],
                    source_traces=[
                        SourceTrace(
                            mode="vector",
                            label="knowledge embedding retrieval",
                            tables=["general.knowledge_embeddings"],
                            row_count=0,
                            join_path=JOIN_MAP_CATALOG["property_knowledge"]["path"],
                            scope_client_ids=payload.scope.client_ids,
                            notes=notes,
                        )
                    ],
                    support_notes=notes,
                )

    matches = []
    for score, chunk in ranked[:limit]:
        matches.append({**chunk, "score": round(float(score), 4), "fit": f"knowledge embedding score {round(float(score), 4)}"})

    if not matches:
        return None

    tables = sorted({"general.knowledge_embeddings", *{str(match.get("table")) for match in matches if match.get("table")}})
    join_key = "media_semantic" if capability == "media_recommendation" else "property_knowledge"
    return RetrievalResult(
        mode="vector",
        template_key=capability,
        tables=tables,
        matches=matches,
        source_traces=[
            SourceTrace(
                mode="vector",
                label="knowledge embedding retrieval",
                tables=tables,
                row_count=len(matches),
                join_path=JOIN_MAP_CATALOG[join_key]["path"],
                scope_client_ids=payload.scope.client_ids,
                notes=notes,
            )
        ],
        support_notes=notes,
    )


def _metric_document_from_row(row: dict[str, Any]) -> str:
    snapshot = extract_analytics_snapshot(row)
    metric_parts = []
    for key in ("likes", "comments", "reactions", "shares", "reach", "impressions"):
        value = snapshot.get(key)
        if value is not None:
            metric_parts.append(f"{key}={value}")
    metric_line = ", ".join(metric_parts) if metric_parts else "no normalized metric values resolved"
    return (
        f"Client: {row.get('client_name')}. "
        f"Network: {row.get('social_network')}. "
        f"Post date: {row.get('post_datetime')}. "
        f"Caption: {row.get('post_text')}. "
        f"Available metric snapshot: {metric_line}. "
        "Metric aliases: engagement, interactions, post performance, social analytics, latest post metrics."
    )


def _load_metric_chunks(client_id: int) -> tuple[list[dict[str, Any]], list[str]]:
    notes: list[str] = []
    if repository.table_exists("analytics", "metric_embeddings"):
        rows = repository.execute_query(
            """
            SELECT
              id,
              client_id,
              source_table,
              source_pk,
              source_ref,
              source_kind,
              metric_document,
              metric_names,
              embedding_model,
              embedding_json,
              updated_datetime
            FROM analytics.metric_embeddings
            WHERE client_id = :client_id
            ORDER BY updated_datetime DESC, id DESC
            LIMIT 250
            """,
            {"client_id": client_id},
        )
        chunks = []
        for row in rows:
            document = str(row.get("metric_document") or "").strip()
            if not document:
                continue
            chunks.append(
                {
                    "table": "analytics.metric_embeddings",
                    "title": f"Metric context {row.get('source_ref') or row.get('source_pk')}",
                    "excerpt": document,
                    "source_pk": row.get("source_pk"),
                    "source_ref": row.get("source_ref"),
                    "embedding_model": row.get("embedding_model"),
                    "embedding_json": row.get("embedding_json"),
                }
            )
        if chunks:
            notes.append("metric embedding table was available and scoped by client_id")
            return chunks, notes
        notes.append("metric embedding table exists but has no rows for the resolved client")

    rows = repository.execute_query(
        """
        SELECT
          asp.id AS analytics_id,
          ct.client_id,
          c.name AS client_name,
          ctp.id AS post_id,
          ctp.post_text,
          ctp.post_datetime,
          ctp.network_post_ref,
          snt.description AS social_network,
          asp.json_value
        FROM analytics.social_media_post asp
        JOIN content.content_topic_post ctp
          ON ctp.network_post_ref = asp.post_ref
          OR ctp.network_post_ref = asp.identifier
        JOIN content.content_topic ct
          ON ct.id = ctp.content_topic_id
        JOIN clients.clients c
          ON c.id = ct.client_id
        LEFT JOIN general.social_network_type snt
          ON snt.id = ctp.social_network_type_id
        WHERE ct.client_id = :client_id
          AND asp.deleted_at IS NULL
          AND ctp.deleted_at IS NULL
          AND c.deleted_at IS NULL
        ORDER BY ctp.post_datetime DESC, asp.id DESC
        LIMIT 80
        """,
        {"client_id": client_id},
    )
    chunks = []
    for row in rows:
        chunks.append(
            {
                "table": "analytics.social_media_post",
                "title": f"Metric snapshot {row.get('network_post_ref') or row.get('analytics_id')}",
                "excerpt": _metric_document_from_row(row),
                "source_pk": row.get("analytics_id"),
                "source_ref": row.get("network_post_ref"),
                "post_id": row.get("post_id"),
                "social_network": row.get("social_network"),
            }
        )
    if chunks:
        notes.append("metric semantic chunks were synthesized from analytics rows because stored embeddings were not populated")
    return chunks, notes


def execute_vector_capability(capability: str, payload: RoutingPayload) -> RetrievalResult:
    client_id = payload.entities.client_id
    if client_id is None:
        return RetrievalResult(mode="vector", template_key=capability, support_notes=["Vector retrieval needs a resolved client_id."])

    embedding_limit = 8 if capability in {"property_knowledge_summary", "audience_lookup"} else 5
    embedding_result = _knowledge_embedding_result(capability, payload, limit=embedding_limit)
    if embedding_result is not None:
        return embedding_result

    if capability == "audience_lookup":
        chunks = _load_property_chunks(client_id)
        audience_chunks = [chunk for chunk in chunks if chunk.get("table") == "clients.client_target_audience"]
        matches = []
        for index, chunk in enumerate(audience_chunks[:8]):
            matches.append({**chunk, "score": round(max(1.0, 8 - index), 2)})
        return RetrievalResult(
            mode="vector",
            template_key=capability,
            tables=["clients.client_target_audience"],
            matches=matches,
            source_traces=[
                SourceTrace(
                    mode="vector",
                    label="target audience retrieval",
                    tables=["clients.client_target_audience"],
                    row_count=len(matches),
                    join_path=JOIN_MAP_CATALOG["property_knowledge"]["path"],
                    scope_client_ids=payload.scope.client_ids,
                    notes=["audience mode returns approved audience rows for the resolved client"],
                )
            ],
        )

    if capability == "property_knowledge_summary":
        chunks = _load_property_chunks(client_id)
        table_priority = {
            "clients.client_notes": 0,
            "clients.property_details": 1,
            "clients.client_details": 2,
            "clients.client_tone_of_voice_settings": 3,
            "clients.client_target_audience": 4,
        }

        def is_useful_summary_chunk(chunk: dict[str, Any]) -> bool:
            text_value = _normalize(str(chunk.get("excerpt") or ""))
            if len(text_value) < 8:
                return False
            if len(text_value.split()) < 2:
                return False
            if text_value.startswith("info ") and " null" in text_value:
                return False
            if text_value.startswith("onboarding "):
                return False
            return text_value not in {
                "amenities",
                "food beverage",
                "highlights",
                "info",
                "location",
                "metadata onboarding",
                "onboarding",
                "overview",
            }

        summary_tables = {"clients.client_notes", "clients.property_details", "clients.client_details"}
        useful_chunks = [
            chunk
            for chunk in chunks
            if str(chunk.get("table")) in summary_tables and is_useful_summary_chunk(chunk)
        ]
        useful_chunks.sort(
            key=lambda chunk: (
                table_priority.get(str(chunk.get("table")), 99),
                -len(str(chunk.get("excerpt") or "")),
            )
        )
        matches = []
        for index, chunk in enumerate(useful_chunks[:8]):
            matches.append({**chunk, "score": round(max(1.0, 8 - index), 2)})
        return RetrievalResult(
            mode="vector",
            template_key=capability,
            tables=sorted({match["table"] for match in matches}) if matches else ["clients.client_notes", "clients.property_details", "clients.client_details"],
            matches=matches,
            source_traces=[
                SourceTrace(
                    mode="vector",
                    label="property summary chunk retrieval",
                    tables=sorted({chunk["table"] for chunk in chunks}),
                    row_count=len(matches),
                    join_path=JOIN_MAP_CATALOG["property_knowledge"]["path"],
                    scope_client_ids=payload.scope.client_ids,
                    notes=["summary mode uses broad approved chunks instead of narrow keyword matching"],
                )
            ],
        )

    if capability in {"property_fact_lookup", "property_knowledge_summary", "tone_of_voice_lookup", "audience_lookup"}:
        chunks = _load_property_chunks(client_id)
        ranked = []
        for chunk in chunks:
            score = _score_text(payload.query, chunk["excerpt"])
            if score > 0:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: item[0], reverse=True)
        matches = []
        for score, chunk in ranked[:5]:
            matches.append({**chunk, "score": round(score, 2)})
        return RetrievalResult(
            mode="vector",
            template_key=capability,
            tables=sorted({match["table"] for match in matches}) if matches else ["clients.client_notes", "clients.property_details", "clients.client_details"],
            matches=matches,
            source_traces=[
                SourceTrace(
                    mode="vector",
                    label="property knowledge chunk retrieval",
                    tables=sorted({chunk["table"] for chunk in chunks}),
                    row_count=len(matches),
                    join_path=JOIN_MAP_CATALOG["property_knowledge"]["path"],
                    scope_client_ids=payload.scope.client_ids,
                    notes=["deterministic lexical similarity over approved read-only text chunks"],
                )
            ],
        )

    if capability == "media_recommendation":
        chunks = _load_media_chunks(client_id)
        ranked = []
        for chunk in chunks:
            score = _score_text(payload.query, chunk["excerpt"])
            if score > 0:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: item[0], reverse=True)
        matches = []
        for score, chunk in ranked[:5]:
            matches.append({**chunk, "fit": f"semantic text match score {round(score, 2)}"})
        return RetrievalResult(
            mode="vector",
            template_key=capability,
            tables=["media.media", "media.media_analysis_ai"],
            matches=matches,
            source_traces=[
                SourceTrace(
                    mode="vector",
                    label="media semantic retrieval",
                    tables=["media.media", "media.media_analysis_ai"],
                    row_count=len(matches),
                    join_path=JOIN_MAP_CATALOG["media_semantic"]["path"],
                    scope_client_ids=payload.scope.client_ids,
                    notes=["deterministic semantic-lite ranking over approved media analysis text"],
                )
            ],
        )

    if capability == "post_performance_lookup":
        chunks, notes = _load_metric_chunks(client_id)
        ranked: list[tuple[float, dict[str, Any]]] = []
        embedded_chunks = [chunk for chunk in chunks if vector_from_json(chunk.get("embedding_json"))]

        if embedded_chunks and embedding_enabled():
            try:
                query_vector = embed_texts([payload.query])[0]
                for chunk in embedded_chunks:
                    score = cosine_similarity(query_vector, vector_from_json(chunk.get("embedding_json")))
                    ranked.append((score, chunk))
                ranked.sort(key=lambda item: item[0], reverse=True)
                notes.append("ranked metric context with OpenAI query embedding against stored metric embeddings")
            except Exception as exc:
                notes.append(f"embedding ranking unavailable, fell back to lexical metric ranking: {exc}")
                ranked = []

        if not ranked:
            for chunk in chunks:
                score = _score_text(payload.query, str(chunk.get("excerpt") or ""))
                if payload.entities.channel and payload.entities.channel in _normalize(str(chunk.get("excerpt") or "")):
                    score += 2.0
                if any(word in payload.normalized_query for word in ("performance", "performing", "engagement", "likes", "comments")):
                    score += 1.0
                if score > 0:
                    ranked.append((score, chunk))
            ranked.sort(key=lambda item: item[0], reverse=True)

        matches = []
        for score, chunk in ranked[:5]:
            matches.append({**chunk, "fit": f"metric context score {round(float(score), 3)}"})
        tables = sorted({str(match.get("table")) for match in matches if match.get("table")})
        if not tables:
            tables = ["analytics.metric_embeddings"] if repository.table_exists("analytics", "metric_embeddings") else ["analytics.social_media_post"]
        return RetrievalResult(
            mode="vector",
            template_key=capability,
            tables=tables,
            matches=matches,
            source_traces=[
                SourceTrace(
                    mode="vector",
                    label="metric semantic retrieval",
                    tables=tables,
                    row_count=len(matches),
                    join_path=JOIN_MAP_CATALOG["content_performance"]["path"],
                    scope_client_ids=payload.scope.client_ids,
                    notes=notes,
                )
            ],
            support_notes=notes,
        )

    return RetrievalResult(mode="vector", template_key=capability, support_notes=["No vector retriever matched this capability."])
