"""Internal API: health, inventory CRUD, documents, admin auth, privacy."""
from __future__ import annotations

import uuid as uuid_mod

import httpx
import pytest

from app.api import routes


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=routes.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ------------------------------------------------------------------- health
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


async def test_health_ready_checks_components(client):
    r = await client.get("/health/ready")
    assert r.status_code == 200
    checks = r.json()["checks"]
    assert checks["postgres"] is True
    assert checks["pgvector"] is True
    assert checks["redis"] is True
    assert checks["storage"] is True


# ------------------------------------------------------------------- inventory
async def test_properties_list_and_filter(client):
    r = await client.get("/properties", params={"city": "Carepa", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(body["properties"])
    assert all("Carepa" in p["city"] for p in body["properties"])


async def test_property_get_404(client):
    r = await client.get(f"/properties/{uuid_mod.uuid4()}")
    assert r.status_code == 404


async def test_property_crud_requires_admin(client):
    r = await client.post("/properties", json={"title": "X", "property_type": "casa", "price": 1})
    assert r.status_code == 401  # no token
    r = await client.post(
        "/properties", json={"title": "X", "property_type": "casa", "price": 1},
        headers={"Authorization": "Bearer invalido.simulado"},
    )
    assert r.status_code == 401
    # El antiguo X-Admin-Token ya no autoriza: el JWT es la única autoridad.
    r = await client.post(
        "/properties", json={"title": "X", "property_type": "casa", "price": 1},
        headers={"X-Admin-Token": "cualquier-token-estatico"},
    )
    assert r.status_code == 401


async def test_property_create_patch_delete(client, admin_token):
    headers = admin_token()
    r = await client.post(
        "/properties",
        json={
            "title": "Test API casa", "property_type": "casa", "price": 123_000_000,
            "city": "Carepa", "bedrooms": 2, "features": ["garaje"],
        },
        headers=headers,
    )
    assert r.status_code == 200
    prop = r.json()
    pid = prop["id"]
    assert prop["code"].startswith("PROP-")

    r = await client.patch(f"/properties/{pid}", json={"price": 130_000_000}, headers=headers)
    assert r.status_code == 200 and r.json()["price"] == 130_000_000

    r = await client.get(f"/properties/{pid}")
    assert r.status_code == 200

    r = await client.delete(f"/properties/{pid}", headers=headers)
    assert r.status_code == 200 and r.json()["deleted"] is True
    r = await client.get(f"/properties/{pid}")
    assert r.status_code == 404


async def test_property_create_rejects_invalid_type(client, admin_token):
    r = await client.post(
        "/properties",
        json={"title": "X", "property_type": "nave-espacial", "price": 1},
        headers=admin_token(),
    )
    assert r.status_code == 422


async def test_property_create_frontend_payload_shape(client, admin_token):
    """El payload exacto que envía el formulario web (admin-vite actions.ts).

    Regresión del bug "API 422 en /properties" (2026-09-24): el formulario
    debe crear la propiedad con todos los campos que administra el frontend.
    """
    headers = admin_token()
    payload = {
        "title": "Casa De MariaJose", "property_type": "casa", "operation": "SALE",
        "price": 250_000_000, "currency": "COP",
        "city": "Carepa", "neighborhood": "El Centro",
        "address": "", "street": "", "street_number": "",
        "descriptive_location": "", "nomenclatura": "Calle 100 # 50-20",
        "area_m2": 120.0, "bedrooms": 3, "bedrooms_description": "",
        "bathrooms": 2, "bathrooms_description": "",
        "living_room_description": "", "laundry_area_description": "",
        "parking_spaces": 1, "has_parking": True, "parking_description": "",
        "rent_price": None, "services_included": "no_incluye",
        "visiting_hours": [], "floors": 2,
        "has_kitchen": True, "has_living_room": True, "has_laundry_area": False,
        "features": ["Piscina"], "description": "Casa de prueba",
        "status": "AVAILABLE",
    }
    # httpx `json=` envía Content-Type: application/json, igual que el
    # frontend corregido (client.ts fija la cabecera para cuerpos string).
    r = await client.post("/properties", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    prop = r.json()
    pid = prop["id"]
    assert prop["title"] == "Casa De MariaJose"
    assert prop["features"] == ["Piscina"]

    r = await client.get(f"/properties/{pid}")
    assert r.status_code == 200 and r.json()["id"] == pid

    r = await client.delete(f"/properties/{pid}", headers=headers)
    assert r.status_code == 200 and r.json()["deleted"] is True


async def test_property_create_rejects_body_without_json_content_type(client, admin_token):
    """Sin `Content-Type: application/json` FastAPI recibe un string, no un
    objeto, y responde 422 `model_attributes_type`.

    Este era el error visible en el panel ("API 422 en /properties") cuando el
    cliente fetch enviaba el JSON como text/plain. El frontend debe fijar siempre
    la cabecera (ver admin-vite/src/api/client.ts).
    """
    import json as json_mod

    raw = json_mod.dumps({"title": "X", "property_type": "casa", "price": 1})
    headers = admin_token()
    r = await client.post("/properties", content=raw, headers=headers)
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "model_attributes_type"


# ------------------------------------------------------------------- documents
async def test_document_upload_requires_admin(client):
    r = await client.post(
        "/documents", files={"file": ("a.txt", b"contenido", "text/plain")},
    )
    assert r.status_code == 401


async def test_document_upload_process_delete(client, admin_token):
    headers = admin_token()
    # Use unique content to avoid deduplication
    unique_id = uuid_mod.uuid4().hex[:8]
    content = (
        f"Doc API de prueba {unique_id}.\n\n"
        f"El Proyecto API-Test cuenta con 55 apartamentos de prueba."
    ).encode()
    fname = f"api_test_{unique_id}.txt"
    r = await client.post(
        "/documents", files={"file": (fname, content, "text/plain")},
        data={"title": "Doc API", "document_type": "general"}, headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    doc = body["document"]
    assert doc["status"] in ("PENDING", "READY")
    doc_id = doc["id"]

    r = await client.post(f"/documents/{doc_id}/process", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "READY" and r.json()["chunk_count"] >= 1

    r = await client.get("/documents", headers=headers)
    assert r.status_code == 200
    assert any(d["id"] == doc_id for d in r.json()["documents"])

    r = await client.delete(f"/documents/{doc_id}", headers=headers)
    assert r.status_code == 200


async def test_document_upload_rejects_bad_extension(client, admin_token):
    r = await client.post(
        "/documents", files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
        headers=admin_token(),
    )
    assert r.status_code == 422


# ------------------------------------------------------------------- privacy
async def test_conversations_and_leads_require_admin(client):
    assert (await client.get("/leads")).status_code == 401
    assert (await client.get("/conversations")).status_code == 401
    assert (await client.get("/appointments")).status_code == 401
    assert (await client.get("/ai-events")).status_code == 401
    assert (await client.get("/audit-log")).status_code == 401
    assert (await client.get("/admin-users")).status_code == 401
    assert (await client.get("/settings")).status_code == 401


async def test_documents_endpoints_require_admin(client):
    """Control de acceso: listar, procesar y borrar documentos exige sesión
    admin (regresión: antes eran públicos, incluido el DELETE destructivo)."""
    doc_id = uuid_mod.uuid4()
    assert (await client.get("/documents")).status_code == 401
    assert (await client.post(f"/documents/{doc_id}/process")).status_code == 401
    assert (await client.delete(f"/documents/{doc_id}")).status_code == 401


async def test_admin_inventory_requires_admin(client, admin_token):
    """El inventario admin (incluye estados no públicos) exige sesión admin;
    el listado público del bot sigue siendo público."""
    assert (await client.get("/properties/admin")).status_code == 401
    r = await client.get("/properties/admin", headers=admin_token())
    assert r.status_code == 200
    assert (await client.get("/properties")).status_code == 200


async def test_images_endpoint_blocks_traversal(client):
    pid = uuid_mod.uuid4()
    assert (await client.get(f"/properties/{pid}/images/..%2F.env")).status_code == 404


# ------------------------------------------------------------------- auth sessions
async def _login(client, email="superadmin@test.local", password="test-password-123"):
    r = await client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


async def test_refresh_rotation_rejects_reused_token(client):
    """Rotación de un solo uso (SEC-11): el refresh consumido queda revocado;
    reutilizarlo es 401 y la cadena legítima sigue viva con el token nuevo."""
    first = await _login(client)
    r = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 200
    second = r.json()["refresh_token"]
    assert second != first["refresh_token"]
    # Reusar el refresh ya consumido → 401 (si lo intenta un tercero, es robo).
    r = await client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert r.status_code == 401
    # La cadena legítima continúa con el token nuevo.
    r = await client.post("/auth/refresh", json={"refresh_token": second})
    assert r.status_code == 200


async def test_logout_revokes_refresh_token(client):
    """Logout invalida el refresh en servidor: robar la cookie después no sirve."""
    body = await _login(client)  # httpx conserva las cookies de login
    r = await client.post("/auth/logout")
    assert r.status_code == 200 and r.json()["ok"] is True
    r = await client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert r.status_code == 401


async def test_logout_without_session_still_ok(client):
    """Logout idempotente: sin sesión también responde 200 (borra cookies igual)."""
    r = await client.post("/auth/logout")
    assert r.status_code == 200 and r.json()["ok"] is True


async def test_legacy_refresh_without_jti_is_rejected(client):
    """Tokens emitidos antes del fix (sin jti) se rechazan: tras el deploy,
    las sesiones viejas obligan a un re-login único."""
    from datetime import UTC, datetime, timedelta

    from jose import jwt

    from app.core.settings import get_settings

    s = get_settings()
    legacy = jwt.encode(
        {"sub": "x", "email": "e@test.local", "role": "superadmin",
         "exp": datetime.now(UTC) + timedelta(days=1), "type": "refresh"},
        s.JWT_SECRET, algorithm=s.JWT_ALGORITHM,
    )
    r = await client.post("/auth/refresh", json={"refresh_token": legacy})
    assert r.status_code == 401


# ------------------------------------------------- pentest 2026-09-26 (V-02/V-05/V-06/V-07)
async def test_csrf_origin_guard_blocks_evil_origin(client, admin_token):
    """V-06: mutación con Origin no confiable -> 403 aunque el token sea válido."""
    evil = {"Origin": "http://evil.com", **admin_token()}
    r = await client.post(
        "/properties", json={"title": "CSRF", "property_type": "casa", "price": 1},
        headers=evil,
    )
    assert r.status_code == 403
    # Origen del panel pasa el guard (la autorización la decide el permiso).
    ok_origin = {"Origin": "http://localhost:3000", **admin_token()}
    r = await client.post(
        "/properties", json={"title": "CSRF", "property_type": "casa", "price": 1},
        headers=ok_origin,
    )
    assert r.status_code in (200, 201, 422)


async def test_property_price_overflow_rejected(client, admin_token):
    """V-02: price=1e30 (fuera de Numeric(14,2)) -> 422, nunca 500."""
    props = (await client.get("/properties", params={"limit": 1})).json()["properties"]
    pid = props[0]["id"]
    before = props[0]["price"]
    r = await client.patch(
        f"/properties/{pid}", json={"price": 1e30}, headers=admin_token(),
    )
    assert r.status_code == 422
    after = (await client.get(f"/properties/{pid}")).json()["price"]
    assert after == before


async def test_image_upload_rejects_empty_and_corrupt(client, admin_token):
    """V-07: archivo vacío o con bytes aleatorios -> 422 (no cover de 0 bytes)."""
    props = (await client.get("/properties", params={"limit": 1})).json()["properties"]
    pid = props[0]["id"]
    for name, content, ctype in [
        ("empty.jpg", b"", "image/jpeg"),
        ("random.jpg", bytes(range(256)) * 4, "image/jpeg"),
    ]:
        r = await client.post(
            f"/properties/{pid}/images",
            files={"file": (name, content, ctype)}, headers=admin_token(),
        )
        assert r.status_code == 422, (name, r.status_code, r.text[:150])


async def test_public_properties_rate_limit(client):
    """V-05: el inventario público corta el abuso por IP con 429."""
    import time

    from app.api import routes as routes_mod
    from app.core.settings import get_settings
    from app.security import ratelimit as ratelimit_mod

    s = get_settings()
    old = s.RATE_LIMIT_PUBLIC_PER_MINUTE
    s.RATE_LIMIT_PUBLIC_PER_MINUTE = 3
    # Aislar del resto de la suite: vaciar buckets de lectura pública de este minuto.
    ratelimit_mod._memory_buckets.clear()
    try:
        redis = ratelimit_mod._get_redis()
        if redis is not None:
            try:
                for k in await redis.keys("rl:pub-properties:*"):
                    await redis.delete(k)
            except Exception:
                pass
        codes = [(await client.get("/properties", params={"limit": 1})).status_code
                 for _ in range(5)]
    finally:
        s.RATE_LIMIT_PUBLIC_PER_MINUTE = old
        ratelimit_mod._memory_buckets.clear()
    assert codes[:3] == [200, 200, 200]
    assert 429 in codes[3:]
