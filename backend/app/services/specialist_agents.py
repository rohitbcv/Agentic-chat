from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..contracts import OrchestratorDecision, RetrievalResult, RoutingPayload, SourceTrace
from ..read_only import agent_read_only_policy
from .retrievers import execute_sql_capability, execute_vector_capability


@dataclass(frozen=True)
class SpecialistAgentContract:
    name: str
    purpose: str
    allowed_retriever_modes: list[str]
    allowed_tables: list[str]
    prompt_rules: list[str]
    task: str = ""
    evidence_priority: list[str] = field(default_factory=list)
    decision_rules: list[str] = field(default_factory=list)
    forbidden_behaviors: list[str] = field(default_factory=list)
    output_contract: dict[str, Any] = field(default_factory=dict)
    failure_behavior: list[str] = field(default_factory=list)

    def prompt_blueprint(self) -> str:
        sections = [
            ("Role", self.purpose),
            ("Task", self.task or "Use approved read-only retriever output to answer the routed capability."),
            ("Allowed Evidence", "; ".join(self.evidence_priority) or "Use only approved retriever output."),
            ("Decision Rules", "; ".join(self.decision_rules or self.prompt_rules)),
            ("Forbidden Behavior", "; ".join(self.forbidden_behaviors or ["Never mutate data.", "Never fabricate missing facts."])),
            ("Output Contract", ", ".join(self.output_contract.keys()) if self.output_contract else "Return grounded evidence and support state."),
            ("Failure Behavior", "; ".join(self.failure_behavior) or "If evidence is missing, say it cannot be verified from approved data."),
        ]
        return "\n".join(f"{label}: {value}" for label, value in sections)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["prompt_blueprint"] = self.prompt_blueprint()
        return payload


UNIVERSAL_FORBIDDEN_BEHAVIORS = [
    "Do not mutate data or call write-capable tools.",
    "Do not run arbitrary SQL or select unapproved tables.",
    "Do not answer from general knowledge.",
    "Do not expose internal table names, SQL, route IDs, or agent names in user-facing answers unless explicitly asked.",
    "Do not use evidence from another client when a client_id is resolved.",
]


BASE_OUTPUT_CONTRACT = {
    "answerable": "boolean indicating whether approved evidence supports the answer",
    "support_level": "fully_supported, partially_supported, or not_supported",
    "evidence_used": "compact source rows, vector matches, or graph paths used",
    "missing_fields": "required scope or source fields that were absent",
    "final_answer_facts": "facts allowed to appear in the final answer",
}


@dataclass
class SpecialistAgentRun:
    agent_name: str
    capability: str
    status: str
    summary: str
    prompt_contract: dict[str, Any]
    allowed_tables: list[str]
    tool_policy: dict[str, Any]
    sql_result: RetrievalResult | None = None
    vector_result: RetrievalResult | None = None
    source_traces: list[SourceTrace] = field(default_factory=list)
    trace_steps: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "capability": self.capability,
            "status": self.status,
            "summary": self.summary,
            "prompt_contract": self.prompt_contract,
            "allowed_tables": self.allowed_tables,
            "tool_policy": self.tool_policy,
            "sql_result": self.sql_result.to_dict() if self.sql_result else None,
            "vector_result": self.vector_result.to_dict() if self.vector_result else None,
            "source_traces": [trace.to_dict() for trace in self.source_traces],
            "trace_steps": self.trace_steps,
            "warnings": self.warnings,
        }


SPECIALIST_AGENT_CONTRACTS: dict[str, SpecialistAgentContract] = {
    "Inbox and Complaint Agent": SpecialistAgentContract(
        name="Inbox and Complaint Agent",
        purpose="Answer inbox, complaint, triage, waiting-on-property, and thread status questions from read-only sources.",
        allowed_retriever_modes=["sql", "vector"],
        allowed_tables=[
            "jx_bridge.messages",
            "jx_bridge.interactions",
            "jx_bridge.thread_triage",
            "jx_bridge.alerts",
            "jx_bridge.alert_replies",
            "inbox.monitor_group",
            "inbox.monitor_group_client",
            "inbox.monitor_group_user",
        ],
        prompt_rules=[
            "Prefer exact thread rows over semantic notes for thread counts and statuses.",
            "Summarize operational state without sending replies or creating alerts.",
            "Ask for client scope when no client is resolved.",
        ],
        task="Resolve active thread, complaint, triage, and waiting-on-property questions for one scoped client.",
        evidence_priority=[
            "Use jx_bridge.interactions as the thread anchor.",
            "Use jx_bridge.messages for exact guest text and timestamps.",
            "Use jx_bridge.thread_triage, jx_bridge.alerts, and jx_bridge.alert_replies for operational status.",
            "Use vector evidence only as supporting context, never for counts.",
        ],
        decision_rules=[
            "Return counts only from SQL rows.",
            "For complaint questions, filter to complaint, issue, problem, cancellation, or property-help evidence.",
            "Every returned thread must match the resolved client_id.",
            "If no active matching rows exist, say no matching active threads were found.",
        ],
        forbidden_behaviors=[
            *UNIVERSAL_FORBIDDEN_BEHAVIORS,
            "Do not send replies, create alerts, assign threads, or mark a thread resolved.",
            "Do not summarize another client's thread when a client is resolved.",
        ],
        output_contract={
            **BASE_OUTPUT_CONTRACT,
            "thread_count": "number of matching active threads",
            "triage_breakdown": "counts by triage state",
            "thread_examples": "most relevant threads with title, triage, timestamp, and preview",
        },
        failure_behavior=[
            "If client scope is missing, ask which client or property to use.",
            "If rows are empty, state that no matching active inbox threads were found.",
            "If thread rows conflict with client scope, discard them and report a scope conflict.",
        ],
    ),
    "Client Knowledge and FAQ Agent": SpecialistAgentContract(
        name="Client Knowledge and FAQ Agent",
        purpose="Answer property facts, FAQs, tone, audience, location, policy, and reusable operational knowledge questions.",
        allowed_retriever_modes=["sql", "vector"],
        allowed_tables=[
            "clients.clients",
            "clients.client_details",
            "clients.property_details",
            "clients.client_notes",
            "clients.client_tone_of_voice_settings",
            "clients.client_target_audience",
            "clients.client_target_audience_suggestions",
            "general.knowledge_embeddings",
            "general.timezone",
            "world.cities",
        ],
        prompt_rules=[
            "Use approved notes and property details as the primary grounding source.",
            "Do not invent amenities, policies, rates, or booking facts when the source is missing.",
            "Keep answer wording clear enough for an operator to reuse with a guest.",
        ],
        task="Answer scoped property knowledge questions from approved text-bearing client sources.",
        evidence_priority=[
            "For property facts, prefer clients.property_details and clients.client_notes.",
            "For FAQs, prefer clients.client_notes with FAQ-like titles or note types.",
            "For tone, prefer clients.client_tone_of_voice_settings.",
            "For audience, prefer clients.client_target_audience and suggestions.",
            "Use general.knowledge_embeddings only as a scoped semantic read model over approved source tables.",
        ],
        decision_rules=[
            "For yes/no questions, answer yes only with explicit positive evidence.",
            "For yes/no questions, answer no only with explicit negative evidence.",
            "If the requested fact is absent, say it could not be verified from approved data.",
            "Do not use nearby facts, broad summaries, or property positioning as a substitute for the requested fact.",
            "Every evidence item must match the resolved client_id.",
        ],
        forbidden_behaviors=[
            *UNIVERSAL_FORBIDDEN_BEHAVIORS,
            "Do not invent amenities, policies, live room rates, booking rules, or availability.",
            "Do not soften a missing fact into a likely answer.",
        ],
        output_contract={
            **BASE_OUTPUT_CONTRACT,
            "fact_status": "explicit_yes, explicit_no, not_found, or conflicting",
            "best_evidence": "the strongest source excerpt supporting the answer",
            "operator_ready_answer": "concise answer suitable for a hotel operator",
        },
        failure_behavior=[
            "If client scope is missing, ask which client or property to use.",
            "If evidence is missing, use the exact limitation wording instead of guessing.",
            "If positive and negative evidence conflict, report the conflict and avoid a final yes/no.",
        ],
    ),
    "Content Planning Agent": SpecialistAgentContract(
        name="Content Planning Agent",
        purpose="Answer scheduled posts, approval workflow, channel planning, post copy/media detail, and limited post-level performance questions.",
        allowed_retriever_modes=["sql", "vector"],
        allowed_tables=[
            "clients.clients",
            "clients.client_content_pillars",
            "clients.client_social_network_cadence",
            "clients.client_social_network_account",
            "content.content_topic",
            "content.content_topic_post",
            "content.content_post_status",
            "content.content_topic_post_type",
            "content.content_topic_post_approval_status",
            "content.content_topic_post_media",
            "media.media",
            "media.media_analysis_ai",
            "general.knowledge_embeddings",
            "analytics.social_media_post",
            "analytics.metric_embeddings",
            "general.social_network_type",
            "general.events",
        ],
        prompt_rules=[
            "Use SQL for exact schedules, statuses, approvals, dates, and numeric metric values.",
            "For post copy and media-used questions, resolve the exact post first and only then join attached media.",
            "Use metric embeddings only for semantic metric/context matching, never for arithmetic.",
            "Label post-performance answers as partial unless the resolved post and analytics snapshot both exist.",
        ],
        task="Answer scoped content workflow, post detail, media-used, approval, and post-performance questions.",
        evidence_priority=[
            "Use content.content_topic as the client-to-post bridge.",
            "Use content.content_topic_post for exact post copy, channel, status, and scheduled/published date.",
            "Use content.content_topic_post_media plus media.media for media actually attached to a post.",
            "Use media.media_analysis_ai only to describe attached media context.",
            "Use analytics.social_media_post for exact metric values.",
            "Use analytics.metric_embeddings only for semantic metric context.",
        ],
        decision_rules=[
            "Resolve the exact post before retrieving media or analytics.",
            "For performance, report only metrics present in the analytics snapshot.",
            "If analytics are missing, say the post was found but performance metrics were unavailable.",
            "For schedule questions, respect date range and channel filters from intake.",
            "Every post must join back to the resolved client_id.",
        ],
        forbidden_behaviors=[
            *UNIVERSAL_FORBIDDEN_BEHAVIORS,
            "Do not approve, publish, schedule, edit, or delete content.",
            "Do not calculate metric values from embeddings.",
            "Do not answer with upcoming posts when the user asked for latest published post details.",
        ],
        output_contract={
            **BASE_OUTPUT_CONTRACT,
            "posts": "matching posts with id, topic, status, channel, date, and copy when needed",
            "metrics": "exact metrics from analytics snapshots only",
            "media_used": "media attached through the post-media bridge",
            "partial_reason": "why performance or schedule evidence is incomplete",
        },
        failure_behavior=[
            "If client scope is missing, ask which client to use.",
            "If no post matches the channel/date/status, say no matching post was found.",
            "If media or analytics joins are absent, answer the available part and state what is missing.",
        ],
    ),
    "Media Discovery Agent": SpecialistAgentContract(
        name="Media Discovery Agent",
        purpose="Find semantically relevant media assets and explain why they match a theme, campaign, audience, or content topic.",
        allowed_retriever_modes=["sql", "vector"],
        allowed_tables=[
            "media.media",
            "media.media_analysis_ai",
            "media.media_asset",
            "media.media_status",
            "general.knowledge_embeddings",
            "content.content_topic_post_media",
            "content.content_topic_post_media_tags",
        ],
        prompt_rules=[
            "Rank approved media analysis text before weak keyword matches.",
            "Mention missing metadata as a retrieval limitation, not as a guessed asset property.",
            "Never upload, tag, edit, or attach media.",
        ],
        task="Find approved media assets that match a scoped theme, campaign, audience, or content need.",
        evidence_priority=[
            "Use media.media for asset identity and ownership.",
            "Use media.media_analysis_ai for semantic descriptions, tags, alt text, and campaign fit.",
            "Use content.content_topic_post_media only to explain prior usage of an asset.",
            "Use general.knowledge_embeddings as a scoped semantic read model when available.",
        ],
        decision_rules=[
            "Return only assets owned by the resolved client_id.",
            "Rank exact semantic media analysis above weak keyword matches.",
            "Explain media fit from retrieved tags, descriptions, and analysis only.",
            "If the user asks what media was used in a post, route should be content_post_detail_lookup, not general media search.",
        ],
        forbidden_behaviors=[
            *UNIVERSAL_FORBIDDEN_BEHAVIORS,
            "Do not upload, tag, attach, edit, delete, or approve media.",
            "Do not claim a real thumbnail or asset URL exists unless retrieved.",
        ],
        output_contract={
            **BASE_OUTPUT_CONTRACT,
            "media": "ranked media assets with id, name, description, tags, and fit reason",
            "preview_available": "whether a generated or real preview is available",
            "usage_context": "known prior post usage when retrieved",
        },
        failure_behavior=[
            "If client scope is missing, ask which client to use.",
            "If no strong media match exists, state that no strong approved media match was found.",
            "If metadata is sparse, say recommendation confidence is limited by missing metadata.",
        ],
    ),
    "Access and Relationship Agent": SpecialistAgentContract(
        name="Access and Relationship Agent",
        purpose="Answer access, organization, collaborator, ownership, event, city, competitor-comparable, and relationship-path questions.",
        allowed_retriever_modes=["sql", "vector", "graph"],
        allowed_tables=[
            "users.users",
            "users.users_roles",
            "organizations.organizations",
            "organizations.organization_users",
            "clients.clients",
            "clients.client_marketing_settings",
            "clients.clients_collaborators",
            "clients.property_details",
            "clients.client_target_audience",
            "entity.entity",
            "entity.entity_relationship",
            "entity.entity_facility_brand",
            "entity.entity_facility_sub_brand",
            "general.events",
            "world.cities",
        ],
        prompt_rules=[
            "Explain relationship paths with table-backed evidence.",
            "Never grant, revoke, or change access.",
            "Use graph-style language only when the path can be traced through approved joins.",
        ],
        task="Answer scoped access, ownership, event, competitor/comparable, and relationship-path questions.",
        evidence_priority=[
            "Use clients.clients as the scope anchor.",
            "Use clients.clients_collaborators, users.users, and organizations.organization_users for access.",
            "Use general.events and world.cities for event/location context.",
            "Use clients.client_marketing_settings plus property details and audience for inferred comparables.",
            "Use entity.entity and entity.entity_relationship for relationship paths.",
        ],
        decision_rules=[
            "For access, return only active collaborator or organization membership evidence.",
            "For relationship questions, include only traceable paths from approved graph rows.",
            "For competitor questions, say likely comparables unless an official competitor source is present.",
            "For event questions, join through client city and future event records.",
            "Every row or graph path must match the resolved client_id or its approved relationship scope.",
        ],
        forbidden_behaviors=[
            *UNIVERSAL_FORBIDDEN_BEHAVIORS,
            "Do not grant, revoke, invite, or change access.",
            "Do not call inferred comparables official competitors.",
            "Do not describe graph paths that were not retrieved.",
        ],
        output_contract={
            **BASE_OUTPUT_CONTRACT,
            "access_records": "active collaborators and roles when applicable",
            "relationship_paths": "traceable graph paths grouped by business domain",
            "events": "future events tied through city when applicable",
            "comparables": "likely comparable clients with basis and limitation when applicable",
        },
        failure_behavior=[
            "If client scope is missing, ask which client to use.",
            "If relationship rows are empty, say no traceable paths were found.",
            "If competitor data is inferred or sparse, label support as partial.",
        ],
    ),
}


def _fallback_contract(agent_name: str) -> SpecialistAgentContract:
    return SpecialistAgentContract(
        name=agent_name,
        purpose="Fallback read-only specialist contract.",
        allowed_retriever_modes=["sql", "vector"],
        allowed_tables=[],
        prompt_rules=["Use only approved retriever output.", "Never mutate data."],
        task="Handle a route only through approved read-only retriever output.",
        evidence_priority=["Use approved retriever output only."],
        decision_rules=["Do not infer facts beyond retrieved evidence."],
        forbidden_behaviors=UNIVERSAL_FORBIDDEN_BEHAVIORS,
        output_contract=BASE_OUTPUT_CONTRACT,
        failure_behavior=["If evidence is missing, state that the answer cannot be verified from approved data."],
    )


def _retriever_trace(result: RetrievalResult, agent_name: str) -> dict[str, Any]:
    row_count = len(result.rows) if result.rows else len(result.matches)
    mode_label = "SQL" if result.mode == "sql" else "semantic"
    summary = f"{agent_name} ran approved {mode_label} retrieval and collected {row_count} evidence item(s)."
    if result.support_notes:
        summary += " " + " ".join(result.support_notes)
    return {
        "agent": f"{agent_name} Retriever",
        "status": "completed",
        "summary": summary,
        "tables": result.tables,
        "mode": result.mode,
        "row_count": row_count,
    }


def _table_policy_warnings(decision: OrchestratorDecision, contract: SpecialistAgentContract) -> list[str]:
    allowed = set(contract.allowed_tables)
    if not allowed:
        return []
    extra_tables = sorted({table for table in decision.tables if table not in allowed})
    if not extra_tables:
        return []
    return [f"Route requested table(s) outside {contract.name} allow-list: {', '.join(extra_tables)}"]


def run_specialist_agent(payload: RoutingPayload, decision: OrchestratorDecision) -> SpecialistAgentRun:
    contract = SPECIALIST_AGENT_CONTRACTS.get(decision.agent_name, _fallback_contract(decision.agent_name))
    warnings = _table_policy_warnings(decision, contract)
    tool_policy = {
        **agent_read_only_policy(),
        "agent": contract.name,
        "allowed_retriever_modes": contract.allowed_retriever_modes,
        "write_tools": "disabled",
        "database_role": "ai_readonly_app",
    }
    trace_steps = [
        {
            "agent": contract.name,
            "status": "started",
            "summary": (
                f"Accepted capability `{decision.capability}` with read-only tools only. "
                f"Allowed retrieval modes: {', '.join(contract.allowed_retriever_modes)}."
            ),
            "capability": decision.capability,
        }
    ]

    sql_result: RetrievalResult | None = None
    vector_result: RetrievalResult | None = None
    source_traces: list[SourceTrace] = []

    if "sql" in decision.retriever_modes:
        if "sql" not in contract.allowed_retriever_modes:
            warnings.append(f"{contract.name} is not allowed to run SQL retrieval.")
        elif decision.template_keys:
            sql_result = execute_sql_capability(decision.template_keys[0], payload)
            source_traces.extend(sql_result.source_traces)
            trace_steps.append(_retriever_trace(sql_result, contract.name))

    if "vector" in decision.retriever_modes:
        if "vector" not in contract.allowed_retriever_modes:
            warnings.append(f"{contract.name} is not allowed to run vector retrieval.")
        else:
            vector_result = execute_vector_capability(decision.capability, payload)
            source_traces.extend(vector_result.source_traces)
            trace_steps.append(_retriever_trace(vector_result, contract.name))

    if "graph" in decision.retriever_modes:
        warnings.append("Graph retrieval is documented but deferred; no graph DB writes or traversal were executed in this POC.")

    evidence_count = (len(sql_result.rows) if sql_result else 0) + (len(vector_result.matches) if vector_result else 0)
    status = "completed_with_warnings" if warnings else "completed"
    summary = f"{contract.name} returned {evidence_count} read-only evidence item(s) for `{decision.capability}`."
    if warnings:
        summary += " " + " ".join(warnings)
    trace_steps.append({"agent": contract.name, "status": status, "summary": summary})

    return SpecialistAgentRun(
        agent_name=contract.name,
        capability=decision.capability,
        status=status,
        summary=summary,
        prompt_contract=contract.to_dict(),
        allowed_tables=contract.allowed_tables,
        tool_policy=tool_policy,
        sql_result=sql_result,
        vector_result=vector_result,
        source_traces=source_traces,
        trace_steps=trace_steps,
        warnings=warnings,
    )
