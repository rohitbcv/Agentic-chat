# SQL Template Catalog

This catalog lists the approved Phase 3 SQL templates that the Phase 4 orchestrator is allowed to call.

## Rules

- all templates are read-only
- every template must apply client scope
- answers must come only from approved tables
- no dynamic free-form SQL generation is allowed in Phase 3 or Phase 4

## Template Summary

| Template Key | Primary Intent | Main Tables | Join Map | Result Shape | Support State |
| --- | --- | --- | --- | --- | --- |
| `client_access_lookup` | access and collaborator questions | `clients.clients`, `clients.clients_collaborators`, `users.users`, `organizations.organization_users` | `client_access` | collaborator rows by client | full |
| `competitor_lookup` | inferred competitor or comparable-set questions | `clients.clients`, `clients.client_marketing_settings`, `clients.property_details`, `clients.client_target_audience`, `world.cities` | `competitor_lookup` | likely comparable clients by city, property type, rate band, and audience | partial |
| `content_schedule_lookup` | scheduled or upcoming posts | `content.content_topic_post`, `content.content_topic`, `content.content_post_status`, `general.social_network_type` | `content_schedule` | post schedule rows | full |
| `content_approval_lookup` | drafts and approval state | `content.content_topic_post`, `content.content_topic`, `content.content_topic_post_approval_status`, `content.content_post_status` | `content_approval` | approval workflow rows | full |
| `content_post_detail_lookup` | latest post copy and attached media | `content.content_topic_post`, `content.content_topic`, `content.content_topic_post_media`, `media.media`, `media.media_analysis_ai`, `general.social_network_type` | `content_post_detail` | one latest post plus media used | full |
| `post_performance_lookup` | latest post performance | `content.content_topic_post`, `content.content_topic`, `analytics.social_media_post`, `content.content_topic_post_media`, `media.media_analysis_ai` | `content_performance` | one latest post plus analytics snapshot | partial |
| `inbox_lookup` | inbox and complaint threads | `jx_bridge.interactions`, `jx_bridge.messages`, `jx_bridge.thread_triage`, `jx_bridge.alerts`, `jx_bridge.alert_replies` | `inbox_threads` | active thread rows | full |
| `event_lookup` | nearby or upcoming events | `clients.clients`, `world.cities`, `general.events` | `event_lookup` | upcoming event rows | full |

## Template Details

### `client_access_lookup`

Use when the user asks:

- who has access to this client
- who owns this account
- which collaborators can work on this property

Required filters:

- `client_id`
- `deleted_at IS NULL`
- collaborator enabled flags where available

Expected output:

- user id
- full name
- access level
- client name

### `competitor_lookup`

Use when the user asks:

- who are competitors of this hotel
- what is the competitive set
- show comparable properties for this client
- which similar hotels should we compare against

Required filters:

- `client_id`
- `deleted_at IS NULL`
- same city, matching property type, or similar average-default-rate band

Expected output:

- target client id and name
- likely comparable client id and name
- same-city signal
- same-property-type signal
- similar-rate-band signal
- comparable score

Known limitation:

- the live schema inspection did not find an official competitor-set table
- `clients.client_marketing_settings` exists but is currently empty in the live DB
- this route must describe results as inferred likely comparables, not confirmed official competitors

### `content_schedule_lookup`

Use when the user asks:

- what is scheduled next week
- what posts are upcoming
- what is on the content calendar

Required filters:

- `client_id`
- `deleted_at IS NULL`
- optional date window from intake

Expected output:

- post id
- topic name
- status
- social network
- scheduled datetime
- preview text

### `content_approval_lookup`

Use when the user asks:

- which posts are in draft
- what needs approval
- which items were rejected

Required filters:

- `client_id`
- `deleted_at IS NULL`
- approval-relevant statuses only

Expected output:

- post id
- topic name
- current status
- network
- approval timestamp
- rejection note if present

### `content_post_detail_lookup`

Use when the user asks:

- which media was used in the latest post
- what is the post copy or caption
- what media was attached to the last Instagram, TikTok, Facebook, or LinkedIn post

Required filters:

- `client_id`
- optional channel filter from intake
- published or already-posted time window

Expected output:

- latest matching post id
- topic name
- social network
- post datetime
- post copy
- attached media ids, names, and media analysis context

### `post_performance_lookup`

Use when the user asks:

- how is the last post performing
- how did our latest Instagram post do
- what engagement did the last post get

Required filters:

- `client_id`
- optional channel filter from intake
- published or already-posted time window

Expected output:

- latest resolved post
- network reference
- media ids
- analytics snapshot from `analytics.social_media_post`

Known limitation:

- analytics joins are network-specific and may be incomplete, so this route is `partially_supported`

### `inbox_lookup`

Use when the user asks:

- which complaints are unresolved
- how many active threads do we have
- what is waiting on property

Required filters:

- `client_id`
- unresolved or active message state
- optional complaint keyword heuristics

Expected output:

- interaction id
- title
- latest guest timestamp
- message count
- triage bucket
- latest preview

### `event_lookup`

Use when the user asks:

- what events are coming up
- what nearby festivals matter for this property
- what local events are relevant

Required filters:

- `client_id` or resolved city
- future dates only
- non-deleted client and event rows

Expected output:

- event id
- name
- date
- type
- location
- audience

## Guardrails

1. templates are enumerated in code and cannot be improvised at runtime
2. missing client scope must trigger clarification, not a broad scan
3. unsupported domains must refuse gracefully
