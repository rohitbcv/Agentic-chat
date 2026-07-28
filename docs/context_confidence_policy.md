# Context Merger and Confidence Policy

This document is the Phase 6 grounding contract.

## Ranking Rules

| Evidence type | Trust priority | Use for |
| --- | --- | --- |
| Exact SQL rows | highest | counts, statuses, dates, schedules, access, exact metrics |
| Property notes/details | high | FAQs, amenities, policies, summaries |
| Tone/audience rows | high | brand voice and target audience questions |
| Metric embeddings | supporting | matching user language like engagement/performance to metric context |
| Media analysis chunks | supporting | visual search, campaign fit, media context |

## Confidence Labels

| Label | Score range | Meaning |
| --- | --- | --- |
| `high` | `0.80+` | Exact route with scoped evidence or confident policy refusal |
| `medium` | `0.55-0.79` | Useful answer with partial or semantic evidence |
| `low` | `<0.55` | Missing scope, missing evidence, contradiction, or unsupported request |

## SQL Zero Rows

For exact SQL routes, zero rows is still useful evidence.

Example:

`What posts are scheduled next week for client 553?`

If the approved schedule SQL returns zero rows for the client and date window, the assistant can say no scheduled posts were found. That is different from a semantic knowledge miss.

## Partial Analytics

Post performance remains `partially_supported` unless all of these are true:

- the post resolves to one client-scoped `content.content_topic_post`
- a network reference joins to `analytics.social_media_post`
- at least one normalized metric exists
- the answer stays scoped to that post and network snapshot

The assistant must not generalize from one snapshot into broad performance diagnosis.

## Missing Scope

The assistant asks a follow-up when any required scope is missing:

- client or property name
- client ID
- city for event-only questions
- date window when the route truly requires one

## Contradictions

If retrieved rows or matches point to a different `client_id` than the resolved scope, the answer is downgraded to `grounding_gap` and should not be trusted until reviewed.
