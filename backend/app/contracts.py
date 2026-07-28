from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(inner) for key, inner in value.items()}
    return value


@dataclass
class DateRange:
    label: str | None = None
    start: date | None = None
    end: date | None = None
    grain: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass
class ExtractedEntities:
    user_id: int | None = None
    organization_id: int | None = None
    client_id: int | None = None
    property_name: str | None = None
    city: str | None = None
    channel: str | None = None
    thread_id: str | None = None
    event: str | None = None
    audience: str | None = None
    topic: str | None = None
    media_theme: str | None = None
    date_range: DateRange | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["date_range"] = self.date_range.to_dict() if self.date_range else None
        return _json_safe(payload)


@dataclass
class AccessScope:
    organization_ids: list[int] = field(default_factory=list)
    client_ids: list[int] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    scope_source: str = "default"

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass
class RoutingPayload:
    query: str
    cleaned_query: str
    normalized_query: str
    language: str
    intent: str
    entities: ExtractedEntities
    scope: AccessScope

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "cleaned_query": self.cleaned_query,
            "normalized_query": self.normalized_query,
            "language": self.language,
            "intent": self.intent,
            "entities": self.entities.to_dict(),
            "scope": self.scope.to_dict(),
        }


@dataclass
class SourceTrace:
    mode: str
    label: str
    tables: list[str] = field(default_factory=list)
    row_count: int | None = None
    sql: str | None = None
    join_path: list[str] = field(default_factory=list)
    scope_client_ids: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass
class RetrievalResult:
    mode: str
    template_key: str | None = None
    tables: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    sql: str | None = None
    matches: list[dict[str, Any]] = field(default_factory=list)
    source_traces: list[SourceTrace] = field(default_factory=list)
    support_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "template_key": self.template_key,
            "tables": self.tables,
            "rows": _json_safe(self.rows),
            "sql": self.sql,
            "matches": _json_safe(self.matches),
            "source_traces": [trace.to_dict() for trace in self.source_traces],
            "support_notes": self.support_notes,
        }


@dataclass
class OrchestratorDecision:
    capability: str
    intent: str
    agent_name: str
    domain: str
    rationale: str
    confidence: float
    capability_state: str
    retriever_modes: list[str] = field(default_factory=list)
    template_keys: list[str] = field(default_factory=list)
    join_paths: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    branch: str = "retrieve"
    clarification_question: str | None = None
    refusal_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))
