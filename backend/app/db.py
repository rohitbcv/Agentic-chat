from __future__ import annotations

import json
import logging
import socket
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import paramiko
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sshtunnel import SSHTunnelForwarder

from os import getenv

# sshtunnel still references paramiko.DSSKey on some installs.
if not hasattr(paramiko, "DSSKey"):
    paramiko.DSSKey = paramiko.RSAKey

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()

logger = logging.getLogger("agent_chat")


def env_str(name: str, default: str = "") -> str:
    return (getenv(name) or default).strip()


def env_int(name: str, default: int) -> int:
    raw = env_str(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


SSH_HOST = env_str("SSH_HOST", "52.86.39.199")
SSH_PORT = env_int("SSH_PORT", 22)
SSH_USER = env_str("SSH_USER", "rohit")
SSH_PRIVATE_KEY = env_str("SSH_PRIVATE_KEY", "/root/comm_inbox/id_rsa")
REMOTE_DB_HOST = env_str("REMOTE_DB_HOST", "stage.86envbiv.bcv.social")
REMOTE_DB_PORT = env_int("REMOTE_DB_PORT", 5432)
DB_NAME = env_str("DB_NAME", "soho")
DB_USER = env_str("DB_USER", "pipelines")
DB_PASS = env_str("DB_PASS")
USE_DUMMY_DB = env_str("USE_DUMMY_DB", "false").lower() in {"1", "true", "yes", "on"}
DUMMY_DB_DIR = Path(env_str("DUMMY_DB_DIR", str(PROJECT_ROOT / "backend" / "app" / "data" / "dummy_db"))).expanduser()
DUMMY_SCHEMAS = ("clients", "content", "media", "analytics", "jx_bridge", "general", "world", "users", "organizations", "entity")


@dataclass
class DatabaseHandle:
    tunnel: SSHTunnelForwarder | None = None
    engine: Engine | None = None


class AgentChatRepository:
    def __init__(self) -> None:
        self._db: DatabaseHandle | None = None

    def is_dummy(self) -> bool:
        return USE_DUMMY_DB

    def _db_enabled(self) -> bool:
        if self.is_dummy():
            return (DUMMY_DB_DIR / "main.sqlite3").exists()
        return bool(DB_PASS) and Path(SSH_PRIVATE_KEY).exists()

    def _get_free_port(self) -> int:
        sock = socket.socket()
        sock.bind(("", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    def _connect(self) -> DatabaseHandle:
        if (
            self._db is not None
            and self._db.engine is not None
            and self._db.tunnel is not None
            and self._db.tunnel.is_active
        ):
            return self._db

        self.shutdown()

        if not self._db_enabled():
            raise RuntimeError("DB credentials are incomplete for a live connection.")

        local_port = self._get_free_port()
        tunnel = SSHTunnelForwarder(
            (SSH_HOST, SSH_PORT),
            ssh_config_file=None,
            ssh_username=SSH_USER,
            ssh_pkey=SSH_PRIVATE_KEY,
            allow_agent=False,
            host_pkey_directories=[],
            remote_bind_address=(REMOTE_DB_HOST, REMOTE_DB_PORT),
            local_bind_address=("127.0.0.1", local_port),
        )
        tunnel.start()

        db_url = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@127.0.0.1:{local_port}/{DB_NAME}"
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={"connect_timeout": 5},
        )
        self._db = DatabaseHandle(tunnel=tunnel, engine=engine)
        logger.info("Connected to agent chat database through SSH tunnel")
        return self._db

    def is_connected(self) -> bool:
        if not self._db_enabled():
            return False
        if self.is_dummy():
            try:
                conn = self._dummy_connection()
                conn.execute("SELECT 1")
                conn.close()
                return True
            except Exception:
                return False
        try:
            db = self._connect()
            if db.engine is None or db.tunnel is None or not db.tunnel.is_active:
                return False
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def shutdown(self) -> None:
        if self._db and self._db.engine is not None:
            self._db.engine.dispose()
        if self._db and self._db.tunnel is not None and self._db.tunnel.is_active:
            self._db.tunnel.stop()
        self._db = None

    def execute_query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self._db_enabled():
            return []
        if self.is_dummy():
            return self._execute_dummy_query(sql, params or {})
        for attempt in range(2):
            try:
                db = self._connect()
                if db.engine is None:
                    return []
                with db.engine.connect() as conn:
                    rows = conn.execute(text(sql), params or {}).mappings().fetchall()
                return [dict(row) for row in rows]
            except Exception as exc:
                logger.warning("execute_query failed on attempt %s: %s", attempt + 1, exc)
                self.shutdown()
        return []

    def table_exists(self, schema_name: str, table_name: str) -> bool:
        if not self._db_enabled():
            return False
        if self.is_dummy():
            try:
                conn = self._dummy_connection()
                rows = conn.execute(
                    f"SELECT name FROM {schema_name}.sqlite_master WHERE type = 'table' AND name = ?",
                    (table_name,),
                ).fetchall()
                conn.close()
                return bool(rows)
            except Exception:
                return False
        try:
            db = self._connect()
            if db.engine is None:
                return False
            with db.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = :schema_name
                          AND table_name = :table_name
                        LIMIT 1
                        """
                    ),
                    {"schema_name": schema_name, "table_name": table_name},
                ).first()
            return bool(row)
        except Exception as exc:
            logger.warning("table_exists failed for %s.%s: %s", schema_name, table_name, exc)
            return False

    def _dummy_connection(self) -> sqlite3.Connection:
        DUMMY_DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DUMMY_DB_DIR / "main.sqlite3")
        conn.row_factory = sqlite3.Row
        for schema in DUMMY_SCHEMAS:
            schema_path = (DUMMY_DB_DIR / f"{schema}.sqlite3").as_posix().replace("'", "''")
            conn.execute(f"ATTACH DATABASE '{schema_path}' AS {schema}")
        return conn

    def _execute_dummy_query(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            conn = self._dummy_connection()
            rows = conn.execute(sql, params).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.warning("dummy execute_query failed: %s", exc)
            return []

    def get_client_catalog(self) -> list[dict[str, Any]]:
        return self.execute_query(
            """
            SELECT
              c.id,
              c.name,
              c.organization_id,
              c.world_city_id
            FROM clients.clients c
            WHERE c.deleted_at IS NULL
            ORDER BY c.name ASC
            """
        )

    def get_client_notes(self, client_id: int) -> list[dict[str, Any]]:
        if not self._db_enabled():
            return []
        if self.is_dummy():
            return self.execute_query(
                """
                SELECT
                    cn.id,
                    cn.title,
                    cn.note,
                    CASE
                        WHEN cn.type_id = 3 THEN 'Response Templates'
                        WHEN cn.type_id = 2 THEN 'FAQ'
                        WHEN cn.type_id = 1 THEN 'General'
                        ELSE 'Note'
                    END AS note_type,
                    cn.type_id AS note_type_id,
                    cn.inserted_datetime,
                    cn.updated_datetime
                FROM clients.client_notes cn
                WHERE cn.client_id = :client_id
                  AND cn.deleted_at IS NULL
                ORDER BY cn.type_id, cn.inserted_datetime DESC, cn.id DESC
                """,
                {"client_id": client_id},
            )
        try:
            db = self._connect()
            if db.engine is None:
                return []
            with db.engine.connect() as conn:
                cols = {
                    str(row[0]).strip().lower()
                    for row in conn.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_schema = 'clients'
                              AND table_name = 'client_notes'
                            """
                        )
                    ).fetchall()
                }
                type_col = "type_id" if "type_id" in cols else ("notes_type_id" if "notes_type_id" in cols else None)
                type_expr = f"cn.{type_col}" if type_col else "NULL"
                order_prefix = f"{type_expr} NULLS LAST, " if type_col else ""
                sql = f"""
                SELECT
                    cn.id,
                    cn.title,
                    cn.note,
                    CASE
                        WHEN {type_expr} = 3 THEN 'Response Templates'
                        WHEN {type_expr} = 2 THEN 'FAQ'
                        WHEN {type_expr} = 1 THEN 'General'
                        ELSE 'Note'
                    END AS note_type,
                    {type_expr} AS note_type_id,
                    cn.inserted_datetime,
                    cn.updated_datetime
                FROM clients.client_notes cn
                WHERE cn.client_id = :client_id
                  AND cn.deleted_at IS NULL
                ORDER BY {order_prefix} cn.inserted_datetime DESC NULLS LAST, cn.id DESC
                """
                rows = conn.execute(text(sql), {"client_id": client_id}).mappings().fetchall()
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.warning("get_client_notes failed for client_id=%s: %s", client_id, exc)
            return []

    def get_property_detail_notes(self, client_id: int) -> list[dict[str, Any]]:
        if not self._db_enabled():
            return []
        if self.is_dummy():
            notes: list[dict[str, Any]] = []
            rows = self.execute_query(
                """
                SELECT location, highlights, amenities, overview, info,
                       food_and_beverages, inserted_datetime, updated_datetime, gallery
                FROM clients.property_details
                WHERE client_id = :client_id
                  AND deleted_at IS NULL
                ORDER BY updated_datetime DESC, inserted_datetime DESC
                LIMIT 1
                """,
                {"client_id": client_id},
            )
            if rows:
                pd_row = rows[0]
                parts = []
                for label, key in (
                    ("Overview", "overview"),
                    ("Location", "location"),
                    ("Amenities", "amenities"),
                    ("Food & Beverage", "food_and_beverages"),
                    ("Info", "info"),
                    ("Highlights", "highlights"),
                ):
                    value = pd_row.get(key)
                    if value:
                        parts.append(f"{label}: {value}")
                detail_text = "\n".join(parts).strip()
                if detail_text:
                    notes.append(
                        {
                            "id": f"pd-{client_id}",
                            "title": "Property details",
                            "note": detail_text[:5000],
                            "note_type": "Property Detail",
                            "note_type_id": None,
                            "inserted_datetime": pd_row.get("inserted_datetime"),
                            "updated_datetime": pd_row.get("updated_datetime"),
                        }
                    )
            rows = self.execute_query(
                """
                SELECT context, metadata, inserted_datetime, updated_datetime
                FROM clients.client_details
                WHERE client_id = :client_id
                  AND deleted_at IS NULL
                ORDER BY updated_datetime DESC, inserted_datetime DESC
                LIMIT 1
                """,
                {"client_id": client_id},
            )
            if rows:
                cd_row = rows[0]
                parts = []
                if cd_row.get("context"):
                    parts.append(str(cd_row.get("context")).strip())
                if cd_row.get("metadata"):
                    parts.append("Metadata: " + str(cd_row.get("metadata")))
                context_text = "\n".join(part for part in parts if part).strip()
                if context_text:
                    notes.append(
                        {
                            "id": f"cd-{client_id}",
                            "title": "Property context",
                            "note": context_text[:5000],
                            "note_type": "Property Detail",
                            "note_type_id": None,
                            "inserted_datetime": cd_row.get("inserted_datetime"),
                            "updated_datetime": cd_row.get("updated_datetime"),
                        }
                    )
            return notes
        try:
            db = self._connect()
            if db.engine is None:
                return []
            notes: list[dict[str, Any]] = []
            with db.engine.connect() as conn:
                pd_row = conn.execute(
                    text(
                        """
                        SELECT location, highlights, amenities, overview, info,
                               food_and_beverages, inserted_datetime, updated_datetime, gallery
                        FROM clients.property_details
                        WHERE client_id = :client_id
                          AND deleted_at IS NULL
                        ORDER BY updated_datetime DESC NULLS LAST, inserted_datetime DESC NULLS LAST
                        LIMIT 1
                        """
                    ),
                    {"client_id": client_id},
                ).mappings().first()
                if pd_row:
                    parts: list[str] = []
                    if pd_row.get("overview"):
                        parts.append(f"Overview: {str(pd_row.get('overview')).strip()}")
                    if pd_row.get("location"):
                        parts.append(f"Location: {str(pd_row.get('location')).strip()}")
                    if pd_row.get("amenities"):
                        amenities = pd_row.get("amenities")
                        if isinstance(amenities, list):
                            parts.append("Amenities: " + ", ".join(str(item) for item in amenities if str(item).strip()))
                        else:
                            parts.append("Amenities: " + str(amenities))
                    if pd_row.get("food_and_beverages"):
                        parts.append("Food & Beverage: " + json.dumps(pd_row.get("food_and_beverages"), ensure_ascii=False))
                    if pd_row.get("info"):
                        parts.append("Info: " + json.dumps(pd_row.get("info"), ensure_ascii=False))
                    if pd_row.get("highlights"):
                        parts.append("Highlights: " + json.dumps(pd_row.get("highlights"), ensure_ascii=False))
                    detail_text = "\n".join(part for part in parts if part).strip()
                    if detail_text:
                        notes.append(
                            {
                                "id": f"pd-{client_id}",
                                "title": "Property details",
                                "note": detail_text[:5000],
                                "note_type": "Property Detail",
                                "note_type_id": None,
                                "inserted_datetime": pd_row.get("inserted_datetime"),
                                "updated_datetime": pd_row.get("updated_datetime"),
                            }
                        )

                cd_row = conn.execute(
                    text(
                        """
                        SELECT context, metadata, inserted_datetime, updated_datetime
                        FROM clients.client_details
                        WHERE client_id = :client_id
                          AND deleted_at IS NULL
                        ORDER BY updated_datetime DESC NULLS LAST, inserted_datetime DESC NULLS LAST
                        LIMIT 1
                        """
                    ),
                    {"client_id": client_id},
                ).mappings().first()
                if cd_row:
                    context_parts: list[str] = []
                    if cd_row.get("context"):
                        context_parts.append(str(cd_row.get("context")).strip())
                    if cd_row.get("metadata"):
                        context_parts.append("Metadata: " + json.dumps(cd_row.get("metadata"), ensure_ascii=False))
                    context_text = "\n".join(part for part in context_parts if part).strip()
                    if context_text:
                        notes.append(
                            {
                                "id": f"cd-{client_id}",
                                "title": "Property context",
                                "note": context_text[:5000],
                                "note_type": "Property Detail",
                                "note_type_id": None,
                                "inserted_datetime": cd_row.get("inserted_datetime"),
                                "updated_datetime": cd_row.get("updated_datetime"),
                            }
                        )
            return notes
        except Exception as exc:
            logger.warning("get_property_detail_notes failed for client_id=%s: %s", client_id, exc)
            return []


repository = AgentChatRepository()
