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
    }
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if t not in STOP and len(t) > 2}


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
""".strip()


def _generate_llm_draft(
    message: str,
    best_notes: list[SourceRow],
    client_name: str,
    few_shot_examples: list[dict[str, Any]],
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

    input_text = (
        f"Hotel: {client_name}\n"
        f"Guest message: {message[:600]}\n\n"
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

    if top_score < SUGGESTED_REPLY_THRESHOLD:
        # Not enough evidence for even a suggested reply
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
    draft = _generate_llm_draft(message, best, client_name, few_shot)

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

    return AutoAnswerResult(
        auto_answered=auto_answered,
        draft=draft,
        confidence=confidence,
        source_table=best[0].table if best else None,
        source_excerpt=best[0].excerpt[:300] if best else None,
        source_rows=best,
        grounding_passed=grounding_passed,
        grounding_issues=grounding_issues,
        answer_method=answer_method,
    )
