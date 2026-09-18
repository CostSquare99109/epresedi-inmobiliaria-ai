# inmobiliaria-ai

Asistente inmobiliario conversacional para Telegram con **RAG real** e inteligencia generativa vía **NVIDIA Build**.

**Local-first**: backend, PostgreSQL, pgvector, Redis, RAG, documentos, imágenes, CRM, agenda, panel administrativo y logs funcionan 100% en local. La única dependencia externa obligatoria es la API de NVIDIA (solo como proveedor de inferencia).

```
TELEGRAM → bot → Conversation Layer → AI Orchestrator
                                          │
              ┌───────────────┬───────────┴─────────┐
              ▼               ▼                     ▼
        Búsqueda híbrida     RAG (pgvector)      CRM / Agenda
        (SQL + FTS + vector)                       │
              └───────────────┬─────────────────────┘
                              ▼
                        NVIDIA Build (LLM)
                              ▼
                        Respuesta al usuario
```

---

## 1. Requisitos

- Python ≥ 3.11 (probado con 3.14)
- PostgreSQL ≥ 16 con la extensión **pgvector**
- Redis ≥ 5 (opcional: el queue hace fallback a memoria)
- Node.js ≥ 20.12 (solo para el panel admin; probado con 24)
- Docker + Docker Compose (opcional, para la infraestructura)

## 2. Instalación

```bash
git clone <repo> && cd inmobiliaria-ai
pip install -r requirements.txt
cp .env.example .env       # y rellena los valores (ver sección 3)
```

## 3. `.env`

Toda la configuración vive en `.env` (copia de `.env.example`). Nunca hay secretos en el código.

Variables obligatorias para el modo completo:

| Variable | Descripción |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token de @BotFather |
| `NVIDIA_API_KEY` | API key de https://build.nvidia.com |
| `NVIDIA_MODEL` | ej. `meta/llama-3.3-70b-instruct` |

Sin esas variables el sistema arranca en **modo determinista**: todas las respuestas se generan desde datos reales (búsqueda estructurada + extracción de documentos) sin LLM. Nada se inventa.

## 4. Docker (infraestructura)

```bash
docker compose up -d     # postgres (pgvector/pgvector:pg18) + redis 7
```

El backend y el panel se ejecutan fuera de Docker (ver sección 12). Alternativa nativa (Termux/localhost): `main.py` arranca automáticamente los clusters locales si detecta `pg_ctl`/`redis-server`.

## 5. PostgreSQL

```bash
# con Docker ya está listo; en nativo:
createdb inmobiliaria   # (main.py crea la BD si falta)
```

Índices: precio, ciudad, tipo, operación, habitaciones, estado, full-text (`search_vector` generado) y vector (`title_embedding`, `halfvec` con `EMBEDDING_DIM` — 2048 con NVIDIA embeddings, ver `.env`).

## 6. Redis

```bash
redis-server --daemonize yes --port 6379   # o docker compose up -d redis
```

Si Redis no está disponible, el queue de jobs funciona con una cola en memoria (documentado en `docs/local-development.md`).

## 7. NVIDIA API

1. Crea una API key en https://build.nvidia.com
2. Ponla en `.env` junto a `NVIDIA_MODEL` (ej. `meta/llama-3.3-70b-instruct`)
3. Verifica con `python -m scripts.doctor`

El proveedor está abstraído (`LLMProvider` → `NVIDIAProvider`, `docs/ai.md`): cambiar de vendor no toca el resto de la app. Los embeddings también son intercambiables (`EmbeddingProvider`): con NVIDIA configurado se usa el modelo de embeddings de NVIDIA (`EMBEDDING_MODEL`, con `input_type` query/passage); sin él, un embedding local determinista (bag-of-tokens, offline). La dimensión (`EMBEDDING_DIM`) debe coincidir con la columna pgvector.

## 8. Telegram Bot

- Crea un bot con @BotFather y pon el token en `.env`.
- Comandos: `/start`, `/help`, `/buscar`, `/propiedades`, `/favoritos`, `/busquedas`, `/citas`, `/perfil`.
- El **lenguaje natural es el mecanismo principal**: «Busco una casa en Carepa de máximo 300 millones, tres habitaciones, garaje y cerca del centro».
- El bot entiende referencias contextuales («la segunda», «la de 280 millones») y respuestas por botones inline.

## 9. Migraciones

```bash
python -m alembic upgrade head   # main.py las ejecuta al arrancar
```

Toda modificación de esquema requiere una migración Alembic nueva (`migrations/versions/`).

## 10. Seed (solo desarrollo y tests)

```bash
python -m scripts.seed
```

⚠️ **Destructivo**: vacía todas las tablas antes de sembrar (propiedades, proyectos, documentos, leads, citas, conversaciones, eventos de IA, favoritos, búsquedas y preferencias). Se **niega a ejecutarse** con `APP_ENV=production` salvo que se exporte `SEED_ALLOW_PRODUCTION=1`. Úsalo siempre contra una BD dedicada de desarrollo; los tests lo reutilizan contra `inmobiliaria_test` (`tests/conftest.py`), nunca contra la BD de desarrollo.

Inserta: 3 proyectos, 16 propiedades (todos los estados: AVAILABLE/RESERVED/SOLD/INACTIVE), 4 documentos (PDF/DOCX/TXT/MD — pasan por el pipeline RAG completo) y portadas JPEG **sintéticas** generadas localmente con Pillow (color + código): son portadas de trabajo, no fotografías reales del inmueble. En producción el inventario se carga con datos y fotos reales vía API. Detalle: `docs/data-audit.md`.

## 11. RAG (ingestión de documentos)

```bash
# colocar archivos en documents/inbox/ y luego:
python -m scripts.ingest
```

Pipeline: validar → hash/dedupe → parsear (PDF/DOCX/TXT/MD) → limpiar → chunking (con secciones y solapamiento) → embeddings → pgvector. Cada chunk guarda trazabilidad completa (`document_id`, `page`, `section`, `chunk_hash`, `embedding_version`). Si cambia un documento, se crea una versión nueva y se reprocesa sin romper el índice.

También se puede subir por el panel admin o por la API (`POST /documents`).

## 12. main.py

```bash
python main.py
```

Único punto de entrada. Boot: config → logging → chequear PostgreSQL/Redis → pgvector → migraciones → servicios → bot → API (`:8000`) → workers → scheduler → apagado controlado (Ctrl+C).

- Con `TELEGRAM_BOT_TOKEN`: bot + API + workers.
- Sin token: API + workers + scheduler (bot desactivado, se avisa en el log).
- Sin NVIDIA: modo determinista (se avisa en el log).

## 13. Panel administrativo

```bash
cd admin && npm install && npm run dev   # http://localhost:3000
```

Next.js + TypeScript. Secciones: Dashboard (salud + contadores), Propiedades (cambiar estado), Documentos·RAG (subir/procesar/reprocesar/eliminar), Leads, Conversaciones, Citas, Logs IA (auditoría).

El token admin se inyecta **server-side** (el `.env` raíz se copia a `admin/.env.local`, gitignored; el navegador nunca lo ve).

## 14. Tests

```bash
python -m pytest tests/ -q
```

155 tests: database (migraciones/índices/constraints/pgvector), search (filtros/precio/disponibilidad), RAG (ingestión/chunking/metadata/retrieval/citas/versioning), agent (intents/referencias/contexto), CRM, appointments (doble-reserva), security (prompt injection/SQL injection/path traversal), API y E2E del flujo completo.

Los tests usan una base de datos aislada (`inmobiliaria_test`), embeddings locales y nunca llaman a NVIDIA ni a Telegram.

## 15. Troubleshooting

| Problema | Solución |
|---|---|
| `pgvector no instalado` | Docker: usa la imagen `pgvector/pgvector`. Termux: compilación manual (ver `docs/local-development.md`) |
| `PostgreSQL no accesible` | `docker compose up -d` o `pg_ctl start`; revisa `DATABASE_URL` en `.env` |
| `NVIDIA API ERROR` en doctor | Revisa `NVIDIA_API_KEY`/`NVIDIA_MODEL`; el bot sigue en modo determinista |
| El bot no responde | Verifica `TELEGRAM_BOT_TOKEN` y que `main.py` esté corriendo; mira los logs |
| 401 en el panel | Copia `ADMIN_TOKEN` del `.env` raíz a `admin/.env.local` |
| Los tests cuelgan | Cierra otras sesiones de pytest contra la misma BD de test (bloqueos de tablas) |

Más detalle: `docs/troubleshooting.md`.

---

## Arquitectura y documentación técnica

```
docs/
├── architecture.md        # capas, flujo, decisiones
├── database.md            # esquema, índices, migraciones
├── rag.md                 # pipeline, chunking, versioning, anti-injection
├── ai.md                  # LLM/embeddings providers, fallbacks, anti-alucinación
├── agent-tools.md         # herramientas del agente y flujo tool-calling
├── telegram.md            # handlers, teclados, UX
├── local-development.md   # entornos nativo/Docker, scripts
├── testing.md             # qué cubre cada suite
├── security.md            # seguridad de archivos, rate limiting, privacidad
├── admin-panel.md         # panel administrativo: arquitectura, componentes, tokens
├── data-audit.md          # auditoría de datos demo/hardcodeados y aislamiento dev/test/prod
└── troubleshooting.md     # diagnóstico de problemas comunes
```

Diagnóstico rápido: `python -m scripts.doctor` (Python, PostgreSQL, Redis, pgvector, NVIDIA, Telegram, esquema, storage, RAG).
