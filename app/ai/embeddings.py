"""Embedding provider abstraction.

LocalHashEmbedding: deterministic 256-dim bag-of-tokens embedding computed with
numpy. No downloads, fully offline, real cosine similarity over normalized
Spanish tokens. Good enough for the prototype's lexical-semantic retrieval;
NVIDIA embeddings (nvidia/nv-embedqa-e5-v5) provide true semantics and are
selected automatically when NVIDIA_API_KEY + NVIDIA_MODEL are configured.

Swapping providers only requires the same embed() interface (docs/ai.md).
"""
from __future__ import annotations

import hashlib
import math
import unicodedata
from typing import Protocol

from app.core.settings import get_settings

try:  # numpy ships with Termux python-numpy
    import numpy as np
except Exception:  # pragma: no cover
    np = None

STOPWORDS = frozenset(
    "de la el los las un una unos unas y o u e en con para por del al que se su sus"
    " mi mis tu tus es son esta este estos estas me te le les nos yo tu el ella"
    " quiero busco busca necesito cerca maximo max menos entre desde hasta donde"
    " pronto hora dia dias minutos gracias hola buen buenao bueno"
).union({})

SPANISH_MIN = "áéíóúüñÁÉÍÓÚÜÑ"


def normalize_text(text: str) -> list[str]:
    """Lowercase, de-accent, drop punctuation, remove stopwords, light stemming."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    out: list[str] = []
    for tok in text.split():
        tok = "".join(ch for ch in tok if ch.isalnum())
        if not tok or tok in STOPWORDS:
            continue
        if len(tok) > 4 and tok.endswith("es"):
            tok = tok[:-2]
        elif len(tok) > 3 and tok.endswith("s"):
            tok = tok[:-1]
        out.append(tok)
    return out


def _token_bucket(token: str, dim: int) -> tuple[int, int]:
    """Two stable hash buckets per token for a mini two-channel projection."""
    h = hashlib.md5(token.encode("utf-8")).digest()
    b1 = int.from_bytes(h[:4], "little") % dim
    b2 = int.from_bytes(h[4:8], "little") % dim
    return b1, b2


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str], input_type: str = "passage") -> list[list[float]]: ...


class LocalHashEmbedding:
    name = "local-hash-bow"
    dim = 256

    def __init__(self, dim: int = 256):
        self.dim = dim

    async def embed(self, texts: list[str], input_type: str = "passage") -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self.dim
            tokens = normalize_text(text)
            if not tokens:
                vectors.append(vec)
                continue
            for tok in tokens:
                b1, b2 = _token_bucket(tok, self.dim)
                vec[b1] += 1.0
                vec[b2] += 0.5
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors


class NVIDIAEmbedding:
    name = "nvidia"

    def __init__(self, dim: int, model: str | None = None):
        self.dim = dim
        s = get_settings()
        self._model = model or s.EMBEDDING_MODEL
        self._api_key = s.NVIDIA_API_KEY
        self._base_url = s.NVIDIA_BASE_URL.rstrip("/")

    @property
    def label(self) -> str:
        return f"nvidia:{self._model}"

    async def embed(self, texts: list[str], input_type: str = "passage") -> list[list[float]]:
        import httpx

        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/embeddings",
                json={
                    "input": texts,
                    "model": self._model,
                    "encoding_format": "float",
                    "input_type": input_type,
                },
                headers=headers,
            )
        resp.raise_for_status()
        data = resp.json()["data"]
        vectors = [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]
        for v in vectors:
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            v = [x / norm for x in v]
        return vectors


_embedding_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    global _embedding_provider
    if _embedding_provider is not None:
        return _embedding_provider
    s = get_settings()
    if s.embedding_is_nvidia and s.nvidia_configured:
        _embedding_provider = NVIDIAEmbedding(s.EMBEDDING_DIM)
    else:
        _embedding_provider = LocalHashEmbedding(s.EMBEDDING_DIM)
    return _embedding_provider


def set_embedding_provider(provider: EmbeddingProvider) -> None:
    global _embedding_provider
    _embedding_provider = provider


def embedding_version() -> str:
    p = get_embedding_provider()
    return f"{p.name}:{p.dim}"
