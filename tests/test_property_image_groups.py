"""Fotografías por característica: nombre, descripción y grupo.

Cubre el flujo completo exigido por el rediseño del formulario:
sanitización de nombres (anti path-traversal), nombres de archivo estilo
"Baño.jpg"/"Baño2.jpg", upload por grupo vía API, filtro por grupo en el
listado y resolución por grupo en la herramienta del agente
("muéstrame el baño" → solo fotos del baño).
"""
from __future__ import annotations

import uuid as uuid_mod

import httpx
import pytest

from app.api import files as img_files
from app.api import routes


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=routes.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _real_jpg() -> bytes:
    """JPEG mínimo válido (los uploads exigen imagen real, no bytes falsos)."""
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, format="JPEG")
    return buf.getvalue()


async def _create_property(client, headers, title="Casa de prueba grupos"):
    r = await client.post(
        "/properties",
        json={
            "title": title, "property_type": "casa", "price": 200_000_000,
            "city": "Carepa", "area_m2": 120, "has_parking": True,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------ sanitización y nombres
def test_sanitize_blocks_traversal():
    assert img_files.sanitize_image_stem("../../archivo") != "../../archivo"
    assert "/" not in img_files.sanitize_image_stem("../../archivo")
    assert img_files.sanitize_image_stem("") == ""
    assert img_files.sanitize_image_stem("...") == ""
    # Nombres lógicos válidos se preservan
    assert img_files.sanitize_image_stem("Baño") == "Baño"
    assert img_files.sanitize_image_stem("Piso1") == "Piso1"
    assert img_files.sanitize_image_stem("Piso 2") == "Piso-2"


def test_save_collision_uses_spec_naming(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        img_files, "get_settings",
        lambda: SimpleNamespace(storage_dir=tmp_path, MAX_UPLOAD_MB=15),
    )
    pid = str(uuid_mod.uuid4())
    data = _real_jpg()
    first = img_files.save_property_image(pid, data, "x.jpg", preferred_name="Baño")
    second = img_files.save_property_image(pid, data, "x.jpg", preferred_name="Baño")
    third = img_files.save_property_image(pid, data, "x.jpg", preferred_name="Baño")
    assert first.endswith("Baño.jpg"), first
    assert second.endswith("Baño2.jpg"), second
    assert third.endswith("Baño3.jpg"), third


def test_save_rejects_bad_extension_and_traversal_name(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        img_files, "get_settings",
        lambda: SimpleNamespace(storage_dir=tmp_path, MAX_UPLOAD_MB=15),
    )
    pid = str(uuid_mod.uuid4())
    with pytest.raises(ValueError):
        img_files.save_property_image(pid, b"x", "shell.php", preferred_name="shell")
    # Nombre de archivo con traversal nunca se sirve
    assert img_files.image_path_or_none(pid, "../../x.jpg") is None


# ------------------------------------------------ API: upload por grupo
async def test_upload_list_filter_and_metadata_by_group(client, admin_token):
    headers = admin_token()
    prop = await _create_property(client, headers)
    pid = prop["id"]

    async def upload(fname, name, description, group, extra_name=""):
        data = {"name": name, "description": description, "group": group}
        if extra_name:
            data["extra_name"] = extra_name
        r = await client.post(
            f"/properties/{pid}/images",
            files={"file": (fname, _real_jpg(), "image/jpeg")},
            data=data,
            headers=headers,
        )
        assert r.status_code == 200, r.text
        return r.json()

    bano = await upload("a.jpg", "Baño", "Baño principal con ducha.", "bano")
    assert bano["saved"] == "Baño.jpg"
    bano2 = await upload("b.jpg", "Baño", "Vista lateral de la ducha.", "bano")
    assert bano2["saved"] == "Baño2.jpg"
    cocina = await upload("c.jpg", "Cocina", "Cocina integral.", "cocina")
    assert cocina["saved"] == "Cocina.jpg"
    piscina = await upload("d.jpg", "Piscina", "Piscina exterior de 20 m².", "extra", "Piscina")
    assert piscina["saved"] == "Piscina.jpg"

    # Listado completo trae metadata por imagen
    r = await client.get(f"/properties/{pid}/images")
    assert r.status_code == 200
    items = {i["filename"]: i for i in r.json()["items"]}
    assert items["Baño.jpg"]["group"] == "bano"
    assert items["Baño.jpg"]["description"] == "Baño principal con ducha."
    assert items["Baño2.jpg"]["description"] == "Vista lateral de la ducha."
    assert items["Piscina.jpg"]["group"] == "extra"
    assert items["Piscina.jpg"]["extra_name"] == "Piscina"

    # Filtro por grupo: solo el baño
    r = await client.get(f"/properties/{pid}/images", params={"group": "bano"})
    assert r.status_code == 200
    got = {i["filename"] for i in r.json()["items"]}
    assert got == {"Baño.jpg", "Baño2.jpg"}

    # Grupo inválido se rechaza
    r = await client.get(f"/properties/{pid}/images", params={"group": "garaje"})
    assert r.status_code == 422

    # Extra sin nombre se rechaza
    r = await client.post(
        f"/properties/{pid}/images",
        files={"file": ("e.jpg", _real_jpg(), "image/jpeg")},
        data={"name": "X", "group": "extra"},
        headers=headers,
    )
    assert r.status_code == 422

    # PATCH de metadata (nombre/descripción)
    r = await client.patch(
        f"/properties/{pid}/images/{cocina['saved']}",
        json={"description": "Cocina remodelada."},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["image"]["description"] == "Cocina remodelada."

    # Limpieza: borrar la propiedad elimina su almacenamiento
    r = await client.delete(f"/properties/{pid}", headers=headers)
    assert r.status_code == 200


async def test_property_without_photos_reports_empty_items(client, admin_token):
    headers = admin_token()
    prop = await _create_property(client, headers, title="Casa sin fotos grupos")
    pid = prop["id"]
    r = await client.get(f"/properties/{pid}/images", params={"group": "bano"})
    assert r.status_code == 200
    assert r.json()["items"] == []
    await client.delete(f"/properties/{pid}", headers=headers)


# ------------------------------------------------ agente: resolución por grupo
async def test_agent_resolves_images_by_group(session, user_id):
    from app.agents.tools import ToolContext, run_tool
    from app.memory import service as memory_service
    from app.properties import repository as prop_repo

    prop = await prop_repo.create_property(session, {
        "title": "Casa grupos agente", "property_type": "casa",
        "operation": "SALE", "price": 150_000_000,
        "city": "Carepa", "status": "AVAILABLE",
    })
    await prop_repo.add_property_image(
        session, prop.id, "Bano.jpg", name="Baño",
        description="Baño principal.", group="bano",
    )
    await prop_repo.add_property_image(
        session, prop.id, "Cocina.jpg", name="Cocina",
        description="Cocina integral.", group="cocina",
    )
    await prop_repo.add_property_image(
        session, prop.id, "Piscina.jpg", name="Piscina",
        description="Piscina exterior.", group="extra", extra_name="Piscina",
    )
    await session.commit()
    pid = str(prop.id)

    await memory_service.get_or_create_user(session, user_id, "t", "T")
    ctx = ToolContext(
        session=session, user_id=user_id,
        conversation_id=uuid_mod.uuid4(), state={}, user_text="Muéstrame el baño.",
    )

    # "Muéstrame el baño" → solo el grupo bano
    res = await run_tool("get_property_images", {"property_id": pid, "group": "bano"}, ctx)
    assert res["ok"] is True
    assert [i["filename"] for i in res["images"]] == ["Bano.jpg"]

    # "¿Tienes foto de la cocina?" → solo cocina
    res = await run_tool("get_property_images", {"property_id": pid, "group": "cocina"}, ctx)
    assert res["ok"] is True
    assert [i["filename"] for i in res["images"]] == ["Cocina.jpg"]

    # "Muéstrame la piscina" → extra por nombre
    res = await run_tool(
        "get_property_images",
        {"property_id": pid, "group": "extra", "extra_name": "Piscina"}, ctx,
    )
    assert res["ok"] is True
    assert [i["filename"] for i in res["images"]] == ["Piscina.jpg"]

    # Grupo sin fotos → error honesto, sin sustituir por otra característica
    res = await run_tool("get_property_images", {"property_id": pid, "group": "lavadero"}, ctx)
    assert res["ok"] is False
    assert res.get("code") == "NO_IMAGES"

    # Grupo inválido → error de validación
    res = await run_tool("get_property_images", {"property_id": pid, "group": "garaje"}, ctx)
    assert res["ok"] is False
    assert res.get("code") == "INVALID_GROUP"


async def test_repository_rejects_extra_without_name(session):
    from app.properties import repository as prop_repo

    prop = await prop_repo.create_property(session, {
        "title": "Casa extra inválido", "property_type": "casa",
        "operation": "SALE", "price": 10, "city": "Carepa", "status": "AVAILABLE",
    })
    with pytest.raises(ValueError):
        await prop_repo.add_property_image(
            session, prop.id, "X.jpg", group="extra", extra_name="",
        )
    with pytest.raises(ValueError):
        prop_repo.normalize_image_group("garaje")
