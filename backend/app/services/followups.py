from __future__ import annotations

import re
from typing import Any

from ..contracts import OrchestratorDecision, RetrievalResult, RoutingPayload
from .context import MergedContext

TOPIC_STOPWORDS = {
    "a",
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
    "have",
    "has",
    "hotel",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "of",
    "on",
    "property",
    "show",
    "tell",
    "the",
    "there",
    "this",
    "to",
    "we",
    "what",
    "which",
    "with",
}


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower()).split())


def _client_ref(payload: RoutingPayload) -> str:
    if payload.entities.property_name:
        return payload.entities.property_name
    if payload.entities.client_id is not None:
        return f"client {payload.entities.client_id}"
    return "the selected client"


def _channel_ref(payload: RoutingPayload, sql_result: RetrievalResult | None) -> str:
    if payload.entities.channel:
        return "TikTok" if payload.entities.channel.lower() == "tiktok" else payload.entities.channel.title()
    if sql_result and sql_result.rows:
        for row in sql_result.rows:
            channel = str(row.get("social_network") or "").strip()
            if channel:
                return "TikTok" if channel.lower() == "tiktok" else channel.replace("_", " ").title()
    return "Instagram"


def _topic_ref(payload: RoutingPayload, decision: OrchestratorDecision, channel_ref: str) -> str:
    if decision.capability in {"content_post_detail_lookup", "post_performance_lookup"}:
        return f"last {channel_ref} post"
    if payload.entities.media_theme:
        return payload.entities.media_theme
    client_terms = set(_normalize(_client_ref(payload)).split())
    terms = []
    for term in _normalize(payload.query).split():
        if len(term) <= 2 or term in TOPIC_STOPWORDS or term in client_terms:
            continue
        if term not in terms:
            terms.append(term)
    if decision.capability == "media_recommendation":
        return "matching media"
    if decision.capability == "inbox_lookup":
        return "threads"
    if terms:
        return " ".join(terms[:3])
    return "this topic"


def _history_questions(chat_history: list[dict[str, Any]] | None) -> set[str]:
    seen: set[str] = set()
    for item in chat_history or []:
        role = str(item.get("role") or "").lower()
        content = str(item.get("content") or "")
        if role == "user" and content:
            seen.add(_normalize(content))
    return seen


def _add_question(out: list[str], question: str, *, asked: set[str], current_query: str, limit: int) -> None:
    cleaned = " ".join(str(question or "").split())
    if not cleaned or len(out) >= limit:
        return
    normalized = _normalize(cleaned)
    if normalized == _normalize(current_query) or normalized in asked:
        return
    if normalized in {_normalize(item) for item in out}:
        return
    out.append(cleaned)


def build_follow_up_questions(
    payload: RoutingPayload,
    decision: OrchestratorDecision,
    context: MergedContext,
    sql_result: RetrievalResult | None,
    vector_result: RetrievalResult | None,
    answer: str,
    *,
    chat_history: list[dict[str, Any]] | None = None,
    limit: int = 3,
) -> list[str]:
    """Create deterministic, route-aware follow-up questions for the UI.

    Follow-ups are suggestions only. They should point users to supported read-only
    routes and should never imply that a missing fact exists.
    """

    client_ref = _client_ref(payload)
    channel_ref = _channel_ref(payload, sql_result)
    topic_ref = _topic_ref(payload, decision, channel_ref)
    asked = _history_questions(chat_history)
    questions: list[str] = []
    capability = decision.capability

    if decision.branch == "clarification":
        candidates = []
    elif decision.branch == "unsupported_action":
        candidates = [
            f"Show approval queue for {client_ref}",
            f"Show scheduled posts for {client_ref}",
            f"Show latest post details for {client_ref}",
        ]
    elif capability == "property_fact_lookup":
        if not context.answerable or "couldn't verify" in answer.lower():
            candidates = [
                f"Show {topic_ref} notes for {client_ref}",
                f"Any {topic_ref} policy for {client_ref}?",
                f"Summarize property details for {client_ref}",
            ]
        else:
            candidates = [
                f"Show {topic_ref} notes for {client_ref}",
                f"Any {topic_ref} policy for {client_ref}?",
                f"Guest reply about {topic_ref} for {client_ref}?",
            ]
    elif capability == "property_knowledge_summary":
        candidates = [
            f"Show FAQs for {client_ref}",
            f"Show tone for {client_ref}",
            f"Show audience for {client_ref}",
        ]
    elif capability == "tone_of_voice_lookup":
        candidates = [
            f"Show audience for {client_ref}",
            f"Show tone rules for {client_ref}",
            f"Show reply style for {client_ref}",
        ]
    elif capability == "audience_lookup":
        candidates = [
            f"Show tone for {client_ref}",
            f"Find audience-fit media for {client_ref}",
            f"Show audience suggestions for {client_ref}",
        ]
    elif capability == "content_schedule_lookup":
        candidates = [
            f"Show approval queue for {client_ref}",
            f"Show last {channel_ref} post copy for {client_ref}",
            f"How is last {channel_ref} performing for {client_ref}?",
        ]
    elif capability == "content_approval_lookup":
        candidates = [
            f"Show scheduled posts for {client_ref}",
            f"Show draft post copy for {client_ref}",
            f"Which media was used in last {channel_ref} post for {client_ref}?",
        ]
    elif capability == "content_post_detail_lookup":
        candidates = [
            f"How is last {channel_ref} performing for {client_ref}?",
            f"Which media was used in last {channel_ref} post for {client_ref}?",
            f"Show nearby scheduled posts for {client_ref}",
        ]
    elif capability == "post_performance_lookup":
        candidates = [
            f"Show last {channel_ref} post copy for {client_ref}",
            f"Which media was used in last {channel_ref} post for {client_ref}?",
            f"Show related posts for {client_ref}",
        ]
    elif capability == "media_recommendation":
        candidates = [
            f"Show more media for {client_ref}",
            f"Why do these assets fit {client_ref}?",
            f"Find similar visuals for {client_ref}",
        ]
    elif capability == "client_access_lookup":
        candidates = [
            f"Show collaborators for {client_ref}",
            f"Show organization access for {client_ref}",
            f"Show user relationship paths for {client_ref}",
        ]
    elif capability == "competitor_lookup":
        candidates = [
            f"Compare audiences for {client_ref}",
            f"Show market positioning for {client_ref}",
            f"Show content themes for {client_ref}",
        ]
    elif capability == "relationship_lookup":
        candidates = [
            f"How is {client_ref} connected to content?",
            f"How is {client_ref} connected to media?",
            f"How is {client_ref} connected to events?",
        ]
    elif capability == "event_lookup":
        candidates = [
            f"Show next events for {client_ref}",
            f"Show event-linked posts for {client_ref}",
            f"Find event-fit media for {client_ref}",
        ]
    elif capability == "inbox_lookup":
        if any(word in payload.normalized_query for word in ("complaint", "complaints", "issue", "problem", "cancel")):
            candidates = [
                f"Show waiting complaints for {client_ref}",
                f"Show reply-now complaints for {client_ref}",
                f"Summarize complaint details for {client_ref}",
            ]
        else:
            candidates = [
                f"Show unresolved threads for {client_ref}",
                f"Show waiting threads for {client_ref}",
                f"Show complaint threads for {client_ref}",
            ]
    elif capability == "pricing_lookup":
        candidates = [
            f"Show price notes for {client_ref}",
            f"Show booking policy for {client_ref}",
            f"Show property details for {client_ref}",
        ]
    else:
        candidates = [
            f"Show more on {topic_ref} for {client_ref}",
            f"Show source details for {client_ref}",
            f"Clarify scope for {client_ref}",
        ]

    for candidate in candidates:
        _add_question(questions, candidate, asked=asked, current_query=payload.query, limit=limit)

    return questions
