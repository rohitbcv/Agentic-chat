# Read-Only Exposure List

## Purpose

This file defines what the intelligence assistant may read, what it may reason over, and what must not be exposed directly.

All entries assume:

- `SELECT` only
- no mutation privileges
- no raw secret disclosure
- no unrestricted tenant access

---

## 1. Allowed Read Domains

### Orchestrator Agent

May read:

- no raw tables directly by default
- only routing metadata, capability registry, and scoped resolver outputs

### Inbox and Complaint Agent

Allowed:

- `jx_bridge.messages`
- `jx_bridge.messages_metadata`
- `jx_bridge.interactions`
- `jx_bridge.thread_triage`
- `jx_bridge.alerts`
- `jx_bridge.alert_replies`
- `jx_bridge.guest_notes`
- `jx_bridge.user_actions`
- `inbox.monitor_group`
- `inbox.monitor_group_client`
- `inbox.monitor_group_user`
- `inbox.monitoring_schedule`
- `clients.client_notes`
- `clients.property_details`

### Client Knowledge and FAQ Agent

Allowed:

- `clients.clients`
- `clients.client_details`
- `clients.property_details`
- `clients.client_notes`
- `clients.client_tone_of_voice_settings`
- `clients.client_target_audience`
- `clients.client_target_audience_suggestions`
- `general.knowledge_embeddings`
- `general.timezone`
- `world.cities`
- `world.states`
- `world.countries`

### Content Planning Agent

Allowed:

- `content.content_topic`
- `content.content_topic_post`
- `content.content_post_status`
- `content.content_topic_post_type`
- `content.content_topic_post_approval_status`
- `content.content_topic_post_comment`
- `content.content_topic_post_edit_history`
- `clients.client_content_pillars`
- `clients.client_social_network_cadence`
- `clients.client_social_network_account`
- `general.social_network_type`
- `general.events`
- `analytics.social_media_post`
- `analytics.metric_embeddings`
- `general.knowledge_embeddings`

### Media Discovery Agent

Allowed:

- `media.media`
- `media.media_analysis_ai`
- `media.media_asset`
- `media.media_type`
- `media.media_status`
- `media.media_tags`
- `content.content_topic_post_media`
- `content.content_topic_post_media_tags`
- `general.knowledge_embeddings`

### Access and Relationship Agent

Allowed:

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

---

## 2. Restricted but Possibly Derived

These should not be exposed raw unless the answer truly requires them and the output is compacted:

- `jx_bridge.messages_ai_suggestions`
- `jx_bridge.user_actions`
- `content.content_topic_post_edit_history`
- `content.content_topic_post_comment`
- `clients.client_metric_goals`

Rule:

- summarize
- do not dump raw rows unless explicitly needed

---

## 3. Do-Not-Expose Tables

These are outside the assistant exposure contract for phase 0 and phase 1.

### Secrets and auth-like data

- `clients.client_access_keys`
- `general.auth_data_storage`
- `general.twitter_oauth_temp`
- `users.email_otp_verification`

### Session and invitation internals

- `users.user_sessions`
- `users.invited_users`

### Internal file and attachment internals

- `jx_bridge.alert_reply_attachments`

### Legacy or product-internal operational tables

- `inbox.legacy_inbox_stream`
- `inbox.legacy_inbox_stream_subscriptions`
- `inbox.legacy_inbox_stream_type`
- `inbox.out_of_office`

### Admin-only or currently irrelevant for assistant answers

- `ad.ad_account`
- `clients.client_report_definition`
- `clients.client_report_definition_detail`

Reason:

- secret-bearing
- not user-facing
- not needed for answer generation
- high risk of accidental leakage

---

## 4. Conditional Analytics Exposure

`analytics.social_media_post` is allowed with strict conditions:

- only for a resolved client in scope
- only for a resolved post or account mapping
- only for network-supported snapshot questions
- only with explicit support-state labeling

Do not use it for:

- ROI claims
- cross-channel trend diagnosis
- performance benchmarking across the business
- revenue attribution

---

## 5. Exposure Rules

For every retrieval:

1. resolve tenant scope first
2. resolve client scope second
3. resolve domain capability third
4. query only approved tables
5. compact output before returning it to the LLM or the user
