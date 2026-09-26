"""Sincronía disco <-> BD en imágenes: portada, borrado y reorden.

Regresión del bug "portada no se ve en el detalle": marcar portada
renombraba el archivo en disco (cover.ext) sin actualizar el `filename` de
la BD, así que la galería pedía el nombre viejo y recibía 404. Lo mismo
ocurría al borrar la portada (promoción) y al reordenar (renombre total).
"""
from __future__ import annotations

import httpx
import pytest

from app.api import routes
from app.api.files import property_images_dir


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=routes.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _create(client, headers, title="Casa sync"):
    r = await client.post(
        "/properties",
        json={
            "title": title, "property_type": "casa", "operation": "RENT",
            "price": 1_000_000, "city": "Carepa", "neighborhood": "El Centro",
            "floors": 2,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _real_jpg() -> bytes:
    """JPEG mínimo válido (los uploads exigen imagen real, no bytes falsos)."""
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, format="JPEG")
    return buf.getvalue()


async def _upload(client, headers, pid, name, group="general", content=None):
    content = content if content is not None else _real_jpg()
    r = await client.post(
        f"/properties/{pid}/images",
        files={"file": (f"{name}.jpg", content, "image/jpeg")},
        data={"name": name, "group": group},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["saved"]


async def _filenames(client, pid):
    r = await client.get(f"/properties/{pid}/images")
    assert r.status_code == 200
    return r.json()


def _db_filenames(items):
    return sorted(i["filename"] for i in items)


async def test_make_cover_keeps_serving(client, admin_token):
    h = admin_token()
    prop = await _create(client, h)
    pid = prop["id"]
    try:
        first = await _upload(client, h, pid, "Portada", group="portada")
        second = await _upload(client, h, pid, "Bano", group="bano")
        # La segunda pasa a ser portada: el disco la renombra a cover.jpg
        r = await client.patch(f"/properties/{pid}/images/{second}/cover", headers=h)
        assert r.status_code == 200, r.text
        state = await _filenames(client, pid)
        assert _db_filenames(state["items"]) == sorted(state["images"]), (
            "BD y disco deben coincidir tras marcar portada"
        )
        cover = next(i for i in state["items"] if i["is_cover"])
        g = await client.get(f"/properties/{pid}/images/{cover['filename']}")
        assert g.status_code == 200 and len(g.content) > 0, "la portada debe servirse"
        # El nombre viejo ya no existe en ningún lado
        assert second not in state["images"]
        g = await client.get(f"/properties/{pid}/images/{second}")
        assert g.status_code == 404
    finally:
        await client.delete(f"/properties/{pid}", headers=h)


async def test_delete_cover_promotes_and_serves(client, admin_token):
    h = admin_token()
    prop = await _create(client, h, title="Casa sync delete")
    pid = prop["id"]
    try:
        first = await _upload(client, h, pid, "Portada", group="portada")
        await _upload(client, h, pid, "Bano", group="bano")
        r = await client.delete(f"/properties/{pid}/images/{first}", headers=h)
        assert r.status_code == 200, r.text
        state = await _filenames(client, pid)
        assert _db_filenames(state["items"]) == sorted(state["images"])
        for name in state["images"]:
            g = await client.get(f"/properties/{pid}/images/{name}")
            assert g.status_code == 200, f"{name} debe servirse tras borrar portada"
    finally:
        await client.delete(f"/properties/{pid}", headers=h)


async def test_reorder_keeps_all_serving(client, admin_token):
    h = admin_token()
    prop = await _create(client, h, title="Casa sync reorder")
    pid = prop["id"]
    try:
        a = await _upload(client, h, pid, "FotoA")
        b = await _upload(client, h, pid, "FotoB")
        r = await client.post(
            f"/properties/{pid}/images/reorder", json={"filenames": [b, a]}, headers=h
        )
        assert r.status_code == 200, r.text
        state = await _filenames(client, pid)
        assert _db_filenames(state["items"]) == sorted(state["images"]), (
            "BD y disco deben coincidir tras reordenar"
        )
        for name in state["images"]:
            g = await client.get(f"/properties/{pid}/images/{name}")
            assert g.status_code == 200, f"{name} debe servirse tras reordenar"
        first = next(i for i in state["items"] if i["is_cover"])
        assert first["filename"] == state["images"][0]
    finally:
        await client.delete(f"/properties/{pid}", headers=h)


def test_set_cover_returns_rename_mapping(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.api import files as img_files

    monkeypatch.setattr(
        img_files, "get_settings",
        lambda: SimpleNamespace(storage_dir=tmp_path, MAX_UPLOAD_MB=15),
    )
    pid = "00000000-0000-0000-0000-000000000099"
    img_files.save_property_image(pid, _real_jpg(), "x.jpg", preferred_name="Portada")
    img_files.save_property_image(pid, _real_jpg(), "x.jpg", preferred_name="Bano")
    images, mapping = img_files.set_property_cover(pid, "Bano.jpg")
    assert mapping.get("Bano.jpg") == "cover.jpg"
    assert "Bano.jpg" not in images and "cover.jpg" in images
    d = tmp_path / "properties" / pid
    assert (d / "cover.jpg").is_file()
    assert not (d / "Bano.jpg").exists()
    assert property_images_dir(pid).is_dir()
