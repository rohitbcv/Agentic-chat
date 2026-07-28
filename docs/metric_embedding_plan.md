# Metric Embedding Plan

This document answers whether we should create embeddings on metrics.

## Short Answer

Yes, but not on raw numeric metric values as the source of truth.

Use embeddings for metric meaning and context.

Use SQL for exact metric values and calculations.

## What To Embed

Create embeddings for metric-context documents built from:

- client name and ID
- network
- post date
- post copy/caption
- normalized metric names and values
- aliases like `engagement`, `performance`, `interactions`, `reach`, `post analytics`
- related media summary when available

Example metric document:

```text
Client: Hotel Ramtin.
Network: instagram_graph.
Post date: 2026-07-17 10:00.
Caption: Hotel Ramtin shares dining moments in Chicago...
Available metric snapshot: likes=24, comments=4, reactions=9, shares=1.
Metric aliases: engagement, interactions, post performance, social analytics, latest post metrics.
```

## What Not To Embed

Do not use embeddings as the answer source for:

- exact like count
- exact comment count
- percentage change
- ranking by highest engagement
- time-series trend
- ROI
- revenue attribution

Those require normalized SQL fact tables or deterministic calculations.

## OpenAI Model

Use:

```env
OPENAI_EMBED_MODEL=text-embedding-3-large
```

The local script uses the OpenAI Embeddings API through the Python SDK.

## Local POC Storage

The dummy DB includes:

```text
analytics.metric_embeddings
```

The embedding rows store:

- `client_id`
- source table and primary key
- metric document
- metric names
- embedding model
- embedding vector JSON
- content hash
- timestamps

## Generate Local Metric Embeddings

After adding `OPENAI_API_KEY` to `.env`, run:

```bash
python3 scripts/create_metric_embeddings.py
```

Dry-run without calling OpenAI:

```bash
python3 scripts/create_metric_embeddings.py --dry-run
```

## Runtime Use

For a question like:

`how is my last instagram post performing?`

The route should:

1. use SQL to resolve the latest matching post
2. use SQL to fetch the analytics snapshot
3. use SQL to fetch related media context
4. optionally use metric embeddings to match query wording to metric/context documents
5. answer with exact available metrics from SQL only

## Production Note

Production should store embeddings in a dedicated read model or vector store maintained by an offline ETL job. The read-only agents should only read that store.
