from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / "backend" / "app" / "data" / "dummy_db"
SCHEMAS = ("clients", "content", "media", "analytics", "jx_bridge", "general", "world", "users", "organizations", "entity")
NOW = datetime(2026, 7, 20, 10, 0, 0)


def connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_DIR / "main.sqlite3")
    conn.row_factory = sqlite3.Row
    for schema in SCHEMAS:
        conn.execute(f"ATTACH DATABASE '{(DB_DIR / f'{schema}.sqlite3').as_posix()}' AS {schema}")
    return conn


def reset_files() -> None:
    if DB_DIR.exists():
        shutil.rmtree(DB_DIR)
    DB_DIR.mkdir(parents=True, exist_ok=True)


def execute_many(conn: sqlite3.Connection, statements: list[str]) -> None:
    for statement in statements:
        conn.execute(statement)


def create_schema(conn: sqlite3.Connection) -> None:
    execute_many(
        conn,
        [
            """
            CREATE TABLE clients.clients (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                organization_id INTEGER,
                world_city_id INTEGER,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE clients.client_notes (
                id INTEGER PRIMARY KEY,
                client_id INTEGER,
                title TEXT,
                note TEXT,
                type_id INTEGER,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE clients.property_details (
                id INTEGER PRIMARY KEY,
                client_id INTEGER,
                location TEXT,
                highlights TEXT,
                amenities TEXT,
                overview TEXT,
                info TEXT,
                food_and_beverages TEXT,
                gallery TEXT,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE clients.client_details (
                id INTEGER PRIMARY KEY,
                client_id INTEGER,
                context TEXT,
                metadata TEXT,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE clients.client_marketing_settings (
                id INTEGER PRIMARY KEY,
                client_id INTEGER,
                property_type TEXT,
                conversion REAL,
                average_default_rate INTEGER,
                average_length_of_stay REAL,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE clients.client_tone_of_voice_settings (
                id INTEGER PRIMARY KEY,
                client_id INTEGER,
                custom_guidelines TEXT,
                use_words TEXT,
                avoid_words TEXT,
                formality INTEGER,
                energy_level INTEGER,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE clients.client_target_audience (
                id INTEGER PRIMARY KEY,
                client_id INTEGER,
                audience TEXT,
                is_custom INTEGER,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE clients.client_target_audience_suggestions (
                id INTEGER PRIMARY KEY,
                client_id INTEGER,
                audience TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE clients.client_social_network_account (
                id INTEGER PRIMARY KEY,
                client_id INTEGER,
                user_id INTEGER,
                social_network_type_id INTEGER,
                social_network_id TEXT,
                social_network_user_name TEXT,
                social_network_url TEXT,
                social_network_name TEXT,
                additional_data TEXT,
                valid_from_timestamp TEXT,
                valid_to_timestamp TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE clients.clients_collaborators (
                id INTEGER PRIMARY KEY,
                client_id INTEGER,
                user_id INTEGER,
                access_level TEXT,
                enabled INTEGER,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE users.users (
                id INTEGER PRIMARY KEY,
                full_name TEXT,
                email TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE users.users_roles (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                role TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE organizations.organizations (
                id INTEGER PRIMARY KEY,
                name TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE organizations.organization_users (
                id INTEGER PRIMARY KEY,
                organization_id INTEGER,
                user_id INTEGER,
                role TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE content.content_topic (
                id INTEGER PRIMARY KEY,
                client_id INTEGER,
                user_id INTEGER,
                content_pillar_id INTEGER,
                name TEXT,
                event_custom_id INTEGER,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT,
                event_id INTEGER
            )
            """,
            """
            CREATE TABLE content.content_topic_post (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                content_topic_id INTEGER,
                social_network_type_id INTEGER,
                content_post_status_id INTEGER,
                post_datetime TEXT,
                post_text TEXT,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT,
                network_post_ref TEXT,
                location_id INTEGER,
                brand_tone_score REAL,
                content_post_type_id INTEGER,
                brand_tone_score_tooltip TEXT,
                ai_generated INTEGER,
                processing INTEGER
            )
            """,
            """
            CREATE TABLE content.content_post_status (
                id INTEGER PRIMARY KEY,
                description TEXT
            )
            """,
            """
            CREATE TABLE content.content_topic_post_approval_status (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                content_topic_post_id INTEGER,
                content_post_status_id INTEGER,
                approval_rejection_text TEXT,
                valid_from_timestamp TEXT,
                valid_to_timestamp TEXT,
                deleted_at TEXT,
                content_post_approval_level_id INTEGER
            )
            """,
            """
            CREATE TABLE content.content_topic_post_media (
                id INTEGER PRIMARY KEY,
                content_topic_post_id INTEGER,
                media_id INTEGER,
                media_asset_id INTEGER,
                media_order INTEGER,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE general.social_network_type (
                id INTEGER PRIMARY KEY,
                description TEXT
            )
            """,
            """
            CREATE TABLE general.events (
                id INTEGER PRIMARY KEY,
                world_city_id INTEGER,
                name TEXT,
                date TEXT,
                type TEXT,
                location TEXT,
                audience TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE general.knowledge_embeddings (
                id INTEGER PRIMARY KEY,
                client_id INTEGER NOT NULL,
                source_table TEXT NOT NULL,
                source_pk INTEGER NOT NULL,
                source_ref TEXT,
                source_kind TEXT NOT NULL,
                knowledge_domain TEXT NOT NULL,
                chunk_label TEXT,
                knowledge_document TEXT NOT NULL,
                embedding_model TEXT,
                embedding_json TEXT,
                content_hash TEXT UNIQUE,
                inserted_datetime TEXT,
                updated_datetime TEXT
            )
            """,
            """
            CREATE TABLE world.cities (
                id INTEGER PRIMARY KEY,
                name TEXT,
                state_id INTEGER,
                country_id INTEGER,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE media.media (
                id INTEGER PRIMARY KEY,
                client_id INTEGER,
                user_id INTEGER,
                media_type_id INTEGER,
                media_status_id INTEGER,
                name TEXT,
                description TEXT,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE media.media_analysis_ai (
                id INTEGER PRIMARY KEY,
                media_id INTEGER,
                short_description TEXT,
                alt_text TEXT,
                visual_tags TEXT,
                descriptive_tags TEXT,
                semantic_keywords TEXT,
                media_metadata TEXT,
                content_analysis TEXT,
                post_copy TEXT,
                dam_metadata TEXT,
                media_asset_id INTEGER,
                embedding TEXT,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE analytics.social_media_post (
                id INTEGER PRIMARY KEY,
                social_network_type_id INTEGER,
                identifier TEXT,
                post_ref TEXT,
                json_value TEXT,
                is_dirty INTEGER,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                created_at TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE analytics.metric_embeddings (
                id INTEGER PRIMARY KEY,
                client_id INTEGER NOT NULL,
                source_table TEXT NOT NULL,
                source_pk INTEGER NOT NULL,
                source_ref TEXT,
                source_kind TEXT NOT NULL,
                metric_document TEXT NOT NULL,
                metric_names TEXT,
                embedding_model TEXT,
                embedding_json TEXT,
                content_hash TEXT UNIQUE,
                inserted_datetime TEXT,
                updated_datetime TEXT
            )
            """,
            """
            CREATE TABLE entity.entity (
                id INTEGER PRIMARY KEY,
                entity_type TEXT NOT NULL,
                node_key TEXT NOT NULL UNIQUE,
                source_table TEXT NOT NULL,
                source_pk TEXT NOT NULL,
                client_id INTEGER,
                name TEXT,
                description TEXT,
                metadata TEXT,
                inserted_datetime TEXT,
                updated_datetime TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE entity.entity_relationship (
                id INTEGER PRIMARY KEY,
                from_entity_id INTEGER NOT NULL,
                to_entity_id INTEGER NOT NULL,
                relationship_type TEXT NOT NULL,
                source_table TEXT,
                source_pk TEXT,
                client_id INTEGER,
                weight REAL,
                metadata TEXT,
                inserted_datetime TEXT,
                deleted_at TEXT,
                UNIQUE(from_entity_id, to_entity_id, relationship_type, source_table, source_pk)
            )
            """,
            """
            CREATE TABLE entity.entity_facility_brand (
                id INTEGER PRIMARY KEY,
                entity_id INTEGER,
                client_id INTEGER,
                brand_name TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE entity.entity_facility_sub_brand (
                id INTEGER PRIMARY KEY,
                entity_id INTEGER,
                client_id INTEGER,
                sub_brand_name TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE jx_bridge.interactions (
                interaction_id INTEGER PRIMARY KEY,
                client_id INTEGER,
                metadata TEXT,
                priority INTEGER,
                title TEXT
            )
            """,
            """
            CREATE TABLE jx_bridge.messages (
                message_id INTEGER PRIMARY KEY,
                client_id INTEGER,
                source_id TEXT,
                source_timestamp TEXT,
                content TEXT,
                author TEXT,
                permalink TEXT,
                social_network_type_id INTEGER,
                interaction_id INTEGER,
                parent_id TEXT,
                last_state TEXT,
                page_social_network_id TEXT,
                type TEXT,
                fts_content TEXT,
                fts_username TEXT,
                translated_language TEXT,
                user TEXT
            )
            """,
            """
            CREATE TABLE jx_bridge.thread_triage (
                id INTEGER PRIMARY KEY,
                interaction_id INTEGER,
                triage TEXT
            )
            """,
            """
            CREATE TABLE jx_bridge.alerts (
                id INTEGER PRIMARY KEY,
                interaction_id INTEGER,
                status TEXT,
                inserted_datetime TEXT,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE jx_bridge.alert_replies (
                id INTEGER PRIMARY KEY,
                alert_id INTEGER,
                reply_text TEXT,
                inserted_datetime TEXT,
                deleted_at TEXT
            )
            """,
        ],
    )


def insert_many(conn: sqlite3.Connection, sql: str, rows: list[tuple[Any, ...]]) -> None:
    conn.executemany(sql, rows)


def dt(days: int = 0, hours: int = 0) -> str:
    return (NOW + timedelta(days=days, hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def d(days: int = 0) -> str:
    return (date(2026, 7, 20) + timedelta(days=days)).isoformat()


def seed_reference(conn: sqlite3.Connection) -> None:
    insert_many(
        conn,
        "INSERT INTO general.social_network_type (id, description) VALUES (?, ?)",
        [
            (1, "facebook"),
            (2, "twitter"),
            (3, "instagram"),
            (6, "linkedin"),
            (7, "instagram_graph"),
            (9, "tiktok"),
            (11, "booking"),
        ],
    )
    insert_many(
        conn,
        "INSERT INTO content.content_post_status (id, description) VALUES (?, ?)",
        [
            (1, "draft"),
            (4, "sent_for_approval"),
            (6, "scheduled"),
            (7, "posted"),
            (8, "sent_for_external_approval"),
            (9, "rejected"),
        ],
    )
    insert_many(
        conn,
        "INSERT INTO world.cities (id, name, state_id, country_id, deleted_at) VALUES (?, ?, ?, ?, NULL)",
        [
            (501, "Geneva", 1, 1),
            (502, "Chicago", 2, 2),
            (503, "Jaipur", 3, 3),
            (504, "London", 4, 4),
            (505, "Goa", 5, 3),
            (506, "Mumbai", 6, 3),
            (507, "Manali", 7, 3),
            (508, "Potsdam", 8, 5),
            (509, "Bihar", 9, 3),
            (510, "Hamburg", 10, 5),
        ],
    )


CLIENTS = [
    (493, "Hotel d'Angleterre", 228, 501, "Geneva", "Luxury city hotel beside the lake."),
    (7403, "Hotel Ramtin", 288, 502, "Chicago", "Business hotel with quick guest-service operations."),
    (382, "hotel Yash", 301, 503, "Jaipur", "Boutique hotel with active social inbox traffic."),
    (328, "Red Carnation Hotels Collection", 302, 504, "London", "Collection brand with large media library."),
    (273, "Bihar Motel", 303, 509, "Bihar", "Value-focused roadside motel."),
    (387, "Hotel Hafenresidenz", 304, 510, "Hamburg", "Harbor hotel for families, wellness and short breaks."),
    (1007, "Grand Hyatt Mumbai", 305, 506, "Mumbai", "Upper-upscale business and leisure hotel."),
    (1008, "Park Hyatt Goa", 306, 505, "Goa", "Resort property for wellness and family escapes."),
    (552, "The Rubens at the Palace", 307, 504, "London", "Luxury hotel near the palace."),
    (1010, "Snow Villa Manali", 308, 507, "Manali", "Mountain villa for snow-season travelers."),
    (553, "Hotel Potsdam", 309, 508, "Potsdam", "Conference and city-break hotel."),
    (1012, "Goa property", 310, 505, "Goa", "Beach-side campaign test property."),
    (1013, "HotelAnand", 311, 503, "Jaipur", "Local hotel with booking questions."),
    (1014, "SoHo Chicago", 312, 502, "Chicago", "Social dining and events venue."),
    (1015, "Lemon Tree Jaipur", 313, 503, "Jaipur", "Mid-market hotel for family and business travelers."),
]

CLIENT_PROFILES: dict[int, dict[str, Any]] = {
    493: {
        "amenities": ["lake-view rooms", "wifi", "breakfast", "rooftop bar", "concierge", "airport pickup"],
        "highlights": ["Geneva lakefront location", "rooftop bar", "luxury guest service"],
        "policies": {"check_in_time": "15:00", "check_out_time": "12:00", "smoking_policy": "public area smoking is not allowed", "pets": "on request"},
        "faqs": [
            ("Rooftop bar timing", "Rooftop bar closing time at 10 pm."),
            ("Smoking policy", "In public area smoking not allowed."),
            ("Airport pickup", "Airport pickup can be arranged with advance notice."),
        ],
        "audiences": ["luxury leisure travelers", "business travelers", "couples", "event planners"],
    },
    7403: {
        "amenities": ["wifi", "breakfast", "concierge", "airport pickup", "mini-bar"],
        "highlights": ["fast guest-service operations", "business-friendly rooms", "Chicago city access"],
        "policies": {"check_in_time": "14:00", "check_out_time": "11:00", "pool": "No swimming pool is listed in the approved property amenities.", "pets": "not listed"},
        "faqs": [
            ("cab service available", "Cab service provided by hotel for pickup and drop at your location."),
            ("Mini-bar service", "Mini-bar in rooms is available at extra cost."),
            ("Pool availability", "No swimming pool is listed in the approved property amenities for Hotel Ramtin."),
            ("Late checkout", "Late checkout is subject to availability and should be confirmed by the front desk."),
        ],
        "audiences": ["business travelers", "short-stay city guests", "corporate bookers", "local event visitors"],
    },
    382: {
        "amenities": ["wifi", "breakfast", "vegetarian dining", "parking", "local taxi desk"],
        "highlights": ["Jaipur boutique style", "high inbox activity", "local dining guidance"],
        "policies": {"check_in_time": "13:00", "check_out_time": "11:00", "parking": "limited parking available", "pets": "not allowed"},
        "faqs": [
            ("Parking", "Limited on-site parking is available for hotel guests."),
            ("Vegetarian dining", "Vegetarian dining options are available."),
            ("Taxi desk", "Local taxi support is available through the front desk."),
        ],
        "audiences": ["family travelers", "domestic leisure guests", "wedding guests", "business travelers"],
    },
    328: {
        "amenities": ["media library", "luxury brand storytelling", "campaign assets", "event creative"],
        "highlights": ["large approved media library", "premium brand portfolio", "London campaign support"],
        "policies": {"brand_usage": "use approved luxury imagery only", "rights": "dummy approved media assets are cleared for POC use"},
        "faqs": [
            ("Media library", "The collection has a broad approved media library for luxury campaign storytelling."),
            ("Brand style", "Use premium, warm, polished and service-led wording."),
        ],
        "audiences": ["luxury travelers", "special occasion guests", "affluent families", "travel advisors"],
    },
    387: {
        "amenities": ["wifi", "breakfast", "wellness area", "family rooms", "harbor views"],
        "highlights": ["Hamburg harbor setting", "wellness breaks", "family-friendly stays"],
        "policies": {"check_in_time": "15:00", "check_out_time": "11:00", "spa": "wellness slots should be reserved in advance"},
        "faqs": [
            ("Wellness booking", "Wellness appointments should be reserved in advance."),
            ("Family rooms", "Family room options are available on request."),
        ],
        "audiences": ["families", "wellness travelers", "short-break guests", "conference travelers"],
    },
    1008: {
        "amenities": ["pool", "spa", "beach access", "family activities", "breakfast"],
        "highlights": ["Goa resort experience", "wellness escapes", "family leisure"],
        "policies": {"check_in_time": "15:00", "check_out_time": "12:00", "pool": "pool access is available for in-house guests"},
        "faqs": [
            ("Pool", "Pool access is available for in-house guests."),
            ("Beach access", "Beach access guidance is available at the concierge desk."),
        ],
        "audiences": ["families", "wellness travelers", "honeymoon couples", "resort guests"],
    },
    1010: {
        "amenities": ["mountain views", "heating", "bonfire area", "snow-season guidance", "wifi"],
        "highlights": ["Manali snow-season villa", "mountain views", "winter travel support"],
        "policies": {"check_in_time": "14:00", "check_out_time": "10:30", "snow_advisory": "winter access can depend on local road conditions"},
        "faqs": [
            ("Snow season", "Winter access and sightseeing depend on local road conditions."),
            ("Bonfire", "Bonfire arrangements can be requested in advance."),
        ],
        "audiences": ["snow-season travelers", "families", "friend groups", "mountain leisure guests"],
    },
}

MARKETING_SETTINGS: dict[int, dict[str, Any]] = {
    493: {"property_type": "luxury city hotel", "conversion": 0.118, "average_default_rate": 620, "average_length_of_stay": 2.4},
    7403: {"property_type": "business city hotel", "conversion": 0.087, "average_default_rate": 210, "average_length_of_stay": 1.8},
    382: {"property_type": "boutique city hotel", "conversion": 0.074, "average_default_rate": 95, "average_length_of_stay": 2.1},
    328: {"property_type": "luxury collection hotel", "conversion": 0.122, "average_default_rate": 540, "average_length_of_stay": 2.8},
    273: {"property_type": "value motel", "conversion": 0.052, "average_default_rate": 45, "average_length_of_stay": 1.3},
    387: {"property_type": "harbor wellness hotel", "conversion": 0.096, "average_default_rate": 185, "average_length_of_stay": 2.2},
    1007: {"property_type": "upper upscale business hotel", "conversion": 0.103, "average_default_rate": 240, "average_length_of_stay": 2.0},
    1008: {"property_type": "resort hotel", "conversion": 0.111, "average_default_rate": 275, "average_length_of_stay": 3.4},
    552: {"property_type": "luxury city hotel", "conversion": 0.116, "average_default_rate": 590, "average_length_of_stay": 2.6},
    1010: {"property_type": "mountain villa", "conversion": 0.083, "average_default_rate": 165, "average_length_of_stay": 2.9},
    553: {"property_type": "conference city hotel", "conversion": 0.081, "average_default_rate": 155, "average_length_of_stay": 1.9},
    1012: {"property_type": "beach hotel", "conversion": 0.079, "average_default_rate": 145, "average_length_of_stay": 2.7},
    1013: {"property_type": "boutique city hotel", "conversion": 0.066, "average_default_rate": 85, "average_length_of_stay": 1.8},
    1014: {"property_type": "business city hotel", "conversion": 0.091, "average_default_rate": 225, "average_length_of_stay": 1.7},
    1015: {"property_type": "mid-market city hotel", "conversion": 0.071, "average_default_rate": 90, "average_length_of_stay": 2.0},
}


def seed_clients(conn: sqlite3.Connection) -> None:
    users = [
        (201, "Asha Manager", "asha@example.test", None),
        (202, "Manmohan Approver", "manmohan@example.test", None),
        (203, "Yash Creator", "yash@example.test", None),
        (204, "Vishakha Creator", "vishakha@example.test", None),
        (205, "Rohit Admin", "rohit@example.test", None),
        (206, "Nina Media", "nina@example.test", None),
        (207, "Priya Analyst", "priya@example.test", None),
        (208, "Kabir Community", "kabir@example.test", None),
    ]
    insert_many(conn, "INSERT INTO users.users (id, full_name, email, deleted_at) VALUES (?, ?, ?, ?)", users)
    role_values = ["admin", "approver", "creator", "creator", "owner", "media", "analyst", "community"]
    insert_many(
        conn,
        "INSERT INTO users.users_roles (id, user_id, role, deleted_at) VALUES (?, ?, ?, NULL)",
        [(index + 1, user[0], role) for index, (user, role) in enumerate(zip(users, role_values))],
    )
    insert_many(
        conn,
        "INSERT INTO organizations.organizations (id, name, deleted_at) VALUES (?, ?, NULL)",
        [(client[2], f"{client[1]} Organization") for client in CLIENTS],
    )
    insert_many(
        conn,
        "INSERT INTO clients.clients (id, name, organization_id, world_city_id, deleted_at) VALUES (?, ?, ?, ?, NULL)",
        [(client_id, name, org_id, city_id) for client_id, name, org_id, city_id, _, _ in CLIENTS],
    )
    org_user_rows = []
    collaborator_rows = []
    collab_id = 1
    org_user_id = 1
    for client_id, _, org_id, _, _, _ in CLIENTS:
        for user_id, role in ((201, "ROLE_OWNER"), (202, "ROLE_APPROVER"), (203, "ROLE_CREATOR"), (206, "ROLE_MEDIA"), (207, "ROLE_ANALYST"), (208, "ROLE_COMMUNITY")):
            org_user_rows.append((org_user_id, org_id, user_id, role, None))
            collaborator_rows.append((collab_id, client_id, user_id, role, 1, None))
            org_user_id += 1
            collab_id += 1
    insert_many(
        conn,
        "INSERT INTO organizations.organization_users (id, organization_id, user_id, role, deleted_at) VALUES (?, ?, ?, ?, ?)",
        org_user_rows,
    )
    insert_many(
        conn,
        "INSERT INTO clients.clients_collaborators (id, client_id, user_id, access_level, enabled, deleted_at) VALUES (?, ?, ?, ?, ?, ?)",
        collaborator_rows,
    )

    note_rows = []
    property_rows = []
    detail_rows = []
    marketing_rows = []
    tone_rows = []
    audience_rows = []
    audience_suggestion_rows = []
    social_account_rows = []
    note_id = 1
    audience_id = 1
    audience_suggestion_id = 1
    social_account_id = 1
    for client_index, (client_id, name, _, _, city, overview) in enumerate(CLIENTS):
        profile = CLIENT_PROFILES.get(
            client_id,
            {
                "amenities": ["wifi", "breakfast", "concierge", "local travel guidance"],
                "highlights": ["guest service", "local experiences", "seasonal content"],
                "policies": {"check_in_time": "14:00", "check_out_time": "11:00", "pets": "on request"},
                "faqs": [
                    ("Airport pickup", f"{name} can arrange local taxi and guest transfers with advance notice."),
                    ("Breakfast", "Breakfast guidance is available from the front desk."),
                    ("Local experiences", f"The team can suggest local experiences in {city}."),
                ],
                "audiences": ["family travelers", "business travelers", "weekend leisure guests", "event planners"],
            },
        )
        facts = [
            (f"{name} overview", overview, 1),
            ("FAQ: transport", f"{name} can arrange airport pickup, local taxi and guest transfers with advance notice when that service is listed for the property.", 2),
            ("FAQ: amenities", f"{name} approved amenities include {', '.join(profile['amenities'])}.", 2),
            ("FAQ: check-in and checkout", f"Check-in is {profile['policies'].get('check_in_time', 'not listed')} and checkout is {profile['policies'].get('check_out_time', 'not listed')} in the approved dummy record.", 2),
        ]
        facts.extend((title, note, 2) for title, note in profile["faqs"])
        for title, note, type_id in facts:
            note_rows.append((note_id, client_id, title, note, type_id, dt(-7), dt(-1), None))
            note_id += 1
        property_rows.append(
            (
                client_id,
                client_id,
                f"{city} central district",
                json.dumps(profile["highlights"]),
                json.dumps(profile["amenities"]),
                overview,
                json.dumps(profile["policies"]),
                json.dumps({"breakfast": "available" if "breakfast" in profile["amenities"] else "not listed", "bar": "available" if any("bar" in item for item in profile["amenities"]) else "not listed"}),
                json.dumps([]),
                dt(-30),
                dt(-2),
                None,
            )
        )
        detail_rows.append(
            (
                client_id,
                client_id,
                "onboarding",
                json.dumps(
                    {
                        "property": name,
                        "city": city,
                        "country": "Dummyland",
                        "positioning": overview,
                        "primary_use_cases": ["property FAQ", "content planning", "media discovery", "relationship graph"],
                    }
                ),
                dt(-30),
                dt(-2),
                None,
            )
        )
        marketing = MARKETING_SETTINGS.get(
            client_id,
            {
                "property_type": "independent hotel",
                "conversion": 0.06,
                "average_default_rate": 120,
                "average_length_of_stay": 2.0,
            },
        )
        marketing_rows.append(
            (
                client_id,
                client_id,
                marketing["property_type"],
                marketing["conversion"],
                marketing["average_default_rate"],
                marketing["average_length_of_stay"],
                dt(-30),
                dt(-2),
                None,
            )
        )
        tone_rows.append(
            (
                client_id,
                client_id,
                f"Use a clear, helpful hospitality tone for {name}. Keep replies specific and locally grounded.",
                json.dumps(["helpful", "welcoming", "local", "clear"]),
                json.dumps(["cheap", "hype", "urgent"]),
                4,
                3,
                dt(-30),
                dt(-2),
                None,
            )
        )
        for audience in profile["audiences"]:
            audience_rows.append((audience_id, client_id, audience, 0, dt(-30), dt(-2), None))
            audience_id += 1
        for suggestion in ("repeat guests", "nearby event visitors", "social media engagers"):
            audience_suggestion_rows.append((audience_suggestion_id, client_id, suggestion, None))
            audience_suggestion_id += 1
        for network_id, network_name in ((1, "facebook"), (7, "instagram_graph"), (6, "linkedin"), (9, "tiktok")):
            handle = f"{name.lower().replace(' ', '_').replace(chr(39), '')}_{network_name}"
            social_account_rows.append(
                (
                    social_account_id,
                    client_id,
                    205 if network_id in {1, 7} else 206,
                    network_id,
                    f"{client_id}-{network_name}",
                    handle,
                    f"https://social.example.test/{handle}",
                    f"{name} {network_name}",
                    json.dumps({"dummy": True, "priority": "primary" if network_id == 7 else "secondary", "client_index": client_index}),
                    dt(-90),
                    None,
                    None,
                )
            )
            social_account_id += 1
    insert_many(
        conn,
        "INSERT INTO clients.client_notes (id, client_id, title, note, type_id, inserted_datetime, updated_datetime, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        note_rows,
    )
    insert_many(
        conn,
        """
        INSERT INTO clients.property_details
        (id, client_id, location, highlights, amenities, overview, info, food_and_beverages, gallery, inserted_datetime, updated_datetime, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        property_rows,
    )
    insert_many(
        conn,
        "INSERT INTO clients.client_details (id, client_id, context, metadata, inserted_datetime, updated_datetime, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        detail_rows,
    )
    insert_many(
        conn,
        """
        INSERT INTO clients.client_marketing_settings
        (id, client_id, property_type, conversion, average_default_rate, average_length_of_stay, inserted_datetime, updated_datetime, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        marketing_rows,
    )
    insert_many(
        conn,
        """
        INSERT INTO clients.client_tone_of_voice_settings
        (id, client_id, custom_guidelines, use_words, avoid_words, formality, energy_level, inserted_datetime, updated_datetime, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tone_rows,
    )
    insert_many(
        conn,
        "INSERT INTO clients.client_target_audience (id, client_id, audience, is_custom, inserted_datetime, updated_datetime, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        audience_rows,
    )
    insert_many(
        conn,
        "INSERT INTO clients.client_target_audience_suggestions (id, client_id, audience, deleted_at) VALUES (?, ?, ?, ?)",
        audience_suggestion_rows,
    )
    insert_many(
        conn,
        """
        INSERT INTO clients.client_social_network_account
        (id, client_id, user_id, social_network_type_id, social_network_id, social_network_user_name,
         social_network_url, social_network_name, additional_data, valid_from_timestamp, valid_to_timestamp, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        social_account_rows,
    )


def seed_content_media_analytics(conn: sqlite3.Connection) -> None:
    topic_rows = []
    post_rows = []
    approval_rows = []
    media_rows = []
    media_ai_rows = []
    post_media_rows = []
    analytics_rows = []
    topic_id = 1
    post_id = 1
    approval_id = 1
    media_id = 1
    analytics_id = 1
    networks = [1, 7, 6, 9]
    statuses = [6, 1, 4, 7]
    for client_index, (client_id, name, _, _, city, _) in enumerate(CLIENTS):
        posted_post_ids: list[int] = []
        for theme in ["Local experiences", "Dining moments", "Guest comfort"]:
            topic_rows.append((topic_id, client_id, 201, None, theme, None, dt(-20), dt(-1), None, None))
            for offset in range(4):
                network_id = networks[(client_index + offset) % len(networks)]
                status_id = statuses[(client_index + offset) % len(statuses)]
                scheduled_at = dt(-3, offset) if status_id == 7 else dt(offset, offset)
                ref = f"{client_id}_{post_id}_ref" if status_id == 7 else None
                post_text = f"{name} shares {theme.lower()} in {city}, inviting guests to discover a thoughtful stay."
                post_rows.append(
                    (
                        post_id,
                        201,
                        topic_id,
                        network_id,
                        status_id,
                        scheduled_at,
                        post_text,
                        dt(-10),
                        dt(-1),
                        None,
                        ref,
                        None,
                        0.86,
                        1,
                        "On brand",
                        1,
                        0,
                    )
                )
                if status_id in {1, 4, 8, 9}:
                    approval_rows.append((approval_id, 202, post_id, status_id, "Looks good, awaiting final review." if status_id == 4 else None, dt(-1), None, None, 1))
                    approval_id += 1
                if ref:
                    posted_post_ids.append(post_id)
                    analytics_rows.append(
                        (
                            analytics_id,
                            network_id,
                            str(client_id),
                            ref,
                            json.dumps(
                                {
                                    "id": ref,
                                    "likes": {"count": 12 + client_index, "totalCount": 12 + client_index},
                                    "comments": {"count": 3 + offset, "total_count": 3 + offset},
                                    "reactions": {"totalCount": 8 + offset},
                                    "shares": {"count": offset},
                                    "permalink_url": f"https://example.test/{ref}",
                                    "created_time": scheduled_at,
                                }
                            ),
                            0,
                            dt(-1),
                            dt(-1),
                            scheduled_at,
                            None,
                        )
                    )
                    analytics_id += 1
                post_id += 1
            topic_id += 1
        topic_rows.append((topic_id, client_id, 201, None, "Performance highlights", None, dt(-12), dt(-1), None, None))
        for network_offset, network_id in enumerate(networks):
            scheduled_at = dt(-1 - network_offset, network_offset)
            ref = f"{client_id}_{post_id}_evergreen_ref"
            network_label = {1: "Facebook", 7: "Instagram", 6: "LinkedIn", 9: "TikTok"}[network_id]
            post_text = f"{name} shares a {network_label} highlight from {city}, featuring guest experience, local moments and service details."
            post_rows.append(
                (
                    post_id,
                    201,
                    topic_id,
                    network_id,
                    7,
                    scheduled_at,
                    post_text,
                    dt(-10),
                    dt(-1),
                    None,
                    ref,
                    None,
                    0.9,
                    1,
                    "On brand",
                    1,
                    0,
                )
            )
            posted_post_ids.append(post_id)
            analytics_rows.append(
                (
                    analytics_id,
                    network_id,
                    str(client_id),
                    ref,
                    json.dumps(
                        {
                            "id": ref,
                            "likes": {"count": 30 + client_index + network_offset, "totalCount": 30 + client_index + network_offset},
                            "comments": {"count": 5 + network_offset, "total_count": 5 + network_offset},
                            "reactions": {"totalCount": 12 + client_index + network_offset},
                            "shares": {"count": 2 + network_offset},
                            "reach": 500 + (client_index * 25) + (network_offset * 30),
                            "impressions": 700 + (client_index * 40) + (network_offset * 45),
                            "permalink_url": f"https://example.test/{ref}",
                            "created_time": scheduled_at,
                        }
                    ),
                    0,
                    dt(-1),
                    dt(-1),
                    scheduled_at,
                    None,
                )
            )
            analytics_id += 1
            post_id += 1
        topic_id += 1
        media_count = max(6, len(posted_post_ids))
        for media_offset in range(media_count):
            media_name = f"{name} visual {media_offset + 1}"
            media_theme = ["exterior", "dining", "room comfort", "local experience", "team service", "event atmosphere", "wellness", "family stay"][media_offset % 8]
            media_rows.append((media_id, client_id, 206, 1, 1, media_name, f"Campaign-ready {media_theme} image for {name}", dt(-15), dt(-1), None))
            media_ai_rows.append(
                (
                    media_id,
                    media_id,
                    f"{name} image showing {city} hospitality, {media_theme}, dining and guest experience.",
                    f"{name} lifestyle visual",
                    json.dumps(["hotel", "guest", media_theme, city.lower()]),
                    json.dumps(["warm", "welcoming", "campaign", media_theme]),
                    json.dumps(["hospitality", "local", "seasonal", name.lower(), media_theme]),
                    json.dumps({"quality": "approved"}),
                    json.dumps({"campaign_fit": "high", "theme": media_theme}),
                    f"Suggested caption for {name} focused on {media_theme} and local hospitality.",
                    json.dumps({}),
                    media_id,
                    None,
                    dt(-15),
                    dt(-1),
                    None,
                )
            )
            target_post_id = posted_post_ids[media_offset % len(posted_post_ids)] if posted_post_ids else max(1, post_id - 1)
            post_media_rows.append((media_id, target_post_id, media_id, media_id, media_offset + 1, dt(-4), dt(-1), None))
            media_id += 1
    insert_many(
        conn,
        """
        INSERT INTO content.content_topic
        (id, client_id, user_id, content_pillar_id, name, event_custom_id, inserted_datetime, updated_datetime, deleted_at, event_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        topic_rows,
    )
    insert_many(
        conn,
        """
        INSERT INTO content.content_topic_post
        (id, user_id, content_topic_id, social_network_type_id, content_post_status_id, post_datetime, post_text, inserted_datetime, updated_datetime, deleted_at, network_post_ref, location_id, brand_tone_score, content_post_type_id, brand_tone_score_tooltip, ai_generated, processing)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        post_rows,
    )
    insert_many(
        conn,
        """
        INSERT INTO content.content_topic_post_approval_status
        (id, user_id, content_topic_post_id, content_post_status_id, approval_rejection_text, valid_from_timestamp, valid_to_timestamp, deleted_at, content_post_approval_level_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        approval_rows,
    )
    insert_many(
        conn,
        "INSERT INTO media.media (id, client_id, user_id, media_type_id, media_status_id, name, description, inserted_datetime, updated_datetime, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        media_rows,
    )
    insert_many(
        conn,
        """
        INSERT INTO media.media_analysis_ai
        (id, media_id, short_description, alt_text, visual_tags, descriptive_tags, semantic_keywords, media_metadata, content_analysis, post_copy, dam_metadata, media_asset_id, embedding, inserted_datetime, updated_datetime, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        media_ai_rows,
    )
    insert_many(
        conn,
        "INSERT INTO content.content_topic_post_media (id, content_topic_post_id, media_id, media_asset_id, media_order, inserted_datetime, updated_datetime, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        post_media_rows,
    )
    insert_many(
        conn,
        """
        INSERT INTO analytics.social_media_post
        (id, social_network_type_id, identifier, post_ref, json_value, is_dirty, inserted_datetime, updated_datetime, created_at, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        analytics_rows,
    )


def seed_inbox_events(conn: sqlite3.Connection) -> None:
    interaction_rows = []
    message_rows = []
    triage_rows = []
    alert_rows = []
    reply_rows = []
    event_rows = []
    interaction_id = 1
    message_id = 1
    alert_id = 1
    event_id = 1
    seen_city_events: set[tuple[int, str]] = set()
    triages = ["reply_now", "needs_property_help", "waiting_on_property", "property_responded"]
    question_templates = [
        "Guest asks {name} about airport pickup in {city}.",
        "Complaint: guest says room cleaning was delayed at {name}.",
        "Guest asks {name} about dining timing in {city}.",
        "Issue: guest says their booking date looks incorrect for next week.",
        "Guest asks whether late checkout is possible at {name}.",
        "Review mention: guest praised staff but asked for parking details.",
        "Guest asks about nearby events and travel time from {name}.",
        "Complaint: guest is unhappy about noise near the room and needs property help.",
    ]
    for client_index, (client_id, name, _, city_id, city, _) in enumerate(CLIENTS):
        for offset in range(8):
            triage = triages[(client_index + offset) % len(triages)]
            title = f"{name} guest question {offset + 1}"
            interaction_rows.append((interaction_id, client_id, json.dumps({"source": "dummy"}), offset % 3, title))
            content = question_templates[offset % len(question_templates)].format(name=name, city=city)
            network_id = [1, 7, 9, 11][offset % 4]
            message_type = ["comments", "messages", "review", "mentions"][offset % 4]
            message_rows.append((message_id, client_id, f"src-{message_id}", dt(-offset), content, f"Guest {offset + 1}", f"https://example.test/messages/{message_id}", network_id, interaction_id, None, "new", "page", message_type, content, f"guest{offset}", "en", json.dumps({"name": f"Guest {offset + 1}"})))
            triage_rows.append((interaction_id, interaction_id, triage))
            if triage in {"waiting_on_property", "property_responded"}:
                alert_rows.append((alert_id, interaction_id, "sent", dt(-offset), None))
                if triage == "property_responded":
                    reply_rows.append((alert_id, alert_id, "Property confirmed the answer.", dt(-offset + 1), None))
                alert_id += 1
            interaction_id += 1
            message_id += 1
        for event_offset, event_name in enumerate(["Food Festival", "Jazz Night", "Design Market"]):
            event_key = (city_id, event_name)
            if event_key in seen_city_events:
                continue
            seen_city_events.add(event_key)
            event_rows.append(
                (
                    event_id,
                    city_id,
                    f"{city} {event_name}",
                    d(event_offset + 1),
                    "local_event",
                    f"{city} downtown",
                    "leisure guests",
                    None,
                )
            )
            event_id += 1
    insert_many(conn, "INSERT INTO jx_bridge.interactions (interaction_id, client_id, metadata, priority, title) VALUES (?, ?, ?, ?, ?)", interaction_rows)
    insert_many(
        conn,
        """
        INSERT INTO jx_bridge.messages
        (message_id, client_id, source_id, source_timestamp, content, author, permalink, social_network_type_id, interaction_id, parent_id, last_state, page_social_network_id, type, fts_content, fts_username, translated_language, user)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        message_rows,
    )
    insert_many(conn, "INSERT INTO jx_bridge.thread_triage (id, interaction_id, triage) VALUES (?, ?, ?)", triage_rows)
    insert_many(conn, "INSERT INTO jx_bridge.alerts (id, interaction_id, status, inserted_datetime, deleted_at) VALUES (?, ?, ?, ?, ?)", alert_rows)
    insert_many(conn, "INSERT INTO jx_bridge.alert_replies (id, alert_id, reply_text, inserted_datetime, deleted_at) VALUES (?, ?, ?, ?, ?)", reply_rows)
    insert_many(conn, "INSERT INTO general.events (id, world_city_id, name, date, type, location, audience, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", event_rows)


def main() -> None:
    reset_files()
    conn = connect()
    create_schema(conn)
    seed_reference(conn)
    seed_clients(conn)
    seed_content_media_analytics(conn)
    seed_inbox_events(conn)
    conn.commit()
    conn.close()
    print(f"Created dummy DB at {DB_DIR}")
    print(f"Seeded {len(CLIENTS)} clients with knowledge, content, inbox, media, analytics, access, and events data.")


if __name__ == "__main__":
    main()
