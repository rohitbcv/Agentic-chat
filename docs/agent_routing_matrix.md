# Agent Routing Matrix

This document is the routing contract for the read-only intelligence assistant.

## Scope

- all routing starts with the shared intake payload
- no agent can write to the database or call mutation APIs
- relationship traversal uses the local derived read-only graph in `entity.entity` and `entity.entity_relationship`
- specialist runtime isolation, context merging, confidence, and safety are implemented after orchestration
- this matrix is a capability registry, not a fixed chatbot prompt list
- new DB-backed question types should become new capabilities after schema, join-map, tool, and evaluation coverage are added

## Intelligence Routing Principle

For any app/DB-related question, the orchestrator must choose one of these outcomes:

| Outcome | When to use |
| --- | --- |
| `direct_answer` | existing route has enough evidence |
| `multi_source_answer` | answer needs more than one route or retrieval mode |
| `relationship_answer` | answer depends on graph or multi-hop joins |
| `partial_answer` | evidence exists but is incomplete or inferred |
| `clarification` | required scope is missing or ambiguous |
| `capability_gap` | schema may support the question, but the approved route is not implemented yet |
| `not_supported` | no dependable approved source exists |
| `read_only_refusal` | user asks for mutation or external action |

The correct fallback is not a generic chatbot answer. The correct fallback is a grounded explanation of what data exists, what data is missing, and what capability should be added next.

## Intake To Agent Mapping

| Intent | Capability | Routed Agent | Retriever Mode | Capability State | Clarification Rule |
| --- | --- | --- | --- | --- | --- |
| `inbox` | `inbox_lookup` | Inbox and Complaint Agent | `sql` | `fully_supported` | ask for client if none resolved |
| `client_knowledge` | `property_fact_lookup` | Client Knowledge and FAQ Agent | `vector` | `fully_supported` | ask for client/property if none resolved |
| `client_knowledge` | `property_knowledge_summary` | Client Knowledge and FAQ Agent | `vector` | `fully_supported` | ask for client/property if none resolved |
| `client_knowledge` | `tone_of_voice_lookup` | Client Knowledge and FAQ Agent | `vector` | `fully_supported` | ask for client/property if none resolved |
| `client_knowledge` | `audience_lookup` | Client Knowledge and FAQ Agent | `vector` | `fully_supported` | ask for client/property if none resolved |
| `client_knowledge` | `competitor_lookup` | Access and Relationship Agent | `sql` | `partially_supported` | ask for client/property if none resolved |
| `content` | `content_schedule_lookup` | Content Planning Agent | `sql` | `fully_supported` | ask for client if none resolved |
| `content` | `content_approval_lookup` | Content Planning Agent | `sql` | `fully_supported` | ask for client if none resolved |
| `content` | `content_post_detail_lookup` | Content Planning Agent | `sql` | `fully_supported` | use when user asks for latest post copy, caption, or media used |
| `content` | `post_performance_lookup` | Content Planning Agent | `sql + vector` | `partially_supported` | ask for client if none resolved |
| `media` | `media_recommendation` | Media Discovery Agent | `vector` | `fully_supported` | ask for client if none resolved |
| `access` | `client_access_lookup` | Access and Relationship Agent | `sql` | `fully_supported` | ask for client if none resolved |
| `access` | `relationship_lookup` | Access and Relationship Agent | `sql` over derived graph | `fully_supported` | use when user asks how entities are connected |
| `event` | `event_lookup` | Access and Relationship Agent | `sql` | `fully_supported` | ask for client or city if none resolved |
| write-like request | `unsupported_action` | Orchestrator Agent | none | `not_supported` | refuse immediately |
| unresolved scope | `clarify_scope` | Orchestrator Agent | none | `not_supported` | ask a follow-up question |
| pricing question | `pricing_lookup` | Client Knowledge and FAQ Agent | none | `not_supported` | refuse fabrication |

## Capability Notes

### Fully supported now

- property facts from approved property notes and details
- tone and audience from approved client profile sources
- inbox thread lookup
- scheduled content lookup
- approval workflow lookup
- collaborator access lookup
- relationship graph lookup from the derived entity graph
- nearby event lookup
- media discovery from approved media analysis text

### Partially supported now

- post performance lookup
- competitor/comparable lookup

Conditions:

- the client must resolve cleanly
- competitor lookup is inferred from city, property type, rate-band, audience, and property context
- competitor lookup must be labeled as likely comparables unless an official competitor source is later added
- the latest relevant post must resolve cleanly
- analytics must join through `network_post_ref`, `post_ref`, or `identifier`
- missing analytics should downgrade the answer to partial evidence, not guessed metrics

### Not supported now

- any write action
- room-rate or booking-price answers without a dependable pricing source

## Orchestrator Rules

1. normalize the message and extract entities first
2. resolve client scope before retrieval
3. prefer exact SQL routes for counts, statuses, schedules, approvals, access, and events
4. prefer approved knowledge retrieval for property facts, tone, audience, and media semantics
5. ask a follow-up question instead of guessing when client scope is missing
6. refuse any write-like request immediately
7. return `fully_supported`, `partially_supported`, or `not_supported` with every run

## Runtime Boundary

This file covers the current POC runtime.

- specialist agent modules validate table and retriever allow-lists
- context merger and answer-grounding layers run after retrieval
- relationship graph materialization is implemented locally through `scripts/create_relationship_graph.py`
