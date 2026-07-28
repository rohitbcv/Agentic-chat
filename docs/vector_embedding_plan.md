# Vector Embedding Plan

This file defines the approved embedding strategy for the read-only intelligence assistant.

## Current Phase

The current implementation uses stored OpenAI embeddings for approved read-only semantic chunks, with deterministic lexical ranking as fallback.

That fallback is intentional for the POC because it keeps retrieval:

- deterministic
- explainable
- read-only
- easy to audit against the schema

Embeddings are added on top of the same approved source list, not on top of arbitrary tables.

The local POC keeps two embedding stores separate:

- `general.knowledge_embeddings` for property notes, FAQs, property details, tone, audience, media analysis, and post copy
- `analytics.metric_embeddings` for metric-context documents only

## Best Embedding Sources

| Priority | Table | Why It Should Be Embedded | Example Questions It Supports | Required Metadata |
| --- | --- | --- | --- | --- |
| 1 | `clients.client_notes` | richest operational knowledge, FAQ fragments, service notes, brand guidance | does this property have a pool, what are the smoking rules, what should we tell guests | `client_id`, `note_type`, timestamps |
| 2 | `clients.property_details` | structured but text-heavy property facts like amenities, overview, location, F&B details | what amenities do we have, where is the hotel located, what is the breakfast setup | `client_id`, section label, timestamps |
| 3 | `clients.client_details` | high-level contextual and metadata-backed client profile knowledge | what do we know about this property, summarize this client | `client_id`, source label, timestamps |
| 4 | `clients.client_tone_of_voice_settings` | best source for voice, wording, and brand-expression guidance | what tone should we use, which words should we avoid | `client_id`, field name, timestamps |
| 5 | `clients.client_target_audience` | direct audience statements for brand and content answers | who are we targeting, who is the audience for this client | `client_id`, `is_custom`, timestamps |
| 6 | `media.media_analysis_ai` | best semantic source for media discovery because it contains tags, alt text, keywords, and copy context | find media for a wedding campaign, show visuals that fit wellness or luxury | `client_id` via media join, `media_id`, tags, timestamps |
| 7 | `content.content_topic_post.post_text` | useful for post-copy similarity, campaign memory, and content clustering | find similar captions, how did recent posts talk about this theme | `client_id` via topic join, `post_id`, network, timestamps |
| 8 | `jx_bridge.messages.content` and approved translations | useful later for complaint clustering, FAQ mining, and guest-intent grouping | what are guests repeatedly complaining about, what questions recur most often | `client_id`, `interaction_id`, channel, timestamps |
| 9 | `analytics.metric_embeddings` | semantic read model for metric context, aliases, and post-performance language | how is the last Instagram post performing, show engagement context for the latest post | `client_id`, source table, source PK, metric names, model |
| 10 | `general.knowledge_embeddings` | generated read model for approved knowledge, media, and post-copy text | property FAQ, tone, audience, media search, similar captions | `client_id`, source table, source PK, domain, model |

## What Not To Embed First

Do not start with:

- access-control tables
- approval-status rows without supporting text
- raw analytics JSON without normalized metric extraction
- raw metric numbers as the answer source
- every table in the schema

Those sources are better handled with SQL first.

## Chunking Strategy

### Property knowledge chunks

Chunk separately by:

- note
- property details section
- client details section
- tone settings record
- audience row

Chunk size target:

- 300 to 800 tokens equivalent per chunk

Overlap:

- minimal overlap
- preserve section boundaries over arbitrary sliding windows

### Media chunks

Build one semantic document per media asset from:

- media name
- description
- short description
- alt text
- visual tags
- descriptive tags
- semantic keywords
- related post copy when available

### Content chunks

Build one semantic document per post from:

- post text
- topic name
- network
- optional related media summaries

## Retrieval Filters

Every vector lookup must enforce:

1. `client_id` scope first
2. table allow-list second
3. deleted-row exclusion third

Do not run semantic search across the whole database without client scope.

## Production Embedding Metadata

Each embedding row should carry:

- `client_id`
- source table
- source primary key
- chunk label
- inserted timestamp
- updated timestamp
- deleted flag or deletion snapshot
- access domain

## Where Embeddings Help Most

Use embeddings for:

- FAQ and property fact grounding
- tone and audience guidance
- semantic media search
- similarity across post copy
- clustering repeated guest questions

Do not use embeddings as the first answer path for:

- counts
- statuses
- approvals
- schedules
- access
- hard metrics

For hard metrics, embed only metric-context documents. Exact values and calculations must still come from SQL.

## Production Upgrade Path

1. keep the current chunk model and metadata contract
2. replace lexical ranking with embedding lookup on the same source set
3. keep SQL as the first route for exact questions
4. add hybrid reranking only after baseline behavior is stable

## Local Generation Commands

```bash
python3 scripts/create_knowledge_embeddings.py --dry-run
python3 scripts/create_knowledge_embeddings.py
python3 scripts/create_metric_embeddings.py --dry-run
python3 scripts/create_metric_embeddings.py
```
