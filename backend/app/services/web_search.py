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
# Parsers
# ---------------------------------------------------------------------------

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

    ota_prices: list[dict[str, str]] = []
    for item in (raw.get("prices") or [])[:8]:
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
            "currency": "USD",  # Guardrail 4 — explicit currency label
        })

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
        "currency": "USD",  # Guardrail 4
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
        ota_prices = _extract_ota_prices(hotel)

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
            "currency": "USD",  # Guardrail 4
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


def _extract_ota_prices(hotel: dict[str, Any]) -> list[dict[str, str]]:
    prices = hotel.get("prices") or hotel.get("deal_prices") or []
    ota: list[dict[str, str]] = []
    for item in prices[:6]:
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
            "currency": "USD",  # Guardrail 4
        })
    return ota


def web_search_status() -> dict[str, Any]:
    return {
        "enabled": _is_enabled(),
        "provider": "SerpAPI Google Hotels" if _is_enabled() else "not configured",
        "key_set": bool(_serpapi_key()),
    }
