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
from backend.app.services.retrievers import extract_analytics_snapshot

load_dotenv(ROOT / ".env")
load_dotenv()

DEFAULT_DB_DIR = ROOT / "backend" / "app" / "data" / "dummy_db"
SCHEMAS = ("clients", "content", "media", "analytics", "general")


def connect(db_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_dir / "main.sqlite3")
    conn.row_factory = sqlite3.Row
    for schema in SCHEMAS:
        conn.execute(f"ATTACH DATABASE '{(db_dir / f'{schema}.sqlite3').as_posix()}' AS {schema}")
    return conn


def ensure_metric_embedding_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics.metric_embeddings (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            source_table TEXT NOT NULL,
            source_pk INTEGER NOT NULL,
            source_ref TEXT,
            source_kind TEXT NOT NULL,
            metric_document TEXT NOT NULL,
            metric_names TEXT,
            embedding_model TEXT,
            embedding_json TEXT,
            content_hash TEXT UNIQUE,
            inserted_datetime TEXT,
            updated_datetime TEXT
        )
        """
    )


def _compact_metric_line(snapshot: dict[str, Any]) -> str:
    metric_parts = []
    for key in ("likes", "comments", "reactions", "shares", "reach", "impressions"):
        value = snapshot.get(key)
        if value is not None:
            metric_parts.append(f"{key}={value}")
    return ", ".join(metric_parts) if metric_parts else "no normalized metric values resolved"


def load_metric_documents(conn: sqlite3.Connection, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
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
        WHERE asp.deleted_at IS NULL
          AND ctp.deleted_at IS NULL
          AND c.deleted_at IS NULL
        ORDER BY ctp.post_datetime DESC, asp.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    documents: list[dict[str, Any]] = []
    for row in rows:
        row_dict = dict(row)
        snapshot = extract_analytics_snapshot(row_dict)
        metric_line = _compact_metric_line(snapshot)
        metric_names = [key for key in ("likes", "comments", "reactions", "shares", "reach", "impressions") if snapshot.get(key) is not None]
        aliases = "engagement, interactions, post performance, social analytics, latest post metrics, reach, impressions"
        document = (
            f"Client: {row_dict.get('client_name')}. "
            f"Network: {row_dict.get('social_network')}. "
            f"Post date: {row_dict.get('post_datetime')}. "
            f"Caption: {row_dict.get('post_text')}. "
            f"Available metric snapshot: {metric_line}. "
            f"Metric aliases: {aliases}."
        )
        documents.append(
            {
                "client_id": int(row_dict["client_id"]),
                "source_table": "analytics.social_media_post",
                "source_pk": int(row_dict["analytics_id"]),
                "source_ref": row_dict.get("network_post_ref"),
                "source_kind": "post_metric_snapshot",
                "metric_document": document,
                "metric_names": json.dumps(metric_names),
                "content_hash": content_hash(document),
            }
        )
    return documents


def upsert_metric_embeddings(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        INSERT INTO analytics.metric_embeddings
        (client_id, source_table, source_pk, source_ref, source_kind, metric_document, metric_names,
         embedding_model, embedding_json, content_hash, inserted_datetime, updated_datetime)
        VALUES
        (:client_id, :source_table, :source_pk, :source_ref, :source_kind, :metric_document, :metric_names,
         :embedding_model, :embedding_json, :content_hash, :inserted_datetime, :updated_datetime)
        ON CONFLICT(content_hash) DO UPDATE SET
          metric_document = excluded.metric_document,
          metric_names = excluded.metric_names,
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
        vectors = embed_texts([row["metric_document"] for row in batch], model=model)
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
    parser = argparse.ArgumentParser(description="Create local metric embeddings for the Agent Chat dummy DB.")
    parser.add_argument("--db-dir", default=str(DEFAULT_DB_DIR), help="Path to backend/app/data/dummy_db")
    parser.add_argument("--limit", type=int, default=500, help="Maximum analytics rows to embed")
    parser.add_argument("--batch-size", type=int, default=32, help="OpenAI embedding batch size")
    parser.add_argument("--dry-run", action="store_true", help="Build documents without calling OpenAI or writing embeddings")
    args = parser.parse_args()

    db_dir = Path(args.db_dir).expanduser()
    conn = connect(db_dir)
    ensure_metric_embedding_table(conn)
    documents = load_metric_documents(conn, args.limit)

    if args.dry_run:
        print(f"Metric documents ready: {len(documents)}")
        if documents:
            print(documents[0]["metric_document"])
        conn.close()
        return 0

    if not embedding_enabled():
        print("OPENAI_API_KEY is missing. Add it to .env before generating embeddings.")
        conn.close()
        return 1

    embedded_rows = build_embeddings(documents, max(1, args.batch_size))
    upsert_metric_embeddings(conn, embedded_rows)
    conn.commit()
    conn.close()
    print(f"Embedded {len(embedded_rows)} metric document(s) with {embedding_model()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
