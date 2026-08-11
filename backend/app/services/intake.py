from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Any

from ..contracts import AccessScope, DateRange, ExtractedEntities, RoutingPayload
from ..db import repository
from ..poc.mock_data import MOCK_CLIENTS

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "show",
    "tell",
    "the",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
}

CLIENT_NAME_STOPWORDS = {
    "and",
    "at",
    "collection",
    "group",
    "hotel",
    "hotels",
    "motel",
    "palace",
    "property",
    "resort",
    "resorts",
    "the",
}

ACTION_PATTERNS = (
    "send ",
    "approve ",
    "publish ",
    "assign ",
    "create ",
    "update ",
    "delete ",
    "grant ",
    "revoke ",
)

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "inbox": ("complaint", "complaints", "thread", "threads", "waiting on property", "reply now", "triage", "message", "messages", "unresolved"),
    "client_knowledge": (
        "pool",
        "check in",
        "check-in",
        "check out",
        "check-out",
        "tone",
        "voice",
        "amenities",
        "faq",
        "policy",
        "what do we know",
        "competitor",
        "competitors",
        "competition",
        "competitive",
        "comp set",
        "compset",
        "comparable",
        "comparables",
        "similar hotels",
    ),
    "content": ("scheduled", "schedule", "draft", "approval", "post", "posts", "caption", "performance", "engagement", "likes", "comments", "published"),
    "media": ("media", "visual", "visuals", "asset", "assets", "image", "images", "photo", "photos", "creative"),
    "event": ("event", "events", "festival", "nearby", "coming up"),
    "access": (
        "who has access",
        "access",
        "collaborator",
        "collaborators",
        "organization",
        "owner",
        "role",
        "relationship",
        "relationships",
        "connected",
        "connection",
        "connections",
        "linked",
        "related",
        "graph",
    ),
}

CHANNEL_PATTERNS = {
    "instagram": ("instagram", "instagram_graph"),
    "facebook": ("facebook",),
    "linkedin": ("linkedin",),
    "tiktok": ("tiktok",),
    "twitter": ("twitter", "x "),
    "google": ("google",),
    "booking": ("booking",),
}


def normalize_text(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9\s\-']", " ", lowered)
    return " ".join(lowered.split())


def _name_tokens(value: str, *, drop_generic: bool = True) -> set[str]:
    normalized = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    tokens = {token for token in normalized.split() if len(token) > 1}
    if drop_generic:
        tokens = {token for token in tokens if token not in CLIENT_NAME_STOPWORDS}
    return tokens


def preprocess_query(query: str) -> tuple[str, str, str]:
    cleaned = " ".join((query or "").strip().split())
    normalized = normalize_text(cleaned)
    language = "en" if cleaned and sum(1 for ch in cleaned if ch.isascii()) / max(len(cleaned), 1) > 0.9 else "unknown"
    return cleaned, normalized, language


def extract_date_range(normalized_query: str) -> DateRange | None:
    today = date.today()
    if "next week" in normalized_query:
        days_until_next_monday = (7 - today.weekday()) or 7
        start = today + timedelta(days=days_until_next_monday)
        end = start + timedelta(days=6)
        return DateRange(label="next_week", start=start, end=end, grain="week")
    if "last 30 days" in normalized_query:
        return DateRange(label="last_30_days", start=today - timedelta(days=29), end=today, grain="day")
    if "last 7 days" in normalized_query:
        return DateRange(label="last_7_days", start=today - timedelta(days=6), end=today, grain="day")
    if "today" in normalized_query:
        return DateRange(label="today", start=today, end=today, grain="day")
    if "yesterday" in normalized_query:
        yesterday = today - timedelta(days=1)
        return DateRange(label="yesterday", start=yesterday, end=yesterday, grain="day")
    return None


def _fallback_clients() -> list[dict[str, Any]]:
    return [
        {
            "id": int(client["id"]),
            "name": str(client["name"]),
            "organization_id": None,
            "world_city_id": None,
            "city": str(client.get("city") or "") or None,
        }
        for client in MOCK_CLIENTS
    ]


def load_client_catalog() -> list[dict[str, Any]]:
    rows = repository.get_client_catalog() if repository._db_enabled() else []
    if not rows:
        return _fallback_clients()
    catalog = []
    mock_city_by_name = {normalize_text(client["name"]): client.get("city") for client in MOCK_CLIENTS}
    for row in rows:
        catalog.append(
            {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "organization_id": row.get("organization_id"),
                "world_city_id": row.get("world_city_id"),
                "city": mock_city_by_name.get(normalize_text(str(row["name"])), None),
            }
        )
    return catalog


def _resolve_client_from_query(normalized_query: str, explicit_client_id: int | None, catalog: list[dict[str, Any]]) -> tuple[int | None, str | None, str | None]:
    # Priority 1: explicit numeric client ID mentioned in the query itself
    # (e.g. "client 7403", "client_id=7403").  This always wins over everything.
    client_id_match = re.search(r"\bclient(?:id|\s+id)?\s+(\d+)\b", normalized_query)
    if client_id_match:
        resolved_id = int(client_id_match.group(1))
        for client in catalog:
            if int(client["id"]) == resolved_id:
                return resolved_id, str(client["name"]), client.get("city")
        return resolved_id, None, None

    # Priority 2: exact name match anywhere in the query (longest first to avoid
    # a short name swallowing a longer one, e.g. "Inn" vs "The Inn at Somewhere").
    for client in sorted(catalog, key=lambda item: len(str(item["name"])), reverse=True):
        normalized_name = normalize_text(str(client["name"]))
        if normalized_name and normalized_name in normalized_query:
            return int(client["id"]), str(client["name"]), client.get("city")

    # Priority 3: fuzzy token overlap — distinctive tokens that unambiguously
    # identify one client.
    query_tokens = _name_tokens(normalized_query, drop_generic=True)
    if query_tokens:
        candidates: list[tuple[float, int, dict[str, Any]]] = []
        for client in catalog:
            raw_name = str(client["name"])
            name_tokens = _name_tokens(raw_name, drop_generic=True)
            if not name_tokens:
                continue
            overlap = name_tokens & query_tokens
            if not overlap:
                continue

            has_multi_token_alias = len(overlap) >= 2
            has_unique_name_token = len(name_tokens) == 1 and len(next(iter(overlap))) >= 4
            has_distinctive_token = any(len(token) >= 5 for token in overlap)
            if not (has_multi_token_alias or has_unique_name_token or has_distinctive_token):
                continue

            coverage = len(overlap) / max(len(name_tokens), 1)
            query_coverage = len(overlap) / max(len(query_tokens), 1)
            score = (coverage * 0.7) + (query_coverage * 0.3)
            candidates.append((score, len(overlap), client))

        if candidates:
            candidates.sort(key=lambda item: (item[0], item[1], len(str(item[2]["name"]))), reverse=True)
            best_score, best_overlap, best_client = candidates[0]
            tied = [
                c
                for s, o, c in candidates[1:]
                if abs(s - best_score) < 0.08 and o == best_overlap
            ]
            if not tied:
                return int(best_client["id"]), str(best_client["name"]), best_client.get("city")

    # Priority 4: session/dropdown client passed from the frontend — only used
    # when the query itself does not name any client.
    if explicit_client_id is not None:
        for client in catalog:
            if int(client["id"]) == int(explicit_client_id):
                return int(client["id"]), str(client["name"]), client.get("city")
        return explicit_client_id, None, None

    return None, None, None


def extract_entities(query: str, normalized_query: str, explicit_client_id: int | None, user_id: int | None = None) -> ExtractedEntities:
    catalog = load_client_catalog()
    client_id, property_name, city = _resolve_client_from_query(normalized_query, explicit_client_id, catalog)

    channel = None
    for label, aliases in CHANNEL_PATTERNS.items():
        if any(alias in normalized_query for alias in aliases):
            channel = label
            break

    thread_match = re.search(r"\b(?:thread|interaction)\s*(?:id)?\s*(\d+)\b", normalized_query)
    topic_match = re.search(r"\bfor\s+([a-z0-9\s\-']+?)\s+campaign\b", normalized_query)
    media_theme = topic_match.group(1).strip() if topic_match else None
    audience = "luxury travelers" if "luxury" in normalized_query else None
    event = "festival" if "festival" in normalized_query else None
    topic = "performance" if any(word in normalized_query for word in ("performance", "engagement")) else None

    return ExtractedEntities(
        user_id=user_id,
        client_id=client_id,
        property_name=property_name,
        city=city,
        channel=channel,
        thread_id=thread_match.group(1) if thread_match else None,
        event=event,
        audience=audience,
        topic=topic,
        media_theme=media_theme,
        date_range=extract_date_range(normalized_query),
    )


def classify_intent(normalized_query: str, entities: ExtractedEntities) -> str:
    if any(normalized_query.startswith(pattern) for pattern in ACTION_PATTERNS):
        return "unsupported_action"

    if any(word in normalized_query for word in ("relationship", "relationships", "connected", "connection", "connections", "linked", "graph")):
        return "access"

    for intent, keywords in INTENT_KEYWORDS.items():
        if any(keyword in normalized_query for keyword in keywords):
            return intent

    if entities.property_name or entities.client_id is not None:
        return "client_knowledge"
    return "clarification"


def resolve_access_scope(entities: ExtractedEntities, catalog: list[dict[str, Any]]) -> AccessScope:
    if entities.client_id is not None:
        organization_ids = [
            int(client["organization_id"])
            for client in catalog
            if client.get("organization_id") is not None and int(client["id"]) == int(entities.client_id)
        ]
        return AccessScope(
            organization_ids=organization_ids,
            client_ids=[int(entities.client_id)],
            domains=["inbox", "content", "media", "knowledge", "access", "events"],
            scope_source="client_scoped",
        )

    organization_ids = sorted(
        {
            int(client["organization_id"])
            for client in catalog
            if client.get("organization_id") is not None
        }
    )
    client_ids = [int(client["id"]) for client in catalog]
    return AccessScope(
        organization_ids=organization_ids,
        client_ids=client_ids,
        domains=["inbox", "content", "media", "knowledge", "access", "events"],
        scope_source="catalog_scoped",
    )


def build_routing_payload(query: str, explicit_client_id: int | None = None, user_id: int | None = None) -> RoutingPayload:
    cleaned_query, normalized_query, language = preprocess_query(query)
    catalog = load_client_catalog()
    entities = extract_entities(cleaned_query, normalized_query, explicit_client_id, user_id=user_id)
    scope = resolve_access_scope(entities, catalog)
    intent = classify_intent(normalized_query, entities)
    return RoutingPayload(
        query=cleaned_query,
        cleaned_query=cleaned_query,
        normalized_query=normalized_query,
        language=language,
        intent=intent,
        entities=entities,
        scope=scope,
    )
