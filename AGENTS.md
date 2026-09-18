# AGENTS.md — inmobiliaria-ai

## Quick Reference

| Task | Command |
|------|---------|
| Run app (bot + API + workers) | `python main.py` |
| Run tests (isolated DB) | `python -m pytest tests/ -q` |
| Run single test file | `python -m pytest tests/test_agent.py -q` |
| Run with coverage | `python -m pytest tests/ --cov=app` |
| Lint (Ruff) | `ruff check .` |
| Typecheck (pyright/mypy if added) | — |
| Migrations | `python -m alembic upgrade head` |
| Create migration | `python -m alembic revision --autogenerate -m "name"` |
| Seed dev data (destructive) | `python -m scripts.seed` |
| Ingest documents | `python -m scripts.ingest` |
| Environment doctor | `python -m scripts.doctor` |
| Admin panel dev | `cd admin && npm run dev` |
| Admin panel typecheck | `cd admin && npm run typecheck` |
| Start infra (Postgres + Redis) | `docker compose up -d` |

## Project Structure

```
expresedi-inmobiliaria-ai/
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
└── tests/                  # 155 tests, isolated DB (inmobiliaria_test)
```

## Key Architecture Facts

- **Single entry point**: `main.py` boots everything (config → logging → infra checks → migrations → pgvector → services → bot → API → workers → scheduler). Do not add other entry points.
- **Local-first**: PostgreSQL (pgvector), Redis, RAG, CRM, admin panel all run locally. Only external dependency is NVIDIA Build API for LLM/embeddings.
- **Deterministic mode**: Without `NVIDIA_API_KEY` + `NVIDIA_MODEL`, the bot answers using only structured search + document extraction — no LLM calls. This is intentional.
- **Provider abstraction**: `LLMProvider` / `EmbeddingProvider` interfaces; `NVIDIAProvider` is one implementation. Swapping vendors doesn't touch app logic.
- **pgvector dimension**: Must match `EMBEDDING_DIM` in `.env` (2048 for NVIDIA embeddings, 256 for local). Changing requires migration + re-embedding.
- **Admin token**: `ADMIN_TOKEN` from root `.env` is copied to `admin/.env.local` at build time (server-side only, never exposed to browser).

## Environment & Config

- All config in `.env` (copy from `.env.example`). Never commit real `.env`.
- `APP_ENV=production` blocks `scripts.seed` unless `SEED_ALLOW_PRODUCTION=1`.
- `LLM_MODE=auto|nvidia|deterministic` controls LLM behavior.
- `EMBEDDING_PROVIDER=auto|nvidia|local` controls embeddings.
- `DATABASE_URL` and `TEST_DATABASE_URL` are separate; tests use the latter.
- `PGDATA` used by `main.py` to auto-start local Postgres (Termux convenience).

## Testing Conventions

- 155 tests across 11 files: database, search, RAG, agent, CRM, appointments, security, API, E2E, Telegram.
- Tests use isolated `inmobiliaria_test` DB (see `tests/conftest.py`).
- Embeddings use local deterministic provider; never call NVIDIA or Telegram in tests.
- Run full suite: `python -m pytest tests/ -q`
- If tests hang: close other pytest sessions against same test DB (table locks).

## Common Gotchas

| Issue | Cause / Fix |
|-------|-------------|
| `pgvector no instalado` | Use Docker image `pgvector/pgvector:pg18` or compile manually (Termux: see `docs/local-development.md`) |
| `PostgreSQL no accesible` | `docker compose up -d` or `pg_ctl start`; verify `DATABASE_URL` |
| `NVIDIA API ERROR` | Check `NVIDIA_API_KEY`/`NVIDIA_MODEL`; bot still works in deterministic mode |
| Bot doesn't respond | Verify `TELEGRAM_BOT_TOKEN` and that `main.py` is running; check logs |
| 401 in admin panel | Copy `ADMIN_TOKEN` from root `.env` to `admin/.env.local` |
| Seed refuses to run | `APP_ENV=production` blocks it; use dev DB or export `SEED_ALLOW_PRODUCTION=1` |

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