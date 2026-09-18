"""Hybrid property search: SQL filters + full-text + pgvector similarity.

Numeric criteria are ALWAYS resolved deterministically here (never by the LLM).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import get_embedding_provider
from app.core.logging import get_logger

log = get_logger(__name__)

NUMBER_WORDS = {
    "un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8,
}

TYPE_WORDS = {
    "casa": "casa", "casas": "casa", "apartamento": "apartamento", "apto": "apartamento",
    "apartamentos": "apartamento", "lote": "lote", "lotecito": "lote", "terreno": "lote",
    "terrenos": "lote", "local": "local", "locales": "local", "oficina": "oficina",
    "oficinas": "oficina", "finca": "finca", "fincas": "finca", "proyecto": "proyecto",
    "proyectos": "proyecto",
}


def _deaccent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


@dataclass
class SearchFilters:
    property_type: str | None = None
    operation: str | None = None
    city: str | None = None
    neighborhood: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_area: float | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    parking: int | None = None
    query_text: str = ""
    include_unavailable: bool = False
    limit: int = 8

    def to_dict(self) -> dict:
        d = {}
        for k in (
            "property_type", "operation", "city", "neighborhood",
            "min_price", "max_price", "min_area", "bedrooms", "bathrooms", "parking",
        ):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        if self.query_text:
            d["query_text"] = self.query_text
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SearchFilters":
        known = {k: v for k, v in d.items() if k in {
            "property_type", "operation", "city", "neighborhood", "min_price", "max_price",
            "min_area", "bedrooms", "bathrooms", "parking", "query_text",
        }}
        return cls(**known, include_unavailable=False)

    def describe(self) -> str:
        parts = []
        if self.operation == "RENT":
            parts.append("arriendo")
        if self.property_type:
            parts.append(self.property_type)
        if self.city:
            parts.append(f"en {self.city}")
        if self.max_price:
            parts.append(f"hasta ${self.max_price:,.0f}")
        if self.min_price:
            parts.append(f"desde ${self.min_price:,.0f}")
        if self.bedrooms:
            parts.append(f"{self.bedrooms}+ habitaciones")
        if self.bathrooms:
            parts.append(f"{self.bathrooms}+ baños")
        if self.parking:
            parts.append(f"{self.parking}+ parqueaderos")
        return ", ".join(parts) or "sin filtros"


def _num(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token.lower())


PRICE_RE = re.compile(
    r"(?P<prefix>(?:hasta|m[aá]ximo|max|menos de|desde|m[ií]nimo|min|de)\s+)?"
    r"(?:\$|cop\s*)?"
    r"(?P<a>\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*"
    r"(?P<mill>millones?|mill|mm)?"
)
PRICE_RANGE_RE = re.compile(
    r"entre\s+(?:\$|cop\s*)?(?P<a>\d[\d.,]*)(?:\s*millones?)?\s*y\s+(?:\$|cop\s*)?(?P<b>\d[\d.,]*)(?:\s*millones?)?"
)
ROOMS_RE = re.compile(
    r"(?P<n>\d+|un|una|dos|tres|cuatro|cinco|seis)\s*"
    r"(?:habitaciones|habitaci[oó]n|habitacion|alcobas|alcoba|cuartos|cuarto|dormitorios|dormitorio|hab\b|habs?\b)"
)
BATHS_RE = re.compile(
    r"(?P<n>\d+|un|una|dos|tres|cuatro|cinco)\s*(?:ba[ñn]os|ba[ñn]o|b[ñn]os)\b"
)
PARK_N_RE = re.compile(
    r"(?P<n>\d+|un|una|dos|tres)\s*(?:garajes|parqueaderos|parqueos|parkings)"
)
PARK_ANY_RE = re.compile(r"\b(?:garaje|garaje|parqueadero|parqueaderos|parqueo|parqueos|parking)\b")
OPERATION_RENT_RE = re.compile(r"\b(?:arriendo|arrendar|alquiler|alquilar|rentar|alquilada)\b")
OPERATION_SALE_RE = re.compile(r"\b(?:venta|vender|comprar|compra|adquirir|en venta)\b")
TYPE_RE = re.compile(
    r"\b(casas?|apartamentos?|aptos?|lotes?|terrenos?|locales?|oficinas?|fincas?|proyectos?)\b"
)
AREA_RE = re.compile(r"(?P<n>\d+)\s*(?:m2|mts2|metros\s*c[uú]adrados|metros)\b")

MAX_ROOMS_RE = re.compile(r"m[aá]ximo\s+(?P<n>\d+|un|una|dos|tres|cuatro|cinco)\s*habitaciones")


def _match_span(text_span: str, regex: re.Pattern, low: str) -> tuple | None:
    m = regex.search(low)
    if not m:
        return None
    return m
def extract_filters(message: str) -> tuple[SearchFilters, str]:
    """Deterministic criteria extraction. Returns (filters, semantic_leftover)."""
    low = _deaccent(message.lower())
    filters = SearchFilters()
    consumed: list[tuple[int, int]] = []

    def consume(m: re.Match) -> None:
        consumed.append((m.start(), m.end()))

    # --- operation
    m = OPERATION_RENT_RE.search(low)
    if m:
        filters.operation = "RENT"
        consume(m)
    m = OPERATION_SALE_RE.search(low)
    if m:
        filters.operation = "SALE"
        consume(m)

    # --- price range "entre X y Y"
    m = PRICE_RANGE_RE.search(low)
    if m:
        a = parse_price_token(m.group("a"), "millones" if "million" in m.group(0) or "millon" in m.group(0) else None)
        b = parse_price_token(m.group("b"), "millones")
        filters.min_price, filters.max_price = a, b
        consume(m)
    else:
        for m in PRICE_RE.finditer(low):
            if not m.group("prefix") and not m.group("mill"):
                # bare number with no context — ignore unless $ or cop present
                if "$" not in m.group(0) and "cop" not in m.group(0):
                    continue
            value = parse_price_token(m.group("a"), m.group("mill"))
            if value is None:
                continue
            prefix = m.group("prefix") or ""
            before = low[max(0, m.start() - 12): m.start()]
            if any(p in prefix for p in ("hasta", "maximo", "max", "menos")):
                filters.max_price = value
            elif any(p in prefix for p in ("desde", "minimo", "min")):
                filters.min_price = value
            elif "hasta" in before:
                filters.max_price = value
            elif "entre" in before or "de" in before:
                filters.max_price = value
            else:
                filters.max_price = value if value >= 10_000_000 else filters.max_price
            consume(m)

    # --- rooms
    if MAX_ROOMS_RE.search(low):
        m = MAX_ROOMS_RE.search(low)
        n = _num(m.group("n"))
        if n:
            filters.bedrooms = n  # treated as exact-ish upper bound preference
            consume(m)
    else:
        m = ROOMS_RE.search(low)
        if m:
            n = _num(m.group("n"))
            if n:
                filters.bedrooms = n
                consume(m)

    m = BATHS_RE.search(low)
    if m:
        n = _num(m.group("n"))
        if n:
            filters.bathrooms = n
            consume(m)

    # --- parking
    m = PARK_N_RE.search(low)
    if m:
        n = _num(m.group("n"))
        if n:
            filters.parking = n
            consume(m)
    else:
        m = PARK_ANY_RE.search(low)
        if m:
            filters.parking = 1
            consume(m)

    # --- property type
    m = TYPE_RE.search(low)
    if m:
        filters.property_type = TYPE_WORDS[m.group(0)]
        consume(m)

    # --- area
    m = AREA_RE.search(low)
    if m:
        try:
            filters.min_area = float(m.group("n"))
            consume(m)
        except ValueError:
            pass

    # --- leftover → semantic query
    leftover_parts: list[str] = []
    last = 0
    for start, end in sorted(consumed):
        piece = low[last:start].strip(" ,.;:")
        if piece:
            leftover_parts.append(piece)
        last = end
    tail = low[last:].strip(" ,.;:")
    if tail:
        leftover_parts.append(tail)
    semantic = " ".join(leftover_parts).strip()
    noise = re.compile(
        r"\b(quiero|busco|busca|necesito|encuentrame|encontrame|deme|dame|muestrame|muestra|"
        r"ver|una|un|el|la|los|las|para|por|que|tenga|tengan|con|y|o|de|del|donde|cerca|bien|"
        r"hola|gracias|porfavor|por favor)\b"
    )
    semantic = noise.sub(" ", semantic)
    semantic = re.sub(r"\s+", " ", semantic).strip()
    filters.query_text = semantic or low.strip()

    # domain rule: a multi-million budget with no explicit operation means a purchase
    if filters.operation is None and filters.max_price and filters.max_price >= 10_000_000:
        filters.operation = "SALE"
    elif filters.operation is None and filters.min_price and filters.min_price >= 10_000_000:
        filters.operation = "SALE"
    return filters, semantic


def _feature_tokens(semantic: str) -> list[str]:
    """Recognized amenity tokens for the features JSONB boost."""
    tokens = []
    for key, words in {
        "garaje": ("garaje", "parqueadero", "parqueo"),
        "piscina": ("piscina",),
        "jardin": ("jardin", "patio"),
        "terraza": ("terraza",),
        "seguridad": ("vigilancia", "seguridad"),
        "mascotas": ("mascotas", "petfriendly", "pet friendly"),
        "ascensor": ("ascensor",),
        "cocina integral": ("cocina integral",),
        "cerca al centro": ("centro", "centro comercial", "plaza"),
        "colegios": ("colegios", "colegio", "escuelas", "escuela"),
    }.items():
        if any(w in semantic for w in words):
            tokens.append(key)
    return tokens


@dataclass
class PropertyHit:
    property_id: str
    score: float
    text_rank: float
    vec_sim: float
    matched_features: list[str] = field(default_factory=list)


def _build_where(filters: SearchFilters, params: dict) -> str:
    conds = []
    if not filters.include_unavailable:
        conds.append("p.status = 'AVAILABLE'")
    if filters.operation:
        conds.append("p.operation = :operation")
        params["operation"] = filters.operation
    if filters.property_type:
        conds.append("p.property_type = :ptype")
        params["ptype"] = filters.property_type
    if filters.city:
        conds.append("p.city ILIKE :city")
        params["city"] = f"%{filters.city}%"
    if filters.neighborhood:
        conds.append("p.neighborhood ILIKE :hood")
        params["hood"] = f"%{filters.neighborhood}%"
    if filters.max_price is not None:
        conds.append("p.price <= :max_price")
        params["max_price"] = filters.max_price
    if filters.min_price is not None:
        conds.append("p.price >= :min_price")
        params["min_price"] = filters.min_price
    if filters.min_area is not None:
        conds.append("p.area_m2 >= :min_area")
        params["min_area"] = filters.min_area
    if filters.bedrooms is not None:
        conds.append("p.bedrooms >= :bedrooms")
        params["bedrooms"] = filters.bedrooms
    if filters.bathrooms is not None:
        conds.append("p.bathrooms >= :bathrooms")
        params["bathrooms"] = filters.bathrooms
    if filters.parking is not None:
        conds.append("p.parking_spaces >= :parking")
        params["parking"] = filters.parking
    return " AND ".join(conds) if conds else "TRUE"


async def search_properties(
    session: AsyncSession, filters: SearchFilters, semantic: str | None = None
) -> list[PropertyHit]:
    """SQL filtering first, then ranking by full-text + vector + features."""
    params: dict = {"limit": filters.limit}
    where = _build_where(filters, params)
    semantic = semantic or filters.query_text

    qvec = None
    if semantic:
        provider = get_embedding_provider()
        try:
            qvec = (await provider.embed([semantic], input_type="query"))[0]
            params["qvec"] = str(qvec)
        except Exception as e:  # embeddings must never break structured search
            log.warning("embedding_failed_falling_back_to_sql_only error=%s", e)
    if semantic:
        params["qtext"] = semantic

    text_rank_expr = (
        "COALESCE(ts_rank(p.search_vector, plainto_tsquery('spanish', :qtext)), 0)"
        if semantic
        else "0"
    )
    vec_expr = (
        "COALESCE(1 - (p.title_embedding <=> CAST(:qvec AS vector)), 0)"
        if qvec is not None
        else "0"
    )
    feats = _feature_tokens(semantic or "")
    feature_expr = "CASE WHEN p.features ?| CAST(:feat_array AS text[]) THEN 0.15 ELSE 0 END" if feats else "0"
    if feats:
        params["feat_array"] = feats

    sql = text(
        f"""
        SELECT p.id,
               ({text_rank_expr}) AS text_rank,
               ({vec_expr}) AS vec_sim,
               ({feature_expr}) AS feat_boost
        FROM properties p
        WHERE {where}
        ORDER BY (2.2 * ({text_rank_expr}) + ({vec_expr}) + ({feature_expr})) DESC,
                 p.created_at DESC
        LIMIT :limit
        """
    )
    rows = (await session.execute(sql, params)).mappings().all()
    hits = [
        PropertyHit(
            property_id=str(row["id"]),
            score=round(2.2 * float(row["text_rank"]) + float(row["vec_sim"]) + float(row["feat_boost"]), 6),
            text_rank=round(float(row["text_rank"]), 6),
            vec_sim=round(float(row["vec_sim"]), 6),
            matched_features=feats,
        )
        for row in rows
    ]
    log.info("property_search filters=%s semantic=%r results=%s",
             filters.describe(), (semantic or "")[:60], len(hits))
    return hits


async def match_saved_search(
    session: AsyncSession, filters_dict: dict, limit: int = 3
) -> list[PropertyHit]:
    """Saved-search worker: find AVAILABLE properties matching stored filters."""
    sf = SearchFilters.from_dict(filters_dict)
    sf.limit = limit
    sf.include_unavailable = False
    return await search_properties(session, sf, sf.query_text)


async def similar_properties(
    session: AsyncSession, property_id: str, limit: int = 3
) -> list[PropertyHit]:
    """Recommendations: same-type/city, price band, vector similarity to target."""
    params: dict = {"pid": property_id, "limit": limit}
    sql = text(
        """
        SELECT p2.id,
               COALESCE(1 - (p2.title_embedding <=> p1.title_embedding), 0) AS vec_sim
        FROM properties p1, properties p2
        WHERE p1.id = :pid
          AND p2.id <> p1.id
          AND p2.status = 'AVAILABLE'
          AND (p2.property_type = p1.property_type OR p2.city = p1.city)
          AND p2.price BETWEEN p1.price * 0.6 AND p1.price * 1.4
        ORDER BY vec_sim DESC, p2.created_at DESC
        LIMIT :limit
        """
    )
    rows = (await session.execute(sql, params)).mappings().all()
    return [
        PropertyHit(
            property_id=row["id"], score=round(float(row["vec_sim"]), 6),
            text_rank=0.0, vec_sim=round(float(row["vec_sim"]), 6),
        )
        for row in rows
    ][:limit]


def parse_price_token(raw: str, mill: str | None) -> float | None:
    raw = raw.strip()
    # COP convention: "." separates thousands ("285.000.000"). But a single
    # separator with 1-2 trailing digits is a decimal ("1.5 millones").
    if re.fullmatch(r"\d{1,3}[.,]\d{1,2}", raw):
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    if mill and mill.strip():
        return value * 1_000_000
    # bare numbers < 10,000 are never COP prices in this domain → treat as millions
    if value < 10_000:
        return value * 1_000_000
    return value




