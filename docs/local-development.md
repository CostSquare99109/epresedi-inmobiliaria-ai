# Desarrollo local

## Requisitos por entorno

| Componente | Nativo / Termux |
|---|---|
| PostgreSQL + pgvector | `pg_ctl` + compilación manual de pgvector |
| Redis | `redis-server` |
| Backend | `python main.py` |
| Panel | `cd admin && npm run dev` |

## Arranque completo

```bash
# PostgreSQL (Termux / Linux)
initdb -D ~/pgdata-inmob
pg_ctl -D ~/pgdata-inmob start
# En la BD: CREATE EXTENSION vector;

# Redis (Termux / Linux)
redis-server --daemonize yes --port 6379

# Backend
python main.py
```

`main.py` comprueba PostgreSQL/Redis/pgvector y ejecuta las migraciones al arrancar. En entornos nativos con `pg_ctl`/`redis-server` disponibles, intenta arrancarlos automáticamente si detecta que los puertos 5432/6379 están libres.

## Scripts

| Comando | Función |
|---|---|
| `python -m scripts.seed` | Datos demo: propiedades (todos los estados), documentos reales (pipeline RAG completo), imágenes JPEG reales |
| `python -m scripts.ingest` | Escanea `documents/inbox/`, dedupe por hash, parsea, chunking, embeddings, almacena, reporta errores. Los ya procesados no se reprocesan |
| `python -m scripts.doctor` | Diagnóstico: Python, PostgreSQL, Redis, pgvector, NVIDIA, Telegram, esquema, storage, RAG |

## Panel admin (Termux)

Los shebangs de `node_modules/.bin` no funcionan en Termux (`/usr/bin/env` inexistente). Ejecutar directamente:

```bash
cd admin
npm install
node node_modules/next/dist/bin/next dev -p 3000
```

El panel compila rutas on-demand (la primera petición a cada página tarda; en Termux puede tardar ~1 min por página la primera vez).

## Entornos

- `APP_ENV=development` (default)
- `LLM_MODE=auto|nvidia|deterministic` — determinista = sin red, respuestas 100% desde datos
- `EMBEDDING_PROVIDER=auto|nvidia|local` — local = hash 256-dim offline

## Redis caído

El queue de jobs (`app/workers/queue.py`) hace fallback automático a una cola en memoria (los jobs sobreviven solo mientras el proceso vive; se documenta como limitación). El rate limiter también tiene fallback a memoria.

## Datos de prueba

Nunca en handlers: el seed (`scripts/seed.py`) genera 16 propiedades en Carepa (disponibles, vendidas, reservadas, inactivas), 4 documentos (reglamento PDF, ficha DOCX, normativa MD, contrato TXT) e imágenes.

## pgvector en Termux

```bash
# Compilación manual de pgvector
git clone https://github.com/pgvector/pgvector
cd pgvector
make
make install
```

Luego en PostgreSQL:
```sql
CREATE EXTENSION vector;
```

La dimensión del vector debe coincidir con `EMBEDDING_DIM` en `.env` (256 para embeddings locales, 2048 para NVIDIA).