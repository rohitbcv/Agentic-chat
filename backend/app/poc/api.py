from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from html import escape
import hashlib
import json
import re
import uuid
from os import getenv
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..contracts import RetrievalResult, RoutingPayload
from ..db import repository
from ..read_only import agent_read_only_policy
from ..services.context import MergedContext, merge_retrieval_context
from ..services.embeddings import embedding_status
from ..services.followups import build_follow_up_questions
from ..services.intake import build_routing_payload, load_client_catalog
from ..services.llm_answer import LLMAnswerResult, generate_llm_answer, llm_answer_status
from ..services.orchestrator import build_orchestrator_decision
from ..services.safety import SafetyReview, build_audit_event, evaluate_answer_safety
from ..services.retrievers import SQL_TEMPLATE_CATALOG
from ..services.specialist_agents import SPECIALIST_AGENT_CONTRACTS, run_specialist_agent, _fallback_contract
from ..services.validation import validate_decision, validate_evidence
from .mock_data import AGENT_CARDS, MOCK_CLIENTS, SAMPLE_QUERIES, VALIDATION_SAMPLE_QUERIES

router = APIRouter(prefix="/api/agent-poc", tags=["agent-poc"])

YES_NO_PREFIXES = ("do ", "does ", "is ", "is there ", "are there ", "has ", "have ")
FACT_TERM_STOPWORDS = {
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
    "tell",
    "the",
    "there",
    "this",
    "to",
    "we",
    "what",
    "with",
}


class PocChatRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    client_id: int | None = None
    user_id: int | None = None
    mode: str = "read_only"
    history: list[dict[str, str]] = Field(default_factory=list)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _client_name(payload: RoutingPayload) -> str:
    if payload.entities.property_name:
        return payload.entities.property_name
    if payload.entities.client_id is not None:
        return f"client {payload.entities.client_id}"
    return "this property"


def _truncate(text_value: Any, limit: int = 180) -> str:
    text = " ".join(str(text_value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _excerpt(value: Any, limit: int = 220) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "Content:" in raw:
        raw = raw.split("Content:", 1)[1].strip()
        if ". Aliases:" in raw:
            raw = raw.split(". Aliases:", 1)[0].strip()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    candidate = lines[0] if lines else raw
    return _truncate(candidate, limit=limit)


def _format_datetime(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text_value = str(value).strip()
    if not text_value:
        return ""
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return text_value.replace("T", " ")[:16]


def _window_label(payload: RoutingPayload) -> str:
    date_range = payload.entities.date_range
    if not date_range or not date_range.label:
        return ""
    label_map = {
        "next_week": "next week",
        "last_30_days": "the last 30 days",
        "last_7_days": "the last 7 days",
        "today": "today",
        "yesterday": "yesterday",
    }
    return label_map.get(date_range.label, date_range.label.replace("_", " "))


def _format_joined(items: list[str]) -> str:
    cleaned = [item for item in items if item]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def _split_aggregate(value: Any, *, split_commas: bool = True) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        text = str(value).strip()
        if not text:
            return []
        if "|||" in text:
            raw_items = text.split("|||")
        elif ";" in text:
            raw_items = text.split(";")
        elif split_commas:
            raw_items = text.split(",")
        else:
            raw_items = [text]
    items = []
    for item in raw_items:
        cleaned = " ".join(str(item or "").split())
        if cleaned and cleaned not in items:
            items.append(cleaned)
    return items


def _split_media_context(value: Any, expected_count: int) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    if "|||" in text:
        return _split_aggregate(text, split_commas=False)
    if expected_count > 1 and ";" in text:
        return _split_aggregate(text, split_commas=False)
    return [" ".join(text.split())]


def _parse_tag_list(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [_truncate(item, limit=28) for item in parsed if str(item or "").strip()][:5]
    except Exception:
        pass
    return [_truncate(item, limit=28) for item in _split_aggregate(text)[:5]]


def _svg_palette(seed: str) -> tuple[str, str, str]:
    palettes = [
        ("#0d7f87", "#cf8a2e", "#fffdf7"),
        ("#142942", "#d76645", "#f6f3ec"),
        ("#0f8b70", "#5368a9", "#fffdf7"),
        ("#6f4f2a", "#0d7f87", "#f5f2eb"),
        ("#203a5f", "#c78a36", "#fff7e8"),
    ]
    index = int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:2], 16) % len(palettes)
    return palettes[index]


def _media_thumbnail_url(name: str, description: str, tags: list[str]) -> str:
    color_a, color_b, paper = _svg_palette(f"{name}|{description}|{' '.join(tags)}")
    title = escape(_truncate(name, limit=34))
    subtitle = escape(_truncate(tags[0] if tags else "approved visual", limit=26))
    detail = escape(_truncate(description, limit=58))
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="640" height="420" viewBox="0 0 640 420" role="img" aria-label="{title}">
      <defs>
        <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="{color_a}"/>
          <stop offset="100%" stop-color="{color_b}"/>
        </linearGradient>
        <radialGradient id="glow" cx="30%" cy="20%" r="70%">
          <stop offset="0%" stop-color="{paper}" stop-opacity="0.45"/>
          <stop offset="100%" stop-color="{paper}" stop-opacity="0"/>
        </radialGradient>
      </defs>
      <rect width="640" height="420" rx="42" fill="url(#bg)"/>
      <rect width="640" height="420" rx="42" fill="url(#glow)"/>
      <circle cx="508" cy="92" r="58" fill="{paper}" opacity="0.2"/>
      <circle cx="128" cy="322" r="92" fill="{paper}" opacity="0.12"/>
      <path d="M84 270 L208 160 L292 238 L356 192 L556 316 L556 350 L84 350 Z" fill="{paper}" opacity="0.32"/>
      <rect x="46" y="42" width="548" height="336" rx="32" fill="none" stroke="{paper}" stroke-opacity="0.35" stroke-width="3"/>
      <text x="58" y="92" fill="{paper}" font-family="Manrope, Arial, sans-serif" font-size="22" font-weight="800" letter-spacing="3">MEDIA PREVIEW</text>
      <text x="58" y="318" fill="{paper}" font-family="Manrope, Arial, sans-serif" font-size="30" font-weight="800">{title}</text>
      <text x="58" y="352" fill="{paper}" font-family="Manrope, Arial, sans-serif" font-size="20" opacity="0.9">{subtitle}</text>
      <text x="58" y="382" fill="{paper}" font-family="Manrope, Arial, sans-serif" font-size="16" opacity="0.72">{detail}</text>
    </svg>
    """
    return "data:image/svg+xml;charset=utf-8," + quote(" ".join(svg.split()))


def _build_media_previews(decision_capability: str, sql_result: RetrievalResult | None) -> list[dict[str, Any]]:
    if decision_capability not in {"content_post_detail_lookup", "post_performance_lookup"}:
        return []
    row = sql_result.rows[0] if sql_result and sql_result.rows else None
    if not row:
        return []

    media_ids = _split_aggregate(row.get("media_ids"))
    media_names = _split_aggregate(row.get("media_names"))
    media_context = _split_media_context(row.get("media_context"), max(len(media_ids), len(media_names), 1))
    media_alt_text = _split_media_context(row.get("media_alt_text"), max(len(media_ids), len(media_names), 1))
    media_visual_tags = _split_media_context(row.get("media_visual_tags"), max(len(media_ids), len(media_names), 1))
    preview_count = max(len(media_ids), len(media_names), len(media_context), len(media_alt_text), len(media_visual_tags))
    previews: list[dict[str, Any]] = []

    for index in range(min(preview_count, 4)):
        media_id = media_ids[index] if index < len(media_ids) else ""
        name = media_names[index] if index < len(media_names) else f"Media {media_id or index + 1}"
        description = media_context[index] if index < len(media_context) else ""
        alt_text = media_alt_text[index] if index < len(media_alt_text) else description
        tags = _parse_tag_list(media_visual_tags[index] if index < len(media_visual_tags) else "")
        if not description and not alt_text and not media_id:
            continue
        previews.append(
            {
                "media_id": int(media_id) if str(media_id).isdigit() else media_id,
                "name": name,
                "description": description,
                "alt_text": alt_text,
                "tags": tags,
                "thumbnail_url": _media_thumbnail_url(name, description or alt_text, tags),
                "thumbnail_kind": "generated_from_media_metadata",
                "has_real_asset_url": False,
                "source": "media.media + media.media_analysis_ai",
            }
        )
    return previews


def _normalized_terms(value: str) -> list[str]:
    normalized = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    return [term for term in normalized.split() if term]


def _fact_focus_terms(payload: RoutingPayload) -> list[str]:
    client_terms = set(_normalized_terms(_client_name(payload)))
    terms = []
    for term in _normalized_terms(payload.query):
        if len(term) <= 2:
            continue
        if term in FACT_TERM_STOPWORDS:
            continue
        if term in client_terms:
            continue
        if term not in terms:
            terms.append(term)
    return terms


def _match_contains_focus(match: dict[str, Any], focus_terms: list[str]) -> bool:
    if not focus_terms:
        return True
    haystack = " ".join(
        str(value or "")
        for value in (
            match.get("title"),
            _excerpt(match.get("excerpt"), limit=5000),
            match.get("source_ref"),
            match.get("source_kind"),
            match.get("chunk_label"),
        )
    ).lower()
    return any(term in haystack for term in focus_terms)


def _build_intake_trace(payload: RoutingPayload) -> dict[str, Any]:
    entities = payload.entities
    resolved_bits = []
    if entities.property_name:
        resolved_bits.append(f"client {entities.property_name}")
    elif entities.client_id is not None:
        resolved_bits.append(f"client_id {entities.client_id}")
    if entities.channel:
        resolved_bits.append(f"channel {entities.channel}")
    if entities.date_range and entities.date_range.label:
        resolved_bits.append(f"time {entities.date_range.label}")
    if entities.city:
        resolved_bits.append(f"city {entities.city}")
    summary = "Preprocessed the message, resolved intent candidates, and extracted scope."
    if resolved_bits:
        summary += " Resolved " + ", ".join(resolved_bits) + "."
    return {
        "agent": "Intake Pipeline",
        "status": "completed",
        "summary": summary,
        "intent": payload.intent,
        "scope_client_ids": payload.scope.client_ids,
    }


def _build_orchestrator_trace(payload: RoutingPayload, decision: Any) -> dict[str, Any]:
    return {
        "agent": "Orchestrator Agent",
        "status": "completed",
        "summary": decision.rationale,
        "intent": payload.intent,
        "confidence": decision.confidence,
        "capability": decision.capability,
        "capability_state": decision.capability_state,
        "tables": decision.tables,
    }


def _build_retriever_trace(result: RetrievalResult, agent_name: str) -> dict[str, Any]:
    tables = result.tables
    row_count = len(result.rows) if result.rows else len(result.matches)
    if result.mode == "sql":
        summary = f"Executed approved SQL retrieval and collected {row_count} row(s)."
    else:
        summary = f"Ran approved semantic retrieval and collected {row_count} grounded match(es)."
    if result.support_notes:
        summary += " " + " ".join(result.support_notes)
    return {
        "agent": agent_name,
        "status": "completed",
        "summary": summary,
        "tables": tables,
    }


def _build_context_trace(context: MergedContext) -> dict[str, Any]:
    status = "completed" if context.answerable else "needs_review"
    summary = (
        f"Merged {context.evidence_count} evidence item(s), selected {context.primary_retrieval} as the primary path, "
        f"and assigned {context.confidence_label} confidence ({context.confidence_score})."
    )
    if context.notes:
        summary += " " + " ".join(context.notes[:2])
    return {
        "agent": "Context Merger",
        "status": status,
        "summary": summary,
        "confidence": context.confidence_score,
        "support_level": context.support_level,
    }


def _build_safety_trace(safety: SafetyReview) -> dict[str, Any]:
    return {
        "agent": "Grounding and Safety Layer",
        "status": safety.status,
        "summary": " ".join(safety.notes[:3]),
        "read_only": safety.read_only,
        "capability_state": safety.capability_state,
    }


def _build_validation_trace(validation: Any) -> dict[str, Any]:
    stage_label = "Decision" if validation.stage == "decision" else "Evidence"
    status = validation.status
    summary_parts = [f"Validation Agent — Stage {1 if validation.stage == 'decision' else 2} ({stage_label}) completed with status '{status}'."]
    if validation.blocking_issues:
        summary_parts.append(f"Blocking: {'; '.join(validation.blocking_issues[:2])}")
    elif validation.warnings:
        summary_parts.append(f"Warnings: {'; '.join(validation.warnings[:2])}")
    return {
        "agent": f"Validation Agent — {stage_label} Validation",
        "status": status,
        "summary": " ".join(summary_parts),
        "stage": validation.stage,
        "passed": validation.passed,
        "blocking_issues": validation.blocking_issues,
        "warnings": validation.warnings,
        "notes": validation.notes,
    }


def _build_llm_trace(llm_result: LLMAnswerResult) -> dict[str, Any]:
    status = "completed" if llm_result.used else "skipped"
    if llm_result.enabled and not llm_result.used and llm_result.fallback_reason:
        status = "fallback"
    summary = (
        f"LLM answer generation used `{llm_result.model}` with prompt `{llm_result.prompt_version}`."
        if llm_result.used
        else f"Deterministic answer retained. {llm_result.fallback_reason or 'LLM answer generation was not required.'}"
    )
    return {
        "agent": "LLM Answer Generator",
        "status": status,
        "summary": summary,
        "model": llm_result.model,
        "used": llm_result.used,
        "prompt_version": llm_result.prompt_version,
    }


def _answer_property_fact(payload: RoutingPayload, vector_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    matches = vector_result.matches if vector_result else []
    focus_terms = _fact_focus_terms(payload)
    if not matches:
        if payload.normalized_query.startswith(YES_NO_PREFIXES) and focus_terms:
            requested_fact = " ".join(focus_terms)
            return (
                f"I couldn't verify that {client_name} has {requested_fact} from the approved property notes and details I can read. "
                "The retrieved records did not contain direct evidence for that specific fact."
            )
        return f"I couldn't verify that detail for {client_name} from the grounded property notes and details I can read."

    focused_matches = [match for match in matches if _match_contains_focus(match, focus_terms)]
    if payload.normalized_query.startswith(YES_NO_PREFIXES) and focus_terms and not focused_matches:
        requested_fact = " ".join(focus_terms)
        return (
            f"I couldn't verify that {client_name} has {requested_fact} from the approved property notes and details I can read. "
            "The retrieved records did not contain direct evidence for that specific fact."
        )

    best = focused_matches[0] if focused_matches else matches[0]
    line = _excerpt(best.get("excerpt"))
    if payload.normalized_query.startswith(YES_NO_PREFIXES):
        normalized_line = f" {line.lower()} "
        negative_markers = (" no ", " not ", " not listed", "not allowed", "does not", "is not", "without ")
        if any(marker in normalized_line for marker in negative_markers):
            return f"No positive confirmation found. The grounded property record for {client_name} says: {line}"
        return f"Yes. Based on the grounded property records for {client_name}: {line}"
    return f"The strongest grounded detail I found for {client_name} is: {line}"


def _answer_property_summary(payload: RoutingPayload, vector_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    matches = vector_result.matches if vector_result else []
    if not matches:
        return f"I couldn't build a grounded summary for {client_name} from the currently approved property knowledge sources."
    snippets = []
    for match in matches[:3]:
        snippet = _excerpt(match.get("excerpt"))
        if snippet and snippet not in snippets:
            snippets.append(snippet)
    return f"Here is the grounded property summary I found for {client_name}: {'; '.join(snippets)}."


def _answer_tone(payload: RoutingPayload, vector_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    matches = vector_result.matches if vector_result else []
    if not matches:
        return f"I couldn't find grounded tone-of-voice guidance for {client_name} in the approved read-only sources."

    tone_match = next((match for match in matches if match.get("table") == "clients.client_tone_of_voice_settings"), matches[0])
    audience_matches = [match for match in matches if match.get("table") == "clients.client_target_audience"]
    answer = f"The strongest grounded tone guidance for {client_name} is: {_excerpt(tone_match.get('excerpt'))}"
    if audience_matches:
        audience_labels = [_excerpt(match.get("excerpt"), limit=90) for match in audience_matches[:2]]
        answer += f" The closest audience context points to {_format_joined(audience_labels)}."
    return answer


def _answer_audience(payload: RoutingPayload, vector_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    matches = vector_result.matches if vector_result else []
    if not matches:
        return f"I couldn't find grounded audience data for {client_name} in the approved read-only sources."
    audience_items = []
    for match in matches[:5]:
        label = _excerpt(match.get("excerpt"), limit=100)
        if label and label not in audience_items:
            audience_items.append(label)
    return f"The grounded audience segments I found for {client_name} are {_format_joined(audience_items)}."


def _answer_media(payload: RoutingPayload, vector_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    matches = vector_result.matches if vector_result else []
    if not matches:
        return f"I couldn't find any strong media matches for {client_name} from the approved read-only media analysis records."
    labels = []
    for match in matches[:3]:
        title = str(match.get("title") or match.get("label") or f"media {match.get('media_id')}")
        fit = str(match.get("fit") or "").strip()
        if "score" in fit.lower():
            fit = ""
        labels.append(f"{title} ({fit})" if fit else title)
    return f"The strongest media matches I found for {client_name} are {_format_joined(labels)}."


def _answer_access(payload: RoutingPayload, sql_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    rows = sql_result.rows if sql_result else []
    if not rows:
        return f"I couldn't find any active collaborator access records for {client_name}."
    preview = []
    for row in rows[:5]:
        full_name = str(row.get("full_name") or row.get("user_id") or "Unknown collaborator").strip()
        access_level = str(row.get("access_level") or "").strip()
        preview.append(f"{full_name} ({access_level})" if access_level else full_name)
    return f"I found {len(rows)} active collaborator access record(s) for {client_name}: {_format_joined(preview)}."


def _format_metric_number(value: Any, *, suffix: str = "") -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except Exception:
        return str(value)
    if number.is_integer():
        return f"{int(number)}{suffix}"
    return f"{number:.2f}{suffix}"


def _answer_competitors(payload: RoutingPayload, sql_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    rows = sql_result.rows if sql_result else []
    if not rows:
        return (
            f"I couldn't verify competitors for {client_name} from the approved data I can read. "
            "I also did not find an official competitor list in the inspected schema, so I will not fabricate one."
        )

    target_city = str(rows[0].get("client_city") or "").strip()
    target_type = str(rows[0].get("target_property_type") or "").strip()
    target_rate = rows[0].get("target_average_default_rate")
    same_city_rows = [row for row in rows if int(row.get("same_city") or 0)]
    broader_rows = [row for row in rows if not int(row.get("same_city") or 0)]
    opening = f"I did not find an official competitor list for {client_name}. "
    if same_city_rows and broader_rows and target_city:
        opening += (
            f"Using approved comparable-market signals, I found {len(same_city_rows)} same-market comparable(s) in {target_city} "
            f"and {len(broader_rows)} broader rate/type comparable(s)."
        )
    elif same_city_rows and target_city:
        opening += f"Using approved comparable-market signals, I found {len(same_city_rows)} likely comparable competitor(s) in {target_city}."
    else:
        opening += f"Using approved comparable-market signals, I found {len(rows)} broader rate/type comparable(s)."

    summary_bits = []
    if target_type:
        summary_bits.append(f"property type: {target_type}")
    if target_rate is not None:
        summary_bits.append(f"average default rate signal: {_format_metric_number(target_rate)}")
    if summary_bits:
        opening += f" Baseline used for {client_name}: {_format_joined(summary_bits)}."

    def format_rows(label: str, candidate_rows: list[dict[str, Any]]) -> str:
        lines = []
        for row in candidate_rows[:5]:
            competitor_name = _truncate(row.get("competitor_name") or f"client {row.get('competitor_client_id')}", limit=80)
            reasons = []
            if int(row.get("same_city") or 0):
                city = str(row.get("competitor_city") or target_city or "same city").strip()
                reasons.append(f"same city ({city})")
            if int(row.get("same_property_type") or 0):
                competitor_type = str(row.get("competitor_property_type") or target_type).strip()
                reasons.append(f"same property type ({competitor_type})")
            if int(row.get("similar_rate_band") or 0):
                competitor_rate = _format_metric_number(row.get("competitor_average_default_rate"))
                target_rate_label = _format_metric_number(target_rate)
                rate_reason = "similar rate band"
                if competitor_rate and target_rate_label:
                    rate_reason += f" ({competitor_rate} vs {target_rate_label})"
                reasons.append(rate_reason)
            if not reasons:
                competitor_type = str(row.get("competitor_property_type") or "").strip()
                if competitor_type:
                    reasons.append(f"market type: {competitor_type}")
            score = _format_metric_number(row.get("comparable_score"))
            score_label = f"; comparable score {score}" if score else ""
            reason_label = _format_joined(reasons) if reasons else "matched by available comparable signals"
            lines.append(f"- {competitor_name}: {reason_label}{score_label}.")
        return f"{label}:\n{chr(10).join(lines)}"

    sections = []
    if same_city_rows:
        sections.append(format_rows("Same-market comparables", same_city_rows))
    if broader_rows:
        sections.append(format_rows("Broader comparables", broader_rows))
    if not sections:
        sections.append(format_rows("Likely comparables", rows))

    return (
        f"{opening}\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        "Treat this as an inferred comparable set for analysis, not a confirmed official competitor set."
    )


def _answer_relationships(payload: RoutingPayload, sql_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    rows = sql_result.rows if sql_result else []
    if not rows:
        return f"I couldn't find relationship-graph paths for {client_name} in the approved dummy DB relationship model."

    relationship_counts = Counter(str(row.get("relationship_type") or "RELATED_TO") for row in rows)

    def collect_names(*entity_types: str, relationship_type: str | None = None) -> list[str]:
        names: list[str] = []
        wanted_types = set(entity_types)
        for row in rows:
            if relationship_type and row.get("relationship_type") != relationship_type:
                continue
            for side in ("from", "to"):
                entity_type = str(row.get(f"{side}_entity_type") or "")
                name = _truncate(row.get(f"{side}_entity_name"), limit=74)
                if entity_type in wanted_types and name and name not in names:
                    names.append(name)
            if len(names) >= 6:
                break
        return names

    content_topics = collect_names("ContentTopic", relationship_type="HAS_CONTENT_TOPIC")
    posts = collect_names("Post", relationship_type="HAS_POST")
    media = collect_names("Media", relationship_type="USES_MEDIA") or collect_names("Media", relationship_type="HAS_MEDIA_ASSET")
    metrics = collect_names("MetricSnapshot", "MetricChunk", relationship_type="HAS_ANALYTICS_SNAPSHOT") or collect_names("MetricSnapshot", "MetricChunk")
    events = collect_names("Event", relationship_type="HAS_NEARBY_EVENT")
    networks = collect_names("SocialNetwork", relationship_type="PUBLISHED_ON_NETWORK")
    statuses = collect_names("PostStatus", relationship_type="HAS_POST_STATUS")
    comparables: list[str] = []
    for row in rows:
        if row.get("relationship_type") != "HAS_COMPARABLE_CLIENT":
            continue
        name = _truncate(row.get("to_entity_name"), limit=74)
        if name and name != client_name and name not in comparables:
            comparables.append(name)
        if len(comparables) >= 6:
            break

    sections: list[str] = []
    if content_topics or posts:
        detail = []
        if content_topics:
            detail.append(f"topics: {_format_joined(content_topics[:4])}")
        if posts:
            detail.append(f"posts: {_format_joined(posts[:4])}")
        sections.append(f"- Content: {relationship_counts.get('HAS_CONTENT_TOPIC', 0)} topic link(s) and {relationship_counts.get('HAS_POST', 0)} post link(s); {'; '.join(detail)}.")
    if media:
        sections.append(f"- Media: {relationship_counts.get('USES_MEDIA', 0) + relationship_counts.get('HAS_MEDIA_ASSET', 0)} media link(s); examples: {_format_joined(media[:4])}.")
    if metrics:
        sections.append(f"- Metrics: {relationship_counts.get('HAS_ANALYTICS_SNAPSHOT', 0)} analytics snapshot link(s); examples: {_format_joined(metrics[:4])}.")
    if events:
        sections.append(f"- Events: {relationship_counts.get('HAS_NEARBY_EVENT', 0)} nearby event link(s); examples: {_format_joined(events[:3])}.")
    if comparables:
        sections.append(f"- Market comparables: {relationship_counts.get('HAS_COMPARABLE_CLIENT', 0)} inferred comparable link(s); examples: {_format_joined(comparables[:4])}.")
    if networks or statuses:
        network_detail = []
        if networks:
            network_detail.append(f"networks: {_format_joined(networks[:4])}")
        if statuses:
            network_detail.append(f"statuses: {_format_joined(statuses[:4])}")
        sections.append(f"- Publishing context: {'; '.join(network_detail)}.")

    example_paths = []
    seen_pairs = set()
    for wanted_type in ("HAS_CONTENT_TOPIC", "HAS_POST", "USES_MEDIA", "HAS_ANALYTICS_SNAPSHOT", "HAS_NEARBY_EVENT", "HAS_COMPARABLE_CLIENT"):
        row = next((candidate for candidate in rows if candidate.get("relationship_type") == wanted_type), None)
        if not row:
            continue
        relationship_type = str(row.get("relationship_type") or "RELATED_TO")
        from_name = _truncate(row.get("from_entity_name") or row.get("from_entity_type") or "source", limit=64)
        to_name = _truncate(row.get("to_entity_name") or row.get("to_entity_type") or "target", limit=72)
        pair_key = (relationship_type, from_name, to_name)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        relationship = relationship_type.lower().replace("_", " ")
        example_paths.append(f"- {from_name} -> {relationship} -> {to_name}")

    return (
        f"{client_name} has {len(rows)} verified relationship path(s) in the read-only relationship graph.\n\n"
        f"Connection summary:\n{chr(10).join(sections)}\n\n"
        f"Representative relationship paths:\n{chr(10).join(example_paths)}"
    )


def _answer_inbox(payload: RoutingPayload, sql_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    rows = sql_result.rows if sql_result else []
    if not rows:
        return f"I couldn't find active inbox threads for {client_name} that match this request."

    is_complaint_request = any(word in payload.normalized_query for word in ("complaint", "complaints", "issue", "problem", "cancel"))
    thread_label = "complaint thread" if is_complaint_request else "inbox thread"
    triage_counts = Counter(str(row.get("triage") or "reply_now") for row in rows)
    status_lines = []
    status_order = ["waiting_on_property", "needs_property_help", "reply_now", "property_responded"]
    ordered_labels = [label for label in status_order if label in triage_counts]
    ordered_labels.extend(label for label in triage_counts if label not in ordered_labels)
    for label in ordered_labels:
        count = triage_counts[label]
        status = label.replace("_", " ")
        status_lines.append(f"- {count} {status}")

    previews = []
    for row in rows[:3]:
        title = _truncate(row.get("title") or row.get("latest_preview") or f"thread {row.get('interaction_id')}", limit=100)
        triage = str(row.get("triage") or "reply_now").replace("_", " ")
        last_guest_message_at = _format_datetime(row.get("last_guest_message_at"))
        preview = _truncate(row.get("latest_preview"), limit=180)
        line = f"- {title} — {triage}"
        if last_guest_message_at:
            line += f" — last guest message: {last_guest_message_at}"
        if preview:
            line += f" — \"{preview}\""
        previews.append(line)

    plural = "s" if len(rows) != 1 else ""
    return (
        f"I found {len(rows)} active {thread_label}{plural} for {client_name}.\n\n"
        f"Status breakdown:\n{chr(10).join(status_lines)}\n\n"
        f"Most relevant threads:\n{chr(10).join(previews)}"
    )


def _answer_content_schedule(payload: RoutingPayload, sql_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    rows = sql_result.rows if sql_result else []
    window = _window_label(payload)
    if not rows:
        if window:
            return f"I couldn't find content items for {client_name} in the {window} schedule window."
        return f"I couldn't find upcoming content items for {client_name} in the current schedule window."
    preview = []
    for row in rows[:3]:
        topic_name = _truncate(row.get("topic_name") or row.get("post_preview") or f"post {row.get('post_id')}", limit=90)
        network = str(row.get("social_network") or "scheduled channel").strip()
        scheduled_at = _format_datetime(row.get("post_datetime"))
        status = str(row.get("status") or "").strip()
        descriptor = f"{topic_name} on {scheduled_at} via {network}"
        if status:
            descriptor += f" [{status}]"
        preview.append(descriptor)
    if window:
        return f"I found {len(rows)} content item(s) for {client_name} in {window}. The next ones are {_format_joined(preview)}."
    return f"I found {len(rows)} content item(s) for {client_name}. The next ones are {_format_joined(preview)}."


def _answer_content_approval(payload: RoutingPayload, sql_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    rows = sql_result.rows if sql_result else []
    if not rows:
        return f"I couldn't find draft or approval-workflow items for {client_name}."
    status_counts = Counter(str(row.get("current_status") or "unknown") for row in rows)
    preview = []
    for row in rows[:3]:
        topic_name = _truncate(row.get("topic_name") or row.get("post_preview") or f"post {row.get('post_id')}", limit=90)
        status = str(row.get("current_status") or "unknown").replace("_", " ")
        preview.append(f"{topic_name} [{status}]")
    status_line = ", ".join(f"{count} {status.replace('_', ' ')}" for status, count in status_counts.items())
    return f"I found {len(rows)} approval-flow content item(s) for {client_name}. The current breakdown is {status_line}. The most recent items are {_format_joined(preview)}."


def _answer_content_post_detail(payload: RoutingPayload, sql_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    rows = sql_result.rows if sql_result else []
    if not rows:
        channel = payload.entities.channel
        channel_label = f" {channel.title()}" if channel else ""
        return f"I couldn't find a published{channel_label} post for {client_name} with attached post details."

    row = rows[0]
    network = str(row.get("social_network") or payload.entities.channel or "post").replace("_", " ").strip()
    network_label = "TikTok" if network.lower() == "tiktok" else network.title()
    topic = _truncate(row.get("topic_name") or f"post {row.get('post_id')}", limit=90)
    posted_at = _format_datetime(row.get("post_datetime"))
    post_copy = _truncate(row.get("post_text"), limit=360)

    media_ids = _split_aggregate(row.get("media_ids"))
    media_names = _split_aggregate(row.get("media_names"))
    media_context = _split_aggregate(row.get("media_context"), split_commas=False)
    media_items = []
    for index, media_name in enumerate(media_names):
        media_id = media_ids[index] if index < len(media_ids) else ""
        context = media_context[index] if index < len(media_context) else ""
        label = media_name
        if media_id:
            label += f" (media ID {media_id})"
        if context:
            label += f" - {_truncate(context, limit=120)}"
        media_items.append(label)

    media_line = _format_joined(media_items) if media_items else "No attached media was found for this post."
    return (
        f"I found the latest {network_label} post for {client_name}: {topic} (post ID {row.get('post_id')}) on {posted_at}.\n"
        f"Post copy: \"{post_copy}\"\n"
        f"Media used: {media_line}"
    )


def _answer_post_performance(payload: RoutingPayload, sql_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    rows = sql_result.rows if sql_result else []
    if not rows:
        return f"I couldn't resolve a published post for {client_name} that matches this performance request."

    row = rows[0]
    title = _truncate(row.get("topic_name") or row.get("post_text") or f"post {row.get('post_id')}", limit=100)
    network = str(row.get("social_network") or payload.entities.channel or "resolved channel").strip()
    network_label = network.replace("_", " ").title()
    if network.lower() == "tiktok":
        network_label = "TikTok"
    posted_at = _format_datetime(row.get("post_datetime"))
    snapshot = row.get("analytics_snapshot") or {}
    metrics = []
    for key, label in (("likes", "likes"), ("comments", "comments"), ("reactions", "reactions"), ("shares", "shares"), ("reach", "reach"), ("impressions", "impressions")):
        value = snapshot.get(key)
        if value is not None:
            metrics.append(f"{value} {label}")

    if metrics:
        media_context = _excerpt(row.get("media_context"), limit=140).rstrip(".")
        media_sentence = f" Related media context: {media_context}." if media_context else ""
        return (
            f"Partially supported: the latest {network_label} post with a linked analytics snapshot for {client_name} was {title} on {posted_at}. "
            f"I found {_format_joined(metrics)} in the linked analytics snapshot.{media_sentence}"
        )

    return (
        f"Partially supported: I found the latest {network_label} post for {client_name} as {title} on {posted_at}, "
        "but I couldn't resolve a linked analytics snapshot for it yet."
    )


def _answer_events(payload: RoutingPayload, sql_result: RetrievalResult | None) -> str:
    client_name = _client_name(payload)
    rows = sql_result.rows if sql_result else []
    if not rows:
        return f"I couldn't find upcoming event records tied to {client_name}."
    preview = []
    for row in rows[:3]:
        name = _truncate(row.get("name") or f"event {row.get('id')}", limit=90)
        event_date = _format_datetime(row.get("date"))
        preview.append(f"{name} on {event_date}")
    return f"I found {len(rows)} upcoming event(s) relevant to {client_name}. The next ones are {_format_joined(preview)}."


def _answer_pricing(payload: RoutingPayload) -> str:
    client_name = _client_name(payload)
    return (
        f"I can't answer live room pricing for {client_name} from the current read-only data because "
        "there isn't a dependable rate or booking-price source exposed to this assistant."
    )


def _build_answer(payload: RoutingPayload, decision: Any, sql_result: RetrievalResult | None, vector_result: RetrievalResult | None) -> str:
    capability = decision.capability

    if capability == "property_fact_lookup":
        return _answer_property_fact(payload, vector_result)
    if capability == "property_knowledge_summary":
        return _answer_property_summary(payload, vector_result)
    if capability == "tone_of_voice_lookup":
        return _answer_tone(payload, vector_result)
    if capability == "audience_lookup":
        return _answer_audience(payload, vector_result)
    if capability == "media_recommendation":
        return _answer_media(payload, vector_result)
    if capability == "client_access_lookup":
        return _answer_access(payload, sql_result)
    if capability == "competitor_lookup":
        return _answer_competitors(payload, sql_result)
    if capability == "relationship_lookup":
        return _answer_relationships(payload, sql_result)
    if capability == "inbox_lookup":
        return _answer_inbox(payload, sql_result)
    if capability == "content_schedule_lookup":
        return _answer_content_schedule(payload, sql_result)
    if capability == "content_approval_lookup":
        return _answer_content_approval(payload, sql_result)
    if capability == "content_post_detail_lookup":
        return _answer_content_post_detail(payload, sql_result)
    if capability == "post_performance_lookup":
        return _answer_post_performance(payload, sql_result)
    if capability == "event_lookup":
        return _answer_events(payload, sql_result)
    if capability == "pricing_lookup":
        return _answer_pricing(payload)

    return "I couldn't complete that request safely from the currently approved read-only routes."


def _build_sql_plan(result: RetrievalResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "template_key": result.template_key,
        "tables": result.tables,
        "query": result.sql,
        "rows": _json_safe(result.rows),
        "mock_rows": _json_safe(result.rows),
        "support_notes": result.support_notes,
    }


def _build_knowledge_plan(result: RetrievalResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    sources = []
    for match in result.matches[:5]:
        sources.append(
            {
                "title": str(match.get("title") or match.get("label") or "Grounded source"),
                "table": str(match.get("table") or "approved_knowledge_source"),
                "excerpt": _excerpt(match.get("excerpt")),
            }
        )
    semantic_matches = []
    for match in result.matches[:5]:
        fit = match.get("fit")
        score = match.get("score")
        if fit:
            semantic_matches.append({"label": str(match.get("title") or match.get("label") or "Match"), "fit": str(fit)})
        elif score is not None:
            semantic_matches.append({"label": str(match.get("title") or match.get("label") or "Match"), "fit": f"grounded text score {score}"})
    return {
        "sources": sources,
        "matches": semantic_matches,
    }


def _config_clients() -> list[dict[str, Any]]:
    mock_by_id = {int(client["id"]): client for client in MOCK_CLIENTS}
    clients = []
    for client in load_client_catalog():
        client_id = int(client["id"])
        fallback = mock_by_id.get(client_id, {})
        clients.append(
            {
                "id": client_id,
                "name": str(client["name"]),
                "city": client.get("city") or fallback.get("city") or "",
                "domain": fallback.get("domain") or "live client scope",
            }
        )
    if clients:
        return clients
    return MOCK_CLIENTS


def _route_payload(decision: Any) -> dict[str, Any]:
    return {
        "intent": decision.intent,
        "next_agent": decision.agent_name,
        "confidence": decision.confidence,
        "rationale": decision.rationale,
        "domain": decision.domain,
        "tables": decision.tables,
        "support_level": decision.capability_state,
        "capability": decision.capability,
        "retriever_modes": decision.retriever_modes,
    }


def _embedding_storage_status() -> dict[str, Any]:
    status = embedding_status().to_dict()
    has_metric_table = repository.table_exists("analytics", "metric_embeddings")
    metric_rows = []
    if has_metric_table:
        metric_rows = repository.execute_query("SELECT COUNT(*) AS count FROM analytics.metric_embeddings")
    has_knowledge_table = repository.table_exists("general", "knowledge_embeddings")
    knowledge_rows = []
    knowledge_domain_rows = []
    if has_knowledge_table:
        knowledge_rows = repository.execute_query("SELECT COUNT(*) AS count FROM general.knowledge_embeddings")
        knowledge_domain_rows = repository.execute_query(
            """
            SELECT knowledge_domain, COUNT(*) AS count
            FROM general.knowledge_embeddings
            GROUP BY knowledge_domain
            ORDER BY knowledge_domain
            """
        )
    status["metric_storage_table"] = "analytics.metric_embeddings"
    status["metric_storage_available"] = has_metric_table
    status["stored_metric_documents"] = int(metric_rows[0].get("count") or 0) if metric_rows else 0
    status["knowledge_storage_table"] = "general.knowledge_embeddings"
    status["knowledge_storage_available"] = has_knowledge_table
    status["stored_knowledge_documents"] = int(knowledge_rows[0].get("count") or 0) if knowledge_rows else 0
    status["stored_knowledge_documents_by_domain"] = {
        str(row.get("knowledge_domain")): int(row.get("count") or 0) for row in knowledge_domain_rows
    }
    return status


@router.get("/config")
def get_agent_poc_config() -> dict[str, Any]:
    return {
        "product_name": "Soho AI Query Studio",
        "mode": "phase-9-read-only-intelligence",
        "read_only": True,
        "read_only_policy": agent_read_only_policy(),
        "embedding_status": _embedding_storage_status(),
        "llm_answer_status": llm_answer_status(),
        "goals": [
            "Route open-ended questions by reusable capability, not fixed prompt examples.",
            "Use specialist read-only agents with approved SQL, vector, and future graph contracts.",
            "Merge exact rows and semantic context into confidence-scored grounded answers.",
            "Keep every action advisory-only: no send, approve, publish, assign, update, or delete.",
        ],
        "agents": AGENT_CARDS,
        "clients": _config_clients(),
        "sample_queries": SAMPLE_QUERIES,
        "validation_sample_queries": VALIDATION_SAMPLE_QUERIES,
        "backend_notes": [
            "Phase 0 and Phase 1 docs lock the read-only scope and exposure rules.",
            "Phase 2 intake resolves intent, entities, and scoped client access before retrieval.",
            "Phase 3 uses approved SQL templates and deterministic semantic retrieval over allowed text sources.",
            "Phase 4 centralizes routing through the Orchestrator Agent and returns capability-state metadata for each run.",
            "Phases 5-7 add specialist-agent contracts, context merging, confidence scoring, and safety checks.",
            "Phase 8 exposes route, source, confidence, and advisory-only state in the UI.",
            "Phase 9 adds evaluation scripts and scorecard docs for regression testing.",
        ],
    }


@router.get("/embedding-status")
def get_embedding_status() -> dict[str, Any]:
    return _embedding_storage_status()


@router.post("/chat")
def run_agent_poc_chat(payload: PocChatRequest) -> dict[str, Any]:
    query = payload.query.strip()
    chat_history = [dict(item) for item in payload.history[-12:]]
    routing_payload = build_routing_payload(query, explicit_client_id=payload.client_id, user_id=payload.user_id)
    decision = build_orchestrator_decision(routing_payload)

    trace: list[dict[str, Any]] = [
        _build_intake_trace(routing_payload),
        _build_orchestrator_trace(routing_payload, decision),
    ]

    if decision.branch == "clarification":
        answer = decision.clarification_question or "Which client or property should I use for this question?"
        context = merge_retrieval_context(routing_payload, decision, None, None)
        safety = evaluate_answer_safety(answer, routing_payload, decision, context)
        follow_up_questions = build_follow_up_questions(
            routing_payload,
            decision,
            context,
            None,
            None,
            answer,
            chat_history=chat_history,
        )
        trace.extend([_build_context_trace(context), _build_safety_trace(safety)])
        return {
            "mode": "clarification",
            "query": query,
            "client_id": routing_payload.entities.client_id,
            "capability_state": decision.capability_state,
            "route": _route_payload(decision),
            "answer": answer,
            "follow_up_questions": follow_up_questions,
            "agent_trace": trace,
            "sql_plan": None,
            "knowledge_plan": None,
            "sources": [],
            "source_trace": [],
            "context": context.to_dict(),
            "safety": safety.to_dict(),
            "audit_event": build_audit_event(query, routing_payload, decision, context, safety),
            "intake": routing_payload.to_dict(),
            "orchestrator": decision.to_dict(),
        }

    if decision.branch == "unsupported_action":
        answer = decision.refusal_message or "This assistant is read-only and cannot perform that action."
        context = merge_retrieval_context(routing_payload, decision, None, None)
        safety = evaluate_answer_safety(answer, routing_payload, decision, context)
        follow_up_questions = build_follow_up_questions(
            routing_payload,
            decision,
            context,
            None,
            None,
            answer,
            chat_history=chat_history,
        )
        trace.extend([_build_context_trace(context), _build_safety_trace(safety)])
        return {
            "mode": "read_only_refusal",
            "query": query,
            "client_id": routing_payload.entities.client_id,
            "capability_state": decision.capability_state,
            "route": _route_payload(decision),
            "answer": answer,
            "follow_up_questions": follow_up_questions,
            "agent_trace": trace,
            "sql_plan": None,
            "knowledge_plan": None,
            "sources": [],
            "source_trace": [],
            "context": context.to_dict(),
            "safety": safety.to_dict(),
            "audit_event": build_audit_event(query, routing_payload, decision, context, safety),
            "intake": routing_payload.to_dict(),
            "orchestrator": decision.to_dict(),
        }

    # Stage 1 — Decision Validation
    _contract = SPECIALIST_AGENT_CONTRACTS.get(decision.agent_name, _fallback_contract(decision.agent_name))
    decision_validation = validate_decision(
        routing_payload,
        decision,
        allowed_tables=_contract.allowed_tables,
        allowed_retriever_modes=_contract.allowed_retriever_modes,
        known_template_keys=set(SQL_TEMPLATE_CATALOG.keys()),
        agent_name=_contract.name,
    )
    trace.append(_build_validation_trace(decision_validation))

    if not decision_validation.passed:
        context = merge_retrieval_context(routing_payload, decision, None, None)
        safety = evaluate_answer_safety(
            "; ".join(decision_validation.blocking_issues) or "Validation blocked this request.",
            routing_payload,
            decision,
            context,
        )
        follow_up_questions = build_follow_up_questions(
            routing_payload, decision, context, None, None,
            "; ".join(decision_validation.blocking_issues),
            chat_history=chat_history,
        )
        trace.extend([_build_context_trace(context), _build_safety_trace(safety)])
        return {
            "mode": "validation_blocked",
            "query": query,
            "client_id": routing_payload.entities.client_id,
            "capability_state": decision.capability_state,
            "route": _route_payload(decision),
            "answer": "This request could not proceed because the decision did not pass validation. " + "; ".join(decision_validation.blocking_issues),
            "follow_up_questions": follow_up_questions,
            "agent_trace": trace,
            "sql_plan": None,
            "knowledge_plan": None,
            "sources": [],
            "source_trace": [],
            "context": context.to_dict(),
            "safety": safety.to_dict(),
            "audit_event": build_audit_event(query, routing_payload, decision, context, safety),
            "intake": routing_payload.to_dict(),
            "orchestrator": decision.to_dict(),
            "decision_validation": decision_validation.to_dict(),
            "evidence_validation": None,
        }

    agent_run = run_specialist_agent(routing_payload, decision)
    sql_result = agent_run.sql_result
    vector_result = agent_run.vector_result
    source_traces = [trace_item.to_dict() for trace_item in agent_run.source_traces]
    trace.extend(agent_run.trace_steps)

    # Stage 2 — Evidence Validation
    evidence_validation = validate_evidence(
        routing_payload,
        decision,
        sql_result,
        vector_result,
        allowed_tables=_contract.allowed_tables,
    )
    trace.append(_build_validation_trace(evidence_validation))

    context = merge_retrieval_context(routing_payload, decision, sql_result, vector_result)
    trace.append(_build_context_trace(context))

    deterministic_answer = _build_answer(routing_payload, decision, sql_result, vector_result)
    llm_result = generate_llm_answer(routing_payload, decision, context, sql_result, vector_result, deterministic_answer)
    trace.append(_build_llm_trace(llm_result))
    answer = llm_result.answer if llm_result.used and llm_result.answer else deterministic_answer
    safety = evaluate_answer_safety(answer, routing_payload, decision, context)
    trace.append(_build_safety_trace(safety))
    follow_up_questions = build_follow_up_questions(
        routing_payload,
        decision,
        context,
        sql_result,
        vector_result,
        answer,
        chat_history=chat_history,
    )
    sql_plan = _build_sql_plan(sql_result)
    knowledge_plan = _build_knowledge_plan(vector_result)
    media_previews = _build_media_previews(decision.capability, sql_result)

    response_mode = "read_only_no_match"
    if sql_result and vector_result:
        response_mode = "hybrid_sql_vector"
    elif sql_result:
        response_mode = "read_only_sql"
    elif vector_result and vector_result.matches:
        response_mode = "grounded_knowledge"
    elif decision.capability_state == "not_supported":
        response_mode = "not_supported"

    sources = []
    for trace_item in source_traces:
        for table in trace_item.get("tables", []):
            if table not in sources:
                sources.append(table)

    return {
        "mode": response_mode,
        "query": query,
        "client_id": routing_payload.entities.client_id,
        "capability_state": context.support_level,
        "route": _route_payload(decision),
        "answer": answer,
        "follow_up_questions": follow_up_questions,
        "media_previews": media_previews,
        "deterministic_answer": deterministic_answer,
        "llm_answer": llm_result.to_dict(),
        "agent_trace": trace,
        "specialist_agent": agent_run.to_dict(),
        "sql_plan": sql_plan,
        "knowledge_plan": knowledge_plan,
        "sources": sources,
        "source_trace": _json_safe(source_traces),
        "context": context.to_dict(),
        "safety": safety.to_dict(),
        "audit_event": build_audit_event(query, routing_payload, decision, context, safety),
        "intake": routing_payload.to_dict(),
        "orchestrator": decision.to_dict(),
        "decision_validation": decision_validation.to_dict(),
        "evidence_validation": evidence_validation.to_dict(),
    }


# ── Intelligent Inbox: Process Message ────────────────────────────────────────

from ..services.message_classifier import classify_message
from ..services.message_auto_answer import (
    attempt_auto_answer,
    attempt_thread_followup,
    relevant_conversation_history,
)
from ..services.message_escalation import (
    build_escalation_packet,
    draft_from_prior_property_response,
    find_similar_property_response,
    find_similar_unanswered_property_question,
    record_property_answer,
)


class ConversationTurn(BaseModel):
    content: str = ""
    reply_text: str | None = None
    replies: list[dict[str, Any]] = Field(default_factory=list)
    category: str | None = None
    triage_state: str | None = None
    ts: str | None = None
    author: str | None = None


class ProcessMessageRequest(BaseModel):
    message_content: str = Field(min_length=1, max_length=5000)
    client_id: int
    message_type: str = "messages"   # comments | messages | review | mentions
    author: str | None = None
    interaction_id: int | None = None
    conversation_history: list[ConversationTurn] = Field(default_factory=list)


def _log_auto_response(
    message_id: int | None,
    client_id: int,
    category: str,
    urgency: str,
    draft: str | None,
    confidence: float,
    source_table: str | None,
    source_excerpt: str | None,
    ops_action: str = "auto_replied",
    final_answer: str | None = None,
) -> None:
    """Insert a row into jx_bridge.auto_response_log for learning + accuracy tracking."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        rows = repository.execute_query(
            "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM jx_bridge.auto_response_log",
            {},
        )
        next_id = rows[0]["next_id"] if rows else 1
        repository.execute_query(
            """
            INSERT INTO jx_bridge.auto_response_log
            (id, message_id, client_id, category, urgency_level, draft_answer, confidence,
             ops_action, final_answer, source_table, source_excerpt, inserted_datetime)
            VALUES (:id, :message_id, :client_id, :category, :urgency_level, :draft_answer,
                    :confidence, :ops_action, :final_answer, :source_table, :source_excerpt,
                    :inserted_datetime)
            """,
            {
                "id": next_id,
                "message_id": message_id,
                "client_id": client_id,
                "category": category,
                "urgency_level": urgency,
                "draft_answer": draft,
                "confidence": confidence,
                "ops_action": ops_action,
                "final_answer": final_answer or draft,
                "source_table": source_table,
                "source_excerpt": (source_excerpt or "")[:400],
                "inserted_datetime": now,
            },
        )
    except Exception:
        pass  # logging must never break the main flow


def _store_learned_faq(client_id: int, message_excerpt: str, corrected_answer: str) -> None:
    """When ops edits/corrects an answer, store it as a learned client_note (type_id=3)."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        rows = repository.execute_query(
            "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM clients.client_notes",
            {},
        )
        next_id = rows[0]["next_id"] if rows else 1
        repository.execute_query(
            """
            INSERT INTO clients.client_notes
            (id, client_id, title, note, type_id, inserted_datetime, updated_datetime, deleted_at)
            VALUES (:id, :client_id, :title, :note, 3, :now, :now, NULL)
            """,
            {
                "id": next_id,
                "client_id": client_id,
                "title": f"Learned response: {message_excerpt[:80]}",
                "note": corrected_answer,
                "now": now,
            },
        )
    except Exception:
        pass


_REPLY_NOW_TEMPLATES: dict[str, str] = {
    "appreciation": "Thank you so much for your kind words — it truly means a lot to our entire team. We're so glad you had a wonderful experience with us and hope to welcome you back very soon!",
    "spam": "Thank you for reaching out. This message does not appear to require a response from our team.",
}

_REPLY_NOW_SYSTEM_PROMPT = """
You are a warm, professional hotel concierge. Write a brief, human-like reply to the guest message.
Keep it to 2-3 sentences. Do not ask questions. Do not mention the hotel name in the first word.
For appreciation/thank-you messages: acknowledge warmly, express gratitude, invite them back.
For spam or irrelevant messages: a polite non-committal acknowledgement.
Return plain text only — no subject line, no greeting.
""".strip()


def _format_auto_answer_source_label(
    source_table: str | None,
    *,
    used_prior_property: bool = False,
    used_conversation: bool = False,
) -> str | None:
    """Human-readable source label for the UI confidence panel."""
    if used_prior_property:
        return "prior property reply for this client"
    if used_conversation or source_table == "conversation_history":
        return "matching prior message in this thread"
    if source_table == "clients.property_details":
        return "property details"
    if source_table == "clients.client_notes":
        return "FAQ / client notes"
    if source_table == "prior_property_response":
        return "prior property reply for this client"
    return source_table


def _normalize_conversation_history(turns: list[ConversationTurn], limit: int = 5) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for turn in turns[-limit:]:
        content = (turn.content or "").strip()
        reply = (turn.reply_text or "").strip()
        replies = [
            {
                "text": str(item.get("text") or "").strip(),
                "ops_action": item.get("ops_action"),
                "source": item.get("source"),
            }
            for item in (turn.replies or [])
            if isinstance(item, dict) and str(item.get("text") or "").strip()
        ]
        if not replies and reply:
            replies = [{"text": reply, "ops_action": None, "source": None}]
        if not content and not reply and not replies:
            continue
        latest = replies[-1]["text"] if replies else (reply or None)
        history.append({
            "content": content,
            "reply_text": latest,
            "replies": replies,
            "category": turn.category,
            "triage_state": turn.triage_state,
            "ts": turn.ts,
            "author": turn.author,
        })
    return history


def _generate_reply_now_draft(
    message: str,
    category: str,
    client_name: str,
    client_id: int,
    conversation_history: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a suggested reply for reply_now categories (appreciation, spam, etc.)."""
    api_key = (getenv("OPENAI_API_KEY") or "").strip()
    model = (getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()

    history_block = ""
    related = relevant_conversation_history(message, conversation_history or [])
    if related:
        from ..services.message_auto_answer import _format_conversation_history
        formatted = _format_conversation_history(related)
        if formatted:
            history_block = f"\nRelated conversation history:\n{formatted}\n"

    if api_key:
        try:
            from openai import OpenAI as _OpenAI
            _client = _OpenAI(api_key=api_key)
            response = _client.responses.create(
                model=model,
                instructions=_REPLY_NOW_SYSTEM_PROMPT,
                input=f"Hotel: {client_name}\nCategory: {category}{history_block}\nGuest message: {message[:800]}",
                max_output_tokens=150,
                temperature=0.4,
            )
            draft = str(getattr(response, "output_text", "") or "").strip()
            if len(draft) > 10:
                return draft
        except Exception:
            pass

    return _REPLY_NOW_TEMPLATES.get(category, "Thank you for your message. Our team will be in touch shortly.")


@router.post("/process-message")
def process_incoming_message(payload: ProcessMessageRequest) -> dict[str, Any]:
    """
    Intelligent inbox processor for incoming guest messages.

    Pipeline:
    1. Classify message (category, urgency, ops action)
    2. If routine question → attempt FAQ auto-answer (confidence >= 0.90 → auto-reply)
    3. If complex/actionable or low confidence → escalate to ops with context + suggested reply
    4. Log everything to auto_response_log for learning and accuracy tracking
    """
    message = (payload.message_content or "").strip()
    client_id = payload.client_id
    conversation_history = _normalize_conversation_history(payload.conversation_history or [])

    # Resolve client name for human-like replies
    client_name = "the hotel"
    try:
        catalog = load_client_catalog()
        match = next((c for c in catalog if c.get("id") == client_id), None)
        if match:
            client_name = str(match.get("name") or "the hotel")
    except Exception:
        pass

    # ── Stage 1: Classify ─────────────────────────────────────────────────────
    classification = classify_message(message, message_type=payload.message_type)

    triage_state = "reply_now"
    auto_answered = False
    auto_answer_draft = None
    auto_answer_confidence = 0.0
    auto_answer_source_table = None
    auto_answer_source_excerpt = None
    escalation_packet_dict = None
    suggested_reply_only = None  # 0.70-0.89 confidence draft for ops
    pending_reply_draft = None   # draft for reply_now categories (appreciation, spam, etc.)
    used_conversation_context = False
    used_prior_property_response = False
    prior_property_match = None
    faq_can_answer = False
    is_critical = (
        classification.category == "crisis"
        or classification.urgency_level == "critical"
    )

    # Only the one prior turn that actually matches this message (not the whole window).
    related_history = relevant_conversation_history(message, conversation_history)

    # ── Stage 1.6: Reuse a prior property answer for this client ─────────────
    # If this exact/similar question was already asked to the property, do not
    # raise it again unless the new message is critical/crisis.
    # Runs before thread follow-up so a real property answer beats a generic
    # "we're checking" draft sitting in Recent Conversations.
    if not is_critical:
        prior_match = find_similar_property_response(
            message,
            client_id,
            extra_candidates=_property_chat_candidates(client_id),
        )
        if prior_match and prior_match.property_reply:
            reused_draft = draft_from_prior_property_response(message, client_name, prior_match)
            used_prior_property_response = True
            prior_property_match = prior_match.to_dict()
            auto_answered = True
            auto_answer_draft = reused_draft
            auto_answer_confidence = round(min(0.94, max(0.88, prior_match.score)), 3)
            auto_answer_source_table = prior_match.source
            auto_answer_source_excerpt = prior_match.property_reply[:300]
            triage_state = "auto_replied"
            _log_auto_response(
                message_id=None,
                client_id=client_id,
                category=classification.category,
                urgency=classification.urgency_level,
                draft=auto_answer_draft,
                confidence=auto_answer_confidence,
                source_table="prior_property_response",
                source_excerpt=f"Guest: {prior_match.guest_message[:180]} Property: {prior_match.property_reply[:180]}",
                ops_action="auto_replied",
                final_answer=auto_answer_draft,
            )

    # ── Stage 2: FAQ / property details (prefer over thread for new questions) ──
    if (
        not auto_answered
        and classification.category in ("question", "booking_related")
        and not classification.requires_ops_action
    ):
        auto_result = attempt_auto_answer(
            message,
            client_id,
            client_name,
            conversation_history=[],  # FAQ answers from property data only
        )
        auto_answer_confidence = auto_result.confidence
        auto_answer_source_table = auto_result.source_table
        auto_answer_source_excerpt = auto_result.source_excerpt

        if auto_result.auto_answered:
            auto_answered = True
            faq_can_answer = True
            auto_answer_draft = auto_result.draft
            triage_state = "auto_replied"
            _log_auto_response(
                message_id=None,
                client_id=client_id,
                category=classification.category,
                urgency=classification.urgency_level,
                draft=auto_answer_draft,
                confidence=auto_answer_confidence,
                source_table=auto_answer_source_table,
                source_excerpt=auto_answer_source_excerpt,
                ops_action="auto_replied",
                final_answer=auto_answer_draft,
            )

        elif auto_result.draft:
            faq_can_answer = True
            pending_reply_draft = auto_result.draft
            auto_answer_draft = auto_result.draft
            suggested_reply_only = auto_result.draft
            triage_state = "pending_ops_approval"
        else:
            triage_state = "pending_ops_approval"

    # ── Stage 1.5: Thread follow-up only when FAQ did not answer ──────────────
    # Example: bag already confirmed held → "is my bag found?" should not re-escalate.
    if (
        not auto_answered
        and not faq_can_answer
        and related_history
        and classification.category != "crisis"
    ):
        thread_result = attempt_thread_followup(message, client_name, related_history)
        if thread_result and thread_result.draft:
            used_conversation_context = True
            auto_answer_confidence = thread_result.confidence
            auto_answer_source_table = thread_result.source_table
            auto_answer_source_excerpt = thread_result.source_excerpt
            if thread_result.auto_answered:
                auto_answered = True
                auto_answer_draft = thread_result.draft
                triage_state = "auto_replied"
                _log_auto_response(
                    message_id=None,
                    client_id=client_id,
                    category=classification.category,
                    urgency=classification.urgency_level,
                    draft=auto_answer_draft,
                    confidence=auto_answer_confidence,
                    source_table=auto_answer_source_table,
                    source_excerpt=auto_answer_source_excerpt,
                    ops_action="auto_replied",
                    final_answer=auto_answer_draft,
                )
            else:
                suggested_reply_only = thread_result.draft
                triage_state = "pending_ops_approval"

    # ── Stage 2b: Draft reply for non-escalated categories (appreciation, spam, reply_now) ──
    # Always generate a suggested reply so ops can review before sending — never send blind.
    elif (
        not auto_answered
        and not used_conversation_context
        and (
            classification.category in ("appreciation", "spam")
            or (
                not classification.requires_ops_action
                and classification.urgency_level == "low"
                and triage_state == "reply_now"
            )
        )
    ):
        pending_reply_draft = _generate_reply_now_draft(
            message,
            classification.category,
            client_name,
            client_id,
            conversation_history=related_history,
        )

    # ── Stage 3: Escalation ───────────────────────────────────────────────────
    needs_escalation = (
        not auto_answered
        and not faq_can_answer
        and (
            classification.requires_ops_action
            or classification.category in ("complaint", "crisis", "in_house_request", "external_dm")
            or classification.urgency_level in ("critical", "high")
            or triage_state == "pending_ops_approval"
        )
    )

    if needs_escalation and not is_critical:
        # Same question already with property (waiting on an answer) — do not re-ask.
        already_asked = find_similar_unanswered_property_question(message, client_id)
        if already_asked:
            needs_escalation = False
            triage_state = "pending_ops_approval"
            if not suggested_reply_only:
                suggested_reply_only = (
                    "Our property team is already looking into this and will follow up shortly. "
                    "We will share the confirmed details as soon as we have them."
                )
            pending_reply_draft = suggested_reply_only
            prior_property_match = already_asked.to_dict()

    if needs_escalation:
        packet = build_escalation_packet(
            message=message,
            client_id=client_id,
            client_name=client_name,
            classification=classification,
            interaction_id=payload.interaction_id,
            auto_answer_draft=suggested_reply_only,
            message_type=payload.message_type,
            conversation_history=related_history,
        )
        escalation_packet_dict = packet.to_dict()
        triage_state = packet.triage_state

        # Log escalation
        _log_auto_response(
            message_id=None,
            client_id=client_id,
            category=classification.category,
            urgency=classification.urgency_level,
            draft=packet.suggested_reply,
            confidence=auto_answer_confidence,
            source_table=auto_answer_source_table,
            source_excerpt=auto_answer_source_excerpt,
            ops_action="pending_ops_approval",
            final_answer=None,
        )

    # ── Persist turn on this client's inbox thread ────────────────────────────
    reply_draft = (
        auto_answer_draft
        or pending_reply_draft
        or suggested_reply_only
        or (escalation_packet_dict or {}).get("suggested_reply")
    )
    inbox_turn = _append_inbox_thread_turn(
        client_id=client_id,
        content=message,
        author=payload.author or "Guest",
        message_type=payload.message_type,
        channel_label=classification.channel_label,
        category=classification.category,
        urgency_level=classification.urgency_level,
        triage_state=triage_state,
        reply_text=reply_draft,
        ops_action=(
            "auto_replied"
            if auto_answered
            else "escalated"
            if triage_state == "escalated_crisis"
            else "pending"
        ),
    )

    # ── Response ──────────────────────────────────────────────────────────────
    return {
        "message_content": message,
        "client_id": client_id,
        "inbox_turn_id": inbox_turn.get("turn_id"),
        "client_name": client_name,
        "message_type": payload.message_type,
        "channel_label": classification.channel_label,
        "classification": classification.to_dict(),
        "auto_answered": auto_answered,
        "auto_answer_draft": auto_answer_draft,
        "auto_answer_confidence": round(auto_answer_confidence, 3),
        "auto_answer_source_table": auto_answer_source_table,
        "auto_answer_source_excerpt": auto_answer_source_excerpt,
        "auto_answer_source_label": _format_auto_answer_source_label(
            auto_answer_source_table,
            used_prior_property=used_prior_property_response,
            used_conversation=used_conversation_context,
        ),
        "pending_reply_draft": pending_reply_draft,   # for reply_now categories (appreciation, etc.)
        "requires_ops_action": classification.requires_ops_action,
        "ops_action_type": classification.ops_action_type,
        "escalation_packet": escalation_packet_dict,
        "triage_state": triage_state,
        "used_conversation_context": used_conversation_context,
        "conversation_turns_used": len(related_history),
        "used_prior_property_response": used_prior_property_response,
        "prior_property_match": prior_property_match,
    }


# ── Inbox thread: per-client conversation memory (inbox monitor session) ─────

_INBOX_THREADS: dict[int, list[dict[str, Any]]] = defaultdict(list)
_INBOX_THREAD_MAX = 100

_CHANNEL_LABELS = {
    "messages": "💬 Direct Message",
    "comments": "🌐 Social Comment",
    "review": "⭐ Platform Review",
    "mentions": "📢 Brand Mention",
}


def _normalize_thread_content(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _make_reply_entry(
    text: str,
    ops_action: str | None = None,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    return {
        "text": (text or "").strip(),
        "ops_action": ops_action,
        "source": source,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _ensure_turn_replies(turn: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a turn to always have a `replies` list (legacy reply_text supported)."""
    replies = turn.get("replies")
    if isinstance(replies, list) and replies:
        return replies
    migrated: list[dict[str, Any]] = []
    legacy = (turn.get("reply_text") or "").strip()
    if legacy:
        migrated.append(_make_reply_entry(
            legacy,
            turn.get("ops_action"),
            source=str(turn.get("source") or "inbox_monitor"),
        ))
    turn["replies"] = migrated
    return migrated


def _sync_turn_reply_fields(turn: dict[str, Any]) -> None:
    """Keep reply_text/ops_action as the latest reply for follow-up + older UI clients."""
    replies = _ensure_turn_replies(turn)
    if replies:
        latest = replies[-1]
        turn["reply_text"] = latest.get("text")
        turn["ops_action"] = latest.get("ops_action") or turn.get("ops_action")
    else:
        turn["reply_text"] = None


def _serialize_inbox_turn(turn: dict[str, Any]) -> dict[str, Any]:
    out = dict(turn)
    _ensure_turn_replies(out)
    _sync_turn_reply_fields(out)
    return out


def _append_inbox_thread_turn(
    *,
    client_id: int,
    content: str,
    author: str = "Guest",
    message_type: str = "messages",
    channel_label: str | None = None,
    category: str | None = None,
    urgency_level: str | None = None,
    triage_state: str | None = None,
    reply_text: str | None = None,
    ops_action: str | None = None,
) -> dict[str, Any]:
    """Append a guest turn to this client's inbox thread."""
    guest = (content or "").strip()
    if not client_id or not guest:
        return {}
    draft = (reply_text or "").strip()
    replies = [_make_reply_entry(draft, ops_action, source="inbox_monitor")] if draft else []
    turn = {
        "turn_id": f"turn-{uuid.uuid4().hex[:12]}",
        "message_id": None,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "content": guest,
        "author": author or "Guest",
        "message_type": message_type or "messages",
        "channel_label": channel_label or _CHANNEL_LABELS.get(message_type or "messages", "📨 Message"),
        "category": category,
        "urgency_level": urgency_level,
        "triage_state": triage_state,
        "reply_text": draft or None,
        "ops_action": ops_action,
        "replies": replies,
        "source": "inbox_monitor",
    }
    key = int(client_id)
    _INBOX_THREADS[key].append(turn)
    if len(_INBOX_THREADS[key]) > _INBOX_THREAD_MAX:
        _INBOX_THREADS[key] = _INBOX_THREADS[key][-_INBOX_THREAD_MAX:]
    return turn


def _update_inbox_thread_reply(
    client_id: int,
    guest_message: str,
    reply_text: str | None,
    ops_action: str,
    *,
    append: bool = False,
    source: str | None = None,
) -> bool:
    """
    Update the most recent matching guest turn's hotel reply.

    - append=False (approve/edit): set/replace the primary (first) reply, keep later ones
    - append=True (property reply): add another hotel reply without overwriting earlier ones
    """
    key = int(client_id)
    needle = _normalize_thread_content(guest_message)
    if not key or not needle:
        return False
    text = (reply_text or "").strip()
    if not text:
        return False
    turns = _INBOX_THREADS.get(key) or []
    for turn in reversed(turns):
        if _normalize_thread_content(str(turn.get("content") or "")) != needle:
            continue
        replies = _ensure_turn_replies(turn)
        entry = _make_reply_entry(text, ops_action, source=source or ("property_chat" if append else "inbox_monitor"))
        if append:
            # Skip exact duplicate of the latest reply
            if replies and _normalize_thread_content(str(replies[-1].get("text") or "")) == _normalize_thread_content(text):
                replies[-1]["ops_action"] = ops_action
                replies[-1]["source"] = entry["source"]
            else:
                replies.append(entry)
        else:
            if replies:
                # Update primary draft/approved reply; preserve later property follow-ups
                replies[0] = {
                    **replies[0],
                    "text": text,
                    "ops_action": ops_action,
                    "source": source or replies[0].get("source") or "inbox_monitor",
                    "ts": entry["ts"],
                }
            else:
                replies.append(entry)
        turn["replies"] = replies
        if ops_action in {"approved", "edited", "auto_replied"}:
            turn["triage_state"] = "auto_replied"
        _sync_turn_reply_fields(turn)
        return True
    return False


def _remove_inbox_thread_turn(client_id: int, guest_message: str) -> bool:
    """Discard the most recent matching guest turn (used when ops rejects)."""
    key = int(client_id)
    needle = _normalize_thread_content(guest_message)
    if not key or not needle:
        return False
    turns = _INBOX_THREADS.get(key) or []
    for idx in range(len(turns) - 1, -1, -1):
        if _normalize_thread_content(str(turns[idx].get("content") or "")) == needle:
            turns.pop(idx)
            return True
    return False


def _inbox_thread_history(client_id: int) -> list[dict[str, Any]]:
    """Return live inbox turns, excluding any that were marked rejected."""
    out: list[dict[str, Any]] = []
    for turn in (_INBOX_THREADS.get(int(client_id), []) or []):
        serialized = _serialize_inbox_turn(turn)
        if str(serialized.get("ops_action") or "") == "rejected":
            continue
        # Also skip if every reply was rejected (shouldn't happen after remove)
        replies = serialized.get("replies") or []
        if replies and all(str(r.get("ops_action") or "") == "rejected" for r in replies):
            continue
        out.append(serialized)
    return out


def _merge_client_conversation_history(
    db_history: list[dict[str, Any]],
    inbox_turns: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Merge seeded DB messages with live inbox-monitor turns; return last `limit`."""
    combined: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in db_history + inbox_turns:
        if str(row.get("ops_action") or "") == "rejected":
            continue
        content_key = _normalize_thread_content(str(row.get("content") or ""))[:220]
        reply_key = _normalize_thread_content(str(row.get("reply_text") or ""))[:220]
        dedupe_key = (content_key, reply_key)
        if content_key and dedupe_key in seen:
            continue
        if content_key:
            seen.add(dedupe_key)
        combined.append(dict(row))
    combined.sort(key=lambda item: str(item.get("ts") or ""))
    return combined[-limit:]


@router.get("/conversation-history")
def get_conversation_history(client_id: int, limit: int = 5) -> dict[str, Any]:
    """
    Return the last `limit` messages for a client, joined with any
    ops response logged in auto_response_log, ordered chronologically
    (oldest first so the frontend can simply append new messages at the bottom).
    """
    # Fetch last `limit` messages from jx_bridge.messages (newest first, then reverse)
    messages_rows = repository.execute_query(
        """
        SELECT
            m.message_id,
            m.source_timestamp  AS ts,
            m.content,
            m.author,
            m.type              AS message_type,
            m.message_category  AS category,
            m.urgency_level,
            m.requires_ops_action,
            m.ops_action_type,
            tt.triage           AS triage_state
        FROM jx_bridge.messages m
        LEFT JOIN jx_bridge.thread_triage tt ON tt.interaction_id = m.interaction_id
        WHERE m.client_id = :client_id
        ORDER BY m.source_timestamp DESC
        LIMIT :limit
        """,
        {"client_id": client_id, "limit": limit},
    )
    # Reverse so oldest is first (chronological order for display)
    messages_rows = list(reversed(messages_rows))

    # Collect message IDs to join with responses
    msg_ids = [row.get("message_id") for row in messages_rows if row.get("message_id") is not None]

    # Fetch logged responses for those messages
    response_rows = repository.execute_query(
        """
        SELECT
            message_id,
            category,
            urgency_level,
            draft_answer,
            final_answer,
            ops_action,
            confidence,
            inserted_datetime   AS ts
        FROM jx_bridge.auto_response_log
        WHERE client_id = :client_id
        ORDER BY inserted_datetime ASC
        """,
        {"client_id": client_id},
    )

    # Index responses by message_id for quick join
    resp_by_msg: dict[int, list[dict]] = {}
    for r in response_rows:
        mid = r.get("message_id")
        if mid is not None:
            resp_by_msg.setdefault(int(mid), []).append(dict(r))

    # Channel label map
    channel_labels = {
        "messages": "💬 Direct Message",
        "comments": "🌐 Social Comment",
        "review":   "⭐ Platform Review",
        "mentions": "📢 Brand Mention",
    }

    history = []
    for row in messages_rows:
        mid = row.get("message_id")
        msg_type = str(row.get("message_type") or "messages")
        responses = resp_by_msg.get(int(mid), []) if mid is not None else []

        # Pick the best response to display (prefer final_answer → draft_answer)
        reply_text = None
        ops_action = None
        if responses:
            latest = responses[-1]
            reply_text = latest.get("final_answer") or latest.get("draft_answer")
            ops_action = latest.get("ops_action")

        history.append({
            "message_id":    mid,
            "ts":            row.get("ts"),
            "content":       row.get("content"),
            "author":        row.get("author") or "Guest",
            "message_type":  msg_type,
            "channel_label": channel_labels.get(msg_type, "📨 Message"),
            "category":      row.get("category"),
            "urgency_level": row.get("urgency_level"),
            "triage_state":  row.get("triage_state"),
            "reply_text":    reply_text,
            "ops_action":    ops_action,
            "replies": (
                [{"text": reply_text, "ops_action": ops_action, "source": "jx_bridge.messages"}]
                if reply_text else []
            ),
            "source":        "jx_bridge.messages",
        })

    merged = _merge_client_conversation_history(
        history,
        _inbox_thread_history(client_id),
        limit=limit,
    )
    return {"client_id": client_id, "limit": limit, "history": merged}


# ── Property Chat: in-memory session store ────────────────────────────────────
# Keyed by "{client_id}_{chat_key}" where chat_key is a short identifier
# (interaction_id or a frontend-generated UUID for brand-new messages).
# Each value is a list of message dicts: {sender, text, ts, guest_reply (opt)}
_PROPERTY_CHAT: dict[str, list[dict]] = defaultdict(list)


def _property_chat_candidates(client_id: int) -> list[dict[str, Any]]:
    """Property Chat answers for this client in the current process (all chat keys)."""
    prefix = f"{int(client_id)}_"
    out: list[dict[str, Any]] = []
    for key, msgs in _PROPERTY_CHAT.items():
        if not str(key).startswith(prefix):
            continue
        for msg in msgs or []:
            if str(msg.get("sender") or "") != "property":
                continue
            guest = str(msg.get("guest_message") or "").strip()
            reply = str(msg.get("text") or "").strip()
            if guest and reply:
                out.append({
                    "guest_message": guest,
                    "property_reply": reply,
                    "replied_at": msg.get("ts"),
                    "source": "property_chat",
                })
    return out


class PropertyReplyRequest(BaseModel):
    chat_key: str               # unique identifier for the alert/conversation
    client_id: int
    client_name: str | None = None
    guest_message: str          # original guest message
    property_reply: str = Field(min_length=1, max_length=2000)
    category: str = "question"
    urgency_level: str = "low"


def _llm_guest_reply_from_property(
    guest_message: str,
    property_reply: str,
    client_name: str,
    category: str,
) -> str:
    """Generate a polished guest-facing reply using the property's raw answer."""
    api_key = (getenv("OPENAI_API_KEY") or "").strip()
    model   = (getenv("OPENAI_MODEL") or "gpt-5.4-mini").strip()

    system = (
        "You are a hospitality communications assistant for a hotel. "
        "The property team has given you their internal answer to a guest query. "
        "Write a warm, professional, concise reply TO THE GUEST — do NOT mention "
        "'the property team' or internal process. "
        "Respond in 2-3 sentences max. Start directly with the answer."
    )
    prompt = (
        f"Hotel: {client_name}\n"
        f"Guest message: {guest_message}\n"
        f"Property team's answer: {property_reply}\n"
        f"Write the guest-facing reply:"
    )
    if not api_key:
        # Deterministic fallback — weave property reply into a polite response
        return f"Thank you for your message! {property_reply.strip().rstrip('.')}. Please let us know if you need anything else."
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.responses.create(
            model=model,
            instructions=system,
            input=prompt,
            max_output_tokens=150,
            temperature=0.4,
        )
        return str(getattr(resp, "output_text", "") or "").strip() or (
            f"Thank you for your patience! {property_reply.strip()}."
        )
    except Exception:
        return f"Thank you for your message! {property_reply.strip().rstrip('.')}. Please let us know if you need anything else."


@router.get("/property-chat/{chat_key}")
def get_property_chat(chat_key: str, client_id: int) -> dict[str, Any]:
    """Return in-memory chat history for a property chat session."""
    key = f"{client_id}_{chat_key}"
    return {"chat_key": chat_key, "messages": _PROPERTY_CHAT.get(key, [])}


@router.post("/property-reply")
def post_property_reply(payload: PropertyReplyRequest) -> dict[str, Any]:
    """
    Property team sends a reply to an escalated guest message.

    1. Saves to in-memory chat store (keyed by client_id + chat_key)
    2. Generates a polished guest-facing reply via LLM
    3. Saves that guest reply to the store too
    4. Returns both the property reply and the generated guest reply
    """
    key          = f"{payload.client_id}_{payload.chat_key}"
    now          = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    client_name  = payload.client_name or "the hotel"

    # Save property message
    _PROPERTY_CHAT[key].append({
        "sender":  "property",
        "text":    payload.property_reply,
        "ts":      now,
        "guest_message": payload.guest_message,
    })

    # Generate guest-facing reply from the property's answer
    guest_reply = _llm_guest_reply_from_property(
        guest_message  = payload.guest_message,
        property_reply = payload.property_reply,
        client_name    = client_name,
        category       = payload.category,
    )

    # Save the generated guest reply as a system message
    _PROPERTY_CHAT[key].append({
        "sender":      "system",
        "text":        guest_reply,
        "ts":          now,
        "is_guest_reply": True,
    })

    # Log to auto_response_log for learning
    record_property_answer(payload.client_id, payload.guest_message, payload.property_reply)
    _update_inbox_thread_reply(
        payload.client_id,
        payload.guest_message,
        guest_reply,
        "auto_replied",
        append=True,
        source="property_chat",
    )
    _log_auto_response(
        message_id    = None,
        client_id     = payload.client_id,
        category      = payload.category,
        urgency       = payload.urgency_level,
        draft         = guest_reply,
        confidence    = 1.0,
        source_table  = "property_chat",
        source_excerpt= f"Guest: {(payload.guest_message or '')[:180]} Property: {payload.property_reply[:180]}",
        ops_action    = "auto_replied",
        final_answer  = guest_reply,
    )

    return {
        "chat_key":        payload.chat_key,
        "property_reply":  payload.property_reply,
        "guest_reply":     guest_reply,
        "ts":              now,
        "messages":        _PROPERTY_CHAT[key],
    }


class OpsDecisionRequest(BaseModel):
    message_id: int | None = None
    client_id: int = 0
    guest_message: str | None = None
    ops_action: str = "approved"       # approved | edited | rejected
    final_answer: str | None = None
    original_draft: str | None = None
    category: str = "question"
    urgency_level: str = "low"
    source_excerpt: str | None = None


@router.post("/process-message/ops-decision")
def record_ops_decision(payload: OpsDecisionRequest) -> dict[str, Any]:
    """
    Record the ops team's decision on an escalated message.

    - approved: ops sends the AI-suggested reply as-is
    - edited: ops modified the reply → store as learned FAQ
    - rejected: discard the draft and remove it from this client's conversation history
    """
    ops_action = payload.ops_action
    client_id = payload.client_id
    final_answer = payload.final_answer
    original_draft = payload.original_draft
    was_edited = ops_action == "edited" and final_answer and final_answer != original_draft
    discarded = False

    # Store correction as learned FAQ for future auto-answers
    if was_edited and client_id and payload.source_excerpt and final_answer:
        _store_learned_faq(client_id, payload.source_excerpt, final_answer)

    if client_id and payload.guest_message and ops_action in {"approved", "edited"}:
        _update_inbox_thread_reply(client_id, payload.guest_message, final_answer, ops_action)
    elif client_id and payload.guest_message and ops_action == "rejected":
        # Reject = discard: do not keep this turn in Recent Conversations
        discarded = _remove_inbox_thread_turn(client_id, payload.guest_message)

    # Log the decision (audit only — rejected turns are not shown in thread UI)
    _log_auto_response(
        message_id=payload.message_id,
        client_id=client_id,
        category=payload.category,
        urgency=payload.urgency_level,
        draft=original_draft,
        confidence=1.0,  # ops-confirmed
        source_table=None,
        source_excerpt=payload.source_excerpt,
        ops_action=ops_action,
        final_answer=None if ops_action == "rejected" else final_answer,
    )

    return {
        "recorded": True,
        "ops_action": ops_action,
        "discarded": discarded,
        "learned_faq_stored": was_edited,
        "message": (
            "Correction stored as a learned FAQ for future auto-answers."
            if was_edited
            else "Draft rejected and removed from conversation history."
            if ops_action == "rejected"
            else f"Decision '{ops_action}' logged."
        ),
    }
