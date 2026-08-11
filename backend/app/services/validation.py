from __future__ import annotations

from typing import Any

from ..contracts import OrchestratorDecision, RetrievalResult, RoutingPayload, ValidationResult
from ..read_only import detect_blocked_action
from .context import CLIENT_REQUIRED_CAPABILITIES, _scope_contradictions


# ---------------------------------------------------------------------------
# Table allow-list check (moved from specialist_agents._table_policy_warnings)
# ---------------------------------------------------------------------------

def validate_table_policy(decision_tables: list[str], allowed_tables: list[str], agent_name: str) -> list[str]:
    """Return blocking issues for tables that fall outside the contract allow-list."""
    allowed = set(allowed_tables)
    if not allowed:
        return []
    extra_tables = sorted({table for table in decision_tables if table not in allowed})
    if not extra_tables:
        return []
    return [f"Route requested table(s) outside {agent_name} allow-list: {', '.join(extra_tables)}"]


# ---------------------------------------------------------------------------
# Stage 1 — Decision Validation
# ---------------------------------------------------------------------------

def validate_decision(
    payload: RoutingPayload,
    decision: OrchestratorDecision,
    allowed_tables: list[str],
    allowed_retriever_modes: list[str],
    known_template_keys: set[str],
    agent_name: str,
) -> ValidationResult:
    """Validate the orchestrator decision before the specialist agent runs.

    Checks:
    - client_id is present for capabilities that require it
    - declared tables are within the contract allow-list
    - requested retriever_modes exist in the contract's allowed set
    - capability_state is not 'not_supported' (should never proceed to retrieval)
    - all template_keys resolve to known entries in SQL_TEMPLATE_CATALOG
    - the query does not contain a blocked write-action
    """
    blocking_issues: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    # client_id required check
    if payload.entities.client_id is None and decision.capability in CLIENT_REQUIRED_CAPABILITIES:
        blocking_issues.append(
            f"Capability '{decision.capability}' requires a resolved client_id, but none was found in scope."
        )

    # table allow-list check
    table_issues = validate_table_policy(decision.tables, allowed_tables, agent_name)
    blocking_issues.extend(table_issues)

    # retriever_mode allow-list check
    disallowed_modes = sorted(
        {mode for mode in decision.retriever_modes if mode not in allowed_retriever_modes}
    )
    for mode in disallowed_modes:
        blocking_issues.append(
            f"Retriever mode '{mode}' is not in the {agent_name} contract's allowed modes: "
            f"{', '.join(allowed_retriever_modes)}."
        )

    # capability_state consistency check
    if decision.capability_state == "not_supported":
        blocking_issues.append(
            f"Capability state is 'not_supported' for '{decision.capability}' — "
            "retrieval should not proceed for a capability that is explicitly not supported."
        )

    # template_key resolution check
    unknown_keys = sorted({key for key in decision.template_keys if key not in known_template_keys})
    for key in unknown_keys:
        blocking_issues.append(
            f"Template key '{key}' declared in orchestrator decision is not registered in SQL_TEMPLATE_CATALOG."
        )

    # double-check for write-action in the original query (advisory)
    blocked_action = detect_blocked_action(payload.query)
    if blocked_action:
        warnings.append(
            f"Query contains a blocked write-action pattern ('{blocked_action}'); "
            "read-only policy should have caught this upstream."
        )

    notes.append(f"Decision validation ran for capability '{decision.capability}' routed to '{agent_name}'.")

    passed = len(blocking_issues) == 0
    if blocking_issues:
        status = "blocked"
    elif warnings:
        status = "warning"
    else:
        status = "passed"

    return ValidationResult(
        stage="decision",
        passed=passed,
        status=status,
        blocking_issues=blocking_issues,
        warnings=warnings,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Stage 2 — Evidence Validation
# ---------------------------------------------------------------------------

_STRUCTURED_REQUIRED_FIELDS: dict[str, list[str]] = {
    "inbox_lookup": ["interaction_id", "triage"],
    "content_schedule_lookup": ["post_id", "post_datetime"],
    "content_approval_lookup": ["post_id", "current_status"],
    "content_post_detail_lookup": ["post_id", "post_text"],
    "post_performance_lookup": ["post_id"],
    "client_access_lookup": ["user_id"],
    "competitor_lookup": ["competitor_client_id"],
    "relationship_lookup": ["relationship_type"],
    "event_lookup": ["id", "date"],
}


def _check_required_fields(capability: str, rows: list[dict[str, Any]]) -> list[str]:
    required = _STRUCTURED_REQUIRED_FIELDS.get(capability)
    if not required or not rows:
        return []
    issues: list[str] = []
    for field in required:
        missing_count = sum(1 for row in rows if row.get(field) is None)
        if missing_count:
            issues.append(
                f"Capability '{capability}' requires field '{field}' but it is absent in "
                f"{missing_count}/{len(rows)} returned row(s)."
            )
    return issues


def validate_evidence(
    payload: RoutingPayload,
    decision: OrchestratorDecision,
    sql_result: RetrievalResult | None,
    vector_result: RetrievalResult | None,
    allowed_tables: list[str],
) -> ValidationResult:
    """Validate specialist agent evidence before the context merger runs.

    Checks:
    - SQL rows have client_id matching the resolved payload client_id
    - SQL rows for structured capabilities contain required field names
    - Vector matches reference tables within the contract allow-list
    - Evidence count is consistent with capability_state
    """
    blocking_issues: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    client_id = payload.entities.client_id

    # client_id scope check on SQL rows (surfaces earlier than context merger)
    if sql_result and client_id is not None:
        mismatched = [
            row for row in sql_result.rows
            if row.get("client_id") is not None and int(row["client_id"]) != int(client_id)
        ]
        if mismatched:
            blocking_issues.append(
                f"{len(mismatched)} SQL row(s) have client_id that does not match the resolved "
                f"client_id {client_id}. Possible scope leak."
            )

    # client_id scope check on vector matches
    if vector_result and client_id is not None:
        mismatched_matches = [
            match for match in vector_result.matches
            if match.get("client_id") is not None and int(match["client_id"]) != int(client_id)
        ]
        if mismatched_matches:
            warnings.append(
                f"{len(mismatched_matches)} vector match(es) have client_id that does not match "
                f"the resolved client_id {client_id}."
            )

    # required-field check for structured capabilities
    if sql_result:
        field_issues = _check_required_fields(decision.capability, sql_result.rows)
        warnings.extend(field_issues)

    # vector table allow-list check
    if vector_result and allowed_tables:
        allowed = set(allowed_tables)
        for match in vector_result.matches:
            match_table = match.get("table") or match.get("source_table") or ""
            if match_table and match_table not in allowed:
                warnings.append(
                    f"Vector match references table '{match_table}' which is outside the contract allow-list."
                )
                break  # one warning per evidence batch is enough

    # evidence count vs capability_state consistency
    sql_count = len(sql_result.rows) if sql_result else 0
    vector_count = len(vector_result.matches) if vector_result else 0
    total_evidence = sql_count + vector_count

    if decision.capability_state == "fully_supported" and total_evidence == 0:
        warnings.append(
            f"Capability state is 'fully_supported' for '{decision.capability}' "
            "but the specialist agent returned 0 evidence items."
        )

    # cross-check using context._scope_contradictions for an early surface
    contradictions = _scope_contradictions(payload, sql_result, vector_result)
    if contradictions:
        blocking_issues.extend(
            [f"Scope contradiction detected: {c}" for c in contradictions[:3]]
        )

    notes.append(
        f"Evidence validation ran for capability '{decision.capability}': "
        f"{sql_count} SQL row(s), {vector_count} vector match(es)."
    )

    passed = len(blocking_issues) == 0
    if blocking_issues:
        status = "blocked"
    elif warnings:
        status = "warning"
    else:
        status = "passed"

    return ValidationResult(
        stage="evidence",
        passed=passed,
        status=status,
        blocking_issues=blocking_issues,
        warnings=warnings,
        notes=notes,
    )
