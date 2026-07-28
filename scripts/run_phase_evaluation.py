from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv()

from backend.app.main import app


@dataclass
class EvalCase:
    query: str
    expected_agent: str | None = None
    expected_capability: str | None = None
    expected_support: str | None = None
    expected_client_id: int | None = None
    expected_status: int = 200
    should_hide_debug_text: bool = True
    expected_answer_contains: str | None = None
    forbidden_answer_contains: str | None = None
    min_media_previews: int = 0


CASES = [
    EvalCase(
        query="What do we know about Hotel Ramtin?",
        expected_agent="Client Knowledge and FAQ Agent",
        expected_capability="property_knowledge_summary",
        expected_support="fully_supported",
    ),
    EvalCase(
        query="Does Hotel Ramtin have cab service?",
        expected_agent="Client Knowledge and FAQ Agent",
        expected_capability="property_fact_lookup",
        expected_support="fully_supported",
    ),
    EvalCase(
        query="Does Hotel Ramtin have pool at its property?",
        expected_agent="Client Knowledge and FAQ Agent",
        expected_capability="property_fact_lookup",
        expected_support="fully_supported",
        expected_answer_contains="No positive confirmation",
        forbidden_answer_contains="Business hotel with quick guest-service operations",
    ),
    EvalCase(
        query="Does Hotel Ramtin have a helipad?",
        expected_agent="Client Knowledge and FAQ Agent",
        expected_capability="property_fact_lookup",
        expected_support="not_supported",
        expected_answer_contains="couldn't verify",
    ),
    EvalCase(
        query="What posts are scheduled for Hotel d'Angleterre?",
        expected_agent="Content Planning Agent",
        expected_capability="content_schedule_lookup",
        expected_support="fully_supported",
    ),
    EvalCase(
        query="Which posts are waiting for approval for Hotel d'Angleterre?",
        expected_agent="Content Planning Agent",
        expected_capability="content_approval_lookup",
        expected_support="fully_supported",
    ),
    EvalCase(
        query="How is the last TikTok post performing for client 7403?",
        expected_agent="Content Planning Agent",
        expected_capability="post_performance_lookup",
        expected_support="partially_supported",
        min_media_previews=1,
    ),
    EvalCase(
        query="In my last TikTok post, which media has been used and what is the post copy for client 7403?",
        expected_agent="Content Planning Agent",
        expected_capability="content_post_detail_lookup",
        expected_support="fully_supported",
        expected_answer_contains="Post copy:",
        forbidden_answer_contains="The next ones are",
        min_media_previews=1,
    ),
    EvalCase(
        query="How is client 7403 connected to posts, media, metrics and events?",
        expected_agent="Access and Relationship Agent",
        expected_capability="relationship_lookup",
        expected_support="fully_supported",
        expected_answer_contains="Connection summary",
        forbidden_answer_contains="could not verify the full set",
    ),
    EvalCase(
        query="Who are competitors of Hotel Ramtin?",
        expected_agent="Access and Relationship Agent",
        expected_capability="competitor_lookup",
        expected_support="partially_supported",
        expected_client_id=7403,
        expected_answer_contains="inferred comparable",
        forbidden_answer_contains="competitors policy",
    ),
    EvalCase(
        query="Find media for Red Carnation Hotels Collection",
        expected_agent="Media Discovery Agent",
        expected_capability="media_recommendation",
        expected_support="fully_supported",
    ),
    EvalCase(
        query="Who has access to hotel Yash?",
        expected_agent="Access and Relationship Agent",
        expected_capability="client_access_lookup",
        expected_support="fully_supported",
    ),
    EvalCase(
        query="What events are coming up for Hotel Hafenresidenz?",
        expected_agent="Access and Relationship Agent",
        expected_capability="event_lookup",
        expected_support="fully_supported",
    ),
    EvalCase(
        query="What active inbox threads are there for hotel Yash?",
        expected_agent="Inbox and Complaint Agent",
        expected_capability="inbox_lookup",
        expected_support="fully_supported",
    ),
    EvalCase(
        query="Show complaint threads for Snow Villa",
        expected_agent="Inbox and Complaint Agent",
        expected_capability="inbox_lookup",
        expected_support="fully_supported",
        expected_client_id=1010,
        expected_answer_contains="Snow Villa Manali",
        forbidden_answer_contains="Hotel Ramtin",
    ),
    EvalCase(
        query="Is there any complaint for Hotel Ramtin?",
        expected_agent="Inbox and Complaint Agent",
        expected_capability="inbox_lookup",
        expected_support="fully_supported",
        expected_client_id=7403,
        expected_answer_contains="Hotel Ramtin",
        forbidden_answer_contains="Snow Villa",
    ),
    EvalCase(
        query="Publish this post for Hotel Ramtin",
        expected_status=403,
        should_hide_debug_text=False,
    ),
]

DEBUG_TEXT_MARKERS = [
    "content.content_topic_post",
    "clients.client_notes",
    "analytics.social_media_post",
    "Show the approved SQL template",
    "Explain why this route",
    "mock POC",
    "Source type:",
    "Aliases:",
]


def _check_response(case: EvalCase, status_code: int, data: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if status_code != case.expected_status:
        failures.append(f"expected status {case.expected_status}, got {status_code}")
        return failures
    if status_code != 200:
        return failures

    route = data.get("route") or {}
    context = data.get("context") or {}
    answer = str(data.get("answer") or "")

    if case.expected_agent and route.get("next_agent") != case.expected_agent:
        failures.append(f"expected agent {case.expected_agent}, got {route.get('next_agent')}")
    if case.expected_capability and route.get("capability") != case.expected_capability:
        failures.append(f"expected capability {case.expected_capability}, got {route.get('capability')}")
    if case.expected_support and context.get("support_level") != case.expected_support:
        failures.append(f"expected support {case.expected_support}, got {context.get('support_level')}")
    if case.expected_client_id is not None and data.get("client_id") != case.expected_client_id:
        failures.append(f"expected client_id {case.expected_client_id}, got {data.get('client_id')}")
    if case.should_hide_debug_text:
        for marker in DEBUG_TEXT_MARKERS:
            if marker in answer:
                failures.append(f"answer leaked debug marker: {marker}")
    if case.expected_answer_contains and case.expected_answer_contains.lower() not in answer.lower():
        failures.append(f"answer did not contain expected text: {case.expected_answer_contains}")
    if case.forbidden_answer_contains and case.forbidden_answer_contains.lower() in answer.lower():
        failures.append(f"answer contained forbidden text: {case.forbidden_answer_contains}")
    if len(data.get("media_previews") or []) < case.min_media_previews:
        failures.append(f"expected at least {case.min_media_previews} media preview(s), got {len(data.get('media_previews') or [])}")
    if not answer.strip():
        failures.append("answer was empty")
    if not data.get("safety"):
        failures.append("missing safety block")
    if not data.get("audit_event"):
        failures.append("missing audit event")
    return failures


def main() -> int:
    client = TestClient(app)
    passed = 0
    failed = 0

    print("Read-only multi-agent phase evaluation")
    print("=" * 44)
    for case in CASES:
        response = client.post("/api/agent-poc/chat", json={"query": case.query, "mode": "read_only"})
        try:
            data = response.json()
        except Exception:
            data = {}
        failures = _check_response(case, response.status_code, data)
        if failures:
            failed += 1
            print(f"FAIL: {case.query}")
            for failure in failures:
                print(f"  - {failure}")
        else:
            passed += 1
            route = data.get("route") or {}
            print(f"PASS: {case.query} -> {route.get('next_agent', 'blocked')} / {route.get('capability', 'policy')}")

    print("=" * 44)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
