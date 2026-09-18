# RAG

Pipeline real de ingestión y recuperación sobre pgvector.

## Pipeline de ingestión

```
Documento (documents/inbox/ o POST /documents)
   ↓
Validación     extensión permitida (.pdf/.docx/.txt/.md), tamaño (MAX_UPLOAD_MB), no vacío, nombre seguro
   ↓
Hash + dedupe  sha256 único → mismo hash = duplicado (skip); mismo filename + contenido nuevo = versión nueva
   ↓
Parser         app/rag/parsing.py (PDF con pypdf y páginas reales; DOCX vía zipfile; TXT/MD)
   ↓
Limpieza       espacios, \x00, normalización
   ↓
Chunking       app/rag/chunking.py: párrafos (máx 900 chars, solapamiento 120), detecta secciones
               ("# …", "Artículo N …", líneas en MAYÚSCULAS tipo "FINANCIACION:")
   ↓
Metadata       document_id, chunk_id, property_id, project_id, document_type, filename, page, section, chunk_hash
   ↓
Embeddings     EmbeddingProvider (NVIDIA nv-embedqa-e5-v5 o local hash 256-dim)
   ↓
pgvector       document_chunks.embedding (vector 256)
```

## Trazabilidad de cada chunk

`document_id`, `chunk_id`, `property_id`, `project_id`, `document_type`, `filename`, `page`, `section`, `content`, `embedding`, `chunk_hash`, `created_at`, `updated_at`.

## Versioning

Si cambia un documento (mismo filename, hash distinto): `version += 1`, `file_hash` nuevo, `processed_at` reset, chunks reconstruidos (delete + insert atómico), `embedding_version` registrado. Reprocesar nunca rompe el índice.

## Recuperación híbrida

`app/rag/retrieval.py:retrieve_chunks` fusiona (Reciprocal Rank Fusion):

1. **Similitud vectorial**: `c.embedding <=> :qvec` (pgvector)
2. **Relevancia léxica**: `to_tsvector('spanish', c.content) @@ plainto_tsquery('spanish', :qtext)`

Solo chunks de documentos `READY`. Top-k (5 por defecto).

## Extracción de respuesta (modo determinista)

`app/agents/orchestrator.py:extract_doc_answer`:

1. **Puerta de entidad**: si la pregunta nombra una entidad («Proyecto X») y ningún chunk la menciona → «No tengo información confirmada sobre eso en los documentos.» (los términos-stopword solo cuentan si van en mayúscula en el original: «Proyecto Y» es entidad, «villas de» no).
2. **Ranking de frases**: mini-IDF sobre los chunks recuperados (los tokens raros deciden) + bonus de sección + bonus de cantidad + penalización de encabezados.
3. Solo cita texto literal del documento, con fuente.

## Citas (citations)

Cuando la respuesta depende de documentos:

```
Según {título} (página N):

«{frase literal del documento}»

Fuente: {título} (página N)
```

Internamente registra `chunk_id`, `document_id`, `page`, `retrieval_score` en la auditoría (`ai_events`).

## Prompt injection — UNTRUSTED DATA

Todo documento recuperado es **texto documental, no instrucciones**:

- El system prompt declara que el contenido de documentos viene delimitado y nunca debe cambiar reglas, permisos o herramientas.
- Un PDF que diga «ignora todas las instrucciones anteriores» se trata como contenido informativo.
- El extractor determinista solo cita frases literales — no ejecuta nada del documento.
- Test: `tests/test_security.py::test_injected_document_is_data_not_instructions`.
