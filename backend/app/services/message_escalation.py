"""
message_escalation.py
=====================
Escalation Engine for complex, actionable, or low-confidence guest messages.

Responsibilities:
1. Build a rich ops packet: original message + classification + available context + suggested reply
2. Create a jx_bridge.alerts row with status = 'pending_ops_approval'
3. Update jx_bridge.thread_triage to 'pending_ops_approval' or 'escalated_crisis'
4. Store the ops packet in jx_bridge.auto_response_log for tracking

Ops teams see: what the guest wants, what context was found, a suggested reply,
and Approve / Edit / Reject actions. They only need to handle exceptions, not every message.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from os import getenv
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()

# Human-readable action descriptions for ops UI
OPS_ACTION_LABELS: dict[str, str] = {
    "cab_rebook":          "Rebook / reschedule guest transport",
    "late_checkout":       "Approve late checkout request",
    "early_checkin":       "Arrange early check-in",
    "room_upgrade":        "Process room upgrade request",
    "complaint_followup":  "Follow up on guest complaint",
    "booking_correction":  "Verify and correct booking details",
    "room_service":        "Coordinate room service delivery",
    "housekeeping":        "Dispatch housekeeping",
    "spa_booking":         "Book spa / wellness appointment",
    "rate_inquiry":        "Respond to group / corporate rate inquiry",
    "flight_delay":        "Adjust arrangements for delayed-flight guest",
}

URGENCY_LABELS: dict[str, str] = {
    "critical": "🔴 CRITICAL — Immediate action required",
    "high":     "🟠 HIGH — Action needed within 1 hour",
    "medium":   "🟡 MEDIUM — Action needed today",
    "low":      "🟢 LOW — Respond when available",
}


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class EscalationPacket:
    interaction_id: int | None
    client_id: int
    client_name: str
    original_message: str
    category: str
    urgency_level: str
    urgency_label: str
    requires_ops_action: bool
    ops_action_type: str | None
    ops_action_label: str | None
    extracted_entities: dict[str, Any]
    available_context: list[dict[str, Any]]   # relevant FAQ rows found
    suggested_reply: str | None
    suggested_action: str | None
    alert_id: int | None = None
    triage_state: str = "pending_ops_approval"

    def to_dict(self) -> dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "client_id": self.client_id,
            "client_name": self.client_name,
            "original_message": self.original_message,
            "category": self.category,
            "urgency_level": self.urgency_level,
            "urgency_label": self.urgency_label,
            "requires_ops_action": self.requires_ops_action,
            "ops_action_type": self.ops_action_type,
            "ops_action_label": self.ops_action_label,
            "extracted_entities": self.extracted_entities,
            "available_context": self.available_context,
            "suggested_reply": self.suggested_reply,
            "suggested_action": self.suggested_action,
            "alert_id": self.alert_id,
            "triage_state": self.triage_state,
        }


# ── Context retrieval ─────────────────────────────────────────────────────────

def _get_relevant_context(client_id: int, message: str) -> list[dict[str, Any]]:
    """Retrieve FAQ/property rows most relevant to the message for the ops packet."""
    from ..db import repository
    from .message_auto_answer import _tokenize, _lexical_score

    try:
        notes = repository.execute_query(
            """
            SELECT cn.title, cn.note,
                   CASE WHEN cn.type_id = 3 THEN 'Response Templates'
                        WHEN cn.type_id = 2 THEN 'FAQ'
                        ELSE 'General' END AS note_type
            FROM clients.client_notes cn
            WHERE cn.client_id = :client_id
              AND cn.deleted_at IS NULL
            ORDER BY cn.type_id ASC, cn.inserted_datetime DESC
            """,
            {"client_id": client_id},
        )
    except Exception:
        notes = []

    scored = []
    for note in notes:
        text = f"{note.get('title', '')} {note.get('note', '')}"
        score = _lexical_score(message, text)
        if score > 0.15:
            scored.append({
                "title": note.get("title"),
                "excerpt": str(note.get("note") or "")[:400],
                "note_type": note.get("note_type"),
                "relevance_score": round(score, 3),
            })

    scored.sort(key=lambda x: x["relevance_score"], reverse=True)
    return scored[:5]


# ── Suggested reply + action (LLM) ───────────────────────────────────────────

_ESCALATION_SYSTEM_PROMPT = """
You are a hotel operations assistant helping staff handle a guest message.
Based on the guest message and available context, provide:
1. A suggested reply the ops team can send (warm, professional, 2-4 sentences)
2. A specific suggested action for the ops team

Rules:
- For the reply: be empathetic, acknowledge the request, give what information is available
- If context is incomplete, acknowledge that and promise follow-up
- For the action: be specific (e.g. "Call transport team to reschedule cab from 12 PM to 2 PM")
- Never fabricate facts not in the context
- Never include pricing, availability, or booking details you don't have

Respond with valid JSON only:
{
  "suggested_reply": "<reply text>",
  "suggested_action": "<specific action for ops team>"
}
""".strip()


def _generate_escalation_suggestions(
    message: str,
    client_name: str,
    category: str,
    ops_action_type: str | None,
    context: list[dict[str, Any]],
    entities: dict[str, Any],
    channel_label: str = "Direct Message",
    is_public_channel: bool = False,
    conversation_history: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str | None]:
    """Returns (suggested_reply, suggested_action)."""
    api_key = (getenv("OPENAI_API_KEY") or "").strip()
    model = (getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()

    if not api_key:
        # Deterministic fallback
        reply = _deterministic_escalation_reply(message, category, context, is_public_channel)
        action = OPS_ACTION_LABELS.get(ops_action_type or "", "Review and respond to guest message")
        if is_public_channel:
            action += f" (⚠ Public {channel_label} — reply is visible to all)"
        return reply, action

    context_block = ""
    if context:
        context_block = "Available property context:\n" + "\n".join(
            f"- {c['title']}: {c['excerpt'][:300]}" for c in context[:3]
        )

    entity_block = ""
    if any(entities.values()):
        entity_block = f"\nExtracted details: {json.dumps(entities, ensure_ascii=False)}"

    history_block = ""
    if conversation_history:
        from .message_auto_answer import _format_conversation_history
        formatted = _format_conversation_history(conversation_history)
        if formatted:
            history_block = f"\nRecent conversation history (last 5 exchanges):\n{formatted}\n"

    # Channel note instructs LLM to adjust tone for public vs private
    channel_note = (
        f"Source channel: {channel_label} ({'PUBLIC — reply will be seen by everyone' if is_public_channel else 'PRIVATE — reply goes only to the guest'})"
    )

    input_text = (
        f"Hotel: {client_name}\n"
        f"Message category: {category}\n"
        f"{channel_note}\n"
        f"Action needed: {OPS_ACTION_LABELS.get(ops_action_type or '', 'Handle guest request')}\n"
        f"{history_block}"
        f"Guest message: {message[:600]}\n"
        f"{context_block}{entity_block}"
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            instructions=_ESCALATION_SYSTEM_PROMPT,
            input=input_text,
            max_output_tokens=400,
            temperature=0.3,
        )
        raw = str(getattr(response, "output_text", "") or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw).rstrip("` \n")
        data = json.loads(raw)
        suggested_action = data.get("suggested_action")
        if is_public_channel and suggested_action:
            suggested_action += f" (⚠ Public {channel_label})"
        return data.get("suggested_reply"), suggested_action
    except Exception:
        reply = _deterministic_escalation_reply(message, category, context, is_public_channel)
        action = OPS_ACTION_LABELS.get(ops_action_type or "", "Review and respond to guest message")
        if is_public_channel:
            action += f" (⚠ Public {channel_label})"
        return reply, action


def _deterministic_escalation_reply(
    message: str,
    category: str,
    context: list[dict[str, Any]],
    is_public_channel: bool = False,
) -> str:
    """Fallback reply when LLM is unavailable."""
    templates = {
        "complaint": "Thank you for bringing this to our attention. We sincerely apologise for the inconvenience and will ensure this is addressed right away. Our team will follow up with you shortly.",
        "in_house_request": "Thank you for reaching out. We have received your request and our team will attend to it as soon as possible. Please don't hesitate to contact us if you need anything else.",
        "booking_related": "Thank you for contacting us. We are looking into your booking details and will get back to you with the correct information shortly.",
        "crisis": "We are treating this as an urgent matter. Our team has been alerted and will respond immediately. Please stay safe.",
        "external_dm": "Thank you for your interest in staying with us. Our reservations team will be in touch shortly with availability and rates.",
    }
    # Public channels (reviews, comments) get a slightly more polished opener
    if is_public_channel:
        templates["complaint"] = "Thank you for your feedback. We are truly sorry to hear about your experience and take this matter very seriously. A member of our team will be in touch with you directly to make this right."

    base = templates.get(category, "Thank you for your message. Our team will review and respond to you shortly.")
    if context:
        snippet = context[0].get("excerpt", "")[:150].rstrip(".")
        if snippet:
            base += f" For your reference: {snippet}."
    return base


# ── Prior property responses (last 2 months) ──────────────────────────────────

PROPERTY_REPLY_LOOKBACK_DAYS = 60
PROPERTY_EMBED_MATCH_THRESHOLD = 0.78
PROPERTY_LEXICAL_MATCH_THRESHOLD = 0.40
PROPERTY_COMBINED_MATCH_THRESHOLD = 0.70

# In-memory Q&A for this process: questions already sent to property, plus answers.
# Dummy DB writes are not committed, so this is the source of truth within a session.
_PROPERTY_QA_MEMORY: list[dict[str, Any]] = []


def _normalize_guest_query(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())).strip()


def record_property_question_asked(client_id: int, guest_message: str) -> None:
    """Remember that this guest question was already raised to the property."""
    guest = (guest_message or "").strip()
    if not client_id or not guest:
        return
    _PROPERTY_QA_MEMORY.append({
        "client_id": int(client_id),
        "guest_message": guest,
        "property_reply": "",
        "replied_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "property_chat_asked",
    })


def record_property_answer(client_id: int, guest_message: str, property_reply: str) -> None:
    """Remember a property team's answer so the same question is not asked again."""
    guest = (guest_message or "").strip()
    reply = (property_reply or "").strip()
    if not client_id or not guest or not reply:
        return
    _PROPERTY_QA_MEMORY.append({
        "client_id": int(client_id),
        "guest_message": guest,
        "property_reply": reply,
        "replied_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "property_chat",
    })


def _memory_candidates(client_id: int, *, answered_only: bool = True) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in _PROPERTY_QA_MEMORY:
        if int(item.get("client_id") or 0) != int(client_id):
            continue
        guest = str(item.get("guest_message") or "").strip()
        reply = str(item.get("property_reply") or "").strip()
        if not guest:
            continue
        if answered_only and not reply:
            continue
        out.append({
            "guest_message": guest,
            "property_reply": reply,
            "replied_at": item.get("replied_at"),
            "source": str(item.get("source") or "property_chat"),
        })
    return out


def _exact_query_match(query: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    needle = _normalize_guest_query(query)
    if not needle:
        return None
    # Newest first so a later property answer wins over an earlier one.
    for item in reversed(candidates):
        hay = _normalize_guest_query(item.get("guest_message") or "")
        if hay and hay == needle:
            return item
    return None


@dataclass
class PriorPropertyMatch:
    guest_message: str
    property_reply: str
    score: float
    source: str
    replied_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "guest_message": self.guest_message[:400],
            "property_reply": self.property_reply[:400],
            "score": round(self.score, 3),
            "source": self.source,
            "replied_at": self.replied_at,
        }


def _cutoff_two_months() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=PROPERTY_REPLY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")


def _load_prior_property_responses(client_id: int) -> list[dict[str, Any]]:
    """Load guest queries that already received a property reply in the last 2 months."""
    from ..db import repository

    cutoff = _cutoff_two_months()
    candidates: list[dict[str, Any]] = _memory_candidates(client_id, answered_only=True)

    try:
        rows = repository.execute_query(
            """
            SELECT
                m.content              AS guest_message,
                ar.reply_text          AS property_reply,
                ar.inserted_datetime   AS replied_at
            FROM jx_bridge.alert_replies ar
            JOIN jx_bridge.alerts a ON a.id = ar.alert_id
            JOIN jx_bridge.interactions i ON i.interaction_id = a.interaction_id
            JOIN jx_bridge.messages m ON m.interaction_id = i.interaction_id
            WHERE i.client_id = :client_id
              AND ar.deleted_at IS NULL
              AND a.deleted_at IS NULL
              AND ar.reply_text IS NOT NULL
              AND TRIM(ar.reply_text) != ''
              AND ar.inserted_datetime >= :cutoff
            ORDER BY ar.inserted_datetime DESC
            LIMIT 120
            """,
            {"client_id": client_id, "cutoff": cutoff},
        )
        for row in rows:
            guest = str(row.get("guest_message") or "").strip()
            reply = str(row.get("property_reply") or "").strip()
            if guest and reply:
                candidates.append({
                    "guest_message": guest,
                    "property_reply": reply,
                    "replied_at": row.get("replied_at"),
                    "source": "jx_bridge.alert_replies",
                })
    except Exception:
        pass

    try:
        log_rows = repository.execute_query(
            """
            SELECT
                source_excerpt,
                draft_answer,
                final_answer,
                inserted_datetime AS replied_at
            FROM jx_bridge.auto_response_log
            WHERE client_id = :client_id
              AND source_table IN ('property_chat', 'jx_bridge.alert_replies', 'prior_property_response')
              AND inserted_datetime >= :cutoff
            ORDER BY inserted_datetime DESC
            LIMIT 80
            """,
            {"client_id": client_id, "cutoff": cutoff},
        )
        for row in log_rows:
            excerpt = str(row.get("source_excerpt") or "").strip()
            reply = str(row.get("final_answer") or row.get("draft_answer") or "").strip()
            guest = excerpt
            property_reply = reply
            if excerpt.lower().startswith("guest:"):
                parts = excerpt.split("Property:", 1)
                guest = parts[0].replace("Guest:", "", 1).strip()
                if len(parts) > 1:
                    property_reply = parts[1].strip() or reply
            if guest and property_reply:
                candidates.append({
                    "guest_message": guest,
                    "property_reply": property_reply,
                    "replied_at": row.get("replied_at"),
                    "source": "jx_bridge.auto_response_log",
                })
    except Exception:
        pass

    # De-dupe by guest message prefix
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in candidates:
        key = re.sub(r"\s+", " ", item["guest_message"].lower())[:180]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _score_property_candidates(query: str, candidates: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
    """Semantic + lexical ranking of prior guest queries against the new message."""
    from .message_auto_answer import _lexical_score

    if not query or not candidates:
        return []

    lex_scored = []
    for item in candidates:
        lex = _lexical_score(query, item["guest_message"])
        lex_scored.append((lex, item))
    lex_scored.sort(key=lambda x: x[0], reverse=True)

    # Pre-filter noisy rows, keep a semantic shortlist
    shortlist = [pair for pair in lex_scored if pair[0] >= 0.10][:40]
    if not shortlist:
        shortlist = lex_scored[:25]

    try:
        from .embeddings import cosine_similarity, embed_texts, embedding_enabled
        if embedding_enabled() and shortlist:
            texts = [query[:500]] + [item["guest_message"][:500] for _, item in shortlist]
            vectors = embed_texts(texts)
            query_vec = vectors[0]
            ranked: list[tuple[float, dict[str, Any]]] = []
            for idx, (lex, item) in enumerate(shortlist):
                emb = cosine_similarity(query_vec, vectors[idx + 1])
                combined = 0.40 * lex + 0.60 * float(emb)
                ranked.append((combined, {**item, "lex_score": lex, "emb_score": round(float(emb), 4)}))
            ranked.sort(key=lambda x: x[0], reverse=True)
            return ranked
    except Exception:
        pass

    return [(lex, item) for lex, item in shortlist]


def _to_prior_match(item: dict[str, Any], score: float) -> PriorPropertyMatch:
    return PriorPropertyMatch(
        guest_message=item["guest_message"],
        property_reply=str(item.get("property_reply") or ""),
        score=float(score),
        source=str(item.get("source") or "jx_bridge.alert_replies"),
        replied_at=item.get("replied_at"),
    )


def _best_similar_candidate(
    message: str,
    candidates: list[dict[str, Any]],
) -> PriorPropertyMatch | None:
    if not message or not candidates:
        return None

    exact = _exact_query_match(message, candidates)
    if exact:
        return _to_prior_match(exact, 1.0)

    ranked = _score_property_candidates(message, candidates)
    if not ranked:
        return None

    score, item = ranked[0]
    emb = float(item.get("emb_score") or 0.0)
    lex = float(item.get("lex_score") or score)
    matched = (
        emb >= PROPERTY_EMBED_MATCH_THRESHOLD
        or score >= PROPERTY_COMBINED_MATCH_THRESHOLD
        or (emb == 0.0 and lex >= PROPERTY_LEXICAL_MATCH_THRESHOLD)
        or lex >= 0.85
    )
    if not matched:
        return None
    return _to_prior_match(item, float(score))


def find_similar_property_response(
    message: str,
    client_id: int,
    extra_candidates: list[dict[str, Any]] | None = None,
) -> PriorPropertyMatch | None:
    """
    If this client already received a property reply to the same/similar query
    in the last 2 months (or this session's Property Chat), return the best match.
    """
    candidates = _load_prior_property_responses(client_id)
    if extra_candidates:
        candidates = list(candidates) + [
            item for item in extra_candidates
            if str(item.get("guest_message") or "").strip()
            and str(item.get("property_reply") or "").strip()
        ]
    return _best_similar_candidate(message, candidates)


def find_similar_unanswered_property_question(
    message: str,
    client_id: int,
) -> PriorPropertyMatch | None:
    """Same question already raised to property for this client, but not yet answered."""
    asked = [
        item for item in _memory_candidates(client_id, answered_only=False)
        if not str(item.get("property_reply") or "").strip()
    ]
    return _best_similar_candidate(message, asked)


_PRIOR_PROPERTY_REPLY_PROMPT = """
You are a warm, professional hotel concierge.
The property already answered a similar guest query in the last two months.
Write a concise guest-facing reply using ONLY that earlier property answer.
Do not invent new facts. Do not mention "previous guest", "alert", or "internal records".
2-4 sentences. Start directly with the answer.
""".strip()


def draft_from_prior_property_response(
    message: str,
    client_name: str,
    match: PriorPropertyMatch,
) -> str:
    """Turn a prior property reply into a guest-facing answer for the current query."""
    api_key = (getenv("OPENAI_API_KEY") or "").strip()
    model = (getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()
    fallback = (
        f"{match.property_reply.strip().rstrip('.')}. "
        "Please let us know if you need anything else."
    )
    if not api_key:
        return fallback
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            instructions=_PRIOR_PROPERTY_REPLY_PROMPT,
            input=(
                f"Hotel: {client_name}\n"
                f"Current guest message: {message[:600]}\n"
                f"Similar earlier guest query: {match.guest_message[:600]}\n"
                f"Property's earlier answer: {match.property_reply[:800]}"
            ),
            max_output_tokens=220,
            temperature=0.2,
        )
        draft = str(getattr(response, "output_text", "") or "").strip()
        return draft if len(draft) > 10 else fallback
    except Exception:
        return fallback


# ── Alert creation ────────────────────────────────────────────────────────────

def _create_alert(
    interaction_id: int,
    client_id: int,
    urgency_level: str,
    packet_json: str,
) -> int | None:
    """Insert a jx_bridge.alerts row. Returns alert_id or None on failure."""
    from ..db import repository
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        # Get next alert id
        rows = repository.execute_query(
            "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM jx_bridge.alerts",
            {},
        )
        next_id = rows[0]["next_id"] if rows else 1
        repository.execute_query(
            """
            INSERT INTO jx_bridge.alerts (id, interaction_id, status, inserted_datetime, deleted_at)
            VALUES (:id, :interaction_id, :status, :inserted_datetime, NULL)
            """,
            {
                "id": next_id,
                "interaction_id": interaction_id,
                "status": f"pending_ops_approval:{urgency_level}",
                "inserted_datetime": now,
            },
        )
        return next_id
    except Exception:
        return None


def _update_triage(interaction_id: int, triage_state: str) -> None:
    """Update thread_triage for an interaction."""
    from ..db import repository
    try:
        repository.execute_query(
            """
            UPDATE jx_bridge.thread_triage
            SET triage = :triage
            WHERE interaction_id = :interaction_id
            """,
            {"triage": triage_state, "interaction_id": interaction_id},
        )
    except Exception:
        pass


# ── Main entry point ──────────────────────────────────────────────────────────

def build_escalation_packet(
    message: str,
    client_id: int,
    client_name: str,
    classification: "Any",           # ClassificationResult from message_classifier
    interaction_id: int | None = None,
    auto_answer_draft: str | None = None,   # partial draft from auto-answer (confidence 0.70-0.89)
    message_type: str = "messages",  # comments | messages | review | mentions
    conversation_history: list[dict[str, Any]] | None = None,
) -> EscalationPacket:
    """
    Build an escalation packet for ops team review.

    Args:
        message: original guest message
        client_id: resolved client
        client_name: hotel name
        classification: ClassificationResult from message_classifier
        interaction_id: existing interaction_id if available
        auto_answer_draft: partial FAQ draft (if confidence was 0.70-0.89)
        message_type: source channel — affects tone and urgency context for ops

    Returns:
        EscalationPacket
    """
    urgency = classification.urgency_level
    triage_state = "escalated_crisis" if urgency == "critical" else "pending_ops_approval"

    # Channel label for ops packet display
    channel_label = getattr(classification, "channel_label", None) or {
        "comments": "Public Social Comment",
        "messages": "Private Direct Message",
        "review":   "Public Platform Review",
        "mentions": "Social Media Mention",
    }.get(message_type, "Direct Message")

    # Public channel flag — affects suggested_action wording
    is_public_channel = message_type in ("comments", "review", "mentions")

    # Get relevant context
    context = _get_relevant_context(client_id, message)

    # Generate suggested reply and action
    entities = classification.entities.to_dict()
    if auto_answer_draft:
        suggested_reply = auto_answer_draft   # use the partial FAQ draft as starting point
        suggested_action = OPS_ACTION_LABELS.get(
            classification.ops_action_type or "",
            "Review and confirm the draft reply before sending"
        )
        if is_public_channel:
            suggested_action += f" (⚠ Public {channel_label} — reply is visible to all)"
    else:
        suggested_reply, suggested_action = _generate_escalation_suggestions(
            message=message,
            client_name=client_name,
            category=classification.category,
            ops_action_type=classification.ops_action_type,
            context=context,
            entities=entities,
            channel_label=channel_label,
            is_public_channel=is_public_channel,
            conversation_history=conversation_history,
        )

    # Create alert if we have an interaction_id
    # Remember this question was raised so a later identical ask is not sent again.
    record_property_question_asked(client_id, message)

    alert_id = None
    if interaction_id:
        packet_preview = json.dumps({
            "category": classification.category,
            "urgency": urgency,
            "channel": channel_label,
            "suggested_reply": (suggested_reply or "")[:200],
        }, ensure_ascii=False)
        alert_id = _create_alert(interaction_id, client_id, urgency, packet_preview)
        _update_triage(interaction_id, triage_state)

    return EscalationPacket(
        interaction_id=interaction_id,
        client_id=client_id,
        client_name=client_name,
        original_message=message,
        category=classification.category,
        urgency_level=urgency,
        urgency_label=URGENCY_LABELS.get(urgency, urgency),
        requires_ops_action=classification.requires_ops_action,
        ops_action_type=classification.ops_action_type,
        ops_action_label=OPS_ACTION_LABELS.get(classification.ops_action_type or "", None),
        extracted_entities=entities,
        available_context=context,
        suggested_reply=suggested_reply,
        suggested_action=suggested_action,
        alert_id=alert_id,
        triage_state=triage_state,
    )
