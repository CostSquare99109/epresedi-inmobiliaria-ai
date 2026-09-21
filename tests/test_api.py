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

    r = await client.get("/documents")
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


async def test_images_endpoint_blocks_traversal(client):
    pid = uuid_mod.uuid4()
    assert (await client.get(f"/properties/{pid}/images/..%2F.env")).status_code == 404
