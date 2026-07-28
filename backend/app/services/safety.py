from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..contracts import OrchestratorDecision, RoutingPayload
from ..read_only import detect_blocked_action
from .context import MergedContext


@dataclass
class SafetyReview:
    status: str
    read_only: bool
    blocked_actions: list[str] = field(default_factory=list)
    claim_policy: str = "Answer only from retrieved SQL/vector context or a documented support limitation."
    confidence_label: str = "low"
    capability_state: str = "not_supported"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_answer_safety(
    answer: str,
    payload: RoutingPayload,
    decision: OrchestratorDecision,
    context: MergedContext,
) -> SafetyReview:
    notes = [
        "No write-capable DB credentials or product API tools are exposed to this agent route.",
        "All retrieved evidence was scoped before answer generation.",
    ]
    blocked = detect_blocked_action(payload.query)
    blocked_actions = [blocked] if blocked else []

    if decision.branch == "unsupported_action" or blocked:
        notes.append("The request was write-like and was blocked by read-only policy.")
        return SafetyReview(
            status="read_only_refusal",
            read_only=True,
            blocked_actions=blocked_actions,
            confidence_label="high",
            capability_state="not_supported",
            notes=notes,
        )

    if decision.branch == "clarification" or context.missing_fields:
        notes.append("The safest response is a clarification question because required scope is missing.")
        return SafetyReview(
            status="needs_clarification",
            read_only=True,
            confidence_label=context.confidence_label,
            capability_state=context.support_level,
            notes=notes,
        )

    if context.contradictions:
        notes.append("Contradictory scope evidence blocked a high-confidence answer.")
        return SafetyReview(
            status="grounding_gap",
            read_only=True,
            confidence_label=context.confidence_label,
            capability_state=context.support_level,
            notes=notes,
        )

    if not context.answerable and decision.capability_state != "not_supported":
        notes.append("The answer is an absence or limitation statement because no supporting rows or chunks were found.")
        return SafetyReview(
            status="grounding_gap",
            read_only=True,
            confidence_label=context.confidence_label,
            capability_state=context.support_level,
            notes=notes,
        )

    if decision.capability == "post_performance_lookup":
        notes.append("Performance claims must remain scoped to available network-specific snapshots.")

    if "couldn't" in answer.lower() or "can't" in answer.lower():
        notes.append("The answer contains an explicit limitation instead of an invented fact.")

    return SafetyReview(
        status="passed",
        read_only=True,
        confidence_label=context.confidence_label,
        capability_state=context.support_level,
        notes=notes,
    )


def build_audit_event(
    query: str,
    payload: RoutingPayload,
    decision: OrchestratorDecision,
    context: MergedContext,
    safety: SafetyReview,
) -> dict[str, Any]:
    return {
        "event_type": "agent_read_only_answer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "user_id": payload.entities.user_id,
        "client_id": payload.entities.client_id,
        "intent": decision.intent,
        "capability": decision.capability,
        "agent": decision.agent_name,
        "support_level": context.support_level,
        "confidence_label": context.confidence_label,
        "confidence_score": context.confidence_score,
        "safety_status": safety.status,
        "read_only": True,
        "persisted": False,
    }
