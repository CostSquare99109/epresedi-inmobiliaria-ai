"""Hybrid retrieval over pgvector: vector similarity + Spanish full-text (RRF merge)."""
from __future__ import annotations

import uuid as uuid_mod
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import get_embedding_provider
from app.core.logging import get_logger

log = get_logger(__name__)

RETRIEVAL_TOP_K = 5


@dataclass
class RetrievedChunk:
    chunk_id: uuid_mod.UUID
    document_id: uuid_mod.UUID
    content: str
    page: int | None
    section: str
    filename: str
    document_title: str
    document_type: str
    score: float
    distance: float | None = field(default=None)


async def retrieve_chunks(
    session: AsyncSession,
    query: str,
    k: int = RETRIEVAL_TOP_K,
    property_id: uuid_mod.UUID | None = None,
    document_type: str | None = None,
) -> list[RetrievedChunk]:
    """Returns the top-k document chunks for a query, merging:
    - cosine similarity on embeddings (pgvector <=>)
    - lexical relevance (to_tsvector('spanish') @@ plainto_tsquery)
    via Reciprocal Rank Fusion."""
    if not query.strip():
        return []
    provider = get_embedding_provider()
    qvec = (await provider.embed([query], input_type="query"))[0]

    conds = ["d.status = 'READY'", "c.embedding IS NOT NULL"]
    params: dict = {"qvec": str(qvec), "qtext": query}
    if property_id:
        conds.append("c.property_id = :prop")
        params["prop"] = property_id
    if document_type:
        conds.append("c.document_type = :dtype")
        params["dtype"] = document_type
    where = " AND ".join(conds)
    k1 = max(k * 2, 10)

    vec_sql = text(
        f"""
        SELECT c.id, c.document_id, c.content, c.page, c.section,
               d.filename, d.title, d.document_type,
               (c.embedding <=> CAST(:qvec AS vector)) AS distance
        FROM document_chunks c JOIN documents d ON d.id = c.document_id
        WHERE {where}
        ORDER BY c.embedding <=> CAST(:qvec AS vector)
        LIMIT :k
        """
    )
    fts_sql = text(
        f"""
        SELECT c.id, c.document_id, c.content, c.page, c.section,
               d.filename, d.title, d.document_type,
               ts_rank(to_tsvector('spanish', c.content), plainto_tsquery('spanish', :qtext)) AS rank
        FROM document_chunks c JOIN documents d ON d.id = c.document_id
        WHERE {where}
          AND to_tsvector('spanish', c.content) @@ plainto_tsquery('spanish', :qtext)
        ORDER BY rank DESC
        LIMIT :k
        """
    )

    def to_chunk(row) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=row["id"],
            document_id=row["document_id"],
            content=row["content"],
            page=row["page"],
            section=row["section"],
            filename=row["filename"],
            document_title=row["title"],
            document_type=row["document_type"],
            score=0.0,
        )

    fused: dict[uuid_mod.UUID, tuple[RetrievedChunk, float]] = {}
    vec_rows = (await session.execute(vec_sql, {**params, "k": k1})).mappings().all()
    for rank, row in enumerate(vec_rows):
        chunk = to_chunk(row)
        chunk.distance = float(row["distance"])
        fused[chunk.chunk_id] = (chunk, 1.0 / (60.0 + rank))
    fts_rows = (await session.execute(fts_sql, {**params, "k": k1})).mappings().all()
    for rank, row in enumerate(fts_rows):
        chunk = to_chunk(row)
        prev = fused.get(chunk.chunk_id)
        fused[chunk.chunk_id] = (chunk, (prev[1] if prev else 0.0) + 1.2 / (60.0 + rank))

    ranked = sorted(fused.values(), key=lambda t: t[1], reverse=True)
    results = []
    for chunk, score in ranked[:k]:
        chunk.score = round(score, 6)
        results.append(chunk)
    log.info("rag_retrieve query_len=%s hits=%s", len(query), len(results))
    return results
