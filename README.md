# Agent Registry & Usage Platform

A minimal Agent Discovery + Usage platform built with Python and FastAPI.

## Quick Start

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

API docs available at `http://127.0.0.1:8000/docs`

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/agents` | Register a new agent |
| GET | `/agents` | List all agents |
| GET | `/search?q=<term>` | Search agents by name or description |
| POST | `/usage` | Log a usage event (idempotent) |
| GET | `/usage-summary` | Total units per target agent |

### POST /agents
```json
{
  "name": "DocParser",
  "description": "Extracts structured data from PDFs",
  "endpoint": "https://api.example.com/parse"
}
```

### POST /usage
```json
{
  "caller": "AgentA",
  "target": "DocParser",
  "units": 10,
  "request_id": "abc123"
}
```
Sending the same `request_id` twice is silently ignored (idempotent).

---

## Design Questions (REQ 5)

### 1. How would you extend this system to support billing without double charging?

The idempotency key (`request_id`) already prevents double-counting at the logging layer. To extend this to billing:

- Persist usage logs in a durable store (PostgreSQL / SQLite with WAL) so records survive restarts.
- Add a `billed` boolean flag per log record. A background job marks records as billed only after a successful payment-processor acknowledgement.
- Wrap the "mark as billed" step in a database transaction so a crash mid-billing does not leave partial state.
- Expose a `/billing` endpoint that aggregates only un-billed records for a given period; never re-read already-billed records.

The key insight: separate the "record the event" step (cheap, idempotent) from the "charge for the event" step (expensive, exactly-once), and only advance the billing cursor after confirmed success.

### 2. How would you store this data if scale increases to 100K agents?

At 100K agents the in-memory dict becomes risky (memory pressure, no persistence). Incremental migration path:

- **SQLite** (0 → ~50K agents): swap the dicts for a single SQLite file. Add a full-text-search index on `name` and `description` for the `/search` endpoint. Zero infrastructure change.
- **PostgreSQL** (~50K+): move to Postgres with a `tsvector` GIN index for fast full-text search. The usage table gets a composite index on `(target, request_id)`. Connection pooling (pgBouncer or asyncpg pool) handles concurrent writes.
- **Usage aggregation**: at 100K agents with high write rates, pre-aggregate usage into a `usage_hourly` rollup table updated by a background task, so `/usage-summary` reads from the rollup rather than scanning every raw log.

The API surface does not change; only the storage backend is swapped.

---

## Key Design Decisions

- **Idempotency on `request_id`**: the second POST /usage with the same ID returns `{"status": "duplicate"}` and takes no action. This is intentional — it allows callers to safely retry on network failures.
- **Validation at the boundary**: Pydantic models reject empty strings and non-positive `units` before any business logic runs.
- **Keyword extraction (REQ 4 – Option B)**: `extract_tags()` uses a simple regex + stopword filter instead of an LLM. It is deterministic, requires no API key, and is fast enough for registration-time use.
