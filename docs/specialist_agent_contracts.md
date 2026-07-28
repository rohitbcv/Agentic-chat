# Specialist Agent Contracts

This document is the Phase 5 implementation contract for the read-only multi-agent assistant.

## Hard Rule

Every specialist agent is read-only.

- no agent receives write credentials
- no agent can call mutable app APIs
- no agent can approve, publish, send, assign, update, delete, grant, or revoke
- every agent can only call approved retriever services

## Agent Contracts

| Agent | Primary job | Retrieval modes | Approved table families | Write tools |
| --- | --- | --- | --- | --- |
| Inbox and Complaint Agent | Threads, complaints, triage, waiting-on-property state | `sql`, optional `vector` | `jx_bridge.messages`, `jx_bridge.interactions`, `jx_bridge.thread_triage`, `jx_bridge.alerts`, `jx_bridge.alert_replies` | disabled |
| Client Knowledge and FAQ Agent | Property facts, FAQs, tone, audience, policies | `vector`, optional `sql` | `general.knowledge_embeddings`, `clients.client_notes`, `clients.property_details`, `clients.client_details`, tone and audience tables | disabled |
| Content Planning Agent | Schedules, approvals, captions, post copy/media detail, limited post performance | `sql`, optional `vector` | `content.*`, `analytics.social_media_post`, `analytics.metric_embeddings`, related media analysis | disabled |
| Media Discovery Agent | Media search and asset fit explanation | `vector`, optional `sql` | `general.knowledge_embeddings`, `media.media`, `media.media_analysis_ai`, content-to-media bridge tables | disabled |
| Access and Relationship Agent | Collaborators, organization, city, event, competitor/comparable, relationship path questions | `sql`, derived graph SQL | users, organizations, clients, marketing settings, property details, audience, entities, events, cities | disabled |

## Runtime Isolation

The API now runs:

1. `Orchestrator Agent` decides the capability and next specialist.
2. `Specialist Agent` validates allowed modes and table families.
3. Approved retrievers execute read-only SQL or semantic retrieval.
4. Source traces are returned with row counts and join paths.
5. Context merger and safety layer decide final confidence and support state.

## Content Planning Performance Rule

For questions like `how is my last Instagram post performing?`, the Content Planning Agent must combine:

- `content.content_topic_post` for resolved post metadata and caption
- `analytics.social_media_post` for exact available metrics
- `content.content_topic_post_media` for attached media IDs
- `media.media_analysis_ai` for related media context
- `analytics.metric_embeddings` for optional metric semantic matching

Exact numeric values always come from SQL, not embeddings.

## Competitor / Comparable Rule

For questions like `who are competitors of Hotel Ramtin?`, the Access and Relationship Agent must use `competitor_lookup`.

- the live schema inspection found no official competitor-set table
- `clients.client_marketing_settings` exists but has zero rows in live data
- the dummy DB seeds `clients.client_marketing_settings` so the POC can demonstrate inferred comparable-market answers
- answers must say `likely comparables` or `inferred comparable set`, not confirmed official competitors
- if no comparable rows exist, the agent must say it cannot verify competitors from approved data
