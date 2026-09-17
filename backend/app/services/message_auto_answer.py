"""
message_auto_answer.py
======================
FAQ Auto-Answer Engine for routine guest questions.

Pipeline:
1. Retrieve relevant client_notes + property_details rows for the client
2. Score each note against the guest message using lexical + embedding similarity
3. If best-match confidence >= AUTO_ANSWER_THRESHOLD: draft a human-like reply
4. Run grounding validator — every claim must trace to a retrieved row
5. Return AutoAnswerResult with draft, confidence, and source info

Confidence gates:
  >= 0.90  → auto_answered = True (reply sent without ops involvement)
  0.70–0.89 → included in ops escalation packet as "suggested reply"
  < 0.70   → no draft, full escalation only
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from os import getenv
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()

AUTO_ANSWER_THRESHOLD = 0.90
SUGGESTED_REPLY_THRESHOLD = 0.70
# FAQ/property note is relevant enough to answer without asking the property.
FAQ_CONTEXT_THRESHOLD = 0.18

# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class SourceRow:
    table: str
    title: str
    excerpt: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "title": self.title,
            "excerpt": self.excerpt[:400],
            "score": self.score,
        }


@dataclass
class AutoAnswerResult:
    auto_answered: bool          # True if confidence >= AUTO_ANSWER_THRESHOLD
    draft: str | None            # Human-like reply text
    confidence: float            # 0.0–1.0
    source_table: str | None
    source_excerpt: str | None
    source_rows: list[SourceRow] = field(default_factory=list)
    grounding_passed: bool = True
    grounding_issues: list[str] = field(default_factory=list)
    answer_method: str = "none"  # "none" | "faq_match" | "llm_grounded"

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_answered": self.auto_answered,
            "draft": self.draft,
            "confidence": self.confidence,
            "source_table": self.source_table,
            "source_excerpt": self.source_excerpt,
            "grounding_passed": self.grounding_passed,
            "grounding_issues": self.grounding_issues,
            "answer_method": self.answer_method,
        }


# ── Lexical scoring ───────────────────────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """Lowercased word tokens, stop words removed."""
    STOP = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "up", "about", "into", "through",
        "and", "or", "but", "not", "this", "that", "it", "its", "i", "my",
        "your", "we", "our", "you", "hotel", "property", "guest", "please",
        "what", "when", "where", "which", "who", "how",
    }
    lowered = (text or "").lower().replace("-", " ").replace("/", " ")
    for src, dst in (("checkout", "check out"), ("checkin", "check in")):
        lowered = lowered.replace(src, dst)
    tokens = re.findall(r"[a-z0-9]+", lowered)
    out: set[str] = set()
    for t in tokens:
        if t in STOP or len(t) <= 2:
            continue
        out.add(t)
        # Light stemming so pet/pets, dog/dogs still match
        if len(t) > 3 and t.endswith("s"):
            out.add(t[:-1])
        elif len(t) > 3:
            out.add(t + "s")
    return out


def _lexical_score(query: str, document: str) -> float:
    """Jaccard-like overlap between query and document token sets."""
    q_tokens = _tokenize(query)
    d_tokens = _tokenize(document)
    if not q_tokens:
        return 0.0
    overlap = q_tokens & d_tokens
    # Precision-weighted: how many query tokens appear in the document
    precision = len(overlap) / len(q_tokens)
    return round(min(precision, 1.0), 4)


def _embedding_score(query: str, document: str) -> float | None:
    """Cosine similarity using OpenAI embeddings. Returns None if unavailable."""
    api_key = (getenv("OPENAI_API_KEY") or "").strip()
    model = (getenv("OPENAI_EMBED_MODEL") or "text-embedding-3-large").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
        import numpy as np
        client = OpenAI(api_key=api_key)
        response = client.embeddings.create(
            model=model,
            input=[query[:500], document[:1000]],
        )
        v1 = response.data[0].embedding
        v2 = response.data[1].embedding
        dot = sum(a * b for a, b in zip(v1, v2))
        n1 = sum(a * a for a in v1) ** 0.5
        n2 = sum(b * b for b in v2) ** 0.5
        if n1 == 0 or n2 == 0:
            return None
        return round(dot / (n1 * n2), 4)
    except Exception:
        return None


def _score_note(query: str, note_text: str, *, use_embeddings: bool = False) -> float:
    """Combined score: lexical always + embedding when available."""
    lex = _lexical_score(query, note_text)
    if use_embeddings:
        emb = _embedding_score(query, note_text)
        if emb is not None:
            # Weighted: 40% lexical, 60% embedding
            return round(0.40 * lex + 0.60 * emb, 4)
    return lex


# ── FAQ retrieval ─────────────────────────────────────────────────────────────

def _get_faq_notes(client_id: int) -> list[dict[str, Any]]:
    """Fetch client_notes (FAQ + learned templates) for a client."""
    from ..db import repository
    try:
        rows = repository.execute_query(
            """
            SELECT cn.id, cn.title, cn.note, cn.type_id,
                   CASE
                     WHEN cn.type_id = 3 THEN 'Response Templates'
                     WHEN cn.type_id = 2 THEN 'FAQ'
                     WHEN cn.type_id = 1 THEN 'General'
                     ELSE 'Note'
                   END AS note_type
            FROM clients.client_notes cn
            WHERE cn.client_id = :client_id
              AND cn.deleted_at IS NULL
            ORDER BY cn.type_id ASC, cn.inserted_datetime DESC
            """,
            {"client_id": client_id},
        )
        return rows
    except Exception:
        return []


def _get_property_details(client_id: int) -> list[dict[str, Any]]:
    """Fetch structured property_details as a pseudo-note."""
    from ..db import repository
    try:
        rows = repository.execute_query(
            """
            SELECT location, highlights, amenities, overview, info, food_and_beverages
            FROM clients.property_details
            WHERE client_id = :client_id AND deleted_at IS NULL
            ORDER BY updated_datetime DESC, inserted_datetime DESC
            LIMIT 1
            """,
            {"client_id": client_id},
        )
        if not rows:
            return []
        r = rows[0]
        parts = []
        for label, key in (
            ("Overview", "overview"),
            ("Location", "location"),
            ("Amenities", "amenities"),
            ("Food & Beverage", "food_and_beverages"),
            ("Info", "info"),
            ("Highlights", "highlights"),
        ):
            val = r.get(key)
            if val:
                parts.append(f"{label}: {val}")
        return [{"id": f"pd-{client_id}", "title": "Property details", "note": "\n".join(parts), "note_type": "Property Detail"}]
    except Exception:
        return []


# ── Recent learning examples ──────────────────────────────────────────────────

def _get_recent_learning_examples(client_id: int, limit: int = 5) -> list[dict[str, Any]]:
    """Return recent approved/edited auto-response log rows for few-shot prompting."""
    from ..db import repository
    try:
        rows = repository.execute_query(
            """
            SELECT category, draft_answer, final_answer, ops_action, source_excerpt
            FROM jx_bridge.auto_response_log
            WHERE client_id = :client_id
              AND ops_action IN ('approved', 'edited')
            ORDER BY inserted_datetime DESC
            LIMIT :limit
            """,
            {"client_id": client_id, "limit": limit},
        )
        return rows
    except Exception:
        return []


# ── LLM draft generation ──────────────────────────────────────────────────────

_DRAFT_SYSTEM_PROMPT = """
You are a warm, professional hotel concierge writing a reply to a guest message.
Write a concise, human-like response using ONLY the provided FAQ evidence.
Rules:
1. Answer directly and warmly. Use "we" for the hotel. Never say "according to our FAQ".
2. If the evidence answers the question fully, give a confident complete answer.
3. If the evidence only partially answers, give what you know and acknowledge the gap.
4. Never invent facts not present in the evidence.
5. Keep it to 2-4 sentences unless listing multiple items.
6. Do not include a subject line or greeting — start directly with the answer.
7. End with an offer to help further if appropriate.
8. If conversation history is provided, use it ONLY when it is clearly about the SAME topic as
   the current guest message (true follow-up). If history is about a different topic, IGNORE it
   completely — do not mention prior topics, do not say you lack details from history, and answer
   only from the FAQ evidence for the current question.
""".strip()

# Minimum lexical overlap with a single prior *guest* turn before treating it as related.
CONVERSATION_RELEVANCE_THRESHOLD = 0.28

_STRONG_FOLLOW_UP_CUES = (
    "my bag", "the bag", "left behind", "hold it", "holding it",
    "did you find", "have you found", "is it found", "is my",
    "any update on", "still holding", "same request",
)


def find_best_matching_conversation_turn(
    message: str,
    conversation_history: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, float]:
    """
    Find the single prior guest turn most related to the current message.
    Compares against each turn individually — never against a concatenated blob,
    which incorrectly linked check-in questions to unrelated pet replies.
    """
    recent = [item for item in (conversation_history or [])[-5:] if isinstance(item, dict)]
    if not message or not recent:
        return None, 0.0

    best_turn: dict[str, Any] | None = None
    best_score = 0.0
    for turn in recent:
        guest = str(turn.get("content") or "").strip()
        if not guest:
            continue
        score = _lexical_score(message, guest)
        if score > best_score:
            best_score = score
            best_turn = turn

    if best_turn and best_score >= CONVERSATION_RELEVANCE_THRESHOLD:
        return best_turn, best_score

    message_lower = (message or "").lower()
    cue_hit = any(cue in message_lower for cue in _STRONG_FOLLOW_UP_CUES)
    if best_turn and cue_hit and best_score >= 0.12:
        return best_turn, best_score

    return None, 0.0


def conversation_history_is_relevant(
    message: str,
    conversation_history: list[dict[str, Any]] | None,
) -> bool:
    """True only when the current message matches a specific prior guest turn."""
    turn, _ = find_best_matching_conversation_turn(message, conversation_history)
    return turn is not None


def relevant_conversation_history(
    message: str,
    conversation_history: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return at most the one prior turn that is actually related to this message."""
    turn, _ = find_best_matching_conversation_turn(message, conversation_history)
    return [turn] if turn else []


def _format_conversation_history(history: list[dict[str, Any]], limit: int = 5) -> str:
    """Format recent conversation history into a readable block for the LLM."""
    if not history:
        return ""
    recent = history[-limit:]
    lines = []
    for item in recent:
        guest_msg = (item.get("content") or "").strip()
        hotel_reply = (item.get("reply_text") or "").strip()
        if guest_msg:
            lines.append(f"Guest: {guest_msg[:300]}")
        if hotel_reply:
            lines.append(f"Hotel: {hotel_reply[:300]}")
    return "\n".join(lines)


def _generate_llm_draft(
    message: str,
    best_notes: list[SourceRow],
    client_name: str,
    few_shot_examples: list[dict[str, Any]],
    conversation_history: list[dict[str, Any]] | None = None,
) -> str | None:
    api_key = (getenv("OPENAI_API_KEY") or "").strip()
    model = (getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()
    if not api_key or not best_notes:
        return None

    evidence_block = "\n".join(
        f"[{i+1}] {n.title}: {n.excerpt[:600]}"
        for i, n in enumerate(best_notes[:4])
    )

    few_shot_block = ""
    if few_shot_examples:
        examples = []
        for ex in few_shot_examples[:3]:
            q = ex.get("source_excerpt", "")
            a = ex.get("final_answer") or ex.get("draft_answer", "")
            if q and a:
                examples.append(f"Example:\nGuest: {q[:200]}\nReply: {a[:300]}")
        if examples:
            few_shot_block = "\n\nPrevious approved replies for context:\n" + "\n\n".join(examples)

    # Conversation history block — gives LLM awareness of prior exchanges
    history_block = ""
    related = relevant_conversation_history(message, conversation_history)
    if related:
        formatted = _format_conversation_history(related)
        if formatted:
            history_block = (
                "\n\nRelated conversation history (same topic only — ignore if unrelated):\n"
                f"{formatted}\n"
            )

    input_text = (
        f"Hotel: {client_name}\n"
        f"{history_block}"
        f"Current guest message: {message[:600]}\n\n"
        f"Approved FAQ evidence:{few_shot_block}\n{evidence_block}"
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            instructions=_DRAFT_SYSTEM_PROMPT,
            input=input_text,
            max_output_tokens=300,
            temperature=0.3,
        )
        answer = str(getattr(response, "output_text", "") or "").strip()
        return answer if len(answer) > 10 else None
    except Exception:
        return None


_THREAD_FOLLOWUP_PROMPT = """
You are a warm, professional hotel concierge. The guest sent a FOLLOW-UP on the SAME topic
as the recent conversation history below.
Answer using ONLY that history (prior guest messages and hotel/property replies).
Rules:
1. If a previous hotel reply already answered this (item found, being held, cab rebooked, etc.), reaffirm that clearly.
2. Never invent new facts. Do not claim the item was found unless a prior hotel reply said so.
3. Do not re-ask the guest to start over or say you will escalate again if the history already resolved it.
4. Do not bring up unrelated earlier topics.
5. 2-4 sentences. No subject line. Start directly with the answer.
""".strip()


def attempt_thread_followup(
    message: str,
    client_name: str,
    conversation_history: list[dict[str, Any]] | None,
) -> AutoAnswerResult | None:
    """
    If the current message is a follow-up on the last 5 window turns and those
    turns already contain a hotel/property reply, draft an answer from that thread.
    Returns None when the history is empty or not topically related.
    """
    matched_turn, overlap = find_best_matching_conversation_turn(message, conversation_history)
    if not matched_turn:
        return None

    prior_reply = str(matched_turn.get("reply_text") or "").strip()
    prior_guest = str(matched_turn.get("content") or "").strip()
    if not prior_reply:
        return None

    recent = [matched_turn]
    source_rows = [
        SourceRow(
            table="conversation_history",
            title="Prior guest message",
            excerpt=prior_guest[:600],
            score=overlap,
        ),
        SourceRow(
            table="conversation_history",
            title="Prior hotel reply",
            excerpt=prior_reply[:600],
            score=overlap,
        ),
    ]

    draft = _generate_thread_followup_draft(message, client_name, recent)
    if not draft:
        draft = (
            f"Yes — following up on your earlier message: {prior_reply[:280].rstrip('.')}. "
            "We'll have this ready for you. Please let us know if you need anything else."
        )

    grounding_passed, grounding_issues = _validate_grounding(draft, source_rows)
    confidence = round(min(0.95, max(0.88, 0.82 + overlap)), 3)
    if not grounding_passed:
        confidence = max(0.72, confidence - 0.08 * len(grounding_issues))

    auto_answered = confidence >= AUTO_ANSWER_THRESHOLD and grounding_passed
    return AutoAnswerResult(
        auto_answered=auto_answered,
        draft=draft,
        confidence=confidence,
        source_table="conversation_history",
        source_excerpt=f"Guest: {prior_guest[:120]} → Hotel: {prior_reply[:160]}",
        source_rows=source_rows,
        grounding_passed=grounding_passed,
        grounding_issues=grounding_issues,
        answer_method="thread_followup",
    )


def _generate_thread_followup_draft(
    message: str,
    client_name: str,
    conversation_history: list[dict[str, Any]],
) -> str | None:
    api_key = (getenv("OPENAI_API_KEY") or "").strip()
    model = (getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()
    formatted = _format_conversation_history(conversation_history)
    if not formatted:
        return None
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            instructions=_THREAD_FOLLOWUP_PROMPT,
            input=(
                f"Hotel: {client_name}\n\n"
                f"Recent conversation history (last 5 exchanges):\n{formatted}\n\n"
                f"Current follow-up from guest: {message[:600]}"
            ),
            max_output_tokens=250,
            temperature=0.2,
        )
        answer = str(getattr(response, "output_text", "") or "").strip()
        return answer if len(answer) > 10 else None
    except Exception:
        return None


# ── Grounding validator ───────────────────────────────────────────────────────

def _validate_grounding(draft: str, source_rows: list[SourceRow]) -> tuple[bool, list[str]]:
    """
    Check that key factual claims in the draft can be traced to at least one source row.
    Heuristic: every sentence in the draft must share at least 2 content tokens with
    the combined source text. Returns (passed, issues_list).
    """
    if not draft or not source_rows:
        return False, ["No draft or no source rows to validate against"]

    combined_source = " ".join(r.excerpt for r in source_rows).lower()
    source_tokens = _tokenize(combined_source)

    issues: list[str] = []
    sentences = [s.strip() for s in re.split(r"[.!?]", draft) if len(s.strip()) > 20]

    for sentence in sentences:
        sentence_tokens = _tokenize(sentence)
        overlap = sentence_tokens & source_tokens
        if len(overlap) < 2:
            # Soft check: allow sentence if it's a standard hospitality phrase
            hospitality_phrases = [
                "happy to help", "please let us know", "feel free", "look forward",
                "assist you", "let us know", "thank you for", "we are delighted",
                "we would be", "our team",
            ]
            is_phrase = any(p in sentence.lower() for p in hospitality_phrases)
            if not is_phrase:
                issues.append(f"Sentence may not be grounded: '{sentence[:80]}...'")

    passed = len(issues) == 0
    return passed, issues


# ── Main entry point ──────────────────────────────────────────────────────────

def attempt_auto_answer(
    message: str,
    client_id: int,
    client_name: str = "the hotel",
    *,
    use_embeddings: bool = False,
    conversation_history: list[dict[str, Any]] | None = None,
) -> AutoAnswerResult:
    """
    Attempt to auto-answer a guest message from FAQ/property data.

    Args:
        message: guest message text
        client_id: resolved client scope
        client_name: hotel name for personalized replies
        use_embeddings: whether to use OpenAI embeddings for scoring (adds latency)

    Returns:
        AutoAnswerResult
    """
    # Retrieve all knowledge for this client
    notes = _get_faq_notes(client_id)
    property_notes = _get_property_details(client_id)
    all_notes = notes + property_notes

    if not all_notes:
        return AutoAnswerResult(
            auto_answered=False,
            draft=None,
            confidence=0.0,
            source_table=None,
            source_excerpt=None,
            answer_method="none",
        )

    # Score each note
    scored: list[SourceRow] = []
    for note in all_notes:
        note_text = str(note.get("note") or "")
        title = str(note.get("title") or "")
        if not note_text:
            continue
        score = _score_note(message, f"{title} {note_text}", use_embeddings=use_embeddings)
        table = "clients.client_notes" if note.get("note_type") != "Property Detail" else "clients.property_details"
        scored.append(SourceRow(
            table=table,
            title=title,
            excerpt=note_text[:600],
            score=score,
        ))

    # Sort by score
    scored.sort(key=lambda x: x.score, reverse=True)
    best = scored[:4]   # top 4 most relevant
    top_score = best[0].score if best else 0.0

    if top_score < FAQ_CONTEXT_THRESHOLD:
        # Not enough evidence to answer from FAQ/property details
        return AutoAnswerResult(
            auto_answered=False,
            draft=None,
            confidence=round(top_score, 3),
            source_table=best[0].table if best else None,
            source_excerpt=best[0].excerpt[:200] if best else None,
            source_rows=best,
            answer_method="none",
        )

    # We have enough evidence — get few-shot learning examples
    few_shot = _get_recent_learning_examples(client_id)

    # Generate LLM draft
    draft = _generate_llm_draft(message, best, client_name, few_shot, conversation_history=conversation_history)

    if not draft:
        # No LLM available — build a deterministic template answer from best note
        draft = f"Thank you for reaching out. {best[0].excerpt[:300].rstrip('.')}. Please let us know if you have any further questions."
        answer_method = "faq_match"
    else:
        answer_method = "llm_grounded"

    # Validate grounding
    grounding_passed, grounding_issues = _validate_grounding(draft, best)

    # Adjust confidence: penalize grounding failures
    confidence = top_score
    if not grounding_passed:
        confidence = max(0.0, confidence - 0.10 * len(grounding_issues))

    confidence = round(min(confidence, 0.99), 3)
    auto_answered = confidence >= AUTO_ANSWER_THRESHOLD and grounding_passed

    best_note = best[0] if best else None
    source_excerpt = None
    if best_note:
        title = (best_note.title or "FAQ").strip()
        excerpt = (best_note.excerpt or "").strip()
        source_excerpt = f"{title}: {excerpt[:260]}" if title else excerpt[:300]

    return AutoAnswerResult(
        auto_answered=auto_answered,
        draft=draft,
        confidence=confidence,
        source_table=best_note.table if best_note else None,
        source_excerpt=source_excerpt,
        source_rows=best,
        grounding_passed=grounding_passed,
        grounding_issues=grounding_issues,
        answer_method=answer_method,
    )
