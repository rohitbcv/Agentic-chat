# Agent chat

Standalone read-only multi-agent project for schema-aware DB question answering. This folder is intentionally separate from Community Inbox.

## Structure

- `backend/app/` contains the standalone FastAPI API
- `frontend/` contains the React/Vite UI
- `AGENT.md` contains the routing contract
- `AI_CHAT_AGENT_ROADMAP.md` and `READ_ONLY_MULTI_AGENT_IMPLEMENTATION_PLAN.md` contain the product and implementation plans
- `docs/` contains the DB mapping and read-only access docs
- `docs/crewai_agent_orchestration_architecture.md` contains the target CrewAI Flow and specialist Crew architecture

## Agent architecture

- `Orchestrator Agent` resolves intent, client scope, capability, and retrieval mode
- `Inbox and Complaint Agent` handles thread, complaint, and triage questions
- `Client Knowledge and FAQ Agent` handles property facts, FAQs, tone, and audience
- `Content Planning Agent` handles schedules, approvals, captions, and limited post-performance intelligence
- `Media Discovery Agent` handles semantic media search and asset-fit reasoning
- `Access and Relationship Agent` handles collaborators, organizations, events, and relationship paths
- the backend is read-only only and does not allow write actions
- target orchestration uses CrewAI Flow for the full `ai-agent-detailed-flow.svg` pipeline and specialist Crews for read-only retrieval branches

## Run the backend

```bash
cd backend
pip install -r ../requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Then open `http://127.0.0.1:5173`.

## Environment

1. Copy `../.env.example` or `.env.example` to `.env` at the `Agent chat/` root.
2. Keep `USE_DUMMY_DB=true` for the local dummy DB, or set `USE_DUMMY_DB=false` and fill live read-only DB credentials.
3. Optionally add `OPENAI_API_KEY` and keep `OPENAI_EMBED_MODEL=text-embedding-3-large` to generate knowledge and metric embeddings.
4. Keep `LLM_ANSWER_ENABLED=true` and set `OPENAI_MODEL=gpt-5.4-mini` to let the LLM synthesize final grounded answers after retrieval.
5. Optionally set `VITE_API_BASE=http://127.0.0.1:8000` in `frontend/.env.local`.

## Dummy DB and embeddings

```bash
python3 scripts/create_dummy_db.py
python3 scripts/create_knowledge_embeddings.py --dry-run
python3 scripts/create_knowledge_embeddings.py
python3 scripts/create_metric_embeddings.py --dry-run
python3 scripts/create_metric_embeddings.py
python3 scripts/create_relationship_graph.py
```

The embedding commands require `OPENAI_API_KEY`. Exact metric answers still come from SQL; metric embeddings are only for metric semantics and context. Knowledge embeddings are used for property notes, FAQs, property details, tone, audience, media analysis, and post copy.

`OPENAI_MODEL` controls LLM answer generation only. Embeddings intentionally stay on `OPENAI_EMBED_MODEL` because OpenAI embedding endpoints require an embedding-capable model.

The relationship graph command materializes a read-only dummy graph in `entity.entity` and `entity.entity_relationship`. It connects clients, organizations, users, cities, events, posts, media, analytics snapshots, inbox messages, knowledge chunks, and metric chunks.

## LLM answer generation

The POC uses the LLM only after deterministic routing, read-only retrieval, context merge, and source scoping. SQL remains responsible for exact rows, counts, dates, statuses, and metric values. If LLM output is unavailable or violates formatting/safety checks, the API returns the deterministic fallback answer.

The configured answer model is `OPENAI_MODEL=gpt-5.4-mini`.

## Main endpoints

- `GET /health`
- `GET /api/agent-poc/config`
- `GET /api/agent-poc/embedding-status`
- `POST /api/agent-poc/chat`

## Evaluation

```bash
python3 scripts/run_phase_evaluation.py
```
