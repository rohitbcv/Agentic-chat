# Join Map Catalog

This file documents the canonical relational paths that the read-only assistant is allowed to use first.

## Principles

- use relational joins before graph materialization
- keep each join map tied to a business question family
- prefer short, explainable paths
- attach source traces to every retrieval

## Join Maps

### `client_access`

Question family:

- ownership
- collaborator access
- client scope

Path:

1. `clients.clients`
2. `clients.clients_collaborators`
3. `users.users`
4. `organizations.organization_users`

Key idea:

- the client is the scope anchor
- collaborators attach directly to the client
- organization membership is supporting evidence, not the primary answer

### `competitor_lookup`

Question family:

- competitors
- competitive set
- comparable properties
- similar hotels

Path:

1. `clients.clients`
2. `world.cities`
3. `clients.client_marketing_settings`
4. `clients.property_details`
5. `clients.client_target_audience`

Key idea:

- the live schema does not expose an official competitor-set table
- `clients.client_marketing_settings` exists, but the live table is currently empty
- the dummy DB uses this path to infer likely comparables from same city, property type, rate band, audience, and property context
- answers must say "likely comparables" unless an official competitor source is later added

### `content_schedule`

Question family:

- scheduled posts
- calendar lookups
- network distribution

Path:

1. `clients.clients`
2. `content.content_topic`
3. `content.content_topic_post`
4. `general.social_network_type`

Key idea:

- `content_topic` provides the client-to-post bridge
- `content_topic_post` provides timing, status, network reference, and post copy

### `content_approval`

Question family:

- drafts
- approval queues
- rejection history

Path:

1. `clients.clients`
2. `content.content_topic`
3. `content.content_topic_post`
4. `content.content_topic_post_approval_status`
5. `content.content_post_status`

Key idea:

- approval is not just the current post status
- approval history rows provide timeline evidence

### `content_post_detail`

Question family:

- latest post copy
- media attached to a post
- channel-specific post detail lookup

Path:

1. `clients.clients`
2. `content.content_topic`
3. `content.content_topic_post`
4. `content.content_topic_post_media`
5. `media.media`
6. `media.media_analysis_ai`
7. `general.social_network_type`

Key idea:

- resolve the latest matching post first
- then join the media bridge to return only media actually used by that post
- use media analysis as supporting context, not as a replacement for the post copy

### `content_performance`

Question family:

- latest post performance
- post analytics
- post copy plus media plus engagement

Path:

1. `clients.clients`
2. `content.content_topic`
3. `content.content_topic_post`
4. `content.content_topic_post_media`
5. `analytics.social_media_post`
6. `media.media_analysis_ai`

Key idea:

- resolve the authored post first
- then join analytics by `network_post_ref`, `post_ref`, or `identifier`
- treat media context as supporting evidence around the same post

### `inbox_threads`

Question family:

- complaints
- unresolved threads
- waiting on property

Path:

1. `clients.clients`
2. `jx_bridge.interactions`
3. `jx_bridge.messages`
4. `jx_bridge.thread_triage`
5. `jx_bridge.alerts`
6. `jx_bridge.alert_replies`

Key idea:

- `interactions` gives the thread anchor
- `messages` gives the factual conversation evidence
- triage and alert tables explain operational state

### `event_lookup`

Question family:

- nearby events
- city-linked event lookups

Path:

1. `clients.clients`
2. `world.cities`
3. `general.events`

Key idea:

- client geography is the bridge to the event domain

### `property_knowledge`

Question family:

- FAQ
- amenities
- property details
- general grounded client knowledge

Path:

1. `clients.clients`
2. `clients.client_notes`
3. `clients.property_details`
4. `clients.client_details`

Key idea:

- this is a blended knowledge path
- structured scope comes from the client
- answer evidence comes from approved text-bearing tables

### `media_semantic`

Question family:

- find suitable media
- connect visuals to campaign themes

Path:

1. `media.media`
2. `media.media_analysis_ai`
3. `content.content_topic_post_media`

Key idea:

- media analysis carries the semantic payload
- the post-media bridge helps connect media to actual content usage later

## When To Add A Graph Layer

Add graph materialization only after:

1. the join maps above are stable
2. SQL template coverage is trusted
3. vector retrieval coverage is trusted
4. multi-hop questions clearly exceed explainable SQL joins
