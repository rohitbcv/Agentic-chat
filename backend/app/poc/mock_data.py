from __future__ import annotations

from typing import Any


MOCK_CLIENTS: list[dict[str, Any]] = [
    {"id": 7403, "name": "Hotel Ramtin", "city": "Chicago", "domain": "property + content + media + analytics"},
    {"id": 493, "name": "Hotel d'Angleterre", "city": "Geneva", "domain": "luxury property + content + inbox"},
    {"id": 382, "name": "hotel Yash", "city": "Jaipur", "domain": "inbox + access + property"},
    {"id": 328, "name": "Red Carnation Hotels Collection", "city": "London", "domain": "media + brand knowledge"},
]


SAMPLE_QUERIES: list[str] = [
    "What do we know about Hotel d'Angleterre?",
    "Does Hotel Ramtin have cab service?",
    "What is the tone of voice for Bihar Motel?",
    "Who is the target audience for Hotel Hafenresidenz?",
    "Who has access to hotel Yash?",
    "What active inbox threads are there for hotel Yash?",
    "What posts are scheduled for Hotel d'Angleterre?",
    "Which posts are waiting for approval for Hotel d'Angleterre?",
    "How is the last TikTok post performing for client 7403?",
    "In my last TikTok post, which media has been used and what is the post copy for client 7403?",
    "Who are likely competitors of Hotel Ramtin?",
    "Find media for Red Carnation Hotels Collection",
    "How is client 7403 connected to posts, media, metrics and events?",
    "What events are coming up for Hotel Ramtin?",
]


VALIDATION_SAMPLE_QUERIES: list[dict[str, str]] = [
    {
        "label": "Missing client → Stage 1 block",
        "query": "What active inbox threads are there?",
        "checks": "client_id required but absent → Decision blocked",
    },
    {
        "label": "Write action → Stage 1 warning",
        "query": "Send a reply to the guest for hotel Yash",
        "checks": "blocked write-action pattern detected → Decision warning",
    },
    {
        "label": "Unsupported capability → Stage 1 block",
        "query": "What is the room pricing for Hotel Ramtin?",
        "checks": "capability_state = not_supported → retrieval blocked",
    },
    {
        "label": "No client for content → Stage 1 block",
        "query": "What posts are scheduled this week?",
        "checks": "content_schedule_lookup requires client_id → Decision blocked",
    },
    {
        "label": "Clean path → both stages pass",
        "query": "What active inbox threads are there for hotel Yash?",
        "checks": "Stage 1 passed + Stage 2 evidence scope verified",
    },
    {
        "label": "Access lookup → client scope check",
        "query": "Who has access to Hotel d'Angleterre?",
        "checks": "Stage 2 — client_id on SQL rows validated",
    },
    {
        "label": "Required fields check",
        "query": "Which posts are waiting for approval for Hotel d'Angleterre?",
        "checks": "Stage 2 — post_id + current_status required fields verified",
    },
    {
        "label": "Zero evidence → Stage 2 warning",
        "query": "What events are coming up for hotel Yash?",
        "checks": "Stage 2 — evidence count vs capability_state checked",
    },
    {
        "label": "SQL + vector → full evidence validation",
        "query": "How is the last TikTok post performing for client 7403?",
        "checks": "Stage 2 — SQL rows + vector matches both scope-checked",
    },
    {
        "label": "Vector table allow-list check",
        "query": "Find media for Red Carnation Hotels Collection",
        "checks": "Stage 2 — vector match tables within contract allow-list",
    },
]


AGENT_CARDS: list[dict[str, str]] = [
    {
        "name": "Orchestrator Agent",
        "purpose": "Runs the intake pipeline, resolves scope, and routes each query to the correct read-only specialist path.",
    },
    {
        "name": "Inbox and Complaint Agent",
        "purpose": "Handles inbox, complaint, thread-status, and triage questions through approved relational routes.",
    },
    {
        "name": "Client Knowledge and FAQ Agent",
        "purpose": "Answers grounded property, FAQ, tone, audience, and client-context questions from approved knowledge sources.",
    },
    {
        "name": "Content Planning Agent",
        "purpose": "Handles schedules, approvals, and post-performance lookups using read-only content and analytics routes.",
    },
    {
        "name": "Media Discovery Agent",
        "purpose": "Finds relevant approved media using read-only semantic retrieval over media analysis text.",
    },
    {
        "name": "Access and Relationship Agent",
        "purpose": "Answers collaborator, ownership, client-scope, competitor-comparable, location-linked, and graph relationship questions through exact joins.",
    },
]


MOCK_PROPERTY_KNOWLEDGE: dict[int, dict[str, Any]] = {
    553: {
        "headline": "Polished, upscale, and approachable.",
        "tone": "Polished welcoming and informative with an upscale but approachable hotel voice.",
        "details": [
            "Use words like discover, relaxation, stylish, modern, exclusive, Potsdam, wellness, and conference.",
            "Avoid words like cheap, party, buzz, hype, urgent, and overrating.",
            "Property positioning leans toward wellness, meetings, and refined city-break travel.",
        ],
        "sources": [
            "clients.client_tone_of_voice_settings",
            "clients.property_details",
            "clients.client_target_audience",
        ],
    },
    552: {
        "headline": "Luxury, discreet, and highly polished.",
        "tone": "Elegant and highly polished with a warm but restrained luxury voice that emphasizes exceptional service and discreet exclusivity.",
        "details": [
            "Audience fit is strongest for luxury leisure travelers, special occasions, and affluent visitors.",
            "Recommended language should feel premium, personal, and timeless rather than trendy.",
        ],
        "sources": [
            "clients.client_tone_of_voice_settings",
            "clients.client_target_audience",
        ],
    },
    493: {
        "headline": "Operational and guest-service oriented.",
        "tone": "Helpful, direct, and practical with a hospitality-first service tone.",
        "details": [
            "Known note: Pool timing is 10 am to 6 pm.",
            "Known note: Public area smoking is not allowed.",
        ],
        "sources": [
            "clients.client_notes",
            "clients.property_details",
        ],
    },
    7403: {
        "headline": "Fast-moving inbox property with room and booking questions.",
        "tone": "Clear, reassuring, and operationally grounded for guest booking and availability queries.",
        "details": [
            "Recent messages cluster around room availability, booking dates, and property amenities.",
            "This property is a good example of when exact inbox retrieval and grounded property knowledge need to collaborate.",
        ],
        "sources": [
            "jx_bridge.messages",
            "clients.client_notes",
        ],
    },
}


MOCK_SQL_SCENARIOS: list[dict[str, Any]] = [
    {
        "match": ["unresolved", "complaint", "snow villa"],
        "intent": "unresolved_complaints",
        "client_id": 7403,
        "answer": "Snow Villa currently has 2 unresolved complaint-like guest threads in the local sample dataset. One is waiting on property input and one is still in reply-now review.",
        "tables": [
            "jx_bridge.messages",
            "jx_bridge.thread_triage",
            "clients.clients",
        ],
        "sql": """SELECT
  m.interaction_id,
  MAX(m.source_timestamp) AS last_guest_message_at,
  tt.triage,
  LEFT(MAX(m.content), 120) AS latest_preview
FROM jx_bridge.messages m
LEFT JOIN jx_bridge.thread_triage tt
  ON tt.interaction_id = m.interaction_id
WHERE m.client_id = 7403
  AND m.last_state = 'new'
  AND (
    LOWER(m.content) LIKE '%cancel%'
    OR LOWER(m.content) LIKE '%complaint%'
    OR LOWER(m.content) LIKE '%issue%'
  )
GROUP BY m.interaction_id, tt.triage
ORDER BY MAX(m.source_timestamp) DESC;""",
        "rows": [
            {
                "interaction_id": 137,
                "triage": "waiting_on_property",
                "last_guest_message_at": "2026-06-25T12:02:35Z",
                "latest_preview": "why is my booking cancelled for next week?",
            },
            {
                "interaction_id": 803,
                "triage": "needs_property_help",
                "last_guest_message_at": "2026-06-25T11:03:21Z",
                "latest_preview": "guest is asking for event details and charges for a pool DJ night",
            },
        ],
        "sources": [
            "jx_bridge.messages",
            "jx_bridge.thread_triage",
        ],
    },
    {
        "match": ["scheduled", "next week", "553"],
        "intent": "scheduled_posts",
        "client_id": 553,
        "answer": "Client 553 has 2 scheduled content items in the local sample response window, with Instagram Graph and LinkedIn-style distribution represented in the content workflow sample.",
        "tables": [
            "content.content_topic_post",
            "content.content_topic",
            "content.content_post_status",
            "general.social_network_type",
        ],
        "sql": """SELECT
  ctp.id,
  ct.name AS topic_name,
  cps.description AS status,
  snt.description AS social_network,
  ctp.post_datetime,
  LEFT(ctp.post_text, 140) AS post_preview
FROM content.content_topic_post ctp
JOIN content.content_topic ct
  ON ct.id = ctp.content_topic_id
LEFT JOIN content.content_post_status cps
  ON cps.id = ctp.content_post_status_id
LEFT JOIN general.social_network_type snt
  ON snt.id = ctp.social_network_type_id
WHERE ct.client_id = 553
  AND ctp.deleted_at IS NULL
  AND ctp.post_datetime >= CURRENT_DATE
ORDER BY ctp.post_datetime ASC;""",
        "rows": [
            {
                "post_id": 10336,
                "topic_name": "Outdoor relaxation scene",
                "status": "scheduled",
                "social_network": "instagram_graph",
                "post_datetime": "2026-06-26T10:00:00",
            },
            {
                "post_id": 10334,
                "topic_name": "Hotel Lounge Conversation Scene",
                "status": "posted",
                "social_network": "instagram_graph",
                "post_datetime": "2026-06-25T08:44:00",
            },
        ],
        "sources": [
            "content.content_topic_post",
            "content.content_topic",
        ],
    },
    {
        "match": ["who has access", "snow villa"],
        "intent": "client_access_lookup",
        "client_id": 7403,
        "answer": "In the local sample result, Snow Villa is shown as shared with 2 internal collaborators and scoped through its organization membership.",
        "tables": [
            "clients.clients",
            "clients.clients_collaborators",
            "organizations.organization_users",
            "users.users",
        ],
        "sql": """SELECT DISTINCT
  u.id,
  u.full_name,
  cc.access_level,
  c.name AS client_name
FROM clients.clients c
LEFT JOIN clients.clients_collaborators cc
  ON cc.client_id = c.id
LEFT JOIN users.users u
  ON u.id = cc.user_id
WHERE c.id = 7403
  AND cc.enabled IS TRUE
  AND cc.deleted_at IS NULL;""",
        "rows": [
            {"user_id": 743, "full_name": "Rohit Patel", "access_level": "editor"},
            {"user_id": 218, "full_name": "Operations Owner", "access_level": "owner"},
        ],
        "sources": [
            "clients.clients_collaborators",
            "users.users",
        ],
    },
]


MOCK_KNOWLEDGE_SCENARIOS: list[dict[str, Any]] = [
    {
        "match": ["tone", "voice", "553"],
        "intent": "tone_of_voice_lookup",
        "client_id": 553,
        "answer": "MAXX Hotel Sanssouci Potsdam should sound polished, welcoming, and informative, with an upscale but approachable hospitality voice. Language should lean toward discovery, relaxation, wellness, and conference-friendly refinement rather than hype or party energy.",
        "sources": [
            {
                "title": "Tone of voice settings",
                "table": "clients.client_tone_of_voice_settings",
                "excerpt": "Polished welcoming and informative with an upscale but approachable hotel voice.",
            },
            {
                "title": "Target audiences",
                "table": "clients.client_target_audience",
                "excerpt": "Business travelers, meetings and conference planners, leisure city-break travelers.",
            },
        ],
    },
    {
        "match": ["what do we know", "ramtin"],
        "intent": "property_knowledge_summary",
        "client_id": 493,
        "answer": "Hotel Ramtin currently has lightweight operational knowledge in the local sample data. The most reliable stored guidance is practical: pool timing runs from 10 am to 6 pm, smoking is not allowed in public areas, and service-facing answers should stay direct, helpful, and operational.",
        "sources": [
            {
                "title": "Client notes",
                "table": "clients.client_notes",
                "excerpt": "Pool timing is 10 am to 6 pm. In public area smoking not allowed.",
            },
            {
                "title": "Knowledge profile",
                "table": "clients.property_details",
                "excerpt": "Use operational notes first and keep answers concise and service-oriented.",
            },
        ],
    },
    {
        "match": ["media", "luxury wedding", "london"],
        "intent": "media_recommendation",
        "client_id": 552,
        "answer": "For a luxury wedding campaign in London, the strongest mock matches are elegant lobby and refined interior visuals, because their AI media analysis already signals premium décor, intimate atmosphere, and high-end hospitality cues that fit special-occasion storytelling.",
        "sources": [
            {
                "title": "Media analysis",
                "table": "media.media_analysis_ai",
                "excerpt": "Elegant lounge, refined ambiance, warm lighting, marble wall, intimate setting.",
            },
            {
                "title": "Tone of voice settings",
                "table": "clients.client_tone_of_voice_settings",
                "excerpt": "Elegant and highly polished with a warm but restrained luxury voice.",
            },
        ],
        "matches": [
            {
                "media_id": 6247,
                "label": "Elegant hotel lounge conversation scene",
                "fit": "Luxury tone, intimate setting, polished atmosphere",
            },
            {
                "media_id": 6241,
                "label": "Iconic premium hotel exterior",
                "fit": "Strong prestige and destination value, weaker wedding intimacy",
            },
        ],
    },
    {
        "match": ["reply", "pool timing"],
        "intent": "faq_reply_guidance",
        "client_id": 493,
        "answer": "A grounded response should say that the pool is open from 10 am to 6 pm, keep the answer short, and avoid over-explaining unless the guest also asks about access rules or booking requirements.",
        "sources": [
            {
                "title": "Client note",
                "table": "clients.client_notes",
                "excerpt": "Pool timing is 10 am to 6 pm.",
            }
        ],
    },
]
