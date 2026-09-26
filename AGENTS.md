# AGENTS.md — inmobiliaria-ai

## Quick Reference

| Task | Command |
|------|---------|
| Run app (bot + API + workers) | `python main.py` (requires NVIDIA creds, see below) |
| Run tests (isolated DB) | `python -m pytest tests/ -q` (~436 tests, ~2.5 min) |
| Run single test file | `python -m pytest tests/test_agent.py -q` |
| Lint (Ruff, line-length 110) | `ruff check .` (⚠ pre-existing findings, see Lint) |
| Migrations | `python -m alembic upgrade head` (main.py runs them on boot) |
| Create migration | `python -m alembic revision --autogenerate -m "name"` |
| Seed dev data (destructive) | `python -m scripts.seed` |
| Ingest documents (`documents/inbox/`) | `python -m scripts.ingest` |
| Environment doctor | `python -m scripts.doctor` |
| Create admin user (RBAC) | `python -m scripts.create_admin email@x.com "Nombre" pass [rol]` |
| Sync filesystem images → PropertyImage table | `python -m scripts.sync_images` |
| Admin panel dev | `cd admin-vite && npm run dev` (Vite on :3000, needs backend on :8000) |
| Admin panel typecheck | `cd admin-vite && npm run typecheck` |
| Admin panel node tests | `cd admin-vite && npm run test:client \|\| npm run test:floors` |
| Start infra manually | `pg_ctl -D ./pgdata start && redis-server --daemonize yes` |

## Project Structure

```
main.py                 # Single entry point (composition root only)
app/
├── agents/             # orchestrator.py (facade) → runtime.py (agentic loop) + llm_orchestrator.py
│                       #   tools.py, tool_specs.py, prompts_v2.py (active prompt), websearch.py (DDG, no key)
├── ai/                 # LLMProvider / EmbeddingProvider abstractions (NVIDIA + local hash)
├── api/                # routes.py (all FastAPI endpoints) + files.py (uploads/images)
├── appointments/       # service.py: business hours + slot validation live here
├── bot/                # Telegram handlers, keyboards, progress.py (RetryAfter-safe edits)
├── core/               # settings.py (all env), bizconfig.py (DB-backed business settings)
├── crm/  memory/       # leads/conversaciones; conversation memory
├── database/           # models.py, base.py (engines), migrations/
├── properties/ rag/    # search/filters; ingestion, chunking, retrieval
├── security/           # auth.py (JWT+RBAC), prompt-injection/SQLi/path-traversal defenses
└── workers/            # queue.py (Redis + in-memory fallback), runner.py (jobs + scheduler)
admin-vite/             # Admin panel: Vite + React 19 + TS (NOT Next.js anymore)
scripts/                # doctor, seed (destructive), ingest, create_admin, sync_images
docs/                   # Technical docs (⚠ admin-panel.md still describes the old Next.js panel)
tests/                  # conftest.py pins env before any app.* import
```

## Key Architecture Facts

- **Single entry point**: `main.py` boots config → logging → infra autostart → migrations → pgvector check → services → bot (if token) → API `:8000` → workers → scheduler (hourly). Do not add other entry points.
- **LLM is mandatory at boot**: `main.py` raises `RuntimeError` if no LLM provider is configured. `LLM_MODE=deterministic` no longer boots the app (there is no full deterministic-brain path anymore). Deterministic pieces survive only as: unit-test mode (conftest pins it) and a **per-turn failsafe** — if the LLM dies mid-turn, the reply is built from real tool evidence (`build_degraded_reply`, metrics `degraded_replies`/`llm_fallbacks`).
- **Orchestrator**: `app/agents/orchestrator.py` is a thin facade; the agent loop is `runtime.py` (LLM → tools → LLM → ...) and turn bootstrap/persistence/audit is `llm_orchestrator.py`. The active system prompt is `prompts_v2.py` (`prompts.py` is legacy, still regression-tested).
- **Backend validates, LLM never invents reality**: critical validation (state, availability, money, dates, business hours) stays in code. Recent hard invariants (regression-tested): price fallback searches real +30% and reports it transparently; the LLM may not invent `max_price`/`min_price`; nearest-property ranking is computed in code, never by the LLM.
- **Admin auth is JWT + RBAC**: login `POST /auth/login` sets httponly cookie `admin_access_token`; roles `superadmin|admin|editor|asesor` (`app/security/auth.py`, `JWT_SECRET` in `.env`). Legacy `X-Admin-Token`/`ADMIN_TOKEN` copy-to-panel flow was **removed** (`ADMIN_TOKEN` lingers unused in settings).
- **Worker jobs**: `document_ingestion, process_document, evaluate_alerts, notify, cleanup` (`app/workers/runner.py`). Property alerts = `SavedSearch` entries evaluated by `evaluate_alerts`, then Telegram notifications.
- **pgvector dimension** must match `EMBEDDING_DIM` in `.env` (2048 NVIDIA / 256 local). Changing it requires migration + re-embedding.
- **Agent observability**: `GET /agent/metrics` (permission-gated) exposes `llm_usage_rate`, `llm_success_rate`, `fallback_rate`, `tool_call_rate`, `rag_usage_rate`, etc.
- Local-first: only external dependencies are NVIDIA Build API and Telegram.

## Language & Behavior Conventions

- All user-facing text, prompts, logs and docstrings are **Spanish**. Keep it that way.
- Brand is **"epresedi"** (lowercase, never "Expresedi"/"EXPRESEDI") — enforced by `tests/test_brand_name_regression.py`.
- Prompt behavior is regression-tested: brand name, greeting policy (`tests/test_greeting_policy.py`), official address + business hours (`tests/test_official_address_and_hours.py`). Editing `prompts_v2.py` or `bizconfig.py` defaults without updating these tests will fail the suite.

## Environment & Config

- All config in `.env` (copy from `.env.example`); everything loads through `app/core/settings.py` (`get_settings()` is `lru_cache`d — env changes after import don't apply).
- `LLM_MODE=auto|nvidia|deterministic`: `auto` = LLM-first when NVIDIA configured; `nvidia` = force (fails without creds); `deterministic` = **tests only** — booting `main.py` in this mode fails.
- `DATABASE_URL` (dev) and `TEST_DATABASE_URL` are separate; tests use the latter (`inmobiliaria_test`).
- `PGDATA=./pgdata` (repo-local, gitignored). `main.py` auto-starts Postgres from `PGDATA` or `~/pgdata-inmob` and Redis if binaries are in PATH and ports 5432/6379 are free.
- `WEB_SEARCH_ENABLED` gates the DDG-based web search tool (no API key needed).
- `APP_ENV=production` blocks `scripts.seed` unless `SEED_ALLOW_PRODUCTION=1`.

### LLM knobs (defaults in `app/core/settings.py`)

| Variable | Default | Description |
|---|---|---|
| `LLM_TEMPERATURE` | `0.2` | Sampling temperature |
| `LLM_MAX_TOKENS` | `4000` | Max output tokens |
| `LLM_REASONING_LEVEL` | `high` | `high/medium/low/minimal/none`; ignored if model lacks `reasoning_effort` (log: `reasoning_level_invalid`) |
| `LLM_MAX_TOOL_ROUNDS` | `4` | Tool-calling rounds per turn |
| `LLM_MAX_TOOL_CALLS_PER_TURN` | `8` | Tool calls per turn |
| `LLM_HISTORY_TURNS` | `8` | History turns in context |
| `LLM_TOOL_RESULT_MAX_CHARS` | `4000` | Max chars per tool result |
| `LLM_RETRY_MAX` | `3` | LLM call retries |

## Testing Conventions

- ~436 tests in 24 files; pytest `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed).
- `tests/conftest.py` pins env vars **before any `app.*` import** (LLM off, local embeddings, test storage/documents dirs). It creates the test DB if missing, runs migrations, and runs `scripts.seed` **destructively once per session**.
- RBAC test users are auto-created: `{role}@test.local` / `test-password-123`; use the `admin_token` fixture (`admin_token('superadmin')` → Bearer headers).
- High-level fixtures: `ask` (sends NL through the agent with `FakeLLMV2`), `user_id` (unique Telegram id), `session`, `property_by_code`.
- Never call NVIDIA or Telegram in tests. Embeddings use the local hash provider.
- If tests hang: another pytest session is locking the test DB — close it.

## Lint

- Only config is `line-length = 110` (`pyproject.toml`). Ruff ≥ 0.16 expanded its default rule set, so `ruff check .` currently reports **~290 pre-existing findings** (B008 `Depends(...)`, BLE001, I001, F821 in WIP CMS code, …). Don't treat it as a pass/fail gate and don't mass-fix it as part of unrelated tasks; do keep new files clean (`ruff check <file>`).
- `admin-vite`: `npm run typecheck` and `npm run test:client` pass; `npm run test:floors` has **3 pre-existing display-label failures**; `npm run lint` is broken (no eslint flat config in `admin-vite/`).

## Common Gotchas

| Issue | Cause / Fix |
|-------|-------------|
| Boot fails: "LLM provider not configured" | `main.py` hard-requires `NVIDIA_API_KEY` + `NVIDIA_MODEL`. Deterministic boot no longer exists. |
| `pgvector no instalado` | Compile manually on Termux (`docs/local-development.md`); `main.py` checks the extension on boot. |
| CMS endpoints NameError (`CmsContent`) | `app/api/routes.py` CMS endpoints are WIP: the model is used but not imported. Not covered by tests. Don't assume they work; fix the import if touching them. |
| 401 in admin panel | Log in via the panel (`POST /auth/login`); create the first user with `python -m scripts.create_admin ...`. `ADMIN_TOKEN` copying is legacy, gone. |
| Admin panel can't reach API | Vite dev server proxies `/api` → `127.0.0.1:8000`; the backend (`python main.py`) must be running. |
| Bot doesn't respond | Verify `TELEGRAM_BOT_TOKEN` and that `main.py` is running; without a token, main.py intentionally starts API+workers only (warning in log). |
| Tests hang | Another pytest session holds locks on `inmobiliaria_test` — close it. |
| Progress message not updating | Telegram rate limits; `RetryAfter` is handled with backoff in `app/bot/progress.py`. |
| Diagnose env issues | `python -m scripts.doctor` (Python, Postgres, Redis, pgvector, schema, NVIDIA, Telegram, storage, RAG). |

## Migration Workflow

1. Modify models in `app/database/models.py`
2. `python -m alembic revision --autogenerate -m "description"`
3. Review the generated file in `migrations/versions/`
4. `python -m alembic upgrade head` (also runs automatically on every `main.py` boot)

## RAG Pipeline

`documents/inbox/` → `python -m scripts.ingest` (or `POST /documents`, or admin panel) → validate → hash/dedupe → parse (PDF/DOCX/TXT/MD) → clean → chunk (sections + overlap) → embeddings → pgvector. Chunks keep full traceability (`document_id`, `page`, `section`, `chunk_hash`, `embedding_version`); document updates create new versions without breaking the index.

## Appointment Scheduling Rules

**Source of truth: `app/core/bizconfig.py`** — hours are stored in the `app_settings` DB table (30s TTL cache) with code defaults; admins can change them via `PUT /settings`.

| Day | Slots (hourly start times) |
|-----|---------------------------|
| Mon–Fri | 08:00–12:00 **and** 14:00–18:00 (lunch break: no 12:00/13:00 slots) |
| Saturday | 08:00–15:00 (slots 08:00–14:00) |
| Sunday | CLOSED |

- Timezone `America/Bogota` (configurable via the `timezone` setting). Minimum advance notice: 2 hours (`app/appointments/service.py`).
- Validation is layered: `bizconfig.is_within_business_hours()` → `appointments/service.validate_business_hours()` (called by create/reschedule) → `app/agents/tools.py:_validate_real_slot()` (returns `reason="business_hours"` before checking occupancy, then `reason="booked"`).
- Agent contract: always validate a requested slot via the `list_available_slots` tool; if `exact_match=false`, offer only real `nearest_slots`; only call `schedule_visit` after explicit user acceptance; confirm only if the tool returns an `appointment` object. 40 tests in `tests/test_appointments.py` + official-hours tests pin this behavior.

## Documentation

Technical docs in `docs/`: `architecture.md`, `database.md`, `rag.md`, `ai.md`, `agent-tools.md`, `telegram.md`, `local-development.md`, `testing.md`, `security.md`, `data-audit.md`, `troubleshooting.md`. Note: `docs/admin-panel.md` still documents the pre-Vite Next.js panel — treat `admin-vite/` code as the truth. Root-level `AUDITORIA_*.md` / `*_AUDIT.md` / `*REPORT*.md` files are historical audit artifacts, not current specs.
