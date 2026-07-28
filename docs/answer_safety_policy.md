# Answer and Safety Policy

This document is the Phase 7 answer-generation and safety contract.

## Answer Rules

The assistant may answer only from:

- approved SQL template output
- approved vector/semantic retrieval output
- documented support limitations
- read-only refusal policy

The assistant must not invent:

- hotel rates or live booking prices
- missing amenities
- broad ROI or revenue attribution
- unpublished analytics conclusions
- access grants or ownership changes

## Main Chat Answer

The main answer should be clean and operator-friendly.

Do not include debug artifacts in the answer text:

- table names
- SQL templates
- route explanations
- suggested debug questions

Those details belong in the trace panel.

## Safety Statuses

| Status | Meaning |
| --- | --- |
| `passed` | Evidence and read-only policy are acceptable |
| `needs_clarification` | Required scope is missing |
| `grounding_gap` | Retrieval did not support a factual answer |
| `read_only_refusal` | User asked for a write-like action |

## Read-Only Refusal

For write-like requests, the assistant can explain recommended manual next steps, but it cannot execute.

Blocked verbs include:

- send
- approve
- publish
- assign
- create
- update
- delete
- edit
- grant
- revoke

## Audit Event

Each response returns a response-only audit event with:

- query
- resolved client
- intent
- capability
- selected specialist
- confidence
- support state
- safety state

The audit event is not persisted by the POC because persistence would be a write path.
