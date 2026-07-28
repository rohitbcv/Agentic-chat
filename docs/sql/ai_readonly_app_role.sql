-- ai_readonly_app_role.sql
--
-- Purpose:
--   Template role for the read-only intelligence assistant layer.
--
-- Important:
--   1. Review object names with your DBA before applying.
--   2. This script is intentionally not executed automatically by the repo.
--   3. Replace the password placeholder using your secrets workflow.

BEGIN;

CREATE ROLE ai_readonly_app
LOGIN
PASSWORD 'REPLACE_WITH_SECRET'
NOSUPERUSER
NOCREATEDB
NOCREATEROLE
NOINHERIT;

GRANT CONNECT ON DATABASE soho TO ai_readonly_app;

GRANT USAGE ON SCHEMA
  clients,
  content,
  media,
  jx_bridge,
  general,
  world,
  users,
  organizations,
  entity,
  analytics
TO ai_readonly_app;

GRANT SELECT ON TABLE
  clients.clients,
  clients.clients_collaborators,
  clients.client_details,
  clients.property_details,
  clients.client_notes,
  clients.client_tone_of_voice_settings,
  clients.client_target_audience,
  clients.client_target_audience_suggestions,
  clients.client_content_pillars,
  clients.client_social_network_account,
  clients.client_social_network_cadence,
  clients.client_metric_goals,
  content.content_topic,
  content.content_topic_post,
  content.content_topic_post_media,
  content.content_post_status,
  content.content_topic_post_type,
  content.content_topic_post_approval_status,
  content.content_topic_post_comment,
  content.content_topic_post_edit_history,
  content.content_pillar,
  content.exemplar_posts,
  content.ai_planner_preferences,
  media.media,
  media.media_analysis_ai,
  media.media_asset,
  media.media_type,
  media.media_status,
  media.media_tags,
  jx_bridge.interactions,
  jx_bridge.messages,
  jx_bridge.messages_metadata,
  jx_bridge.thread_triage,
  jx_bridge.alerts,
  jx_bridge.alert_replies,
  jx_bridge.guest_notes,
  jx_bridge.user_actions,
  jx_bridge.messages_ai_suggestions,
  inbox.monitor_group,
  inbox.monitor_group_client,
  inbox.monitor_group_user,
  inbox.monitoring_schedule,
  general.events,
  general.knowledge_embeddings,
  general.social_network_type,
  general.timezone,
  world.cities,
  world.states,
  world.countries,
  users.users,
  users.users_roles,
  organizations.organizations,
  organizations.organization_users,
  entity.entity,
  entity.entity_facility_brand,
  entity.entity_facility_sub_brand,
  analytics.metric_embeddings,
  analytics.social_media_post,
  analytics.linkedin_geo_display_name
TO ai_readonly_app;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
ON ALL TABLES IN SCHEMA
  clients,
  content,
  media,
  jx_bridge,
  general,
  world,
  users,
  organizations,
  entity,
  analytics
FROM ai_readonly_app;

COMMIT;
