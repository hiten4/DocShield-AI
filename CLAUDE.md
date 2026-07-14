# BeFree — Working Memory

Project context for future Claude sessions. Read this first when opening this folder.

## What this is

Secure, multi-tenant RAG document query prototype. Users upload PDF/DOCX/TXT/XLSX per tenant; queries return grounded answers with citations. Built as an interview take-home. Free/open-source stack only. Owner: coco (avishkajindal05@gmail.com).

**Source of truth for design decisions:** `../docs/project_handoff_document.md` (in the Claude.ai knowledge, not in this folder). Do not deviate from the finalized decisions in section 21 of that doc without asking.

## Architecture (one paragraph)

FastAPI backend + React (Vite) frontend + RQ worker for async ingestion. Postgres 16 stores parent chunks + metadata + audit under Row-Level Security. Qdrant stores child embeddings with a `tenant_id` payload filter. Redis backs the RQ queue. Ingestion: AV scan (ClamAV) → sandboxed parse (subprocess, no network) → sanitize → PII mask (Presidio + regex) → component-type classify → type-specific chunk (tables 3-row windows, lists 4-item windows, paragraphs 512-token recursive) → per-chunk injection classifier → embed (bge-large) → store. Query: JWT-scoped tenant filter → Qdrant top-30 → cross-encoder rerank (bge-reranker-base) → dedupe by parent → context-level injection scan → LiteLLM (Groq) with structural `<context>` delimiter defense → answer + citations. Two independent tenant isolation layers (Qdrant filter + Postgres RLS), two independent injection defenses (ingest + query time) + structural.

## Stack pins that matter

- Python 3.11 in container (user has 3.14 locally, don't run locally).
- `sentence-transformers >=3.0` requires `low_cpu_mem_usage=False` in `model_kwargs` (both embedder + reranker) — meta-tensor bug otherwise.
- `rq >=1.16,<2.0` — 2.x removed `Connection` import path.
- `qdrant-client >=1.11,<1.12` matches server version.
- `pydantic[email]` extra is needed for `EmailStr`, but login uses plain `str` because `.test` TLD isn't valid per RFC.
- Presidio configured to use `en_core_web_sm` (not the default `_lg`) via `NlpEngineProvider` in `app/ingestion/pii_mask.py`.
- Docker `job_timeout` on ingestion queue is 1800s (allows first-run model downloads).

## Known-good stack commands

```powershell
docker compose up -d
docker compose exec -e PYTHONPATH=/app backend alembic upgrade head
docker compose exec -e PYTHONPATH=/app backend python -m app.seed.seed_tenants
# open http://localhost:5173
```

Any `.env` change → `docker compose up -d --force-recreate backend` (plain `restart` reuses old env).

## Demo credentials

Seeded by `app.seed.seed_tenants`:

- Acme admin: `admin@acme.test` / `acme-admin-pw`
- Acme user: `user@acme.test` / `acme-user-pw`
- Globex admin: `admin@globex.test` / `globex-admin-pw`
- Globex user: `user@globex.test` / `globex-user-pw`

## Patches applied on top of the initial generation

1. `docker-compose.yml`: removed obsolete `version:`, ClamAV pinned to `:stable`.
2. `backend/pyproject.toml`: dropped unused `unstructured`; added `[build-system]`; used `pydantic[email]`; pinned `rq<2.0`, `qdrant-client<1.12`, `bcrypt<4.1`, `spacy<3.8`; swapped `uvicorn[standard]` → `uvicorn` (extras fail on some builds).
3. `backend/Dockerfile`: replaced `python -m spacy download en_core_web_sm` with direct wheel install (deterministic).
4. `backend/app/workers/rq_worker.py`: updated to RQ 1.x API (removed Connection context manager).
5. `backend/app/auth/router.py`: `email: str` (not `EmailStr`) so `.test` TLD works.
6. `backend/migrations/versions/0001_init.py`: enum types created via raw SQL + `create_type=False` on columns (SQLAlchemy double-creates them otherwise).
7. `backend/app/ingestion/embedder.py` + `backend/app/query/reranker.py`: `model_kwargs={"low_cpu_mem_usage": False}` to work around torch 2.4 meta-tensor issue.
8. `backend/app/ingestion/sandbox.py`: child code inserts `/app` into `sys.path` (needed because `python -I` strips PYTHONPATH).
9. `backend/app/ingestion/pii_mask.py`: `NlpEngineProvider` configured for `en_core_web_sm` (avoids 587 MB `_lg` download).
10. `backend/app/ingestion/router.py`: `db.commit()` before RQ enqueue (fixed race where worker looked up doc before insert committed); `job_timeout=1800`.
11. `backend/app/ingestion/pipeline.py`: explicit `db.flush()` between parent inserts, chunk_meta inserts, and flagged_chunk inserts (FK order).
12. `.env`: `LITELLM_MODEL=groq/llama-3.3-70b-versatile` (3.1-70b decommissioned by Groq).
13. **RLS was silently OFF**: app connected as `befree`, which the postgres image creates as SUPERUSER — superusers bypass RLS even with FORCE. Added non-superuser `befree_app` role (`backend/db/init/01_app_role.sql`, mounted into `/docker-entrypoint-initdb.d`); `POSTGRES_DSN` now uses `befree_app`. `test_isolation.py` caught this. For an existing pgdata volume, run the SQL once manually (see file header).
14. `backend/app/ingestion/router.py`: `delete_document` now deletes `flagged_chunks` → `chunks_meta` → doc's `pii_vault` rows before the document (FK order) — previously 500'd on processed docs.
15. `backend/app/ingestion/pii_mask.py`: CLIENT_ID pattern accepts alphanumerics+dashes (was digits-only, leaked `CID-12345` style IDs); `PASSWORD` entity renamed `PASSWORD_FIELD`.
16. `backend/app/ingestion/pipeline.py`: `db.rollback()` at top of the failure handler (DB errors used to leave docs stuck in `processing`).
17. `backend/pyproject.toml`: added `pytest` (image had no test runner).
18. `docker-compose.yml`: `PYTHONPATH: /app` moved from postgres (wrong service) to backend + worker — `-e PYTHONPATH=/app` no longer needed on exec.
19. `backend/tests/conftest.py`: `db.flush()` inside the per-tenant loop — with real RLS a single end-commit batched both users' INSERTs under the last tenant's GUC and WITH CHECK rejected the first one.
20. **Person misattribution fix** (`backend/app/query/person_grounding.py`, new): person names are masked into `[PERSON_xxxx]` tokens at ingestion, so the LLM couldn't tell whose record it was answering from and misattributed other customers' data (found via Demo TEST 4: Globex user asking about Acme's Priya got Michael's balance). Query router now NER-detects person names in the question, resolves them against the tenant vault (RLS-scoped, partial-name containment allowed), substitutes the deterministic tokens into the question before embed/rerank/prompt, and refuses pre-LLM when every named person is unknown to the tenant. Prompt gained redaction-token rules (identical tokens = same entity; never attribute unidentified records). Because identity ("Account Holder: [PERSON_x]") and facts live in different chunks after masking, `parent_merge.person_anchors` pins the token-bearing block from retrieved documents into the context — otherwise the LLM correctly refuses to attribute (over-refusal seen in demo).

## Common gotchas — check these before debugging

- **`docker compose exec` fails with "container not running"** → the target service exited/crashed. Use `docker compose run --rm <svc> <cmd>` to spin a fresh one.
- **`test_isolation.py` fails / RLS not filtering** → check the app isn't connecting as a superuser or BYPASSRLS role. DSN must use `befree_app`, not `befree`. Verify: `SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname LIKE 'befree%';`
- **Backend imports fail (`No module named 'app'`)** → pass `-e PYTHONPATH=/app` to `docker compose exec`, or add `environment: PYTHONPATH: /app` to `backend`/`worker` in compose (not done yet, on todo).
- **Login returns 422** → `EmailStr` rejecting the email. LoginIn should use `str`.
- **Login returns 401 but users are seeded** → RLS blocking the cross-tenant email lookup. Login iterates tenants and sets `app.tenant_id` per iteration; if that logic is broken we get 401.
- **Doc stuck in `pending`** → worker is downloading models or the queue is stalled. `docker compose logs -f worker`.
- **Doc → `failed`** → look at `documents.error` column: `SET row_security = off; SELECT filename, status, error FROM documents ORDER BY created_at DESC LIMIT 5;`.
- **Query 500** → tail backend logs. Most common: Groq model decommissioned (update `.env` + `--force-recreate`).
- **First query is slow** → embedder (~1.3 GB) + reranker (~275 MB) download on first use. Second query onward is fast.
- **Wrong person's data in an answer / person questions misattributed** → person grounding (`app/query/person_grounding.py`) depends on spaCy tagging the name AND the vault containing it (`SELECT entity_type, token FROM pii_vault` as the tenant). If the name was never masked at ingestion (NER miss), grounding can't protect it.
- **Demo docs + expected answers** → `Document-Demo/DEMO_QUESTIONS.md`. TEST 1 questions (Priya/Kavita/Rajesh/Ananya) are Acme-tenant data — asking them as a Globex user must refuse.

## Postgres RLS quick reference

- Every tenant-scoped table has `FORCE ROW LEVEL SECURITY` + policy `USING (tenant_id::text = current_setting('app.tenant_id', true))`.
- App code sets the GUC per request via `SELECT set_config('app.tenant_id', :t, true)` in `get_db` dependency.
- Worker uses `set_config(..., false)` (session-scoped) in `_db_for_tenant`.
- To inspect from `psql` as `befree` (superuser), use `SET row_security = off;` first — otherwise you see zero rows.

## Test the isolation guarantee

```powershell
docker compose exec -e PYTHONPATH=/app backend pytest tests/test_isolation.py -xvs
```

That test spins up two tenants and proves cross-tenant reads + writes fail at both Postgres RLS and Qdrant payload-filter layers.

## Todos / known gaps

- Add `environment: PYTHONPATH: /app` to backend + worker in `docker-compose.yml` so we can drop the `-e` flag.
- Frontend `vite.config.ts` proxy targets `http://backend:8000` — only works inside the docker network. If running frontend locally, edit to `http://localhost:8000`.
- ClamAV fails-open in dev (see `app/ingestion/av_scan.py`); production should fail-closed.
- No pagination on `/documents` list.
- No streaming on `/query` — full answer returned at once.
