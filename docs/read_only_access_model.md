# Read-Only Access Model

## Purpose

This document describes the phase 1 access model for the intelligence assistant layer.

Scope:

- applies to the new assistant routes
- does not rewrite the legacy inbox product behavior in this phase

---

## 1. Core Rule

The assistant layer is `read-only by design`.

That means:

- one dedicated read-only DB role
- one restricted route surface
- one scoped middleware guard
- no write-capable app APIs exposed to agents

---

## 2. DB Credential Model

### Assistant credential

- role name: `ai_readonly_app`
- capability: `SELECT` only on approved tables

### Non-goals for phase 1

- no shared write credential
- no privilege escalation through stored procedures
- no dynamic SQL with mutation verbs

---

## 3. Route-Scope Model

Phase 1 code enforcement is intentionally scoped to:

- `/api/agent-poc/*`

Reason:

- this repo still contains a legacy inbox application with existing write routes
- phase 1 should enforce read-only behavior for the new intelligence-assistant layer without breaking the legacy operational UI

---

## 4. Middleware Enforcement

Implemented behavior:

### Blocked HTTP methods on assistant routes

- `PUT`
- `PATCH`
- `DELETE`

### Blocked action intent in assistant chat payloads

The middleware rejects requests that appear to ask the assistant to execute write actions such as:

- `send reply`
- `approve draft`
- `publish post`
- `assign thread`
- `create alert`
- `update note`
- `delete draft`
- `grant access`
- `revoke access`

### Allowed requests

- analysis
- explanation
- planning
- recommendation
- grounded question answering
- capability/state explanation

---

## 5. Product Behavior for Blocked Requests

When a blocked request reaches the assistant route, return:

- `403`
- `read_only_action_blocked`
- a clear explanation
- guidance to ask for analysis or recommendations instead

The assistant must never:

- send
- approve
- publish
- assign
- insert
- update
- delete
- grant
- revoke

---

## 6. Scope Resolution Rules

Before any retriever runs:

1. authenticate user
2. resolve allowed organizations
3. resolve allowed clients
4. resolve allowed domains
5. apply those filters to SQL, vector, and graph retrieval

---

## 7. Logging and Audit Expectations

At minimum, log:

- user id if available
- resolved client scope
- route selected
- tables queried
- support state
- refusal events caused by read-only policy

Do not log:

- secrets
- access tokens
- raw auth payloads

---

## 8. Phase 1 Deliverables Status

Implemented in repo:

- read-only route guard middleware
- assistant route policy metadata
- read-only SQL role template
- DB contract and exposure docs

Deferred to later phases:

- graph retriever
- write-capable operational executor
- global migration of legacy routes into the same guard model
