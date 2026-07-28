from __future__ import annotations

from datetime import datetime, timezone
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import repository
from .poc.api import router as agent_poc_router
from .read_only import AgentReadOnlyGuardMiddleware

logger = logging.getLogger("agent_chat")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(handler)


app = FastAPI(title="Agent chat", version="0.1.0")
app.add_middleware(AgentReadOnlyGuardMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "Origin", "X-Requested-With"],
)
app.include_router(agent_poc_router)


@app.get("/")
def root() -> dict[str, object]:
    return {
        "product": "Agent chat",
        "read_only": True,
        "status": "ok",
    }


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "db_connected": repository.is_connected(),
        "db_mode": "dummy" if repository.is_dummy() else "real",
        "read_only": True,
        "product": "Agent chat",
    }


@app.on_event("shutdown")
def shutdown() -> None:
    repository.shutdown()
