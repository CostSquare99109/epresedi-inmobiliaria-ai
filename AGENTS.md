# AGENTS.md — inmobiliaria-ai

## Quick Reference

| Task | Command |
|------|---------|
| Run app (bot + API + workers) | `python main.py` |
| Run tests (isolated DB) | `python -m pytest tests/ -q` |
| Run single test file | `python -m pytest tests/test_agent.py -q` |
| Run with coverage | `python -m pytest tests/ --cov=app` |
| Lint (Ruff) | `ruff check .` |
| Migrations | `python -m alembic upgrade head` |
| Create migration | `python -m alembic revision --autogenerate -m "name"` |
| Seed dev data (destructive) | `python -m scripts.seed` |
| Ingest documents | `python -m scripts.ingest` |
| Environment doctor | `python -m scripts.doctor` |
| Create admin user | `python -m scripts.create_admin` |
| Admin panel dev | `cd admin && npm run dev` |
| Admin panel typecheck | `cd admin && npm run typecheck` |
| Start infra (Postgres + Redis) | `docker compose up -d` |

## Project Structure

```
epresedi-inmobiliaria-ai/
├── main.py                 # Single entry point (composition root)
├── alembic.ini             # Alembic config (DATABASE_URL from .env)
├── pyproject.toml          # Python project config (pytest, ruff)
├── requirements.txt        # Python deps
├── .env.example            # Config template (copy to .env)
├── app/                    # Application packages (all logic here)
│   ├── agents/             # Orchestrator + agent tools
│   ├── ai/                 # LLM/embedding providers (NVIDIA + fallbacks)
│   ├── api/                # FastAPI routes
│   ├── appointments/       # Citas/agenda
│   ├── bot/                # Telegram handlers + keyboards
│   ├── core/               # Settings, logging
│   ├── crm/                # Leads, conversaciones
│   ├── database/           # SQLAlchemy models, session, engines
│   ├── memory/             # Conversation memory
│   ├── properties/         # Property search, filters
│   ├── rag/                # Document ingestion, chunking, retrieval
│   ├── security/           # Prompt injection, SQLi, path traversal defenses
│   └── workers/            # Background queue + scheduler
├── migrations/             # Alembic versions
├── scripts/
│   ├── doctor.py           # Environment health checks
│   ├── seed.py             # Dev/test data (DESTRUCTIVE)
│   ├── ingest.py           # RAG document ingestion
│   └── create_admin.py     # Admin user creation
├── docs/                   # Technical docs (architecture, rag, ai, etc.)
├── admin/                  # Next.js admin panel (separate npm project)
├── storage/                # File uploads (gitignored)
├── documents/              # RAG inbox + processed (gitignored)
└── tests/                  # ~270 tests, isolated DB (inmobiliaria_test)
```

## Key Architecture Facts

- **Single entry point**: `main.py` boots everything (config → logging → infra checks → migrations → pgvector → services → bot → API → workers → scheduler). Do not add other entry points.
- **Local-first**: PostgreSQL (pgvector), Redis, RAG, CRM, admin panel all run locally. Only external dependency is NVIDIA Build API for LLM/embeddings.
- **LLM-FIRST / TOOL-DRIVEN / DETERMINISTIC-SAFETY**: with NVIDIA configured (`LLM_MODE=auto|nvidia`), the LLM is the brain of every turn: it interprets natural language, decides and chains tools (`app/agents/llm_orchestrator.py`), reasons over results and writes the reply. `app/agents/orchestrator.py` is the entry point and keeps the deterministic pipeline as a per-turn failsafe.
- **Deterministic mode**: without `NVIDIA_API_KEY` + `NVIDIA_MODEL` (or `LLM_MODE=deterministic`), the deterministic pipeline IS the brain — structured search, reference resolution, document extraction, no LLM calls. It also runs as fallback whenever the provider fails, the loop exhausts its rounds, or the reply asserts an unverified fact. This is intentional.
- **Backend validates, tools execute, DB confirms reality**: the LLM never touches PostgreSQL. Critical validation (state, availability, permissions, money, dates) stays in code.
- **Provider abstraction**: `LLMProvider` / `EmbeddingProvider` interfaces; `NVIDIAProvider` is one implementation, `LLMProviderChain` orders providers. Swapping vendors doesn't touch app logic.
- **pgvector dimension**: Must match `EMBEDDING_DIM` in `.env` (2048 for NVIDIA embeddings, 256 for local). Changing requires migration + re-embedding.
- **Admin token**: `ADMIN_TOKEN` from root `.env` is copied to `admin/.env.local` at build time (server-side only, never exposed to browser).
- **Agent observability**: `GET /agent/metrics` (permission `settings.read`) exposes `llm_usage_rate`, `llm_success_rate`, `fallback_rate`, `tool_call_rate`, `rag_usage_rate`, `average_tool_calls_per_turn`.

## Environment & Config

- All config in `.env` (copy from `.env.example`). Never commit real `.env`.
- `APP_ENV=production` blocks `scripts.seed` unless `SEED_ALLOW_PRODUCTION=1`.
- `LLM_MODE=auto|nvidia|deterministic` controls LLM behavior. `auto` means **LLM-first** (the model orchestrates every turn); deterministic is the per-turn failsafe.
- `LLM_PROVIDERS=nvidia` orders the provider chain (first healthy provider wins).
- `EMBEDDING_PROVIDER=auto|nvidia|local` controls embeddings.
- `DATABASE_URL` and `TEST_DATABASE_URL` are separate; tests use the latter.
- `PGDATA` used by `main.py` to auto-start local Postgres (Termux convenience).

### LLM Configuration

| Variable | Default | Description |
|---|---|---|
| `LLM_TEMPERATURE` | `0.2` | Sampling temperature |
| `LLM_MAX_TOKENS` | `4000` | Max output tokens |
| `LLM_REASONING_LEVEL` | `high` | Reasoning effort: `high`, `medium`, `low`, `minimal`, `none` (ignored if unsupported) |
| `LLM_MAX_TOOL_ROUNDS` | `4` | Max tool-calling rounds per turn |
| `LLM_MAX_TOOL_CALLS_PER_TURN` | `8` | Max tool calls per turn |
| `LLM_HISTORY_TURNS` | `8` | History turns in context |
| `LLM_TOOL_RESULT_MAX_CHARS` | `4000` | Max chars per tool result in context |
| `LLM_RETRY_MAX` | `3` | Max LLM call retries |

## Testing Conventions

- ~270 tests across 18 files: database, search, RAG, agent, LLM orchestrator, agent loop, CRM, appointments, security, API, E2E, Telegram, websearch, retry, fake LLM v2, partial failure.
- Tests use isolated `inmobiliaria_test` DB (see `tests/conftest.py`).
- Embeddings use local deterministic provider; never call NVIDIA or Telegram in tests.
- Run full suite: `python -m pytest tests/ -q`
- If tests hang: close other pytest sessions against same test DB (table locks).
- Test bootstrap in `tests/conftest.py` pins env vars before any `app.*` import.

## Common Gotchas

| Issue | Cause / Fix |
|-------|-------------|
| `pgvector no instalado` | Use Docker image `pgvector/pgvector:pg18` or compile manually (Termux: see `docs/local-development.md`) |
| `PostgreSQL no accesible` | `docker compose up -d` or `pg_ctl start`; verify `DATABASE_URL` |
| `NVIDIA API ERROR` | Check `NVIDIA_API_KEY`/`NVIDIA_MODEL`; bot still works in deterministic mode |
| Bot doesn't respond | Verify `TELEGRAM_BOT_TOKEN` and that `main.py` is running; check logs |
| 401 in admin panel | Copy `ADMIN_TOKEN` from root `.env` to `admin/.env.local` |
| Seed refuses to run | `APP_ENV=production` blocks it; use dev DB or export `SEED_ALLOW_PRODUCTION=1` |
| Progress message not updating | Check `TELEGRAM_BOT_TOKEN` and rate limits; `RetryAfter` is handled with backoff |
| Reasoning level not working | Model must support `reasoning_effort` (NVIDIA Build compatible models); check logs for `reasoning_level_invalid` |
| Auto-start fails on Termux | `main.py` tries `pg_ctl`/`redis-server` if ports 5432/6379 are free; ensure they're in PATH or use Docker |
| Diagnose env issues | Run `python -m scripts.doctor` (checks Python, Postgres, Redis, pgvector, NVIDIA, schema, storage, RAG) |

## Migration Workflow

1. Modify models in `app/database/models.py`
2. `python -m alembic revision --autogenerate -m "description"`
3. Review generated file in `migrations/versions/`
4. `python -m alembic upgrade head`
5. `main.py` runs migrations automatically on boot

## RAG Pipeline

`documents/inbox/` → `python -m scripts.ingest` → validate → hash/dedupe → parse (PDF/DOCX/TXT/MD) → clean → chunk (sections + overlap) → embeddings → pgvector. Each chunk stores full traceability (`document_id`, `page`, `section`, `chunk_hash`, `embedding_version`). Document updates create new versions without breaking index.

## Development Notes

- Ruff line-length: 110 (from `pyproject.toml`)
- Python ≥ 3.11 required (tested on 3.14)
- Async throughout (FastAPI, python-telegram-bot v22, SQLAlchemy 2.0 async)
- Worker queue: Redis-backed with in-memory fallback (see `app/workers/queue.py`)
- Scheduler runs hourly by default (document ingestion re-check)
- `main.py` auto-starts local Postgres/Redis if `pg_ctl`/`redis-server` are in PATH and ports 5432/6379 are free (Termux/native convenience)

## Appointment Scheduling Rules

**Business Hours (source of truth: `app/core/bizconfig.py`)**

| Day | Allowed Hours | Slots (start times) |
|-----|---------------|---------------------|
| Monday–Friday | 08:00–18:00 | 08:00, 09:00, 10:00, 11:00, 12:00, 13:00, 14:00, 15:00, 16:00, 17:00 |
| Saturday | 09:00–15:00 | 09:00, 10:00, 11:00, 12:00, 13:00, 14:00 |
| Sunday | CLOSED | — |

**Key Points:**
- Slots are hourly. The last slot starts at 17:00 (Mon–Fri) or 14:00 (Sat) and ends at 18:00 or 15:00 respectively.
- Timezone: `America/Bogota` (configurable via `timezone` setting).
- Minimum advance notice: 2 hours from current time.

**Three Categories of Validation (defense in depth):**

| Category | Description | Backend Behavior | Agent Response |
|----------|-------------|------------------|----------------|
| **A. Allowed & Available** | Within business hours AND slot free | `list_available_slots` returns `exact_match=true` | Confirm and proceed to `schedule_visit` |
| **B. Not Allowed** | Outside business hours (Sun, before/after hours) | `is_within_business_hours` returns `False` | Reject immediately, explain business hours, ask for new time |
| **C. Allowed but Booked** | Within business hours BUT slot occupied | `list_available_slots` returns `exact_match=false` + `nearest_slots` | Inform specific slot unavailable, offer real alternatives from `nearest_slots` |

**Backend Validation (Capa 2 — Tool/Service):**
- `app/core/bizconfig.py`: `is_within_business_hours()`, `get_appointment_hours_for_weekday()`, `is_business_day()`
- `app/appointments/service.py`: `validate_business_hours()` called in `create_appointment()` and `reschedule_appointment()`
- `app/agents/tools.py`: `_validate_real_slot()` checks business hours first (returns `reason="business_hours"`), then availability (returns `reason="booked"`)

**Agent Flow (Capa 1 — LLM Prompt):**
1. **FASE A**: User wants to schedule but no date/time → ask "¿Qué día y hora? Horarios: lun–vie 8–18, sáb 9–15, dom cerrado"
2. **FASE B**: User gives date/time → resolve relative dates using system time (UTC provided in context)
3. **FASE C**: Call `list_available_slots` with `requested_datetime` (ISO in business TZ)
4. **FASE D**: If `exact_match=false` → offer `nearest_slots` only
5. **FASE E–F**: Negotiate alternatives, only `schedule_visit` on explicit acceptance
6. **FASE G**: Confirm only if tool returns `appointment` object

**Tests:** 32 tests in `tests/test_appointments.py` covering all 18 requirement cases + integration.

## Documentation

Technical docs in `docs/`:
- `architecture.md` — layers, flow, decisions
- `database.md` — schema, indexes, migrations
- `rag.md` — pipeline, chunking, versioning, anti-injection
- `ai.md` — LLM/embedding providers, fallbacks, anti-hallucination
- `agent-tools.md` — tool-calling flow
- `telegram.md` — handlers, keyboards, UX
- `local-development.md` — native/Docker environments
- `testing.md` — suite coverage
- `security.md` — file security, rate limiting, privacy
- `admin-panel.md` — admin architecture, components, tokens
- `data-audit.md` — demo data isolation dev/test/prod
- `troubleshooting.md` — common problems