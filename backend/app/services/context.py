from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from ..contracts import OrchestratorDecision, RetrievalResult, RoutingPayload


@dataclass
class MergedContext:
    answerable: bool
    confidence_score: float
    confidence_label: str
    support_level: str
    primary_retrieval: str
    evidence_count: int
    ranked_sources: list[dict[str, Any]] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    clarification_question: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SQL_EXACT_CAPABILITIES = {
    "client_access_lookup",
    "competitor_lookup",
    "relationship_lookup",
    "content_schedule_lookup",
    "content_approval_lookup",
    "content_post_detail_lookup",
    "post_performance_lookup",
    "inbox_lookup",
    "event_lookup",
}

CLIENT_REQUIRED_CAPABILITIES = {
    "client_access_lookup",
    "competitor_lookup",
    "relationship_lookup",
    "content_schedule_lookup",
    "content_approval_lookup",
    "content_post_detail_lookup",
    "post_performance_lookup",
    "inbox_lookup",
    "event_lookup",
    "property_fact_lookup",
    "property_knowledge_summary",
    "tone_of_voice_lookup",
    "audience_lookup",
    "media_recommendation",
}

TABLE_TRUST_PRIORITY = {
    "clients.client_notes": 1,
    "clients.property_details": 2,
    "clients.client_details": 3,
    "clients.client_tone_of_voice_settings": 4,
    "clients.client_target_audience": 5,
    "clients.client_marketing_settings": 6,
    "content.content_topic_post": 6,
    "analytics.social_media_post": 7,
    "analytics.metric_embeddings": 8,
    "general.knowledge_embeddings": 9,
    "media.media_analysis_ai": 10,
}

GENERIC_NAME_TOKENS = {"and", "at", "collection", "group", "hotel", "hotels", "motel", "palace", "property", "resort", "resorts", "the"}


def _label(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def _result_count(result: RetrievalResult | None) -> int:
    if not result:
        return 0
    return len(result.rows) + len(result.matches)


def _snapshot_has_metrics(row: dict[str, Any]) -> bool:
    snapshot = row.get("analytics_snapshot")
    if not isinstance(snapshot, dict):
        return False
    return any(snapshot.get(key) is not None for key in ("likes", "comments", "reactions", "shares", "reach", "impressions"))


def _name_tokens(value: Any) -> set[str]:
    normalized = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    return {token for token in normalized.split() if len(token) > 1 and token not in GENERIC_NAME_TOKENS}


def _names_conflict(left: Any, right: Any) -> bool:
    left_tokens = _name_tokens(left)
    right_tokens = _name_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    return not bool(left_tokens & right_tokens)


def _ranked_sources(sql_result: RetrievalResult | None, vector_result: RetrievalResult | None) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if sql_result:
        for index, trace in enumerate(sql_result.source_traces):
            sources.append(
                {
                    "rank": len(sources) + 1,
                    "mode": "sql",
                    "label": trace.label,
                    "tables": trace.tables,
                    "row_count": trace.row_count or 0,
                    "trust_weight": 1.0,
                    "reason": "exact relational evidence",
                    "source_order": index,
                }
            )
    if vector_result:
        for index, trace in enumerate(vector_result.source_traces):
            table_priority = min((TABLE_TRUST_PRIORITY.get(table, 99) for table in trace.tables), default=99)
            sources.append(
                {
                    "rank": len(sources) + 1,
                    "mode": "vector",
                    "label": trace.label,
                    "tables": trace.tables,
                    "row_count": trace.row_count or 0,
                    "trust_weight": 0.72,
                    "reason": "semantic supporting evidence",
                    "source_order": table_priority + index,
                }
            )
    sources.sort(key=lambda item: (-float(item["trust_weight"]), int(item["source_order"])))
    for index, source in enumerate(sources, start=1):
        source["rank"] = index
    return sources


def _scope_contradictions(payload: RoutingPayload, *results: RetrievalResult | None) -> list[str]:
    contradictions: list[str] = []
    client_id = payload.entities.client_id
    if client_id is None:
        return contradictions
    for result in results:
        if not result:
            continue
        for row in result.rows:
            row_client_id = row.get("client_id")
            if row_client_id is not None and int(row_client_id) != int(client_id):
                contradictions.append(f"row client_id {row_client_id} did not match resolved client_id {client_id}")
            row_client_name = row.get("client_name")
            if payload.entities.property_name and row_client_name and _names_conflict(payload.entities.property_name, row_client_name):
                contradictions.append(f"row client_name {row_client_name} did not match resolved property {payload.entities.property_name}")
        for match in result.matches:
            match_client_id = match.get("client_id")
            if match_client_id is not None and int(match_client_id) != int(client_id):
                contradictions.append(f"match client_id {match_client_id} did not match resolved client_id {client_id}")
            match_client_name = match.get("client_name")
            if payload.entities.property_name and match_client_name and _names_conflict(payload.entities.property_name, match_client_name):
                contradictions.append(f"match client_name {match_client_name} did not match resolved property {payload.entities.property_name}")
    return contradictions


def merge_retrieval_context(
    payload: RoutingPayload,
    decision: OrchestratorDecision,
    sql_result: RetrievalResult | None,
    vector_result: RetrievalResult | None,
) -> MergedContext:
    missing_fields: list[str] = []
    notes: list[str] = []

    if decision.branch == "clarification":
        return MergedContext(
            answerable=False,
            confidence_score=0.35,
            confidence_label="low",
            support_level="not_supported",
            primary_retrieval="clarification",
            evidence_count=0,
            missing_fields=["client_id_or_property_name"],
            notes=["intake could not resolve enough scope for a safe retrieval"],
            clarification_question=decision.clarification_question,
        )

    if payload.entities.client_id is None and decision.capability in CLIENT_REQUIRED_CAPABILITIES:
        missing_fields.append("client_id")

    evidence_count = _result_count(sql_result) + _result_count(vector_result)
    ranked_sources = _ranked_sources(sql_result, vector_result)
    contradictions = _scope_contradictions(payload, sql_result, vector_result)

    if decision.capability_state == "not_supported":
        score = 0.9 if decision.branch == "unsupported_action" or decision.capability == "pricing_lookup" else 0.35
        return MergedContext(
            answerable=True,
            confidence_score=score,
            confidence_label=_label(score),
            support_level="not_supported",
            primary_retrieval="policy",
            evidence_count=evidence_count,
            ranked_sources=ranked_sources,
            missing_fields=missing_fields,
            contradictions=contradictions,
            notes=["the system can explain the limitation but cannot produce the requested factual or mutable outcome"],
        )

    sql_count = _result_count(sql_result)
    vector_count = _result_count(vector_result)
    primary_retrieval = "none"
    score = 0.35
    answerable = False

    if sql_result and decision.capability in SQL_EXACT_CAPABILITIES:
        primary_retrieval = "sql"
        answerable = True
        score = 0.88 if sql_count else 0.78
        notes.append("SQL was ranked above semantic retrieval for exact records, statuses, dates, counts, and metric values.")

    if vector_result and not sql_result:
        primary_retrieval = "vector"
        answerable = bool(vector_count)
        score = 0.76 if vector_count else 0.36
        notes.append("Vector retrieval is the primary evidence path for this knowledge-style request.")

    if sql_result and vector_result:
        primary_retrieval = "sql+vector"
        answerable = True
        score = max(score, 0.82 if vector_count else score)
        notes.append("Vector evidence was used as supporting context after exact SQL retrieval.")

    if decision.capability == "post_performance_lookup":
        row = sql_result.rows[0] if sql_result and sql_result.rows else {}
        if row and _snapshot_has_metrics(row):
            score = min(score, 0.72)
            answerable = True
            notes.append("Performance evidence is limited to the latest resolved post and its available network-specific snapshot.")
        elif row:
            score = min(score, 0.52)
            answerable = True
            notes.append("A post was resolved, but the linked analytics snapshot did not expose normalized metrics.")
        else:
            score = 0.42
            answerable = False
            notes.append("No published post with a resolvable analytics reference was found for the requested scope.")

    if decision.capability in {"property_fact_lookup", "property_knowledge_summary", "tone_of_voice_lookup", "audience_lookup", "media_recommendation"}:
        if vector_count:
            score = max(score, 0.76)
            answerable = True
        else:
            score = min(score, 0.4)
            answerable = False
            notes.append("No approved text-bearing source matched the question strongly enough.")

    if missing_fields:
        answerable = False
        score = min(score, 0.3)
    if contradictions:
        answerable = False
        score = min(score, 0.45)
        notes.append("Conflicting scope evidence was detected and the answer should not be trusted without review.")

    support_level = decision.capability_state
    if not answerable and not missing_fields and decision.capability_state != "not_supported":
        support_level = "not_supported"
    if decision.capability == "post_performance_lookup":
        support_level = "partially_supported"

    return MergedContext(
        answerable=answerable,
        confidence_score=round(score, 2),
        confidence_label=_label(score),
        support_level=support_level,
        primary_retrieval=primary_retrieval,
        evidence_count=evidence_count,
        ranked_sources=ranked_sources,
        missing_fields=missing_fields,
        contradictions=contradictions,
        notes=notes,
        clarification_question=decision.clarification_question if not answerable and missing_fields else None,
    )
