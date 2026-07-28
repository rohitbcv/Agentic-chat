from __future__ import annotations

import json
import re
from typing import Any

from fastapi.responses import JSONResponse


READ_ONLY_ROUTE_PREFIXES = ("/api/agent-poc",)
BLOCKED_HTTP_METHODS = frozenset({"PUT", "PATCH", "DELETE"})
INFORMATIONAL_PREFIXES = (
    "how do i ",
    "how can i ",
    "what is the process to ",
    "what steps do i follow to ",
    "can you explain how to ",
    "tell me how to ",
    "what happens if we ",
)

BLOCKED_ACTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "send",
        re.compile(r"\bsend\s+(?:this|that|it|the|a|an|my|our)?\s*(?:reply|message|response|draft)\b", re.IGNORECASE),
    ),
    (
        "approve",
        re.compile(r"\bapprove\s+(?:this|that|it|the|a|an|my|our)?\s*(?:draft|post|content|caption)\b", re.IGNORECASE),
    ),
    (
        "publish",
        re.compile(r"\bpublish\s+(?:this|that|it|the|a|an|my|our)?\s*(?:draft|post|content|caption)\b", re.IGNORECASE),
    ),
    (
        "assign",
        re.compile(r"\bassign\s+(?:this|that|it|the|a|an|my|our)?\s*(?:thread|ticket|conversation|message|post)\b", re.IGNORECASE),
    ),
    (
        "create",
        re.compile(r"\bcreate\s+(?:this|that|it|the|a|an|my|our)?\s*(?:alert|note|reply|draft|assignment)\b", re.IGNORECASE),
    ),
    (
        "update",
        re.compile(r"\bupdate\s+(?:this|that|it|the|a|an|my|our)?\s*(?:note|guideline|draft|post|reply|access|assignment|client|property)\b", re.IGNORECASE),
    ),
    (
        "delete",
        re.compile(r"\bdelete\s+(?:this|that|it|the|a|an|my|our)?\s*(?:note|guideline|draft|post|reply|access|assignment|client|property)\b", re.IGNORECASE),
    ),
    (
        "edit",
        re.compile(r"\bedit\s+(?:this|that|it|the|a|an|my|our)?\s*(?:note|guideline|draft|post|reply|caption|content)\b", re.IGNORECASE),
    ),
    (
        "grant",
        re.compile(r"\bgrant\s+(?:this|that|it|the|a|an|my|our)?\s*(?:access|permission|permissions|role)\b", re.IGNORECASE),
    ),
    (
        "revoke",
        re.compile(r"\brevoke\s+(?:this|that|it|the|a|an|my|our)?\s*(?:access|permission|permissions|role)\b", re.IGNORECASE),
    ),
)


def agent_read_only_policy() -> dict[str, Any]:
    return {
        "read_only": True,
        "route_prefixes": list(READ_ONLY_ROUTE_PREFIXES),
        "blocked_http_methods": sorted(BLOCKED_HTTP_METHODS),
        "blocked_action_verbs": [action for action, _ in BLOCKED_ACTION_PATTERNS],
        "policy_mode": "scoped_to_agent_routes",
        "notes": [
            "The intelligence-assistant layer can read and reason over data, but it cannot mutate application state.",
            "Legacy inbox product routes remain unchanged in this phase and are outside the assistant guard scope.",
        ],
    }


def detect_blocked_action(query_text: str) -> str | None:
    normalized = " ".join(str(query_text or "").strip().lower().split())
    if not normalized:
        return None
    if any(normalized.startswith(prefix) for prefix in INFORMATIONAL_PREFIXES):
        return None
    for action, pattern in BLOCKED_ACTION_PATTERNS:
        if pattern.search(normalized):
            return action
    return None


def _extract_candidate_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for inner in value.values():
            out.extend(_extract_candidate_strings(inner))
        return out
    if isinstance(value, list):
        out: list[str] = []
        for inner in value:
            out.extend(_extract_candidate_strings(inner))
        return out
    return []


def _read_only_refusal_response(path: str, *, blocked_action: str | None = None, blocked_method: str | None = None) -> JSONResponse:
    detail = "This intelligence assistant is running in read-only mode and cannot execute write actions."
    if blocked_method:
        detail = f"{blocked_method} is not allowed on the read-only assistant routes."
    if blocked_action:
        detail = (
            f"The request appears to ask for a write action (`{blocked_action}`), "
            "which is disabled in read-only mode."
        )
    return JSONResponse(
        status_code=403,
        content={
            "error": "read_only_action_blocked",
            "message": detail,
            "read_only": True,
            "blocked_action": blocked_action,
            "blocked_method": blocked_method,
            "path": path,
            "allowed_next_steps": [
                "Ask for analysis, explanation, or recommendations instead.",
                "Request the data needed to justify a future manual action.",
                "Use the legacy operational app separately if a human should execute the change.",
            ],
        },
    )


class AgentReadOnlyGuardMiddleware:
    def __init__(self, app: Any, *, route_prefixes: tuple[str, ...] = READ_ONLY_ROUTE_PREFIXES) -> None:
        self.app = app
        self.route_prefixes = route_prefixes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET").upper()
        if not any(path.startswith(prefix) for prefix in self.route_prefixes):
            await self.app(scope, receive, send)
            return

        if method in BLOCKED_HTTP_METHODS:
            await _read_only_refusal_response(path, blocked_method=method)(scope, receive, send)
            return

        if method != "POST":
            await self.app(scope, receive, send)
            return

        body = await self._consume_body(receive)
        blocked_action = self._detect_blocked_action_in_body(body)
        if blocked_action:
            await _read_only_refusal_response(path, blocked_action=blocked_action)(scope, receive, send)
            return

        replay_receive = self._replay_body(body)
        await self.app(scope, replay_receive, send)

    async def _consume_body(self, receive: Any) -> bytes:
        chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                continue
            chunks.append(message.get("body", b""))
            more_body = bool(message.get("more_body", False))
        return b"".join(chunks)

    def _replay_body(self, body: bytes) -> Any:
        sent = False

        async def receive() -> dict[str, Any]:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        return receive

    def _detect_blocked_action_in_body(self, body: bytes) -> str | None:
        if not body:
            return None
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return None
        for candidate in _extract_candidate_strings(payload):
            blocked = detect_blocked_action(candidate)
            if blocked:
                return blocked
        return None
