# DB Dictionary

## Snapshot

- Source: live PostgreSQL schema inspection through the existing SSH tunnel
- Snapshot date: `July 16, 2026`
- Purpose: freeze the phase 0 source contract for the read-only intelligence assistant

Important note:

- this is a `user-facing assistant dictionary`, not a raw dump of every internal table
- sensitive and internal-only tables are listed separately in [read_only_exposure_list.md](./read_only_exposure_list.md)

---

## Schema Summary

| Schema | Role in assistant | Key observation |
|---|---|---|
| `clients` | core knowledge and scoping | strongest source for client profile, notes, tone, and audience |
| `content` | workflow and authored post data | strong for planning, scheduling, and post history |
| `media` | visual intelligence | strongest semantic retrieval domain |
| `jx_bridge` | inbox and reputation | strong thread, triage, alert, and guest-message domain |
| `general` | reference and events | supports network lookup and event-aware planning |
| `world` | geography reference | supports client and event location context |
| `users` | access and identity | usable for access explanations, not for direct exposure of session data |
| `organizations` | ownership and scope | needed for tenant and client ownership joins |
| `entity` | brand/entity relationships | useful for later graph-style reasoning |
| `analytics` | limited performance snapshots | partially usable for post-level performance, not for broad analytics claims |

---

## Identity and Access Domain

| Table | Approx rows | Exposure | Purpose |
|---|---:|---|---|
| `users.users` | 31 | `secondary` | user identity for access explanations |
| `users.users_roles` | 31 | `secondary` | role lookup |
| `organizations.organizations` | 258 | `secondary` | organization ownership |
| `organizations.organization_users` | 48 | `secondary` | organization membership |
| `clients.clients` | 519 | `primary` | client master table and tenant boundary |
| `clients.clients_collaborators` | 46 | `primary` | explicit user-to-client access mapping |

---

## Client Knowledge Domain

| Table | Approx rows | Exposure | Purpose |
|---|---:|---|---|
| `clients.client_details` | 558 | `primary` | client context and metadata |
| `clients.property_details` | 56 | `primary` | property facts, amenities, overview, policies |
| `clients.client_notes` | 45 | `primary` | FAQs, operational notes, reusable response notes |
| `clients.client_tone_of_voice_settings` | 311 | `primary` | tone, use/avoid words, guidelines |
| `clients.client_target_audience` | 1382 | `primary` | audience rows |
| `clients.client_target_audience_suggestions` | 1547 | `secondary` | suggested audiences and expansion ideas |
| `clients.client_social_network_account` | 199 | `primary` | account mapping between client and platform identity |
| `clients.client_social_network_cadence` | 1480 | `secondary` | publishing cadence targets |
| `clients.client_content_pillars` | 194 | `secondary` | planning structure |
| `clients.client_metric_goals` | 132 | `secondary` | sparse goal records, not primary analytics evidence |
| `clients.client_marketing_settings` | 0 | `secondary` | schema exists for property type, conversion, average default rate, and length of stay, but live table is empty |

Competitor schema finding from July 20, 2026:

- no explicit `competitors`, `competitor_set`, `comp_set`, or `client_competitors` table was found in the live schema
- `clients.client_marketing_settings` is the closest adjacent schema, but it currently has zero rows in live PostgreSQL
- competitor answers should therefore be treated as inferred comparable-market answers unless an official competitor source is added later

---

## Inbox and Reputation Domain

| Table | Approx rows | Exposure | Purpose |
|---|---:|---|---|
| `jx_bridge.messages` | 2285 | `primary` | guest messages and thread text |
| `jx_bridge.messages_metadata` | 2285 | `primary` | enriched message metadata and embeddings |
| `jx_bridge.interactions` | 438 | `primary` | interaction-level thread records |
| `jx_bridge.thread_triage` | 322 | `primary` | triage and escalation state |
| `jx_bridge.alerts` | 116 | `primary` | alert history for explanation |
| `jx_bridge.alert_replies` | 24 | `primary` | property-response history |
| `jx_bridge.messages_ai_suggestions` | 2955 | `secondary` | prior reply-suggestion history |
| `jx_bridge.guest_notes` | 34 | `secondary` | guest note context |
| `jx_bridge.user_actions` | 1937 | `secondary` | operator action history |
| `inbox.monitor_group` | 22 | `secondary` | monitoring structure |
| `inbox.monitor_group_client` | 53 | `secondary` | group-to-client mapping |
| `inbox.monitor_group_user` | 25 | `secondary` | group-to-user mapping |
| `inbox.monitoring_schedule` | 14 | `secondary` | monitoring schedule data |

---

## Content Workflow Domain

| Table | Approx rows | Exposure | Purpose |
|---|---:|---|---|
| `content.content_topic` | 1614 | `primary` | client topics and content planning anchor |
| `content.content_topic_post` | 3738 | `primary` | authored posts, captions, channels, status |
| `content.content_topic_post_media` | 3906 | `primary` | post-to-media linkage |
| `content.content_post_status` | 9 | `reference` | workflow state values |
| `content.content_topic_post_type` | 5 | `reference` | post type values |
| `content.content_topic_post_approval_status` | 6658 | `secondary` | approval trail |
| `content.content_topic_post_comment` | 26 | `secondary` | comments on post workflow |
| `content.content_topic_post_edit_history` | 3127 | `secondary` | edit history |
| `content.content_pillar` | 37 | `reference` | pillar taxonomy |
| `content.exemplar_posts` | 34 | `secondary` | style and tone references |
| `content.ai_planner_preferences` | 3 | `secondary` | sparse planning preferences |

---

## Media and Visual Intelligence Domain

| Table | Approx rows | Exposure | Purpose |
|---|---:|---|---|
| `media.media` | 2380 | `primary` | media catalog |
| `media.media_analysis_ai` | 2308 | `primary` | semantic descriptions, tags, embeddings |
| `media.media_asset` | 2600 | `secondary` | physical asset metadata |
| `media.media_type` | 2 | `reference` | media type lookup |
| `media.media_status` | 2 | `reference` | media status lookup |
| `media.media_tags` | 74 | `secondary` | manual tag support |
| `media.edited_media` | 43 | `internal` | edit lineage, not a first-wave assistant source |

---

## Events and Geography Domain

| Table | Approx rows | Exposure | Purpose |
|---|---:|---|---|
| `general.events` | 3836 | `primary` | event and local context |
| `general.social_network_type` | 12 | `reference` | channel lookup |

## Derived Embedding Read Models

These are POC read-model tables generated from approved source tables. They are not source-of-truth transactional tables.

| Table | Exposure | Purpose |
|---|---|---|
| `general.knowledge_embeddings` | `primary read model` | property notes, FAQs, property details, tone, audience, media analysis, and post copy embeddings |
| `analytics.metric_embeddings` | `primary read model` | post metric-context embeddings for performance and engagement language |
| `general.timezone` | 425 | `reference` | time normalization |
| `world.cities` | 154223 | `reference` | city resolution |
| `world.states` | 5308 | `reference` | state resolution |
| `world.countries` | 250 | `reference` | country resolution |
| `entity.entity` | 434 | `secondary` | entity root table for brand relationships |
| `entity.entity_facility_brand` | 631 | `secondary` | brand mapping |
| `entity.entity_facility_sub_brand` | 1074 | `secondary` | sub-brand mapping |

---

## Analytics Snapshot Domain

| Table | Approx rows | Exposure | Purpose |
|---|---:|---|---|
| `analytics.social_media_post` | 581 | `primary_limited` | network-specific JSON snapshots for some published posts |
| `analytics.linkedin_geo_display_name` | 11 | `reference` | LinkedIn location label lookup |

Important notes:

- `analytics.social_media_post` is usable for `limited post-level performance intelligence`
- it is not a normalized warehouse fact table
- metrics are stored inside `json_value`
- current observed network coverage is:
  - `facebook`: `385`
  - `instagram_graph`: `150`
  - `linkedin`: `46`
- content-to-analytics join coverage is partial:
  - `facebook`: `103 / 128` posts with refs matched
  - `instagram_graph`: `45 / 166`
  - `linkedin`: `16 / 37`
  - `twitter`: `0 / 69`
  - `tiktok`: `0 / 2`

Conclusion:

- allow post-level performance answers only when the exact post and analytics row can be resolved
- do not treat this domain as a general-purpose analytics warehouse

---

## Phase 0 Contract Decisions

### Primary sources for phase 1 assistant work

- `clients.*`
- `content.*`
- `media.*`
- `jx_bridge.*`
- `general.events`
- `general.social_network_type`
- `world.*`
- `users.users`
- `users.users_roles`
- `organizations.*`
- `entity.*`
- `analytics.social_media_post` with partial-support caveats

### Sparse or conditional sources

- `clients.client_metric_goals`
- `content.ai_planner_preferences`
- `analytics.social_media_post`

### Internal or restricted sources

See [read_only_exposure_list.md](./read_only_exposure_list.md).
