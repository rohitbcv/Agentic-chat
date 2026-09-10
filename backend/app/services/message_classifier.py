"""
message_classifier.py
=====================
Classifies incoming guest messages into categories and urgency levels.

Pipeline:
1. Rule-based fast pass using keyword patterns (covers ~85% of messages)
2. LLM fallback for ambiguous/mixed messages (raises accuracy to 94-95%)

Returns a ClassificationResult with:
  - category
  - urgency_level
  - requires_ops_action
  - ops_action_type
  - extracted_entities (dates, booking refs, names, times)
  - confidence (0.0–1.0)
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

# ── Category definitions ─────────────────────────────────────────────────────

CATEGORIES = {
    "crisis": [
        "emergency", "fire", "smoke", "medical", "ambulance", "police", "unsafe",
        "danger", "injured", "hurt", "accident", "flood", "gas leak", "security threat",
        "robbery", "assault", "unconscious", "chest pain", "call 911", "help me",
    ],
    "complaint": [
        "not happy", "unhappy", "disappointed", "terrible", "awful", "horrible",
        "unacceptable", "disgusting", "dirty", "broken", "not working", "issue",
        "problem", "complain", "complaint", "refund", "compensation", "manager",
        "escalate", "rude", "ignored", "waiting too long", "noise", "smell",
        "cold room", "hot room", "no hot water", "delay", "late check-in issue",
        "bed bugs", "cockroach", "cockroaches", "pest", "stain", "damaged",
    ],
    "appreciation": [
        "thank you", "thanks", "thank u", "thx", "loved", "amazing", "wonderful",
        "excellent", "fantastic", "great stay", "beautiful", "perfect", "outstanding",
        "highly recommend", "will come back", "five stars", "5 stars", "well done",
        "compliment", "kudos", "brilliant", "superb", "exceptional", "appreciate",
    ],
    "in_house_request": [
        "can you change", "please change", "need to change", "reschedule", "rebook",
        "update my booking", "modify my booking", "can i get", "please bring",
        "room service", "housekeeping", "extra towels", "extra pillow",
        "cab", "taxi", "car", "transfer", "pickup", "drop", "airport",
        "late checkout", "early check-in", "extend my stay", "upgrade",
        "wake up call", "do not disturb", "spa appointment", "restaurant reservation",
        "flight delayed", "flight delay", "my flight", "arriving late", "arriving early",
    ],
    "booking_related": [
        "i booked", "my booking", "my reservation", "booking number", "confirmation",
        "check-in date", "check-out date", "arrival date", "departure date",
        "booking for", "reserved for", "my stay", "cancelled booking", "modify reservation",
        "booking reference", "invoice", "payment", "charged", "receipt",
        "group booking", "group reservation", "bulk booking",
    ],
    "question": [
        "is there", "do you have", "does the hotel", "what time", "when is",
        "what are", "how do i", "how can i", "is it possible", "can i",
        "pet-friendly", "pet friendly", "pets allowed", "smoking", "parking",
        "pool", "spa", "gym", "fitness", "wifi", "breakfast", "restaurant",
        "airport shuttle", "check-in time", "checkout time", "check in time",
        "amenities", "facilities", "services", "policy", "policies",
        "late checkout", "early check in", "what is included",
    ],
    "external_dm": [
        "looking to book", "want to book", "planning to visit", "how much",
        "price", "rate", "availability", "do you have availability",
        "interested in", "enquiry", "inquiry", "quote",
    ],
    "spam": [
        "buy now", "click here", "free offer", "limited time", "win a prize",
        "congratulations you have won", "claim your reward", "subscribe",
        "unsubscribe", "promotional", "advertisement", "advert", "follow us",
        "http://", "https://bit.ly", "bit.ly",
    ],
}

# ── Ops action detection ──────────────────────────────────────────────────────

OPS_ACTION_PATTERNS: list[tuple[str, list[str]]] = [
    ("cab_rebook",         ["cab", "taxi", "car", "transfer", "pickup", "airport transfer"]),
    ("late_checkout",      ["late checkout", "late check-out", "extend checkout", "extra hour"]),
    ("early_checkin",      ["early check-in", "early checkin", "arrive early", "early arrival"]),
    ("room_upgrade",       ["upgrade", "better room", "suite", "executive floor"]),
    ("complaint_followup", ["complaint", "not happy", "unhappy", "refund", "compensation", "manager"]),
    ("booking_correction", ["booking date", "wrong date", "incorrect booking", "check-in date", "check-out date"]),
    ("room_service",       ["room service", "food delivery", "bring to room", "in-room dining"]),
    ("housekeeping",       ["housekeeping", "clean my room", "towels", "pillow", "amenities"]),
    ("spa_booking",        ["spa", "massage", "wellness", "treatment"]),
    ("rate_inquiry",       ["group booking", "group rate", "bulk booking", "corporate rate"]),
    ("flight_delay",       ["flight delayed", "flight delay", "delayed flight", "my flight is"]),
]

# ── Urgency rules ─────────────────────────────────────────────────────────────

URGENCY_OVERRIDES: dict[str, str] = {
    "crisis":         "critical",
    "complaint":      "medium",
    "in_house_request": "high",
    "booking_related": "medium",
    "question":       "low",
    "appreciation":   "low",
    "external_dm":    "low",
    "spam":           "low",
}

HIGH_URGENCY_KEYWORDS = [
    "flight delayed", "flight delay", "emergency", "urgent", "asap", "immediately",
    "right now", "help me", "can't wait", "cannot wait", "as soon as possible",
    "stuck", "stranded", "need help now",
]

# ── Requires ops action by category ──────────────────────────────────────────

REQUIRES_OPS_BY_CATEGORY: dict[str, bool] = {
    "crisis":           True,
    "complaint":        True,
    "in_house_request": True,
    "booking_related":  True,
    "question":         False,   # FAQ auto-answer handles these
    "appreciation":     False,
    "external_dm":      True,
    "spam":             False,
}


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class ExtractedEntities:
    dates: list[str] = field(default_factory=list)
    times: list[str] = field(default_factory=list)
    booking_refs: list[str] = field(default_factory=list)
    guest_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dates": self.dates,
            "times": self.times,
            "booking_refs": self.booking_refs,
            "guest_names": self.guest_names,
        }


@dataclass
class ClassificationResult:
    category: str
    urgency_level: str
    requires_ops_action: bool
    ops_action_type: str | None
    confidence: float
    entities: ExtractedEntities
    classification_method: str   # "rule_based" | "llm" | "llm_fallback_rule"

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "urgency_level": self.urgency_level,
            "requires_ops_action": self.requires_ops_action,
            "ops_action_type": self.ops_action_type,
            "confidence": self.confidence,
            "entities": self.entities.to_dict(),
            "classification_method": self.classification_method,
        }


# ── Entity extraction ─────────────────────────────────────────────────────────

_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:\s+\d{4})?"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+\d{4})?)\b",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)\b|\b\d{1,2}:\d{2}\b")
_BOOKING_REF_RE = re.compile(r"\b(?:booking|reservation|ref|confirmation|#)\s*[:#]?\s*([A-Z0-9]{5,12})\b", re.IGNORECASE)
_NAME_RE = re.compile(r"\bmy name is ([A-Z][a-z]+(?: [A-Z][a-z]+)?)\b", re.IGNORECASE)


def _extract_entities(text: str) -> ExtractedEntities:
    return ExtractedEntities(
        dates=[m.group(0) for m in _DATE_RE.finditer(text)],
        times=[m.group(0) for m in _TIME_RE.finditer(text)],
        booking_refs=[m.group(1) for m in _BOOKING_REF_RE.finditer(text)],
        guest_names=[m.group(1) for m in _NAME_RE.finditer(text)],
    )


# ── Ops action detection ──────────────────────────────────────────────────────

def _detect_ops_action(text_lower: str) -> str | None:
    for action_type, keywords in OPS_ACTION_PATTERNS:
        if any(kw in text_lower for kw in keywords):
            return action_type
    return None


# ── Rule-based classifier ─────────────────────────────────────────────────────

def _rule_based_classify(text: str) -> tuple[str, float]:
    """
    Returns (category, confidence).
    Higher confidence when a single category wins with many keyword hits.
    """
    text_lower = text.lower()
    scores: dict[str, int] = {}

    for category, keywords in CATEGORIES.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits:
            scores[category] = hits

    if not scores:
        return "question", 0.45   # default fallback with low confidence

    # Sort by score descending
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_cat, top_score = ranked[0]

    # Confidence: normalized hit ratio, boosted if category is unambiguous
    total_hits = sum(s for _, s in ranked)
    confidence = min(0.97, 0.60 + (top_score / max(total_hits, 1)) * 0.37)

    # Crisis always gets maximum confidence override
    if top_cat == "crisis":
        confidence = 0.99

    return top_cat, round(confidence, 3)


# ── LLM classifier ────────────────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """
You are a hotel inbox message classifier. Classify the guest message into exactly one category and one urgency level.

Categories (pick exactly one):
- crisis: emergency, fire, medical, security threat, unsafe situation
- complaint: unhappy guest, service failure, damage, noise, bad experience
- appreciation: thank you, compliment, positive feedback, loved their stay
- in_house_request: change cab/taxi, room service, housekeeping, upgrade request, late checkout, flight delay rebook
- booking_related: booking date issue, reservation query, invoice, group booking, payment question
- question: factual question about hotel policy, amenities, services, check-in/out times, pet policy, etc.
- external_dm: enquiry from potential guest not yet booked, availability, pricing
- spam: promotional, irrelevant, automated message

Urgency levels:
- critical: crisis / immediate danger / medical emergency
- high: in-house request needing immediate action, flight delay, urgent complaint
- medium: complaint needing follow-up, booking issue, group inquiry
- low: routine question, appreciation, external DM

Respond with ONLY valid JSON, no explanation:
{
  "category": "<one of the categories above>",
  "urgency_level": "<critical|high|medium|low>",
  "confidence": <0.0 to 1.0>,
  "ops_action_type": "<specific action string or null>",
  "reasoning": "<one sentence>"
}
""".strip()


def _llm_classify(text: str) -> ClassificationResult | None:
    api_key = (getenv("OPENAI_API_KEY") or "").strip()
    model = (getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()
    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            instructions=_LLM_SYSTEM_PROMPT,
            input=f"Guest message:\n{text[:1500]}",
            max_output_tokens=200,
            temperature=0.0,
        )
        raw = str(getattr(response, "output_text", "") or "").strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw).rstrip("` \n")
        data = json.loads(raw)
        category = str(data.get("category", "question")).lower()
        if category not in CATEGORIES:
            category = "question"
        urgency = str(data.get("urgency_level", "low")).lower()
        if urgency not in ("critical", "high", "medium", "low"):
            urgency = URGENCY_OVERRIDES.get(category, "low")
        confidence = float(data.get("confidence", 0.80))
        ops_action = data.get("ops_action_type") or _detect_ops_action(text.lower())
        requires_ops = REQUIRES_OPS_BY_CATEGORY.get(category, False)
        entities = _extract_entities(text)
        return ClassificationResult(
            category=category,
            urgency_level=urgency,
            requires_ops_action=requires_ops,
            ops_action_type=ops_action if requires_ops else None,
            confidence=round(confidence, 3),
            entities=entities,
            classification_method="llm",
        )
    except Exception:
        return None


# ── Main classifier entry point ───────────────────────────────────────────────

def classify_message(
    text: str,
    *,
    use_llm_fallback: bool = True,
    llm_confidence_threshold: float = 0.72,
) -> ClassificationResult:
    """
    Classify a guest message.

    Args:
        text: raw guest message content
        use_llm_fallback: if True, send low-confidence messages to LLM
        llm_confidence_threshold: rule-based confidence below this triggers LLM

    Returns:
        ClassificationResult
    """
    text = (text or "").strip()
    if not text:
        return ClassificationResult(
            category="question",
            urgency_level="low",
            requires_ops_action=False,
            ops_action_type=None,
            confidence=0.0,
            entities=ExtractedEntities(),
            classification_method="rule_based",
        )

    text_lower = text.lower()

    # Rule-based pass
    category, confidence = _rule_based_classify(text)

    # Apply urgency overrides
    urgency = URGENCY_OVERRIDES.get(category, "low")

    # Upgrade urgency if high-urgency keywords found
    if any(kw in text_lower for kw in HIGH_URGENCY_KEYWORDS):
        if urgency not in ("critical",):
            urgency = "high"

    # Detect ops action
    ops_action = _detect_ops_action(text_lower)
    requires_ops = REQUIRES_OPS_BY_CATEGORY.get(category, False)
    # If ops action detected, ensure requires_ops is True
    if ops_action:
        requires_ops = True

    entities = _extract_entities(text)

    result = ClassificationResult(
        category=category,
        urgency_level=urgency,
        requires_ops_action=requires_ops,
        ops_action_type=ops_action if requires_ops else None,
        confidence=confidence,
        entities=entities,
        classification_method="rule_based",
    )

    # LLM fallback for ambiguous messages
    if use_llm_fallback and confidence < llm_confidence_threshold:
        llm_result = _llm_classify(text)
        if llm_result:
            return llm_result
        # LLM failed — return rule result but mark it
        result.classification_method = "llm_fallback_rule"

    return result
