from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from os import getenv
from typing import Any

logger = logging.getLogger("agent_chat")

_MAX_RETRIES = 2
_RETRY_DELAY_S = 1.5
_MAX_BOOKING_HORIZON_DAYS = 365


def _serpapi_key() -> str:
    return (getenv("SERPAPI_KEY") or "").strip()


def _is_enabled() -> bool:
    return bool(_serpapi_key())


# ---------------------------------------------------------------------------
# Guardrail 1 — Date validation
# ---------------------------------------------------------------------------

def validate_and_fix_dates(
    check_in: str | None,
    check_out: str | None,
) -> tuple[str, str, list[str]]:
    """Validate and sanitise check-in / check-out dates.

    Returns (check_in_iso, check_out_iso, warnings).
    Warnings are advisory; the function always returns usable dates.
    """
    today = date.today()
    default_in = today + timedelta(days=1)
    default_out = today + timedelta(days=2)
    warnings: list[str] = []

    # Parse check_in
    ci: date | None = None
    if check_in:
        try:
            ci = date.fromisoformat(check_in)
        except ValueError:
            warnings.append(f"Check-in date '{check_in}' could not be parsed — using tomorrow.")

    # Reject past dates
    if ci and ci < today:
        warnings.append(
            f"Check-in date {ci.isoformat()} is in the past — using tomorrow instead."
        )
        ci = None

    # Reject dates too far in the future
    if ci and (ci - today).days > _MAX_BOOKING_HORIZON_DAYS:
        warnings.append(
            f"Check-in date {ci.isoformat()} is more than {_MAX_BOOKING_HORIZON_DAYS} days out — "
            "OTA prices this far ahead are rarely reliable."
        )

    ci = ci or default_in

    # Parse check_out
    co: date | None = None
    if check_out:
        try:
            co = date.fromisoformat(check_out)
        except ValueError:
            warnings.append(f"Check-out date '{check_out}' could not be parsed — using the day after check-in.")

    # Fix reversed / same-day dates
    if co and co <= ci:
        warnings.append(
            f"Check-out date {co.isoformat()} is not after check-in {ci.isoformat()} — "
            "setting check-out to one day after check-in."
        )
        co = ci + timedelta(days=1)

    co = co or (ci + timedelta(days=1))

    return ci.isoformat(), co.isoformat(), warnings


# ---------------------------------------------------------------------------
# Guardrail 2 — Hotel name match (hallucination / wrong-hotel check)
# ---------------------------------------------------------------------------

def _name_tokens(name: str) -> set[str]:
    """Lowercase alphabetic tokens ≥ 3 chars from a hotel name."""
    return {t for t in re.findall(r"[a-z]{3,}", name.lower()) if t not in {"the", "and", "for", "hotel", "inn"}}


def check_hotel_name_match(queried: str, returned: str) -> tuple[float, str]:
    """Return (confidence 0-1, warning_message_or_empty).

    Compares token overlap between the queried property name and the
    hotel name returned by SerpAPI to catch wrong-hotel results.
    """
    qt = _name_tokens(queried)
    rt = _name_tokens(returned)
    if not qt or not rt:
        return 1.0, ""
    overlap = qt & rt
    score = len(overlap) / max(len(qt), len(rt))
    if score < 0.25:
        return score, (
            f"The OTA result '{returned}' may not match the queried property '{queried}' "
            f"(name match confidence: {round(score * 100)}%). "
            "Verify the hotel identity before using these prices."
        )
    return score, ""


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def search_hotel_prices(
    property_name: str,
    city: str,
    check_in: str | None = None,
    check_out: str | None = None,
) -> dict[str, Any]:
    """Search OTA hotel prices via SerpAPI Google Hotels engine.

    Returns a dict with keys:
        results          - list of hotel/OTA result dicts
        source           - "serpapi" | "stub"
        query            - the search string used
        enabled          - whether a real API call was made
        error            - error message if the call failed (None on success)
        fetched_at       - ISO timestamp of when the data was retrieved
        date_warnings    - list of date-validation warnings
        name_warnings    - list of hotel-name-match warnings
        check_in         - effective check-in date used
        check_out        - effective check-out date used
    """
    query_parts = [property_name]
    if city:
        query_parts.append(city)
    search_query = " ".join(query_parts)

    # Guardrail 1 — validate dates
    effective_in, effective_out, date_warnings = validate_and_fix_dates(check_in, check_out)

    fetched_at = datetime.now(timezone.utc).isoformat()

    if not _is_enabled():
        logger.warning("web_search: SERPAPI_KEY not set — returning stub response")
        return {
            "results": [],
            "source": "stub",
            "query": search_query,
            "enabled": False,
            "error": "SERPAPI_KEY is not configured. Add it to .env to enable live OTA price search.",
            "fetched_at": fetched_at,
            "date_warnings": date_warnings,
            "name_warnings": [],
            "check_in": effective_in,
            "check_out": effective_out,
        }

    params: dict[str, Any] = {
        "engine": "google_hotels",
        "q": search_query,
        "api_key": _serpapi_key(),
        "gl": "us",
        "hl": "en",
        "currency": "USD",
        "check_in_date": effective_in,
        "check_out_date": effective_out,
    }

    # Guardrail 5 — retry on transient failure
    last_error: str | None = None
    raw: dict[str, Any] = {}
    for attempt in range(1, _MAX_RETRIES + 2):
        try:
            from serpapi import GoogleSearch  # type: ignore[import]
            raw = GoogleSearch(params).get_dict()
            if raw.get("error") and attempt <= _MAX_RETRIES:
                last_error = str(raw["error"])
                logger.warning("web_search: attempt %d failed: %s — retrying", attempt, last_error)
                time.sleep(_RETRY_DELAY_S)
                continue
            last_error = raw.get("error")
            break
        except ImportError:
            return {
                "results": [],
                "source": "stub",
                "query": search_query,
                "enabled": False,
                "error": "google-search-results package not installed. Run: pip install google-search-results",
                "fetched_at": fetched_at,
                "date_warnings": date_warnings,
                "name_warnings": [],
                "check_in": effective_in,
                "check_out": effective_out,
            }
        except Exception as exc:
            last_error = str(exc)
            logger.warning("web_search: attempt %d exception: %s", attempt, exc)
            if attempt <= _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_S)

    fetched_at = datetime.now(timezone.utc).isoformat()

    if last_error and not raw.get("name") and not (raw.get("properties") or raw.get("hotels_results")):
        return {
            "results": [],
            "source": "serpapi",
            "query": search_query,
            "enabled": True,
            "error": last_error,
            "fetched_at": fetched_at,
            "date_warnings": date_warnings,
            "name_warnings": [],
            "check_in": effective_in,
            "check_out": effective_out,
        }

    hotels_list = raw.get("properties") or raw.get("hotels_results") or []
    if hotels_list:
        results = _parse_hotel_results(hotels_list)
        # Stage 2 — fetch room-level detail for the best-matching hotel
        best_hotel_raw = _find_best_hotel_raw(hotels_list, property_name)
        property_token = best_hotel_raw.get("property_token") if best_hotel_raw else None
        if property_token:
            detail_raw = _fetch_property_detail(property_token, effective_in, effective_out)
            if detail_raw:
                detail_results = _parse_single_hotel(detail_raw)
                if detail_results:
                    # Merge room categories from the detail page into the matching result
                    detail_hotel = detail_results[0]
                    for r in results:
                        if _name_tokens(r.get("name") or "") & _name_tokens(detail_hotel.get("name") or ""):
                            r["room_categories"] = detail_hotel.get("room_categories") or r.get("room_categories") or []
                            r["ota_prices"] = detail_hotel.get("ota_prices") or r.get("ota_prices") or []
                            break
    else:
        results = _parse_single_hotel(raw)

    # Guardrail 2 — hotel name match check
    name_warnings: list[str] = []
    for r in results:
        _, warning = check_hotel_name_match(property_name, r.get("name") or "")
        if warning and warning not in name_warnings:
            name_warnings.append(warning)

    return {
        "results": results,
        "source": "serpapi",
        "query": search_query,
        "enabled": True,
        "error": None,
        "fetched_at": fetched_at,
        "date_warnings": date_warnings,
        "name_warnings": name_warnings,
        "check_in": effective_in,
        "check_out": effective_out,
    }


# ---------------------------------------------------------------------------
# Stage-2 helpers — property detail fetch
# ---------------------------------------------------------------------------

def _find_best_hotel_raw(hotels_list: list[Any], queried_name: str) -> dict[str, Any] | None:
    """Return the hotel dict from the list whose name best matches `queried_name`."""
    best: dict[str, Any] | None = None
    best_score = -1.0
    qt = _name_tokens(queried_name)
    for hotel in hotels_list[:5]:
        if not isinstance(hotel, dict):
            continue
        name = hotel.get("name") or ""
        rt = _name_tokens(name)
        if not qt or not rt:
            if best is None:
                best = hotel
            continue
        score = len(qt & rt) / max(len(qt), len(rt))
        if score > best_score:
            best_score = score
            best = hotel
    return best


def _fetch_property_detail(
    property_token: str,
    check_in: str,
    check_out: str,
) -> dict[str, Any] | None:
    """Call SerpAPI Google Hotels property-detail endpoint for a specific token.

    Returns the raw dict or None on failure.
    Room-type pricing lives in raw["prices"] on the detail page.
    """
    params: dict[str, Any] = {
        "engine": "google_hotels",
        "property_token": property_token,
        "api_key": _serpapi_key(),
        "gl": "us",
        "hl": "en",
        "currency": "USD",
        "check_in_date": check_in,
        "check_out_date": check_out,
    }
    try:
        from serpapi import GoogleSearch  # type: ignore[import]
        raw = GoogleSearch(params).get_dict()
        if raw.get("error"):
            logger.warning("web_search: property detail fetch failed: %s", raw["error"])
            return None
        return raw
    except Exception as exc:
        logger.warning("web_search: property detail exception: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _extract_room_categories(prices: list[Any]) -> list[dict[str, Any]]:
    """Group SerpAPI price entries by room_type to build a room category breakdown.

    Each category entry:
        room_type   - str  (e.g. "Deluxe Room", "Junior Suite")
        lowest_rate - str  (cheapest rate across OTAs for this room)
        offers      - list of {source, rate, total_rate, link, num_guests}
    """
    from collections import defaultdict

    bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in prices:
        if not isinstance(item, dict):
            continue
        room_type = (
            item.get("room_type")
            or item.get("type")
            or item.get("room_name")
            or item.get("description")
            or ""
        ).strip()
        # Use internal sentinel when no room type is provided by the API.
        # "__unknown__" is filtered out at the end so the UI can show
        # a flat fallback list instead of a misleading "Standard Room" label.
        if not room_type:
            room_type = "__unknown__"

        rpn = item.get("rate_per_night")
        rate_str = ""
        if isinstance(rpn, dict):
            rate_str = rpn.get("lowest") or rpn.get("before_taxes_fees") or ""
        elif isinstance(rpn, (str, int, float)):
            rate_str = str(rpn)

        tr = item.get("total_rate")
        total_str = ""
        if isinstance(tr, dict):
            total_str = tr.get("lowest") or tr.get("before_taxes_fees") or ""
        elif isinstance(tr, (str, int, float)):
            total_str = str(tr)

        bucket[room_type].append({
            "source": item.get("source") or "OTA",
            "rate": rate_str,
            "total_rate": total_str,
            "link": item.get("link") or "",
            "num_guests": item.get("num_guests") or item.get("guests"),
        })

    categories: list[dict[str, Any]] = []
    for room_type, offers in bucket.items():
        # Find the lowest numeric rate for sorting / headline display
        numeric_rates = []
        for o in offers:
            raw_rate = re.sub(r"[^\d.]", "", o["rate"])
            try:
                numeric_rates.append(float(raw_rate))
            except ValueError:
                pass
        lowest = f"${min(numeric_rates):.0f}" if numeric_rates else (offers[0]["rate"] if offers else "N/A")

        categories.append({
            "room_type": room_type,
            "lowest_rate": lowest,
            "currency": "USD",
            "offers": offers[:8],
        })

    # Sort: named suites/deluxe last, standard first; then by numeric lowest rate
    def _sort_key(cat: dict[str, Any]) -> tuple[int, float]:
        tier_order = 0
        rt = cat["room_type"].lower()
        if any(w in rt for w in ("suite", "penthouse", "presidential")):
            tier_order = 3
        elif any(w in rt for w in ("deluxe", "premium", "superior", "executive")):
            tier_order = 2
        elif any(w in rt for w in ("junior", "club", "grand")):
            tier_order = 1
        raw = re.sub(r"[^\d.]", "", cat["lowest_rate"])
        try:
            price = float(raw)
        except ValueError:
            price = 9999.0
        return (tier_order, price)

    categories.sort(key=_sort_key)

    # If every category is the sentinel (API returned no room_type at all),
    # return an empty list so the UI can show a plain flat OTA price list
    # instead of a misleading "Standard Room" heading.
    real_categories = [c for c in categories if c["room_type"] != "__unknown__"]
    return real_categories


def _parse_single_hotel(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse a SerpAPI single-hotel detail page."""
    name = raw.get("name") or ""
    if not name:
        return []

    rate_per_night = _extract_rate(raw)
    total_rate = _extract_total_rate(raw)
    link = raw.get("link") or ""
    rating = raw.get("overall_rating") or raw.get("rating")
    reviews = raw.get("reviews") or raw.get("review_count")
    check_in_time = raw.get("check_in_time") or ""
    check_out_time = raw.get("check_out_time") or ""

    prices_raw = raw.get("prices") or []
    ota_prices: list[dict[str, Any]] = []
    for item in prices_raw[:10]:
        if not isinstance(item, dict):
            continue
        rpn = item.get("rate_per_night")
        rate_str = (
            rpn.get("lowest") or rpn.get("before_taxes_fees")
            if isinstance(rpn, dict) else str(rpn or "")
        )
        ota_prices.append({
            "source": item.get("source") or "OTA",
            "rate": rate_str,
            "link": item.get("link") or "",
            "currency": "USD",
            "room_type": item.get("room_type") or "",
            "num_guests": item.get("num_guests"),
        })

    room_categories = _extract_room_categories(prices_raw)

    return [{
        "name": name,
        "rate_per_night": rate_per_night,
        "total_rate": total_rate,
        "rating": rating,
        "reviews": reviews,
        "check_in_time": check_in_time,
        "check_out_time": check_out_time,
        "link": link,
        "ota_prices": ota_prices,
        "room_categories": room_categories,
        "currency": "USD",
    }]


def _parse_hotel_results(hotels: list[Any]) -> list[dict[str, Any]]:
    """Normalise a list of SerpAPI hotel result objects."""
    results: list[dict[str, Any]] = []
    for hotel in hotels[:8]:
        if not isinstance(hotel, dict):
            continue

        name = hotel.get("name") or hotel.get("hotel_name") or ""
        rate_per_night = _extract_rate(hotel)
        total_rate = _extract_total_rate(hotel)
        link = hotel.get("link") or hotel.get("url") or ""
        rating = hotel.get("overall_rating") or hotel.get("rating")
        reviews = hotel.get("reviews") or hotel.get("review_count")
        check_in_time = hotel.get("check_in_time") or ""
        check_out_time = hotel.get("check_out_time") or ""
        prices_raw = hotel.get("prices") or hotel.get("deal_prices") or []
        ota_prices = _extract_ota_prices(hotel)
        room_categories = _extract_room_categories(prices_raw)

        results.append({
            "name": name,
            "rate_per_night": rate_per_night,
            "total_rate": total_rate,
            "rating": rating,
            "reviews": reviews,
            "check_in_time": check_in_time,
            "check_out_time": check_out_time,
            "link": link,
            "ota_prices": ota_prices,
            "room_categories": room_categories,
            "currency": "USD",
        })
    return results


def _extract_rate(hotel: dict[str, Any]) -> str | None:
    rpn = hotel.get("rate_per_night")
    if isinstance(rpn, dict):
        return rpn.get("lowest") or rpn.get("before_taxes_fees")
    if isinstance(rpn, str):
        return rpn
    return hotel.get("price") or hotel.get("rate")


def _extract_total_rate(hotel: dict[str, Any]) -> str | None:
    tr = hotel.get("total_rate")
    if isinstance(tr, dict):
        return tr.get("lowest") or tr.get("before_taxes_fees")
    if isinstance(tr, str):
        return tr
    return None


def _extract_ota_prices(hotel: dict[str, Any]) -> list[dict[str, Any]]:
    prices = hotel.get("prices") or hotel.get("deal_prices") or []
    ota: list[dict[str, Any]] = []
    for item in prices[:10]:
        if not isinstance(item, dict):
            continue
        rpn = item.get("rate_per_night")
        rate_str = (
            rpn.get("lowest") or rpn.get("before_taxes_fees")
            if isinstance(rpn, dict) else str(rpn or "")
        ) or item.get("price") or ""
        ota.append({
            "source": item.get("source") or item.get("provider") or "OTA",
            "rate": rate_str,
            "link": item.get("link") or item.get("url") or "",
            "currency": "USD",
            "room_type": item.get("room_type") or "",
            "num_guests": item.get("num_guests"),
        })
    return ota


def web_search_status() -> dict[str, Any]:
    return {
        "enabled": _is_enabled(),
        "provider": "SerpAPI Google Hotels" if _is_enabled() else "not configured",
        "key_set": bool(_serpapi_key()),
    }
