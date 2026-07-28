from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from os import getenv
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..contracts import OrchestratorDecision, RetrievalResult, RoutingPayload
from .context import MergedContext


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv()

DEFAULT_ANSWER_MODEL = "gpt-5.4-mini"
PROMPT_VERSION = "answer-generator-v2"

SKIP_CAPABILITIES = {
    "clarify_scope",
    "competitor_lookup",
    "inbox_lookup",
    "relationship_lookup",
    "unsupported_action",
    "pricing_lookup",
}

FORBIDDEN_ANSWER_MARKERS = (
    "mock poc",
    "mock response",
    "source type:",
    "aliases:",
    "show the approved sql",
    "explain why this route",
    "media_recommendation",
    "property_fact_lookup",
    "property_knowledge_summary",
    "content_schedule_lookup",
    "content_approval_lookup",
    "content_post_detail_lookup",
    "post_performance_lookup",
    "client_access_lookup",
    "relationship_lookup",
    "competitor_lookup",
    "inbox_lookup",
)

LIMITATION_MARKERS = (
    "couldn't verify",
    "could not verify",
    "can't answer",
    "cannot answer",
    "no positive confirmation",
    "couldn't find",
)

SYSTEM_PROMPT = """
Role:
You are the final Answer Synthesis Agent inside a read-only Soho AI intelligence assistant.

Task:
Write the best possible user-facing answer from the provided JSON payload only.
The payload already contains routed evidence, support state, and a deterministic draft.
Your job is wording and synthesis, not retrieval, calculation, or table selection.

Allowed evidence:
- SQL rows for exact records, counts, dates, statuses, post copy, access, and metrics.
- Analytics snapshots only for exact numeric metric values.
- Vector matches only for semantic property, FAQ, audience, tone, media, and metric context.
- Graph rows only for relationship/path explanations.
- The deterministic draft when it is more precise than a rewrite.

Forbidden behavior:
1. Do not fabricate facts.
2. Do not use general knowledge.
3. Do not infer missing amenities, prices, policies, metrics, dates, media, posts, access, competitors, or availability.
4. Do not expose internal table names, SQL, capability ids, route ids, or agent names.
5. Do not say "mock", "POC", "sample", or "demo".
6. Do not perform or imply write actions such as approve, publish, send, assign, update, delete, grant, or revoke.
7. Do not use vector matches for arithmetic.
8. Do not soften negative proof or missing evidence into a likely answer.

Decision rules:
1. Start with the direct answer.
2. If support is partial, say what is supported and what is missing.
3. If evidence is absent, say: "I couldn't verify this from the approved data I can read."
4. If evidence contains explicit negative proof, state the negative fact clearly.
5. Use exact numbers only when they appear in SQL rows or analytics snapshots.
6. If the deterministic draft is already the safest factual wording, preserve its substance and improve only readability.
7. Every claim must be traceable to the payload evidence.

Output contract:
- Return plain user-facing prose only.
- Use compact bullets only when listing records, posts, media, threads, metrics, or relationship paths.
- For exact record/list answers, include count first, then the strongest 2-4 examples.
- For performance answers, include resolved post, channel, date, exact metrics, missing metrics, post copy/media only when available.
- For post copy/media questions, preserve the labels "Post copy:" and "Media used:" on separate lines.
- For relationship questions, include "relationship path" or "relationship paths".
- Do not include follow-up suggestions; the API returns them separately.
""".strip()


@dataclass
class LLMAnswerResult:
    enabled: bool
    used: bool
    model: str
    prompt_version: str
    answer: str | None = None
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def answer_model() -> str:
    return (getenv("OPENAI_MODEL") or DEFAULT_ANSWER_MODEL).strip()


def llm_answer_enabled() -> bool:
    configured = (getenv("LLM_ANSWER_ENABLED") or "true").strip().lower()
    if configured in {"0", "false", "no", "off"}:
        return False
    return bool((getenv("OPENAI_API_KEY") or "").strip())


def llm_answer_status() -> dict[str, Any]:
    enabled = llm_answer_enabled()
    notes = [
        "LLM answer generation runs after deterministic routing, access scope, retrieval, and context merge.",
        "The LLM can synthesize wording but cannot choose unapproved tables, calculate metrics, or mutate data.",
        "Set OPENAI_MODEL to control the LLM answer model for this POC.",
    ]
    if not enabled:
        notes.append("LLM answer generation is disabled because OPENAI_API_KEY is missing or LLM_ANSWER_ENABLED=false.")
    return {
        "enabled": enabled,
        "model": answer_model(),
        "provider": "openai",
        "prompt_version": PROMPT_VERSION,
        "purpose": "grounded final answer synthesis",
        "notes": notes,
    }


def _truncate(value: Any, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return _truncate(value, 240)
    if isinstance(value, dict):
        return {str(key): _compact_value(inner, depth=depth + 1) for key, inner in list(value.items())[:24]}
    if isinstance(value, list):
        return [_compact_value(item, depth=depth + 1) for item in value[:12]]
    if isinstance(value, tuple):
        return [_compact_value(item, depth=depth + 1) for item in value[:12]]
    if isinstance(value, str):
        return _truncate(value)
    return value


def _compact_rows(result: RetrievalResult | None, *, limit: int = 10) -> list[dict[str, Any]]:
    if not result:
        return []
    return [_compact_value(row) for row in result.rows[:limit]]


def _compact_matches(result: RetrievalResult | None, *, limit: int = 8) -> list[dict[str, Any]]:
    if not result:
        return []
    compacted = []
    for match in result.matches[:limit]:
        compacted.append(
            {
                "title": _truncate(match.get("title") or match.get("label") or match.get("chunk_label"), 180),
                "excerpt": _truncate(match.get("excerpt"), 900),
                "source_kind": _truncate(match.get("source_kind"), 120),
                "score": match.get("score"),
                "fit": _truncate(match.get("fit"), 180),
            }
        )
    return compacted


def _result_tables(*results: RetrievalResult | None) -> list[str]:
    tables: list[str] = []
    for result in results:
        if not result:
            continue
        for table in result.tables:
            if table and table not in tables:
                tables.append(table)
    return tables


def _should_skip_llm(
    payload: RoutingPayload,
    decision: OrchestratorDecision,
    context: MergedContext,
    deterministic_answer: str,
) -> str | None:
    if not llm_answer_enabled():
        return "LLM answer generation is disabled or OPENAI_API_KEY is missing."
    if decision.capability in SKIP_CAPABILITIES:
        return f"Capability `{decision.capability}` should stay deterministic."
    if not context.answerable or context.evidence_count <= 0:
        return "No grounded evidence was available for LLM synthesis."
    lowered = deterministic_answer.lower()
    if any(marker in lowered for marker in LIMITATION_MARKERS):
        return "Limitation or negative-proof answers stay deterministic to avoid softening the evidence boundary."
    if decision.capability == "property_fact_lookup" and payload.normalized_query.startswith(("do ", "does ", "is ", "is there ", "are there ", "has ", "have ")):
        return "Yes/no property fact answers stay deterministic for strict no-fabrication behavior."
    return None


def _validate_llm_answer(answer: str, tables: list[str], decision: OrchestratorDecision) -> str | None:
    cleaned = " ".join(answer.split()).lower()
    if len(cleaned) < 8:
        return "LLM answer was empty or too short."
    if any(marker in cleaned for marker in FORBIDDEN_ANSWER_MARKERS):
        return "LLM answer contained internal/debug wording."
    for table in tables:
        if table and table.lower() in cleaned:
            return f"LLM answer exposed internal table name `{table}`."
    if decision.capability == "content_post_detail_lookup" and ("post copy:" not in cleaned or "media used:" not in cleaned):
        return "LLM answer did not preserve required post detail labels."
    if decision.capability == "relationship_lookup" and "relationship path" not in cleaned:
        return "LLM answer did not preserve relationship-path language."
    return None


def generate_llm_answer(
    payload: RoutingPayload,
    decision: OrchestratorDecision,
    context: MergedContext,
    sql_result: RetrievalResult | None,
    vector_result: RetrievalResult | None,
    deterministic_answer: str,
) -> LLMAnswerResult:
    model = answer_model()
    skip_reason = _should_skip_llm(payload, decision, context, deterministic_answer)
    if skip_reason:
        return LLMAnswerResult(
            enabled=llm_answer_enabled(),
            used=False,
            model=model,
            prompt_version=PROMPT_VERSION,
            fallback_reason=skip_reason,
        )

    payload_json = {
        "user_question": payload.query,
        "resolved_client": {
            "client_id": payload.entities.client_id,
            "property_name": payload.entities.property_name,
            "city": payload.entities.city,
            "channel": payload.entities.channel,
            "date_range": payload.entities.date_range.to_dict() if payload.entities.date_range else None,
        },
        "route": {
            "agent": decision.agent_name,
            "capability": decision.capability,
            "domain": decision.domain,
            "support_level": context.support_level,
            "confidence_label": context.confidence_label,
            "confidence_score": context.confidence_score,
        },
        "deterministic_draft": deterministic_answer,
        "answer_contract": {
            "answerable": context.answerable,
            "support_level": context.support_level,
            "primary_retrieval": context.primary_retrieval,
            "evidence_count": context.evidence_count,
            "missing_fields": context.missing_fields,
            "contradictions": context.contradictions,
            "required_behavior": [
                "answer only from evidence",
                "state missing evidence clearly when support is partial",
                "do not expose route metadata",
                "do not include follow-up questions",
            ],
        },
        "evidence": {
            "sql_rows": _compact_rows(sql_result),
            "vector_matches": _compact_matches(vector_result),
            "source_notes": (sql_result.support_notes if sql_result else []) + (vector_result.support_notes if vector_result else []),
        },
    }

    try:
        from openai import OpenAI

        client = OpenAI(api_key=(getenv("OPENAI_API_KEY") or "").strip())
        response = client.responses.create(
            model=model,
            instructions=SYSTEM_PROMPT,
            input=json.dumps(payload_json, ensure_ascii=False),
            max_output_tokens=650,
            temperature=0.2,
        )
        answer = str(getattr(response, "output_text", "") or "").strip()
        validation_error = _validate_llm_answer(answer, _result_tables(sql_result, vector_result), decision)
        if validation_error:
            return LLMAnswerResult(
                enabled=True,
                used=False,
                model=model,
                prompt_version=PROMPT_VERSION,
                fallback_reason=validation_error,
            )
        return LLMAnswerResult(
            enabled=True,
            used=True,
            model=model,
            prompt_version=PROMPT_VERSION,
            answer=answer,
        )
    except Exception as exc:
        return LLMAnswerResult(
            enabled=True,
            used=False,
            model=model,
            prompt_version=PROMPT_VERSION,
            fallback_reason=f"OpenAI answer generation failed; used deterministic fallback: {exc}",
        )
