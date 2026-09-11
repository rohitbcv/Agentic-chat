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
from datetime import datetime, timezone
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

    # Channel note instructs LLM to adjust tone for public vs private
    channel_note = (
        f"Source channel: {channel_label} ({'PUBLIC — reply will be seen by everyone' if is_public_channel else 'PRIVATE — reply goes only to the guest'})"
    )

    input_text = (
        f"Hotel: {client_name}\n"
        f"Message category: {category}\n"
        f"{channel_note}\n"
        f"Action needed: {OPS_ACTION_LABELS.get(ops_action_type or '', 'Handle guest request')}\n"
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
        )

    # Create alert if we have an interaction_id
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
