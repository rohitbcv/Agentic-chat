from __future__ import annotations

import logging
from os import getenv
from typing import Any

logger = logging.getLogger("agent_chat")


def _serpapi_key() -> str:
    return (getenv("SERPAPI_KEY") or "").strip()


def _is_enabled() -> bool:
    return bool(_serpapi_key())


def search_hotel_prices(
    property_name: str,
    city: str,
    check_in: str | None = None,
    check_out: str | None = None,
) -> dict[str, Any]:
    """Search OTA hotel prices via SerpAPI Google Hotels engine.

    Returns a dict with keys:
        results   - list of hotel/OTA result dicts
        source    - "serpapi" | "stub"
        query     - the search string used
        enabled   - whether a real API call was made
        error     - error message if the call failed (None on success)
    """
    query_parts = [property_name]
    if city:
        query_parts.append(city)

    search_query = " ".join(query_parts)

    if not _is_enabled():
        logger.warning("web_search: SERPAPI_KEY not set — returning stub response")
        return {
            "results": [],
            "source": "stub",
            "query": search_query,
            "enabled": False,
            "error": "SERPAPI_KEY is not configured. Add it to .env to enable live OTA price search.",
        }

    params: dict[str, Any] = {
        "engine": "google_hotels",
        "q": search_query,
        "api_key": _serpapi_key(),
        "gl": "us",
        "hl": "en",
        "currency": "USD",
    }
    if check_in:
        params["check_in_date"] = check_in
    if check_out:
        params["check_out_date"] = check_out

    try:
        from serpapi import GoogleSearch  # type: ignore[import]

        search = GoogleSearch(params)
        raw = search.get_dict()
        hotels = raw.get("properties") or raw.get("hotels_results") or []
        results = _parse_hotel_results(hotels)
        return {
            "results": results,
            "source": "serpapi",
            "query": search_query,
            "enabled": True,
            "error": None,
        }
    except ImportError:
        logger.error("web_search: google-search-results package not installed")
        return {
            "results": [],
            "source": "stub",
            "query": search_query,
            "enabled": False,
            "error": "google-search-results package is not installed. Run: pip install google-search-results",
        }
    except Exception as exc:
        logger.error("web_search: SerpAPI call failed: %s", exc)
        return {
            "results": [],
            "source": "serpapi",
            "query": search_query,
            "enabled": True,
            "error": str(exc),
        }


def _parse_hotel_results(hotels: list[Any]) -> list[dict[str, Any]]:
    """Normalise SerpAPI hotel result objects into a flat, consistent shape."""
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
        check_in = hotel.get("check_in_time") or ""
        check_out = hotel.get("check_out_time") or ""

        # OTA-level prices may appear in `rate_per_night.before_taxes_fees`
        # or in a `prices` sub-list
        ota_prices = _extract_ota_prices(hotel)

        results.append(
            {
                "name": name,
                "rate_per_night": rate_per_night,
                "total_rate": total_rate,
                "rating": rating,
                "reviews": reviews,
                "check_in": check_in,
                "check_out": check_out,
                "link": link,
                "ota_prices": ota_prices,
            }
        )
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
        ota.append(
            {
                "source": item.get("source") or item.get("provider") or "OTA",
                "rate": item.get("rate_per_night") or item.get("price") or "",
                "link": item.get("link") or item.get("url") or "",
            }
        )
    return ota


def web_search_status() -> dict[str, Any]:
    return {
        "enabled": _is_enabled(),
        "provider": "SerpAPI Google Hotels" if _is_enabled() else "not configured",
        "key_set": bool(_serpapi_key()),
    }
