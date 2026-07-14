# BeFree — Secure Multi-Tenant RAG

Secure, multi-tenant RAG prototype: tenants upload documents; users query them with grounded, cited answers. Airtight tenant isolation at both Qdrant (payload filter) and Postgres (row-level security). PII masked before embedding. Two-layer prompt-injection defense.

## Quick start

```bash
cp .env.example .env
# Add GROQ_API_KEY to .env
make up
make migrate
make seed        # creates two demo tenants + users
```

Then open http://localhost:5173. Demo users are printed by `make seed`.

## Architecture

```
Ingestion (async, queue-driven):
Upload → AV scan → Sandboxed parse → Sanitize → PII mask → Component classify
      → Type-specific chunk → Injection classify → Embed → Store
        (Qdrant child vectors, Postgres parents)

Query (sync):
Query → Auth + tenant resolve → Qdrant top-30 (tenant filter)
      → Cross-encoder rerank → Parent merge (dedupe)
      → Injection scan on context → LiteLLM → Answer + citations
      → RAGAS eval (offline)
```

Tenant isolation is enforced at TWO independent layers:

1. **Qdrant**: `tenant_id` is a hard payload filter on every query.
2. **Postgres**: row-level security policy `USING (tenant_id = current_setting('app.tenant_id')::uuid)` on every tenant-scoped table. The backend sets the GUC per-request from the JWT.

`tenant_id` is NEVER accepted from client input — always resolved server-side from the JWT.

## Scaling narrative (for the interview)

- **Ingestion bottleneck** → horizontal RQ workers + batched embedding.
- **Vector-search latency** → Qdrant sharding, per-tenant collections once tenant count > ~100.
- **Rerank cost** → cross-encoder only runs on top-30, and rerank results cached in Redis.
- **LLM latency** → LiteLLM load-balances providers; response streaming.
- **DB read load** → Postgres read replicas + PgBouncer; parent read-through cache in Redis.
- **Free → managed migration** → Qdrant Cloud, hosted rerank (Cohere), managed Postgres. Architecture unchanged, only hosting.

## Security

- JWT auth; tenant_id in claims.
- Postgres RLS + Qdrant payload filter (defense-in-depth).
- Sandboxed parsers (subprocess, no network, resource limits) + ClamAV.
- Content sanitization (zero-width, hidden text).
- Presidio + regex PII masking before embedding.
- Two-layer injection defense (per-chunk at ingest, on assembled context at query time) + structural delimiter-wrapping in the prompt.
- Audit log for uploads, queries, admin actions.

## Tests

The most important test is `backend/tests/test_isolation.py` — it attempts to read tenant B's data as tenant A at every layer and asserts it's impossible.

```
make test
```
