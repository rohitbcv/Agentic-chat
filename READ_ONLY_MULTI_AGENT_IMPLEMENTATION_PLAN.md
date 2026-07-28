# Read-Only Multi-Agent Implementation Plan

## Purpose

This document converts the current DB-first roadmap and the orchestration diagram into a concrete implementation plan for a new multi-agent application.

The target product is an `intelligence assistant`, not a narrow chatbot with fixed prompts.

That means the system should:

- accept open-ended natural language questions
- decompose each question into reusable retrieval capabilities
- combine evidence from multiple tables and retrieval modes
- answer with `fully supported`, `partially supported`, or `not supported` reasoning when needed
- discover when a new DB-backed capability is needed instead of pretending the answer does not exist
- grow through schema catalog, join-map, retrieval-tool, and evaluation coverage

Hard requirement:

- every agent is `read-only`
- no agent can write to the database
- no agent can call write-capable app APIs
- no agent can approve, publish, send, update, delete, or mutate anything

Because of that constraint, the `App API Tools` branch in the original diagram is replaced in Phase 1 by:

- `Action Advisory Node`
- `Read-Only Refusal Policy`

The system may explain what action should be taken, but it must never execute the action.

## Current Implementation Status

The POC now implements Phases 0-9 in the standalone `Agent chat` app.

| Phase | Status | Implemented artifacts |
| --- | --- | --- |
| Phase 0 | implemented | data dictionary, domain map, exposure list, join maps |
| Phase 1 | implemented | read-only guard middleware, read-only policy, local dummy DB mode |
| Phase 2 | implemented | intake service, entity extraction, date parsing, scope resolution |
| Phase 3 | implemented | approved SQL retrievers, semantic retrievers, source traces |
| Phase 4 | implemented | Orchestrator Agent and routing matrix |
| Phase 5 | implemented | five specialist agent contracts and runtime validation |
| Phase 6 | implemented | context merger, confidence scoring, support-state handling |
| Phase 7 | implemented | answer safety review, read-only refusal, response-only audit metadata |
| Phase 8 | implemented | React/Vite UI with route, source, confidence, and safety trace panel |
| Phase 9 | implemented | evaluation script and scorecard docs |

Knowledge and metric embeddings are supported as optional local read models:

- `general.knowledge_embeddings`
- `analytics.metric_embeddings`

Important metric rule:

- exact metric values and calculations must come from SQL
- embeddings should be created only for metric semantics and context, using `text-embedding-3-large`

Important knowledge rule:

- property notes, FAQs, property details, tone, audience, media analysis, and post copy are embedded into `general.knowledge_embeddings`
- each chunk keeps `client_id`, source table, source PK, domain, model, and source reference metadata
- agents may read the embedding table but may not create or update embeddings during chat

---

## 0. Product Contract: Intelligence Assistant, Not Chatbot

The assistant must handle any question related to approved app/DB data through a safe decision tree.

| User asks | Assistant should do |
| --- | --- |
| direct data question | resolve scope, run approved SQL, answer exactly |
| semantic/property/FAQ question | retrieve approved knowledge chunks, answer only from evidence |
| relationship question | use derived graph or approved multi-hop joins |
| analytical question | combine exact SQL metrics with semantic context and state limitations |
| cross-domain question | run multiple retrieval modes, merge context, and answer with sources |
| missing-scope question | ask one concise clarification question |
| unsupported-data question | state that the approved DB does not contain dependable evidence |
| write/action request | refuse execution and provide read-only advisory help |

This means unsupported is a data/evidence state, not a product failure.

### Capability Expansion Loop

When the user asks a new kind of DB-related question, the system should follow this loop:

1. Identify the business object, such as client, post, media, metric, event, competitor, thread, user, campaign, or audience.
2. Find candidate tables from `docs/db_dictionary.md`.
3. Find or propose a join path in `docs/join_map_catalog.md`.
4. Decide if the answer needs SQL, vector, graph, or hybrid retrieval.
5. Add a capability in `docs/agent_routing_matrix.md`.
6. Add an approved SQL/vector/graph tool.
7. Add dummy DB seed data when live data is sparse.
8. Add evaluation cases before exposing the capability as supported.

The app should never rely on hardcoded sample prompts as the product boundary.

### Future Schema Intelligence Milestone

After the current POC routes are stable, add a `Schema Intelligence` layer before the Query Router.

Purpose:

- read the DB dictionary, exposure list, join maps, and capability registry
- detect whether a new question is answerable from existing approved data
- propose a safe capability gap when the route does not exist yet
- avoid returning a generic "I cannot verify" before checking the relevant schema domain

In the POC this layer should propose a route and ask for implementation. In production it can become a read-only SQL compiler only if it has strict schema allow-lists, tenant scoping, row limits, static SQL validation, and evaluation coverage.

---

## 1. Final Agent Set

Use `6 agents` in total.

### 1. Orchestrator Agent

Purpose:

- receives the user query first
- normalizes the request
- classifies intent
- decides which specialist agent should handle the question
- decides whether the route is `SQL`, `SQL + Vector`, `SQL + Graph`, `Vector only`, or `Clarification`

Primary domains:

- all domains at routing level only

Read-only rule:

- no direct DB writes
- no direct external actions

### 2. Inbox and Complaint Agent

Purpose:

- handles guest threads
- complaints
- triage state
- escalation context
- thread-level reputation questions

Primary tables:

- `jx_bridge.messages`
- `jx_bridge.messages_metadata`
- `jx_bridge.thread_triage`
- `jx_bridge.alerts`
- `jx_bridge.alert_replies`
- `inbox.monitor_group`
- `inbox.monitor_group_client`
- `inbox.monitor_group_user`

Read-only rule:

- may explain what alert or reply should happen
- may not create alerts or send replies

### 3. Client Knowledge and FAQ Agent

Purpose:

- answers property facts
- FAQs
- tone of voice
- target audience
- location
- policy
- reusable operational notes

Primary tables:

- `clients.clients`
- `clients.client_details`
- `clients.property_details`
- `clients.client_notes`
- `clients.client_tone_of_voice_settings`
- `clients.client_target_audience`
- `clients.client_target_audience_suggestions`
- `general.timezone`
- `world.cities`

Read-only rule:

- may summarize known facts
- may not edit notes, property details, or guidelines

### 4. Content Planning Agent

Purpose:

- handles scheduled posts
- drafts waiting for approval
- post workflow questions
- content pillar usage
- channel planning
- event-aware content planning
- limited post-level performance intelligence for supported networks

Primary tables:

- `content.content_topic`
- `content.content_topic_post`
- `content.content_post_status`
- `content.content_topic_post_type`
- `content.content_topic_post_approval_status`
- `clients.client_content_pillars`
- `clients.client_social_network_cadence`
- `clients.client_social_network_account`
- `analytics.social_media_post`
- `general.social_network_type`
- `general.events`

Read-only rule:

- may recommend content actions
- may not schedule, publish, approve, or edit posts

### 5. Media Discovery Agent

Purpose:

- handles media search
- semantic visual matching
- asset recommendation
- missing metadata checks
- content-to-media matching

Primary tables:

- `media.media`
- `media.media_analysis_ai`
- `media.media_asset`
- `media.media_status`
- `content.content_topic_post_media`
- `content.content_topic_post_media_tags`

Read-only rule:

- may recommend assets
- may not upload, tag, edit, or attach media

### 6. Access and Relationship Agent

Purpose:

- answers access questions
- organization ownership questions
- collaborator scope questions
- client-to-entity-to-event relationship questions
- multi-hop connected entity questions

Primary tables:

- `users.users`
- `users.users_roles`
- `organizations.organizations`
- `organizations.organization_users`
- `clients.clients`
- `clients.clients_collaborators`
- `entity.entity`
- `entity.entity_facility_brand`
- `entity.entity_facility_sub_brand`
- `general.events`
- `world.cities`

Read-only rule:

- may explain access and ownership
- may not grant or revoke access

---

## 2. Shared Non-Agent Services

These should be deterministic services, not autonomous agents.

### Message Preprocessor

Responsibilities:

- normalize text
- detect language
- expand date phrases like `next week`, `last 30 days`, `today`
- strip noise

### Entity Extractor

Responsibilities:

- extract:
  - `user_id`
  - `organization_id`
  - `client_id`
  - `property_name`
  - `city`
  - `channel`
  - `thread_id`
  - `date range`
  - `event`
  - `audience`
  - `topic`
  - `media theme`

### Access Resolver

Responsibilities:

- resolve allowed `organization_id`s
- resolve allowed `client_id`s
- resolve allowed domains for the requesting user
- deny cross-tenant retrieval

### SQL Retriever

Responsibilities:

- execute approved SQL templates only
- inject access scope into every query
- reject free-form SQL generation

### Vector Retriever

Responsibilities:

- run semantic search over approved embeddings
- filter by allowed client scope before retrieval

### Graph Retriever

Responsibilities:

- handle multi-hop relationship questions
- return connected entities with traceable paths

Important note:

- graph is useful, but not required for phase 1
- start with relational join maps plus vector retrieval
- add graph after SQL and vector retrieval are stable

### Context Merger

Responsibilities:

- deduplicate
- rank
- compact
- attach sources
- mark unsupported or low-confidence evidence

### Grounding and Safety Layer

Responsibilities:

- verify permissions
- verify source coverage
- detect unsupported requests
- refuse all write-like behavior

---

## 3. Read-Only Permission Model

This is mandatory for every phase.

### DB role rules

Create one dedicated DB role for the app:

- `ai_readonly_app`

Permissions:

- `SELECT` only on approved schemas and tables
- no `INSERT`
- no `UPDATE`
- no `DELETE`
- no `TRUNCATE`
- no `CREATE`
- no `ALTER`
- no `DROP`

### Agent execution rules

Every agent must:

- use the same read-only DB credential
- call retriever services only
- never receive write credentials
- never call mutable stored procedures
- never hit write-capable product APIs

### Product behavior rules

For requests like:

- `send this reply`
- `approve this draft`
- `publish this post`
- `assign this thread`
- `create an alert`

The app must respond with:

- a recommended action
- the data used to justify it
- a statement that execution is disabled in read-only mode

---

## 4. Mapping the Diagram to the New App

### Stage 1. Incoming Message

Input:

- natural language user query

Output:

- raw request envelope with user identity and session context

### Stage 2. Message Preprocessor

Input:

- raw query

Output:

- cleaned query
- normalized dates
- language

### Stage 3. Intent Classifier

Classes:

- `inbox`
- `complaint`
- `client_knowledge`
- `content`
- `media`
- `event`
- `access`
- `unsupported_action`

### Stage 4. Entity Extractor

Extract:

- client
- property
- city
- social channel
- date window
- thread id
- event name
- audience type
- topic
- media theme

### Stage 5. Access Control Check

Checks:

- is the user authenticated
- is the client in scope
- is the organization in scope
- is the requested domain allowed

### Stage 6. Query Router

Allowed branches in this read-only version:

- `SQL Search`
- `Graph Search`
- `Vector DB Search`
- `Web/API Search` only for optional event enrichment
- `Clarification Question`

Disabled branch:

- `App API Tools`

Replacement behavior:

- `Action Advisory Node`

Important routing note:

- in phase 1, most questions should route to `SQL`, `SQL + Vector`, or `Clarification`
- `Graph Search` should be used only when relational joins and vector retrieval are not enough to explain a multi-hop relationship

### Stage 7. Retrieved Context

Sources may include:

- exact rows
- semantic matches
- relationship paths
- optional external event data

### Stage 8. Context Merger

Tasks:

- remove duplicates
- rank by trust
- keep only client-scoped context
- attach source labels

### Stage 9. Retrieval Confidence Check

If low confidence:

- ask follow-up
- explain missing field or unsupported domain

If enough confidence:

- continue to answer generation

### Stage 10. LLM Answer Generator

Tasks:

- generate grounded answer
- preserve uncertainty
- never invent unsupported facts

### Stage 11. Grounding and Safety Check

Checks:

- source support exists
- no write action requested
- permissions are valid
- unsupported claims are clearly labeled

### Stage 12. Final Output

Return:

- answer
- route used
- sources
- confidence
- next recommended step

---

## 5. Concrete Routing Rules

The assistant should route by `capability`, not by a fixed list of hardcoded questions.

Examples of capabilities:

- `latest_post_resolution`
- `post_performance_lookup`
- `media_context_lookup`
- `client_scope_resolution`
- `thread_triage_explainer`
- `property_fact_lookup`
- `tone_guidance_lookup`
- `access_path_explainer`

### Route to Inbox and Complaint Agent

When the user asks:

- unresolved complaints
- waiting on property
- reply now
- triage state
- why a thread is escalated
- what changed in inbox

Preferred retrieval:

- `SQL`
- optional `Vector` for reply guidance
- optional `Graph` for alert chain explanation

### Route to Client Knowledge and FAQ Agent

When the user asks:

- does this property have a pool
- what is check-in time
- what is the tone of voice
- what do we know about this client
- what note or FAQ exists for this property

Preferred retrieval:

- `Vector`
- `SQL`

### Route to Content Planning Agent

When the user asks:

- what posts are scheduled next week
- which drafts need approval
- what pillars are underused
- what content should we plan around this event
- how is my last Instagram post performing
- which recent published posts have engagement data

Preferred retrieval:

- `SQL`
- optional `Vector`
- optional `Graph`

Important note:

- performance-style questions are only `partially supported` in phase 1
- they depend on analytics coverage for the requested network and post
- the assistant should merge:
  - post metadata from `content.content_topic_post`
  - account mapping from `clients.client_social_network_account`
  - performance facts from `analytics.social_media_post`
  - related media from `content.content_topic_post_media`
  - media semantics from `media.media_analysis_ai`

### Route to Media Discovery Agent

When the user asks:

- find visuals for a wedding campaign
- which assets match this topic
- which media is missing alt text

Preferred retrieval:

- `Vector`
- `SQL`
- optional `Graph`

### Route to Access and Relationship Agent

When the user asks:

- who has access to this client
- which organization owns this property
- what entity or brand is connected to this client
- which event is related to this city and client profile

Preferred retrieval:

- `SQL`
- `Graph`

### Route to Clarification

When:

- no client is resolved
- multiple clients match
- no date range exists for a time-bounded request
- the requested domain is empty for that client
- the user asked for a write action

---

## 6. Supported Retrieval Modes by Agent

| Agent | SQL | Vector | Graph | Web/API | Write Tools |
|---|---|---|---|---|---|
| Orchestrator Agent | no | no | no | no | `disabled` |
| Inbox and Complaint Agent | yes | yes | yes | no | `disabled` |
| Client Knowledge and FAQ Agent | yes | yes | low | no | `disabled` |
| Content Planning Agent | yes | yes | yes | optional | `disabled` |
| Media Discovery Agent | yes | yes | yes | no | `disabled` |
| Access and Relationship Agent | yes | low | yes | optional | `disabled` |

---

## 6.1 Capability Coverage Model

The assistant should classify every answer into one of three states:

- `fully_supported`
- `partially_supported`
- `not_supported`

### Fully supported

Use when:

- the join path is known
- the required tables exist
- the relevant row coverage is present
- the evidence is sufficient to answer directly

Examples:

- scheduled posts
- content approval status
- property FAQs backed by notes
- client tone of voice
- media matching

### Partially supported

Use when:

- some but not all evidence exists
- coverage is network-specific or client-specific
- metrics exist but are not normalized enough for broad conclusions

Examples:

- last Instagram post performance
- latest Facebook post engagement snapshot
- content plus media plus basic reaction counts

### Not supported

Use when:

- the schema cannot answer the question reliably
- the data is missing or too sparse
- the user asked for a forbidden write action

Examples:

- ROI by campaign
- revenue attribution
- trend diagnosis across all channels
- send, publish, approve, or assign actions

---

## 7. Step-by-Step Implementation Plan

## Phase 0. Freeze the Contract

### Goal

Lock the DB-first scope before building agent logic.

### Tasks

1. freeze the table list per domain
2. define `allowed` vs `do-not-expose` tables
3. document join paths
4. document empty or sparse domains
5. confirm every supported question category
6. classify each major capability as fully supported, partially supported, or not supported

### Deliverables

- data dictionary
- domain map
- read-only exposure list

## Phase 1. Enforce Read-Only Infrastructure

### Goal

Make it impossible for any agent to write.

### Tasks

1. create dedicated read-only DB role
2. revoke all mutation privileges
3. store only read-only credentials in the app
4. disable action APIs in the agent layer
5. add request guard for write verbs:
   - `send`
   - `approve`
   - `publish`
   - `assign`
   - `create`
   - `update`
   - `delete`

### Deliverables

- read-only role
- access policy doc
- write-refusal middleware

## Phase 2. Build the Shared Intake Pipeline

### Goal

Implement the top half of the diagram.

### Tasks

1. build message preprocessor
2. build intent classifier
3. build entity extractor
4. build access resolver
5. define routing payload contract

### Output contract

```json
{
  "query": "Does Snow Villa have a pool?",
  "intent": "client_knowledge",
  "entities": {
    "client_id": 7403,
    "property_name": "Snow Villa",
    "city": null,
    "date_range": null,
    "channel": null
  },
  "scope": {
    "organization_ids": [54],
    "client_ids": [7403, 553, 552],
    "domains": ["inbox", "content", "media", "knowledge"]
  }
}
```

### Deliverables

- intake service
- routing payload schema

## Phase 3. Build Approved Retriever Services

### Goal

Implement the middle retrieval layer from the diagram.

### Tasks

1. build SQL template library
2. build vector chunk pipeline
3. build canonical relational join maps
4. add scope filters to every retriever
5. add query logging and source tracing
6. add analytics JSON extractors for supported network-specific metrics
7. defer graph materialization until SQL and vector routes are stable

### Deliverables

- SQL retriever
- vector retriever
- join map catalog
- source trace format

## Phase 4. Build Agent 1: Orchestrator Agent

### Goal

Centralize routing decisions.

### Tasks

1. map intents to agents
2. map intents to retriever combinations
3. add clarification branch
4. add unsupported-action refusal branch
5. add capability-state output:
   - `fully_supported`
   - `partially_supported`
   - `not_supported`

### Deliverables

- orchestrator policy
- routing matrix

## Phase 5. Build the 5 Specialist Agents

### Goal

Implement domain-specialized reasoning over read-only retrieval.

### Tasks

1. build Inbox and Complaint Agent
2. build Client Knowledge and FAQ Agent
3. build Content Planning Agent
4. build Media Discovery Agent
5. build Access and Relationship Agent
6. teach Content Planning Agent to answer limited post-level performance questions for supported networks only

### Deliverables

- one prompt contract per agent
- one test set per agent
- one approved table map per agent

## Phase 6. Build Context Merger and Confidence Check

### Goal

Implement the lower-middle part of the diagram.

### Tasks

1. rank SQL over vector when exact fact exists
2. rank property notes above weak semantic matches
3. reject contradictory evidence
4. ask follow-up when required fields are missing
5. produce answerable vs not-answerable decision
6. mark partial analytics answers clearly when only network-specific snapshots are available

### Deliverables

- context merger
- confidence scoring rules
- clarification templates

## Phase 7. Build Answer Generator and Safety Layer

### Goal

Produce grounded answers only.

### Tasks

1. generate answer from merged context
2. attach source references
3. add unsupported-domain wording
4. add read-only advisory wording for blocked actions
5. add confidence label
6. add capability-state label to every response

### Deliverables

- answer template
- safety policy
- refusal policy

## Phase 8. Build the UI

### Goal

Expose the orchestration flow clearly to users.

### Tasks

1. show active route
2. show chosen agent
3. show SQL / Vector / Graph path used
4. show retrieved sources
5. show confidence
6. show follow-up question when clarification is needed
7. show advisory-only state for action requests

### Deliverables

- multi-panel agent UI
- source trace panel
- follow-up flow

## Phase 9. Evaluate and Expand

### Goal

Make the system trustworthy before adding more capability.

### Tasks

1. create benchmark questions per domain
2. measure route accuracy
3. measure grounding accuracy
4. measure clarification quality
5. measure unsupported-domain refusal quality
6. measure partial-support accuracy for analytics and mixed-evidence questions

### Deliverables

- routing scorecard
- source-trust scorecard
- production-readiness checklist

---

## 8. Approved Question Coverage for Phase 1

This list is illustrative, not exhaustive.

The assistant should generalize by capability and relationship path, not by memorizing these exact phrasings.

### Inbox and complaint

- Which complaints are unresolved for client X?
- Why is this thread waiting on property?
- What changed since my last visit?

### Client knowledge and FAQ

- Does this property have a pool?
- What is the check-in time?
- What is the tone of voice for this client?
- What notes exist for this property?

### Content

- What posts are scheduled next week?
- Which drafts are waiting for approval?
- Which channels are underused?
- How is my last Instagram post performing?
- Show the caption, attached media, and basic engagement for the latest published post.

### Media

- Find visuals for a luxury wedding campaign.
- Which assets match this content topic?
- Which media items are missing alt text?

### Access and relationships

- Who has access to this client?
- Which organization owns this property?
- Which events near this city fit this audience?

---

## 9. Explicitly Unsupported in Phase 1

The system should refuse, narrow, or downgrade these depending on evidence:

- send reply
- approve draft
- publish content
- assign thread
- create alert
- update note
- change tone guidelines
- grant or revoke access
- campaign ROI analysis
- broad performance analytics diagnosis across all channels
- reliable revenue attribution

Reason:

- write behavior is forbidden
- analytics support is partial, network-specific, and not yet normalized enough for general analytics claims

### Partially supported in Phase 1

The system may answer these with explicit caveats:

- how is my last Facebook post performing
- how is my last Instagram post performing
- show recent post caption plus related media plus available engagement snapshot

Conditions:

- the post must be resolvable
- the network must have analytics coverage
- the analytics row must join through `network_post_ref` or account mapping
- the answer must be labeled `partially_supported` unless evidence is complete

---

## 10. Recommended File Outputs for the Build Team

Create these artifacts next:

1. `docs/db_dictionary.md`
2. `docs/read_only_access_model.md`
3. `docs/agent_routing_matrix.md`
4. `docs/sql_template_catalog.md`
5. `docs/join_map_catalog.md`
6. `docs/vector_embedding_plan.md`
7. `docs/graph_entity_map.md`
8. `docs/evaluation_dataset.md`
9. `docs/capability_coverage_matrix.md`

---

## 11. Final Recommendation

Start with `6 agents` and keep all retrieval services deterministic.

Implementation priority:

1. relational join maps first
2. SQL and vector retrieval second
3. capability-aware reasoning third
4. graph reasoning after the first three are stable

Production shape for the first real version:

1. `Orchestrator Agent`
2. `Inbox and Complaint Agent`
3. `Client Knowledge and FAQ Agent`
4. `Content Planning Agent`
5. `Media Discovery Agent`
6. `Access and Relationship Agent`

Important implementation rule:

- every agent remains `read-only`
- no write permission is ever passed to any agent
- every answer must be grounded in `SQL`, `Vector`, `Graph`, or a clear clarification/refusal path
- the product should behave like an intelligence assistant with dynamic decomposition, not a fixed-question chatbot
