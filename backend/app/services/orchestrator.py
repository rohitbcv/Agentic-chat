from __future__ import annotations

from ..contracts import OrchestratorDecision, RoutingPayload

ROUTING_MATRIX: list[dict[str, object]] = [
    {
        "capability": "inbox_lookup",
        "intent": "inbox",
        "agent_name": "Inbox and Complaint Agent",
        "domain": "inbox",
        "retriever_modes": ["sql"],
        "capability_state": "fully_supported",
        "template_keys": ["inbox_lookup"],
        "join_paths": ["inbox_threads"],
        "tables": ["jx_bridge.messages", "jx_bridge.interactions", "jx_bridge.thread_triage", "jx_bridge.alerts", "jx_bridge.alert_replies"],
    },
    {
        "capability": "property_fact_lookup",
        "intent": "client_knowledge",
        "agent_name": "Client Knowledge and FAQ Agent",
        "domain": "knowledge",
        "retriever_modes": ["vector"],
        "capability_state": "fully_supported",
        "template_keys": [],
        "join_paths": ["property_knowledge"],
        "tables": ["general.knowledge_embeddings", "clients.client_notes", "clients.property_details", "clients.client_details"],
    },
    {
        "capability": "property_knowledge_summary",
        "intent": "client_knowledge",
        "agent_name": "Client Knowledge and FAQ Agent",
        "domain": "knowledge",
        "retriever_modes": ["vector"],
        "capability_state": "fully_supported",
        "template_keys": [],
        "join_paths": ["property_knowledge"],
        "tables": ["general.knowledge_embeddings", "clients.client_notes", "clients.property_details", "clients.client_details"],
    },
    {
        "capability": "tone_of_voice_lookup",
        "intent": "client_knowledge",
        "agent_name": "Client Knowledge and FAQ Agent",
        "domain": "knowledge",
        "retriever_modes": ["vector"],
        "capability_state": "fully_supported",
        "template_keys": [],
        "join_paths": ["property_knowledge"],
        "tables": ["general.knowledge_embeddings", "clients.client_tone_of_voice_settings", "clients.client_target_audience"],
    },
    {
        "capability": "audience_lookup",
        "intent": "client_knowledge",
        "agent_name": "Client Knowledge and FAQ Agent",
        "domain": "knowledge",
        "retriever_modes": ["vector"],
        "capability_state": "fully_supported",
        "template_keys": [],
        "join_paths": ["property_knowledge"],
        "tables": ["general.knowledge_embeddings", "clients.client_target_audience", "clients.client_target_audience_suggestions"],
    },
    {
        "capability": "competitor_lookup",
        "intent": "client_knowledge",
        "agent_name": "Access and Relationship Agent",
        "domain": "market",
        "retriever_modes": ["sql"],
        "capability_state": "partially_supported",
        "template_keys": ["competitor_lookup"],
        "join_paths": ["competitor_lookup"],
        "tables": [
            "clients.clients",
            "clients.client_marketing_settings",
            "clients.property_details",
            "clients.client_target_audience",
            "world.cities",
        ],
    },
    {
        "capability": "content_schedule_lookup",
        "intent": "content",
        "agent_name": "Content Planning Agent",
        "domain": "content",
        "retriever_modes": ["sql"],
        "capability_state": "fully_supported",
        "template_keys": ["content_schedule_lookup"],
        "join_paths": ["content_schedule"],
        "tables": ["content.content_topic_post", "content.content_topic", "content.content_post_status"],
    },
    {
        "capability": "content_approval_lookup",
        "intent": "content",
        "agent_name": "Content Planning Agent",
        "domain": "content",
        "retriever_modes": ["sql"],
        "capability_state": "fully_supported",
        "template_keys": ["content_approval_lookup"],
        "join_paths": ["content_approval"],
        "tables": ["content.content_topic_post", "content.content_topic_post_approval_status", "content.content_post_status"],
    },
    {
        "capability": "content_post_detail_lookup",
        "intent": "content",
        "agent_name": "Content Planning Agent",
        "domain": "content",
        "retriever_modes": ["sql"],
        "capability_state": "fully_supported",
        "template_keys": ["content_post_detail_lookup"],
        "join_paths": ["content_post_detail"],
        "tables": ["content.content_topic_post", "content.content_topic", "content.content_topic_post_media", "media.media", "media.media_analysis_ai", "general.social_network_type"],
    },
    {
        "capability": "post_performance_lookup",
        "intent": "content",
        "agent_name": "Content Planning Agent",
        "domain": "content",
        "retriever_modes": ["sql", "vector"],
        "capability_state": "partially_supported",
        "template_keys": ["post_performance_lookup"],
        "join_paths": ["content_performance"],
        "tables": ["content.content_topic_post", "analytics.social_media_post", "analytics.metric_embeddings", "content.content_topic_post_media", "media.media", "media.media_analysis_ai"],
    },
    {
        "capability": "media_recommendation",
        "intent": "media",
        "agent_name": "Media Discovery Agent",
        "domain": "media",
        "retriever_modes": ["vector"],
        "capability_state": "fully_supported",
        "template_keys": [],
        "join_paths": ["media_semantic"],
        "tables": ["general.knowledge_embeddings", "media.media", "media.media_analysis_ai", "content.content_topic_post_media"],
    },
    {
        "capability": "client_access_lookup",
        "intent": "access",
        "agent_name": "Access and Relationship Agent",
        "domain": "access",
        "retriever_modes": ["sql"],
        "capability_state": "fully_supported",
        "template_keys": ["client_access_lookup"],
        "join_paths": ["client_access"],
        "tables": ["clients.clients", "clients.clients_collaborators", "users.users", "organizations.organization_users"],
    },
    {
        "capability": "relationship_lookup",
        "intent": "access",
        "agent_name": "Access and Relationship Agent",
        "domain": "relationships",
        "retriever_modes": ["sql"],
        "capability_state": "fully_supported",
        "template_keys": ["relationship_lookup"],
        "join_paths": ["entity_relationship_graph"],
        "tables": ["entity.entity", "entity.entity_relationship", "clients.clients"],
    },
    {
        "capability": "event_lookup",
        "intent": "event",
        "agent_name": "Access and Relationship Agent",
        "domain": "events",
        "retriever_modes": ["sql"],
        "capability_state": "fully_supported",
        "template_keys": ["event_lookup"],
        "join_paths": ["event_lookup"],
        "tables": ["general.events", "clients.clients", "world.cities"],
    },
    {
        "capability": "pricing_lookup",
        "intent": "client_knowledge",
        "agent_name": "Client Knowledge and FAQ Agent",
        "domain": "pricing",
        "retriever_modes": ["sql"],
        "capability_state": "not_supported",
        "template_keys": [],
        "join_paths": ["property_knowledge"],
        "tables": ["clients.property_details", "clients.client_notes"],
    },
]


def _matrix_entry(capability: str) -> dict[str, object]:
    for entry in ROUTING_MATRIX:
        if entry["capability"] == capability:
            return entry
    raise KeyError(f"Unknown capability: {capability}")


def _requires_client(capability: str) -> bool:
    return capability not in {"clarify_scope", "unsupported_action"}


def _clarification(message: str) -> OrchestratorDecision:
    return OrchestratorDecision(
        capability="clarify_scope",
        intent="clarification",
        agent_name="Orchestrator Agent",
        domain="clarification",
        rationale="The request is missing a required entity such as client, property, or date range.",
        confidence=0.55,
        capability_state="not_supported",
        branch="clarification",
        clarification_question=message,
    )


def _unsupported_action(message: str) -> OrchestratorDecision:
    return OrchestratorDecision(
        capability="unsupported_action",
        intent="unsupported_action",
        agent_name="Orchestrator Agent",
        domain="actions",
        rationale="The user asked for a write-like action, which is disabled in the read-only assistant.",
        confidence=0.99,
        capability_state="not_supported",
        branch="unsupported_action",
        refusal_message=message,
    )


def build_orchestrator_decision(payload: RoutingPayload) -> OrchestratorDecision:
    q = payload.normalized_query
    intent = payload.intent

    if intent == "unsupported_action":
        return _unsupported_action(
            "This assistant is read-only. I can explain what should be approved, published, assigned, or sent, but I cannot execute that action."
        )

    if intent == "clarification":
        return _clarification("Which client or property should I use for this question?")

    if intent == "content":
        if payload.entities.client_id is None:
            return _clarification("Which client should I use for this content question?")
        if any(phrase in q for phrase in ("performance", "performing", "engagement", "likes", "comments", "reactions")):
            entry = _matrix_entry("post_performance_lookup")
            return OrchestratorDecision(
                capability="post_performance_lookup",
                intent=intent,
                agent_name=str(entry["agent_name"]),
                domain=str(entry["domain"]),
                rationale="The request needs the latest resolved post, its analytics snapshot, and related media context.",
                confidence=0.92,
                capability_state=str(entry["capability_state"]),
                retriever_modes=list(entry["retriever_modes"]),
                template_keys=list(entry["template_keys"]),
                join_paths=list(entry["join_paths"]),
                tables=list(entry["tables"]),
            )
        if any(phrase in q for phrase in ("post copy", "caption", "which media", "what media", "media used", "used media", "attached media", "media has been used")):
            entry = _matrix_entry("content_post_detail_lookup")
            return OrchestratorDecision(
                capability="content_post_detail_lookup",
                intent=intent,
                agent_name=str(entry["agent_name"]),
                domain=str(entry["domain"]),
                rationale="The request asks for exact post content and attached media, so it should resolve the latest matching post and its media join path.",
                confidence=0.95,
                capability_state=str(entry["capability_state"]),
                retriever_modes=list(entry["retriever_modes"]),
                template_keys=list(entry["template_keys"]),
                join_paths=list(entry["join_paths"]),
                tables=list(entry["tables"]),
            )
        if any(phrase in q for phrase in ("draft", "drafts", "approval", "approvals", "needs approval")):
            entry = _matrix_entry("content_approval_lookup")
            return OrchestratorDecision(
                capability="content_approval_lookup",
                intent=intent,
                agent_name=str(entry["agent_name"]),
                domain=str(entry["domain"]),
                rationale="The request is about draft and approval workflow state, so it should use the approval trail templates.",
                confidence=0.94,
                capability_state=str(entry["capability_state"]),
                retriever_modes=list(entry["retriever_modes"]),
                template_keys=list(entry["template_keys"]),
                join_paths=list(entry["join_paths"]),
                tables=list(entry["tables"]),
            )
        entry = _matrix_entry("content_schedule_lookup")
        return OrchestratorDecision(
            capability="content_schedule_lookup",
            intent=intent,
            agent_name=str(entry["agent_name"]),
            domain=str(entry["domain"]),
            rationale="The request is a structured schedule or post-calendar lookup, so it should route through approved content SQL templates.",
            confidence=0.95,
            capability_state=str(entry["capability_state"]),
            retriever_modes=list(entry["retriever_modes"]),
            template_keys=list(entry["template_keys"]),
            join_paths=list(entry["join_paths"]),
            tables=list(entry["tables"]),
        )

    if intent == "media":
        if payload.entities.client_id is None:
            return _clarification("Which client should I use for this media search?")
        entry = _matrix_entry("media_recommendation")
        return OrchestratorDecision(
            capability="media_recommendation",
            intent=intent,
            agent_name=str(entry["agent_name"]),
            domain=str(entry["domain"]),
            rationale="The request is semantic media matching, so it should combine approved media SQL scope with deterministic vector-style retrieval.",
            confidence=0.9,
            capability_state=str(entry["capability_state"]),
            retriever_modes=list(entry["retriever_modes"]),
            template_keys=list(entry["template_keys"]),
            join_paths=list(entry["join_paths"]),
            tables=list(entry["tables"]),
        )

    if intent == "access":
        if payload.entities.client_id is None:
            return _clarification("Which client should I use for this access question?")
        if any(word in q for word in ("relationship", "relationships", "connected", "connection", "connections", "linked", "related", "graph")):
            entry = _matrix_entry("relationship_lookup")
            return OrchestratorDecision(
                capability="relationship_lookup",
                intent=intent,
                agent_name=str(entry["agent_name"]),
                domain=str(entry["domain"]),
                rationale="The request asks for connected entities, so it should read the derived entity relationship graph for the resolved client.",
                confidence=0.93,
                capability_state=str(entry["capability_state"]),
                retriever_modes=list(entry["retriever_modes"]),
                template_keys=list(entry["template_keys"]),
                join_paths=list(entry["join_paths"]),
                tables=list(entry["tables"]),
            )
        entry = _matrix_entry("client_access_lookup")
        return OrchestratorDecision(
            capability="client_access_lookup",
            intent=intent,
            agent_name=str(entry["agent_name"]),
            domain=str(entry["domain"]),
            rationale="The request is about ownership, collaborator, or client access scope and should use exact relational rows.",
            confidence=0.97,
            capability_state=str(entry["capability_state"]),
            retriever_modes=list(entry["retriever_modes"]),
            template_keys=list(entry["template_keys"]),
            join_paths=list(entry["join_paths"]),
            tables=list(entry["tables"]),
        )

    if intent == "event":
        if payload.entities.client_id is None and not payload.entities.city:
            return _clarification("Which client or city should I use for this event lookup?")
        entry = _matrix_entry("event_lookup")
        return OrchestratorDecision(
            capability="event_lookup",
            intent=intent,
            agent_name=str(entry["agent_name"]),
            domain=str(entry["domain"]),
            rationale="The request is about nearby or upcoming events and should use client geography plus exact event rows.",
            confidence=0.88,
            capability_state=str(entry["capability_state"]),
            retriever_modes=list(entry["retriever_modes"]),
            template_keys=list(entry["template_keys"]),
            join_paths=list(entry["join_paths"]),
            tables=list(entry["tables"]),
        )

    if intent == "inbox":
        if payload.entities.client_id is None:
            return _clarification("Which client should I use for this inbox or complaint question?")
        entry = _matrix_entry("inbox_lookup")
        return OrchestratorDecision(
            capability="inbox_lookup",
            intent=intent,
            agent_name=str(entry["agent_name"]),
            domain=str(entry["domain"]),
            rationale="The request is about thread triage or complaints and should route through exact inbox tables first.",
            confidence=0.95,
            capability_state=str(entry["capability_state"]),
            retriever_modes=list(entry["retriever_modes"]),
            template_keys=list(entry["template_keys"]),
            join_paths=list(entry["join_paths"]),
            tables=list(entry["tables"]),
        )

    if any(word in q for word in ("competitor", "competitors", "competition", "competitive", "comp set", "compset", "comparable", "comparables", "similar hotels")):
        if payload.entities.client_id is None:
            return _clarification("Which client should I use for this competitor or comparable-set question?")
        entry = _matrix_entry("competitor_lookup")
        return OrchestratorDecision(
            capability="competitor_lookup",
            intent="client_knowledge",
            agent_name=str(entry["agent_name"]),
            domain=str(entry["domain"]),
            rationale="The request asks for competitors or comparable properties, so it should infer a read-only comparable set from client city, property type, audience, and marketing settings.",
            confidence=0.86,
            capability_state=str(entry["capability_state"]),
            retriever_modes=list(entry["retriever_modes"]),
            template_keys=list(entry["template_keys"]),
            join_paths=list(entry["join_paths"]),
            tables=list(entry["tables"]),
        )

    if any(word in q for word in ("price", "pricing", "rate", "rates", "cost")):
        entry = _matrix_entry("pricing_lookup")
        return OrchestratorDecision(
            capability="pricing_lookup",
            intent="client_knowledge",
            agent_name=str(entry["agent_name"]),
            domain=str(entry["domain"]),
            rationale="The request is a pricing question, but the current schema does not provide dependable hotel rate facts.",
            confidence=0.98,
            capability_state=str(entry["capability_state"]),
            retriever_modes=list(entry["retriever_modes"]),
            template_keys=list(entry["template_keys"]),
            join_paths=list(entry["join_paths"]),
            tables=list(entry["tables"]),
        )

    if payload.entities.client_id is None and _requires_client("property_fact_lookup"):
        return _clarification("Which client or property should I use for this knowledge question?")

    if any(word in q for word in ("tone", "voice", "guidelines", "use words", "avoid words")):
        entry = _matrix_entry("tone_of_voice_lookup")
        return OrchestratorDecision(
            capability="tone_of_voice_lookup",
            intent="client_knowledge",
            agent_name=str(entry["agent_name"]),
            domain=str(entry["domain"]),
            rationale="The request is about tone guidance and should use grounded client voice settings plus supporting knowledge rows.",
            confidence=0.96,
            capability_state=str(entry["capability_state"]),
            retriever_modes=list(entry["retriever_modes"]),
            template_keys=list(entry["template_keys"]),
            join_paths=list(entry["join_paths"]),
            tables=list(entry["tables"]),
        )

    if any(word in q for word in ("audience", "audiences", "target audience", "targeting")):
        entry = _matrix_entry("audience_lookup")
        return OrchestratorDecision(
            capability="audience_lookup",
            intent="client_knowledge",
            agent_name=str(entry["agent_name"]),
            domain=str(entry["domain"]),
            rationale="The request is about audience definition and should use grounded audience and client context sources.",
            confidence=0.94,
            capability_state=str(entry["capability_state"]),
            retriever_modes=list(entry["retriever_modes"]),
            template_keys=list(entry["template_keys"]),
            join_paths=list(entry["join_paths"]),
            tables=list(entry["tables"]),
        )

    if any(word in q for word in ("what do we know", "overview", "amenities", "details")):
        entry = _matrix_entry("property_knowledge_summary")
        return OrchestratorDecision(
            capability="property_knowledge_summary",
            intent="client_knowledge",
            agent_name=str(entry["agent_name"]),
            domain=str(entry["domain"]),
            rationale="The request asks for grounded client or property context, so it should use trusted note and detail sources.",
            confidence=0.9,
            capability_state=str(entry["capability_state"]),
            retriever_modes=list(entry["retriever_modes"]),
            template_keys=list(entry["template_keys"]),
            join_paths=list(entry["join_paths"]),
            tables=list(entry["tables"]),
        )

    entry = _matrix_entry("property_fact_lookup")
    return OrchestratorDecision(
        capability="property_fact_lookup",
        intent="client_knowledge",
        agent_name=str(entry["agent_name"]),
        domain=str(entry["domain"]),
        rationale="The safest default is a grounded property-fact route over approved notes and property detail sources.",
        confidence=0.82,
        capability_state=str(entry["capability_state"]),
        retriever_modes=list(entry["retriever_modes"]),
        template_keys=list(entry["template_keys"]),
        join_paths=list(entry["join_paths"]),
        tables=list(entry["tables"]),
    )
