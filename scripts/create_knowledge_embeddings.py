from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.services.embeddings import content_hash, embed_texts, embedding_enabled, embedding_model, vector_to_json

load_dotenv(ROOT / ".env")
load_dotenv()

DEFAULT_DB_DIR = ROOT / "backend" / "app" / "data" / "dummy_db"
SCHEMAS = ("clients", "content", "media", "general")


def connect(db_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_dir / "main.sqlite3")
    conn.row_factory = sqlite3.Row
    for schema in SCHEMAS:
        conn.execute(f"ATTACH DATABASE '{(db_dir / f'{schema}.sqlite3').as_posix()}' AS {schema}")
    return conn


def ensure_knowledge_embedding_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS general.knowledge_embeddings (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            source_table TEXT NOT NULL,
            source_pk INTEGER NOT NULL,
            source_ref TEXT,
            source_kind TEXT NOT NULL,
            knowledge_domain TEXT NOT NULL,
            chunk_label TEXT,
            knowledge_document TEXT NOT NULL,
            embedding_model TEXT,
            embedding_json TEXT,
            content_hash TEXT UNIQUE,
            inserted_datetime TEXT,
            updated_datetime TEXT
        )
        """
    )


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    raw = str(value).strip()
    if not raw:
        return ""
    if raw.startswith("{") or raw.startswith("["):
        try:
            return json.dumps(json.loads(raw), ensure_ascii=False)
        except Exception:
            return raw
    return raw


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    raw = str(value).strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
        except Exception:
            pass
    return [item.strip() for item in raw.split(",") if item.strip()]


def _document(
    *,
    client_name: str,
    source_kind: str,
    label: str,
    body: str,
    aliases: list[str] | None = None,
) -> str:
    alias_text = f" Aliases: {', '.join(aliases)}." if aliases else ""
    return f"Client: {client_name}. Source type: {source_kind}. Section: {label}. Content: {body}.{alias_text}"


def _base_row(
    *,
    client_id: int,
    source_table: str,
    source_pk: int,
    source_ref: str | None,
    source_kind: str,
    knowledge_domain: str,
    chunk_label: str,
    knowledge_document: str,
) -> dict[str, Any]:
    return {
        "client_id": client_id,
        "source_table": source_table,
        "source_pk": source_pk,
        "source_ref": source_ref,
        "source_kind": source_kind,
        "knowledge_domain": knowledge_domain,
        "chunk_label": chunk_label,
        "knowledge_document": knowledge_document,
        "content_hash": content_hash(knowledge_document),
    }


def load_client_note_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT cn.id, cn.client_id, c.name AS client_name, cn.title, cn.note, cn.type_id
        FROM clients.client_notes cn
        JOIN clients.clients c ON c.id = cn.client_id
        WHERE cn.deleted_at IS NULL
          AND c.deleted_at IS NULL
          AND COALESCE(cn.note, '') <> ''
        ORDER BY cn.client_id, cn.id
        """
    ).fetchall()
    docs = []
    for row in rows:
        type_id = int(row["type_id"] or 0)
        source_kind = "faq" if type_id == 2 else ("response_template" if type_id == 3 else "client_note")
        title = str(row["title"] or source_kind).strip()
        body = _as_text(row["note"])
        aliases = ["FAQ", "guest question", "property note", "operational note"]
        docs.append(
            _base_row(
                client_id=int(row["client_id"]),
                source_table="clients.client_notes",
                source_pk=int(row["id"]),
                source_ref=title,
                source_kind=source_kind,
                knowledge_domain="property_knowledge",
                chunk_label=title,
                knowledge_document=_document(client_name=row["client_name"], source_kind=source_kind, label=title, body=body, aliases=aliases),
            )
        )
    return docs


def load_property_detail_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT pd.*, c.name AS client_name
        FROM clients.property_details pd
        JOIN clients.clients c ON c.id = pd.client_id
        WHERE pd.deleted_at IS NULL
          AND c.deleted_at IS NULL
        ORDER BY pd.client_id, pd.id
        """
    ).fetchall()
    docs = []
    sections = [
        ("overview", "overview", ["summary", "about property", "what do we know"]),
        ("location", "location", ["where is it", "city", "address"]),
        ("amenities", "amenities", ["facilities", "pool", "wifi", "breakfast", "service"]),
        ("food_and_beverages", "food and beverage", ["breakfast", "restaurant", "bar", "dining"]),
        ("info", "property info", ["check in", "check out", "policy", "rules"]),
        ("highlights", "highlights", ["selling points", "features", "experience"]),
    ]
    for row in rows:
        for key, label, aliases in sections:
            body = _as_text(row[key])
            if not body:
                continue
            docs.append(
                _base_row(
                    client_id=int(row["client_id"]),
                    source_table="clients.property_details",
                    source_pk=int(row["id"]),
                    source_ref=key,
                    source_kind="property_detail",
                    knowledge_domain="property_knowledge",
                    chunk_label=label,
                    knowledge_document=_document(client_name=row["client_name"], source_kind="property_detail", label=label, body=body, aliases=aliases),
                )
            )
    return docs


def load_client_detail_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT cd.id, cd.client_id, c.name AS client_name, cd.context, cd.metadata
        FROM clients.client_details cd
        JOIN clients.clients c ON c.id = cd.client_id
        WHERE cd.deleted_at IS NULL
          AND c.deleted_at IS NULL
        ORDER BY cd.client_id, cd.id
        """
    ).fetchall()
    docs = []
    for row in rows:
        body = " ".join(part for part in (_as_text(row["context"]), _as_text(row["metadata"])) if part)
        if not body:
            continue
        docs.append(
            _base_row(
                client_id=int(row["client_id"]),
                source_table="clients.client_details",
                source_pk=int(row["id"]),
                source_ref="client_context",
                source_kind="client_context",
                knowledge_domain="property_knowledge",
                chunk_label="client context",
                knowledge_document=_document(
                    client_name=row["client_name"],
                    source_kind="client_context",
                    label="client context",
                    body=body,
                    aliases=["profile", "summary", "metadata", "about client"],
                ),
            )
        )
    return docs


def load_tone_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT tov.id, tov.client_id, c.name AS client_name, tov.custom_guidelines, tov.use_words, tov.avoid_words
        FROM clients.client_tone_of_voice_settings tov
        JOIN clients.clients c ON c.id = tov.client_id
        WHERE tov.deleted_at IS NULL
          AND c.deleted_at IS NULL
        ORDER BY tov.client_id, tov.id
        """
    ).fetchall()
    docs = []
    for row in rows:
        parts = [_as_text(row["custom_guidelines"])]
        use_words = _as_text_list(row["use_words"])
        avoid_words = _as_text_list(row["avoid_words"])
        if use_words:
            parts.append("Use words: " + ", ".join(use_words))
        if avoid_words:
            parts.append("Avoid words: " + ", ".join(avoid_words))
        body = " ".join(part for part in parts if part)
        if not body:
            continue
        docs.append(
            _base_row(
                client_id=int(row["client_id"]),
                source_table="clients.client_tone_of_voice_settings",
                source_pk=int(row["id"]),
                source_ref="tone_of_voice",
                source_kind="tone_of_voice",
                knowledge_domain="tone",
                chunk_label="tone of voice",
                knowledge_document=_document(
                    client_name=row["client_name"],
                    source_kind="tone_of_voice",
                    label="tone of voice",
                    body=body,
                    aliases=["brand voice", "writing style", "reply style", "use words", "avoid words"],
                ),
            )
        )
    return docs


def load_audience_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT cta.id, cta.client_id, c.name AS client_name, cta.audience, cta.is_custom
        FROM clients.client_target_audience cta
        JOIN clients.clients c ON c.id = cta.client_id
        WHERE cta.deleted_at IS NULL
          AND c.deleted_at IS NULL
          AND COALESCE(cta.audience, '') <> ''
        ORDER BY cta.client_id, cta.id
        """
    ).fetchall()
    docs = []
    for row in rows:
        source_kind = "custom_audience" if row["is_custom"] else "target_audience"
        body = _as_text(row["audience"])
        docs.append(
            _base_row(
                client_id=int(row["client_id"]),
                source_table="clients.client_target_audience",
                source_pk=int(row["id"]),
                source_ref=body[:120],
                source_kind=source_kind,
                knowledge_domain="audience",
                chunk_label="target audience",
                knowledge_document=_document(
                    client_name=row["client_name"],
                    source_kind=source_kind,
                    label="target audience",
                    body=body,
                    aliases=["audience", "targeting", "guest segment", "traveler segment"],
                ),
            )
        )
    return docs


def load_audience_suggestion_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ctas.id, ctas.client_id, c.name AS client_name, ctas.audience
        FROM clients.client_target_audience_suggestions ctas
        JOIN clients.clients c ON c.id = ctas.client_id
        WHERE ctas.deleted_at IS NULL
          AND c.deleted_at IS NULL
          AND COALESCE(ctas.audience, '') <> ''
        ORDER BY ctas.client_id, ctas.id
        """
    ).fetchall()
    docs = []
    for row in rows:
        body = _as_text(row["audience"])
        docs.append(
            _base_row(
                client_id=int(row["client_id"]),
                source_table="clients.client_target_audience_suggestions",
                source_pk=int(row["id"]),
                source_ref=body[:120],
                source_kind="audience_suggestion",
                knowledge_domain="audience",
                chunk_label="audience suggestion",
                knowledge_document=_document(
                    client_name=row["client_name"],
                    source_kind="audience_suggestion",
                    label="audience suggestion",
                    body=body,
                    aliases=["audience", "targeting", "recommended segment", "potential traveler segment"],
                ),
            )
        )
    return docs


def load_social_account_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          csna.id,
          csna.client_id,
          c.name AS client_name,
          snt.description AS social_network,
          csna.social_network_user_name,
          csna.social_network_url,
          csna.social_network_name,
          csna.additional_data
        FROM clients.client_social_network_account csna
        JOIN clients.clients c ON c.id = csna.client_id
        LEFT JOIN general.social_network_type snt ON snt.id = csna.social_network_type_id
        WHERE csna.deleted_at IS NULL
          AND c.deleted_at IS NULL
        ORDER BY csna.client_id, csna.id
        """
    ).fetchall()
    docs = []
    for row in rows:
        body = (
            f"Network: {row['social_network']}. "
            f"Handle: {row['social_network_user_name']}. "
            f"URL: {row['social_network_url']}. "
            f"Account name: {row['social_network_name']}. "
            f"Metadata: {_as_text(row['additional_data'])}"
        )
        docs.append(
            _base_row(
                client_id=int(row["client_id"]),
                source_table="clients.client_social_network_account",
                source_pk=int(row["id"]),
                source_ref=str(row["social_network"] or ""),
                source_kind="social_account",
                knowledge_domain="property_knowledge",
                chunk_label=str(row["social_network"] or "social account"),
                knowledge_document=_document(
                    client_name=row["client_name"],
                    source_kind="social_account",
                    label=str(row["social_network"] or "social account"),
                    body=body,
                    aliases=["channel", "social account", "handle", "platform"],
                ),
            )
        )
    return docs


def load_media_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          mai.id,
          m.client_id,
          c.name AS client_name,
          m.id AS media_id,
          m.name,
          m.description,
          mai.short_description,
          mai.alt_text,
          mai.visual_tags,
          mai.descriptive_tags,
          mai.semantic_keywords,
          mai.post_copy
        FROM media.media_analysis_ai mai
        JOIN media.media m ON m.id = mai.media_id
        JOIN clients.clients c ON c.id = m.client_id
        WHERE mai.deleted_at IS NULL
          AND m.deleted_at IS NULL
          AND c.deleted_at IS NULL
        ORDER BY m.client_id, mai.id
        """
    ).fetchall()
    docs = []
    for row in rows:
        tags = _as_text_list(row["visual_tags"]) + _as_text_list(row["descriptive_tags"]) + _as_text_list(row["semantic_keywords"])
        body = " ".join(
            part
            for part in (
                _as_text(row["name"]),
                _as_text(row["description"]),
                _as_text(row["short_description"]),
                _as_text(row["alt_text"]),
                "Tags: " + ", ".join(tags) if tags else "",
                _as_text(row["post_copy"]),
            )
            if part
        )
        if not body:
            continue
        docs.append(
            _base_row(
                client_id=int(row["client_id"]),
                source_table="media.media_analysis_ai",
                source_pk=int(row["id"]),
                source_ref=str(row["media_id"]),
                source_kind="media_analysis",
                knowledge_domain="media",
                chunk_label=str(row["name"] or f"media {row['media_id']}"),
                knowledge_document=_document(
                    client_name=row["client_name"],
                    source_kind="media_analysis",
                    label=str(row["name"] or "media asset"),
                    body=body,
                    aliases=["image", "photo", "visual", "asset", "campaign creative"],
                ),
            )
        )
    return docs


def load_post_copy_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          ctp.id,
          ct.client_id,
          c.name AS client_name,
          ct.name AS topic_name,
          snt.description AS social_network,
          ctp.post_datetime,
          ctp.post_text
        FROM content.content_topic_post ctp
        JOIN content.content_topic ct ON ct.id = ctp.content_topic_id
        JOIN clients.clients c ON c.id = ct.client_id
        LEFT JOIN general.social_network_type snt ON snt.id = ctp.social_network_type_id
        WHERE ctp.deleted_at IS NULL
          AND c.deleted_at IS NULL
          AND COALESCE(ctp.post_text, '') <> ''
        ORDER BY ct.client_id, ctp.id
        """
    ).fetchall()
    docs = []
    for row in rows:
        body = (
            f"Topic: {row['topic_name']}. Network: {row['social_network']}. "
            f"Post date: {row['post_datetime']}. Copy: {row['post_text']}"
        )
        docs.append(
            _base_row(
                client_id=int(row["client_id"]),
                source_table="content.content_topic_post",
                source_pk=int(row["id"]),
                source_ref=str(row["social_network"] or ""),
                source_kind="post_copy",
                knowledge_domain="content",
                chunk_label=str(row["topic_name"] or "post copy"),
                knowledge_document=_document(
                    client_name=row["client_name"],
                    source_kind="post_copy",
                    label=str(row["topic_name"] or "post copy"),
                    body=body,
                    aliases=["caption", "post copy", "content theme", "social post"],
                ),
            )
        )
    return docs


def load_knowledge_documents(conn: sqlite3.Connection, limit: int | None = None) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    documents.extend(load_client_note_documents(conn))
    documents.extend(load_property_detail_documents(conn))
    documents.extend(load_client_detail_documents(conn))
    documents.extend(load_tone_documents(conn))
    documents.extend(load_audience_documents(conn))
    documents.extend(load_audience_suggestion_documents(conn))
    documents.extend(load_social_account_documents(conn))
    documents.extend(load_media_documents(conn))
    documents.extend(load_post_copy_documents(conn))
    if limit is not None:
        return documents[:limit]
    return documents


def upsert_knowledge_embeddings(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT INTO general.knowledge_embeddings
        (client_id, source_table, source_pk, source_ref, source_kind, knowledge_domain, chunk_label,
         knowledge_document, embedding_model, embedding_json, content_hash, inserted_datetime, updated_datetime)
        VALUES
        (:client_id, :source_table, :source_pk, :source_ref, :source_kind, :knowledge_domain, :chunk_label,
         :knowledge_document, :embedding_model, :embedding_json, :content_hash, :inserted_datetime, :updated_datetime)
        ON CONFLICT(content_hash) DO UPDATE SET
          source_ref = excluded.source_ref,
          source_kind = excluded.source_kind,
          knowledge_domain = excluded.knowledge_domain,
          chunk_label = excluded.chunk_label,
          knowledge_document = excluded.knowledge_document,
          embedding_model = excluded.embedding_model,
          embedding_json = excluded.embedding_json,
          updated_datetime = excluded.updated_datetime
        """,
        [
            {
                **row,
                "inserted_datetime": now,
                "updated_datetime": now,
            }
            for row in rows
        ],
    )


def build_embeddings(documents: list[dict[str, Any]], batch_size: int) -> list[dict[str, Any]]:
    model = embedding_model()
    embedded_rows: list[dict[str, Any]] = []
    for start in range(0, len(documents), batch_size):
        batch = documents[start : start + batch_size]
        vectors = embed_texts([row["knowledge_document"] for row in batch], model=model)
        for row, vector in zip(batch, vectors):
            embedded_rows.append(
                {
                    **row,
                    "embedding_model": model,
                    "embedding_json": vector_to_json(vector),
                }
            )
    return embedded_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Create local knowledge embeddings for the Agent Chat dummy DB.")
    parser.add_argument("--db-dir", default=str(DEFAULT_DB_DIR), help="Path to backend/app/data/dummy_db")
    parser.add_argument("--limit", type=int, default=0, help="Maximum documents to embed; 0 means all")
    parser.add_argument("--batch-size", type=int, default=32, help="OpenAI embedding batch size")
    parser.add_argument("--dry-run", action="store_true", help="Build documents without calling OpenAI or writing embeddings")
    args = parser.parse_args()

    db_dir = Path(args.db_dir).expanduser()
    conn = connect(db_dir)
    ensure_knowledge_embedding_table(conn)
    documents = load_knowledge_documents(conn, limit=args.limit or None)

    if args.dry_run:
        print(f"Knowledge documents ready: {len(documents)}")
        counts: dict[str, int] = {}
        for row in documents:
            counts[row["knowledge_domain"]] = counts.get(row["knowledge_domain"], 0) + 1
        for domain, count in sorted(counts.items()):
            print(f"{domain}: {count}")
        if documents:
            print(documents[0]["knowledge_document"])
        conn.close()
        return 0

    if not embedding_enabled():
        print("OPENAI_API_KEY is missing. Add it to .env before generating embeddings.")
        conn.close()
        return 1

    embedded_rows = build_embeddings(documents, max(1, args.batch_size))
    upsert_knowledge_embeddings(conn, embedded_rows)
    conn.commit()
    conn.close()
    print(f"Embedded {len(embedded_rows)} knowledge document(s) with {embedding_model()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
