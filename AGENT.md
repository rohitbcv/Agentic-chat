# AGENT.md — Soho AI Query Studio POC

## Purpose

This file defines the first proof-of-concept for a new read-only AI application built on top of the Soho database.

This POC is intentionally separate from the current Community AI Inbox product implementation.

## Product Identity

This product is an `intelligence assistant`, not a fixed chatbot.

The assistant must be able to handle any reasonable question about app or DB data by doing one of four things:

1. answer from grounded evidence
2. combine multiple grounded sources and explain the result
3. ask for missing scope, such as client, channel, metric, or date range
4. say the data is not available instead of fabricating

The system should grow by adding new `capabilities`, `join maps`, `retrieval tools`, and `evaluation cases`, not by adding hardcoded sample prompts.

## POC Goals

1. Prove that a small multi-agent system can route open-ended DB questions correctly.
2. Demonstrate the difference between:
   - structured DB questions that need SQL
   - grounded knowledge questions that need property or contextual answers
   - relationship questions that need graph traversal
   - cross-domain questions that need multiple retrieval modes
3. Show a polished React/Vite UI that makes the routing visible to the user.
4. Stay read-only and safe.
5. Run against the local dummy DB now, then wire the same read-only routes to the live DB when credentials and coverage are ready.

## Product Scope

The POC supports:

- client and property questions
- inbox and complaint summaries
- scheduled content and workflow questions
- media recommendation questions
- event and local context questions
- access and scope questions
- competitor and comparable-market questions when supported by data
- cross-domain questions that connect content, media, analytics, inbox, events, users, and client knowledge

The POC does not support:

- write actions
- updates, deletions, or publishing
- unrestricted SQL execution
- autonomous workflows
- production analytics claims from sparse tables

The POC should still respond to unsupported questions intelligently. Unsupported means the assistant cannot verify the answer from approved data, not that the conversation is outside scope.

## Agent System

This POC uses 6 read-only agent roles. These are not six fixed chatbot categories; they are reusable intelligence domains backed by approved tools.

### 1. Orchestrator Agent

Purpose:

- receives the user query first
- runs intake, entity extraction, and scope resolution
- chooses the right specialist agent
- chooses the approved SQL/vector retrieval path
- asks clarification questions when scope is missing

Responsibilities:

- detect intent and capability
- enforce read-only routing boundaries
- return capability state: `fully_supported`, `partially_supported`, or `not_supported`
- expand a broad question into a safe retrieval plan when the answer needs more than one table family

### 2. Inbox and Complaint Agent

Purpose:

- handles inbox threads, complaints, triage state, and waiting-on-property questions
- uses approved `jx_bridge` SQL routes
- may explain what should happen next, but cannot send or assign

### 3. Client Knowledge and FAQ Agent

Purpose:

- answers property facts, FAQs, tone, audience, and policies
- uses approved client notes/details/tone/audience sources
- refuses to invent missing facts, amenities, prices, or policies
- answers only with positive or negative proof when the question asks for a specific fact

### 4. Content Planning Agent

Purpose:

- answers scheduled posts, approval queues, captions, and content workflow questions
- answers latest-post copy and media-used questions by resolving the exact post-media join
- answers limited post-level performance questions by combining post, analytics, and media evidence
- handles cross-domain content intelligence, such as "which media was used and how did it perform?"
- may recommend manual actions, but cannot schedule, approve, publish, or edit content

### 5. Media Discovery Agent

Purpose:

- finds relevant media assets from approved media analysis text
- explains why assets fit a campaign, audience, or content topic
- cannot upload, tag, attach, edit, or delete media

### 6. Access and Relationship Agent

Purpose:

- answers collaborator, organization, owner, city, event, and relationship-path questions
- answers competitor/comparable-market questions when data exists
- uses exact joins and the local derived relationship graph only when paths are traceable
- cannot grant, revoke, or change access

## Intelligence Coverage Model

Every user question should be classified into one of these outcome types:

| Outcome | Meaning | Example |
| --- | --- | --- |
| `direct_answer` | one approved route has enough evidence | `Who has access to Hotel Ramtin?` |
| `multi_source_answer` | multiple table families must be joined or merged | `How did the last TikTok post perform and which media was used?` |
| `relationship_answer` | graph or multi-hop joins explain connections | `How is client 7403 connected to posts, media, metrics, and events?` |
| `partial_answer` | some evidence exists, but the data is incomplete | `Who are competitors of Hotel Ramtin?` when only inferred comparables exist |
| `clarification` | required scope is missing or ambiguous | `What posts are scheduled next week?` without client scope |
| `not_supported` | approved schema does not contain dependable evidence | `What is tonight's live room price?` without a rate source |
| `read_only_refusal` | user asks the assistant to mutate data | `Publish this post` |

This is what makes the product an intelligence assistant: every question receives the safest correct handling path, even when the answer is "I cannot verify that from approved data."

## Runtime Layers

The app now runs:

1. intake pipeline
2. orchestrator decision
3. specialist agent contract validation
4. approved SQL/vector retrieval
5. derived relationship-graph retrieval when routed to `relationship_lookup`
6. context merger and confidence check
7. LLM answer generation when grounded evidence exists and the route is safe
8. grounding and safety review
9. response-only audit event

## LLM Answer Generator

The LLM is allowed to synthesize final answer wording only after retrieval has completed.

- answer generation must use `OPENAI_MODEL=gpt-5.4-mini`
- embedding generation must keep using `OPENAI_EMBED_MODEL` because embeddings require an embedding-capable model
- it cannot choose tables
- it cannot write SQL
- it cannot calculate metrics
- it cannot call mutable tools
- it must answer only from SQL rows, vector matches, or relationship paths already retrieved
- it falls back to deterministic answers for unsupported, missing-evidence, negative-proof, and strict yes/no property-fact cases

## Routing Rules

### Route by exact-data capability when the user asks for:

- counts
- lists
- statuses
- schedules
- unresolved / waiting / pending items
- who / which / how many style questions
- access lookups
- date-bounded results
- competitor/comparable lists when backed by approved comparable signals

These requests go to the relevant specialist with approved SQL templates.

### Route by knowledge/semantic capability when the user asks for:

- property facts
- tone or style guidance
- FAQ-like questions
- recommendation questions
- media suitability
- event-aware content ideas
- reply guidance

These requests go to the relevant specialist with approved vector/semantic retrieval and optional SQL support.

### Ask for clarification when:

- no client or property can be inferred
- the time range is missing for a timeline question
- multiple likely entities match
- the user asks for unsupported analytics or actions

### Use schema intelligence when:

- the question does not match an existing capability exactly
- the answer may require a new join path
- a new table family appears in the DB dictionary
- the user asks a business question that can be answered from approved data, but not from an existing route

In the current POC, schema intelligence should propose the route and ask for implementation/evaluation before executing arbitrary new SQL. In production, this becomes a safe read-only SQL compiler with allow-listed schemas, row limits, tenant scope, and query review.

## Database Routing Rules

### Exact-data retrieval tables

- `jx_bridge.messages`
- `jx_bridge.thread_triage`
- `jx_bridge.alerts`
- `jx_bridge.alert_replies`
- `clients.clients`
- `clients.clients_collaborators`
- `content.content_topic`
- `content.content_topic_post`
- `content.content_post_status`
- `content.content_topic_post_media`
- `media.media`
- `users.users`
- `organizations.organizations`

### Knowledge/semantic retrieval tables

- `clients.client_notes`
- `clients.property_details`
- `clients.client_details`
- `clients.client_tone_of_voice_settings`
- `clients.client_target_audience`
- `clients.client_target_audience_suggestions`
- `content.exemplar_posts`
- `media.media_analysis_ai`
- `general.events`
- `general.knowledge_embeddings`
- `analytics.metric_embeddings`

## Safety Rules

This POC is read-only only.

### Hard rules

- no write actions
- no draft submission to external systems
- no reply sending
- no alert creation
- no data mutation
- no unscoped data access

### Retrieval rules

- local dummy DB first, live read-only DB second
- specialist agents must use approved query plans
- specialist agents must cite source traces in metadata
- knowledge embeddings and metric embeddings are generated offline, never during chat
- all agent results should surface confidence and route rationale in the UI

## UI Behavior

The POC UI should make the agent system visible and understandable.

### UI goals

- feel like a modern product, not a debugging console
- show the user which agent handled the question
- show routing rationale
- show the tables or knowledge sources used
- show a SQL preview for structured questions
- show source cards for knowledge questions

### Main UI sections

1. Left rail
   - product summary
   - POC goals
   - agent definitions
   - sample queries

2. Main conversation area
   - user input
   - routed agent response
   - answer summary
   - suggested follow-up prompts

3. Right trace panel
   - active route
   - agent-by-agent timeline
   - SQL plan or knowledge sources
   - context confidence
   - safety status
   - current mode: local dummy DB or live read-only DB

## POC Architecture

### Frontend

- proper React/Vite app in `frontend/`
- clean conversational UX with source and safety trace panel
- calls POC backend endpoints

### Backend

- FastAPI POC endpoints under `/api/agent-poc/*`
- local dummy DB and live DB adapters behind the same contracts
- specialist-agent runtime, context merger, safety review, and audit metadata

## POC API Contract

Recommended endpoints for the first version:

- `GET /api/agent-poc/config`
- `POST /api/agent-poc/chat`

## Phase Plan

### Phase 1

- enforce read-only infrastructure
- define the six-agent runtime
- build the UI shell

### Phase 2

- build shared intake pipeline
- resolve entities, scope, intent, and dates

### Phase 3

- build approved SQL/vector retrievers
- document join maps and source traces

### Phase 4

- build the Orchestrator Agent
- centralize capability-state routing

### Phase 5-9

- build the five specialist agents
- merge context and score confidence
- add answer safety
- expose trace UI
- run evaluation scorecards

## Success Criteria

The POC is successful if:

1. a user can ask a structured question and see it routed to the correct specialist
2. a user can ask a property or recommendation question and see grounded evidence
3. the UI clearly explains what happened
4. the system stays read-only
5. the architecture is clean enough to replace local dummy data with live read-only DB logic later
