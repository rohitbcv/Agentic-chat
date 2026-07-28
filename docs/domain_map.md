# Domain Map

## Purpose

This file freezes the canonical relationship paths the intelligence assistant should use before any graph layer is introduced.

Phase 1 principle:

- use `relational join maps first`
- use `vector retrieval` for unstructured text
- add a `graph DB` only after the SQL and vector paths are stable

---

## 1. Canonical Join Paths

### Ownership and access

`organizations.organizations`
-> `clients.clients.organization_id`
-> `clients.clients`

`users.users`
-> `organizations.organization_users.user_id`
-> `organizations.organizations`

`users.users`
-> `clients.clients_collaborators.user_id`
-> `clients.clients`

### Client knowledge

`clients.clients`
-> `clients.client_details.client_id`
-> `clients.property_details.client_id`
-> `clients.client_notes.client_id`
-> `clients.client_tone_of_voice_settings.client_id`
-> `clients.client_target_audience.client_id`

### Inbox and complaint

`clients.clients`
-> `jx_bridge.interactions.client_id`
-> `jx_bridge.messages.interaction_id`
-> `jx_bridge.thread_triage.interaction_id`
-> `jx_bridge.alerts.message_id`
-> `jx_bridge.alert_replies.alert_id`

### Content workflow

`clients.clients`
-> `content.content_topic.client_id`
-> `content.content_topic_post.content_topic_id`
-> `content.content_topic_post_media.content_topic_post_id`

### Media workflow

`clients.clients`
-> `media.media.client_id`
-> `media.media_asset.media_id`
-> `media.media_analysis_ai.media_id`

### Content to media

`content.content_topic_post`
-> `content.content_topic_post_media.content_topic_post_id`
-> `media.media.id`
-> `media.media_analysis_ai.media_id`

### Content to event

`content.content_topic`
-> `general.events.id`

### Client to geography

`clients.clients.world_city_id`
-> `world.cities.id`
-> `world.states.id`
-> `world.countries.id`

---

## 2. Capability-Oriented Retrieval Map

The assistant should not rely on fixed question templates. It should resolve a question into one or more reusable capabilities.

### `client_scope_resolution`

Goal:

- determine allowed client scope for the user

Sources:

- `clients.clients`
- `clients.clients_collaborators`
- `organizations.organization_users`
- `users.users`

### `property_fact_lookup`

Goal:

- answer property and FAQ questions

Sources:

- `clients.client_notes`
- `clients.property_details`
- `clients.client_details`

Retrieval mode:

- `SQL + Vector`

### `thread_triage_explainer`

Goal:

- explain why a thread is waiting, escalated, or ready for reply

Sources:

- `jx_bridge.messages`
- `jx_bridge.thread_triage`
- `jx_bridge.alerts`
- `jx_bridge.alert_replies`
- optional `clients.client_notes`

Retrieval mode:

- `SQL`
- optional `Vector`

### `latest_post_resolution`

Goal:

- find the most recent relevant published or scheduled post

Sources:

- `content.content_topic`
- `content.content_topic_post`
- `general.social_network_type`

Retrieval mode:

- `SQL`

### `media_context_lookup`

Goal:

- attach related media and its semantics to a post or topic

Sources:

- `content.content_topic_post_media`
- `media.media`
- `media.media_analysis_ai`

Retrieval mode:

- `SQL + Vector`

### `post_performance_lookup`

Goal:

- attach available performance evidence to a specific published post

Sources:

- `content.content_topic_post`
- `clients.client_social_network_account`
- `analytics.social_media_post`
- `general.social_network_type`

Retrieval mode:

- `SQL`
- JSON extraction from analytics snapshots

Support level:

- `partially_supported`

### `event_fit_lookup`

Goal:

- link a client or topic to local events and audience fit

Sources:

- `clients.clients`
- `general.events`
- `clients.client_target_audience`
- `content.content_topic`

Retrieval mode:

- `SQL + Vector`
- optional `Graph` later

---

## 3. Example: “How is my last Instagram post performing?”

This is the key phase-0 reasoning test for the assistant.

### Step 1. Resolve the client

Use:

- authenticated scope
- explicit client name if present
- account mapping if needed

### Step 2. Resolve the latest Instagram post

Use:

- `content.content_topic`
- `content.content_topic_post`
- `general.social_network_type`

Condition:

- filter to `instagram_graph`

### Step 3. Resolve related media

Use:

- `content.content_topic_post_media`
- `media.media`
- `media.media_analysis_ai`

### Step 4. Resolve analytics evidence

Preferred join:

- `content.content_topic_post.network_post_ref`
-> `analytics.social_media_post.post_ref`

Fallback join:

- `analytics.social_media_post.identifier`
-> `clients.client_social_network_account.social_network_id`

### Step 5. Extract network-specific metrics

For `instagram_graph`, current JSON keys include:

- `caption`
- `like_count`
- `comments_count`
- `media_url`
- `permalink`
- `timestamp`

### Step 6. Merge and label support state

If:

- latest post is found
- analytics row is found
- media link is found

Then:

- answer as `partially_supported` or `fully_supported` depending on completeness

If analytics row is missing:

- answer with post copy and media context only
- label as `partially_supported`

If neither post nor analytics can be resolved:

- ask clarification or return `not_supported`

---

## 4. When a Graph DB Helps

Use a graph layer later when the question is:

- multi-hop
- explanation-heavy
- relationship-heavy
- cross-domain

Good future graph cases:

- “Which luxury-themed posts tied to London events also used indoor lounge visuals?”
- “Which clients under this organization have both active content and media but no target audience data?”
- “How are this client, entity, brand, event, post, and media connected?”

Not necessary for phase 1:

- latest post lookup
- property FAQ lookup
- approval status
- media attached to a post
- recent post performance snapshots

---

## 5. Phase 0 Join Map Decisions

### Required now

- access join map
- client knowledge join map
- inbox join map
- content/media join map
- content/performance join map
- client/event join map

### Deferred

- graph node schema
- graph sync jobs
- graph retriever
- multi-hop path ranking
