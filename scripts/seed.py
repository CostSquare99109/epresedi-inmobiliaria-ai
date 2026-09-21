"""Seed de DESARROLLO/TEST: proyectos, propiedades (todos los estados), documentos reales e imágenes.

Usage: python -m scripts.seed

DESTRUCTIVO: vacía todas las tablas antes de sembrar (idempotente para dev/test).
Se niega a ejecutarse con APP_ENV=production salvo SEED_ALLOW_PRODUCTION=1
(ver ``_assert_safe_to_wipe``). Lo consume también la suite de tests contra
``inmobiliaria_test`` (tests/conftest.py), que nunca toca la BD de desarrollo.

Documents go through the REAL RAG pipeline (parse → chunk → embed).
Images are synthetic JPEGs generated locally with Pillow (color + text): sirven
como portada de trabajo, no son fotografías reales del inmueble.
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import delete, select

from app.ai.embeddings import LocalHashEmbedding, set_embedding_provider
from app.core.logging import get_logger, setup_logging
from app.core.settings import get_settings
from app.database.base import AsyncSessionLocal
from app.database.models import (
    AiEvent,
    Appointment,
    Conversation,
    Document,
    DocumentChunk,
    Favorite,
    Lead,
    Message,
    Project,
    Property,
    SavedSearch,
    UserPreference,
)
from app.properties.repository import create_property

log = get_logger("seed")

PROJECTS = [
    {"name": "Villas de Carepa", "city": "Carepa",
     "description": "Conjunto cerrado de casas con zonas verdes, piscina comunal y vigilancia 24/7."},
    {"name": "Torres del Sinú", "city": "Carepa",
     "description": "Torres de apartamentos con ascensor, salón social y terraza mirador."},
    {"name": "Centro Empresarial Urabá", "city": "Carepa",
     "description": "Oficinas y locales comerciales en el centro de Carepa."},
]

PROPERTIES = [
    {"code": "PROP-0001", "title": "Casa familiar 3 habitaciones cerca del centro",
     "property_type": "casa", "operation": "SALE", "price": 285_000_000, "city": "Carepa",
     "neighborhood": "El Centro", "address": "Calle 45 #23-10", "area_m2": 120,
     "bedrooms": 3, "bathrooms": 2, "parking_spaces": 1, "project": 0, "status": "AVAILABLE",
     "features": ["garaje", "patio", "cocina integral", "cerca al centro"],
     "description": "Casa de dos plantas en conjunto cerrado, a dos cuadras del parque principal de Carepa."},
    {"code": "PROP-0002", "title": "Casa moderna con garaje doble",
     "property_type": "casa", "operation": "SALE", "price": 320_000_000, "city": "Carepa",
     "neighborhood": "La Esperanza", "address": "Carrera 8 #12-30", "area_m2": 140,
     "bedrooms": 4, "bathrooms": 3, "parking_spaces": 2, "project": 0, "status": "AVAILABLE",
     "features": ["garaje", "terraza", "jardin", "vigilancia"],
     "description": "Casa moderna de dos niveles con acabados premium, doble garaje y jardin amplio."},
    {"code": "PROP-0003", "title": "Casa económica para estrenar",
     "property_type": "casa", "operation": "SALE", "price": 180_000_000, "city": "Carepa",
     "neighborhood": "Villa Fátima", "address": "Calle 30 #5-22", "area_m2": 84,
     "bedrooms": 3, "bathrooms": 2, "parking_spaces": 0, "project": 0, "status": "AVAILABLE",
     "features": ["cocina integral"],
     "description": "Casa de un nivel para estrenar en sector de alta valorización."},
    {"code": "PROP-0004", "title": "Casa amplia con piscina",
     "property_type": "casa", "operation": "SALE", "price": 480_000_000, "city": "Carepa",
     "neighborhood": "El Centro", "address": "Calle 50 #20-15", "area_m2": 210,
     "bedrooms": 5, "bathrooms": 4, "parking_spaces": 2, "status": "AVAILABLE",
     "features": ["garaje", "piscina", "jardin", "terraza"],
     "description": "Casa independiente con piscina privada y amplias zonas sociales."},
    {"code": "PROP-0005", "title": "Apartamento 3 habitaciones con ascensor",
     "property_type": "apartamento", "operation": "SALE", "price": 240_000_000, "city": "Carepa",
     "neighborhood": "La Esperanza", "address": "Carrera 9 #18-50", "area_m2": 96,
     "bedrooms": 3, "bathrooms": 2, "parking_spaces": 1, "project": 1, "status": "AVAILABLE",
     "features": ["ascensor", "vigilancia", "balcón"],
     "description": "Apartamento en tercer piso con balcón y vista a la zona verde."},
    {"code": "PROP-0006", "title": "Apartamento compacto para inversión",
     "property_type": "apartamento", "operation": "SALE", "price": 150_000_000, "city": "Carepa",
     "neighborhood": "La Esperanza", "address": "Carrera 9 #18-52", "area_m2": 62,
     "bedrooms": 2, "bathrooms": 1, "parking_spaces": 1, "project": 1, "status": "AVAILABLE",
     "features": ["ascensor", "vigilancia"],
     "description": "Apartamento ideal para renta, cerca de colegios y universidad."},
    {"code": "PROP-0007", "title": "Apartamento penthouse con terraza",
     "property_type": "apartamento", "operation": "SALE", "price": 420_000_000, "city": "Carepa",
     "neighborhood": "La Esperanza", "address": "Carrera 9 #18-60", "area_m2": 130,
     "bedrooms": 3, "bathrooms": 3, "parking_spaces": 2, "project": 1, "status": "AVAILABLE",
     "features": ["ascensor", "terraza", "vigilancia", "mascotas"],
     "description": "Penthouse con terraza privada y acabados de lujo."},
    {"code": "PROP-0008", "title": "Apartamento en arriendo amueblado",
     "property_type": "apartamento", "operation": "RENT", "price": 1_200_000, "city": "Carepa",
     "neighborhood": "El Centro", "address": "Calle 44 #22-08", "area_m2": 58,
     "bedrooms": 2, "bathrooms": 1, "parking_spaces": 0, "status": "AVAILABLE",
     "features": ["amoblado", "cerca al centro"],
     "description": "Apartamento amueblado listo para habitar, incluye administracion."},
]

PROPERTIES += [
    {"code": "PROP-0009", "title": "Casa en arriendo con patio",
     "property_type": "casa", "operation": "RENT", "price": 1_800_000, "city": "Carepa",
     "neighborhood": "Villa Fátima", "address": "Calle 32 #7-40", "area_m2": 90,
     "bedrooms": 3, "bathrooms": 2, "parking_spaces": 1, "status": "AVAILABLE",
     "features": ["garaje", "patio", "mascotas"],
     "description": "Casa amplia con patio, apta para mascotas."},
    {"code": "PROP-0010", "title": "Lote urbano esquinero",
     "property_type": "lote", "operation": "SALE", "price": 95_000_000, "city": "Carepa",
     "neighborhood": "Villa Fátima", "address": "Calle 28 con Carrera 11", "area_m2": 250,
     "status": "AVAILABLE", "features": ["esquinero"],
     "description": "Lote plano con todos los servicios, ideal para construccion de vivienda."},
    {"code": "PROP-0011", "title": "Local comercial sobre vía principal",
     "property_type": "local", "operation": "SALE", "price": 310_000_000, "city": "Carepa",
     "neighborhood": "El Centro", "address": "Calle 45 #21-01", "area_m2": 80,
     "bathrooms": 1, "status": "AVAILABLE", "features": ["alto trafico"],
     "description": "Local con vitrina sobre la vía principal, ideal para retail."},
    {"code": "PROP-0012", "title": "Oficina ejecutiva Centro Empresarial",
     "property_type": "oficina", "operation": "SALE", "price": 210_000_000, "city": "Carepa",
     "neighborhood": "El Centro", "address": "Calle 45 #21-05", "area_m2": 55,
     "bathrooms": 1, "project": 2, "status": "AVAILABLE",
     "features": ["vigilancia", "cerca al centro"],
     "description": "Oficina en tercer piso con recepción y sala de juntas."},
    {"code": "PROP-0013", "title": "Finca productiva con fuente de agua",
     "property_type": "finca", "operation": "SALE", "price": 650_000_000, "city": "Carepa",
     "neighborhood": "Zona Rural Norte", "address": "Vía Apartadó km 4", "area_m2": 12000,
     "bedrooms": 2, "bathrooms": 2, "status": "AVAILABLE",
     "features": ["nacimiento de agua", "potrero"],
     "description": "Finca ganadera con casa de administracion y establo."},
    {"code": "PROP-0014", "title": "Casa vendida en conjunto cerrado",
     "property_type": "casa", "operation": "SALE", "price": 295_000_000, "city": "Carepa",
     "neighborhood": "La Esperanza", "address": "Carrera 10 #15-33", "area_m2": 110,
     "bedrooms": 3, "bathrooms": 2, "parking_spaces": 1, "project": 0, "status": "SOLD",
     "features": ["garaje"],
     "description": "Registrada como vendida: no debe aparecer en búsquedas."},
    {"code": "PROP-0015", "title": "Apartamento reservado",
     "property_type": "apartamento", "operation": "SALE", "price": 230_000_000, "city": "Carepa",
     "neighborhood": "La Esperanza", "address": "Carrera 9 #18-40", "area_m2": 90,
     "bedrooms": 3, "bathrooms": 2, "parking_spaces": 1, "project": 1, "status": "RESERVED",
     "features": ["ascensor"],
     "description": "Apartamento con reserva activa."},
    {"code": "PROP-0016", "title": "Casa retirada del mercado",
     "property_type": "casa", "operation": "SALE", "price": 260_000_000, "city": "Carepa",
     "neighborhood": "El Centro", "address": "Calle 47 #19-12", "area_m2": 100,
     "bedrooms": 3, "bathrooms": 2, "status": "INACTIVE", "features": [],
     "description": "Propiedad inactiva para pruebas de filtrado."},
]

# ---------------------------------------------------------------- documents
REGLAMENTO_LINES = [
    "REGLAMENTO DE PROPIEDAD HORIZONTAL - PROYECTO X (VILLAS DE CAREPA)",
    "",
    "Articulo 1. Generalidades.",
    "El Proyecto X cuenta con 120 apartamentos distribuidos en tres torres.",
    "La administracion del conjunto esta a cargo de la Copropiedad Villas de Carepa.",
    "",
    "Articulo 2. Cuota de administracion.",
    "La cuota de administracion para apartamentos es de $180.000 COP mensuales.",
    "Para casas del conjunto la cuota es de $220.000 COP mensuales.",
    "El pago se realiza dentro de los primeros cinco dias de cada mes.",
    "",
    "Articulo 3. Mascotas.",
    "Se permiten mascotas en el Proyecto X hasta 15 kilogramos.",
    "Las mascotas deben circular siempre con correa por las zonas comunes.",
    "Queda prohibido el ingreso de mascotas a la piscina y al salon social.",
    "",
    "Articulo 4. Piscina.",
    "La piscina comunal opera de martes a domingo entre 9:00 y 19:00 horas.",
    "El uso de la piscina requiere registro previo en la portería.",
    "",
    "Articulo 5. Parqueaderos.",
    "Cada unidad cuenta con un parqueadero privado cubierto.",
    "Los visitantes pueden usar el parqueadero temporal hasta por 6 horas.",
    "",
    "Articulo 6. Reformas.",
    "Las reformas interiores requieren aprobacion previa del consejo de administracion.",
    "No se permiten modificaciones de fachada.",
    "",
    "Articulo 7. Seguridad.",
    "El conjunto cuenta con vigilancia 24 horas y camaras de videovigilancia.",
    "",
    "Articulo 8. Silencio y convivencia.",
    "El horario de silencio va de las 22:00 a las 6:00 horas.",
    "",
    "Articulo 9. Zonas comunes.",
    "Las zonas comunes incluyen piscina, salon social, gimnasio, zonas verdes y juegos infantiles.",
    "",
    "Articulo 10. Vigencia.",
    "Este reglamento rige desde el 1 de enero de 2026 y fue aprobado por la asamblea general.",
]
FICHA_LINES = [
    "FICHA TECNICA - VILLAS DE CAREPA",
    "",
    "Villas de Carepa es un conjunto cerrado ubicado en el municipio de Carepa, Antioquia.",
    "El proyecto cuenta con 48 casas de dos y tres niveles.",
    "Entrega inmediata para las etapas 1 y 2.",
    "",
    "FINANCIACION:",
    "Cuota inicial desde el 20% del valor total.",
    "Financiacion directa con la constructora hasta por 60 meses sin intereses.",
    "Tambien se acepta credito hipotecario con bancos Aliados y Banco del Sinu.",
    "El subsidio Mi Casa Ya aplica para viviendas de hasta 135 millones de pesos.",
    "",
    "AREAS Y TIPOLOGIAS:",
    "Casas de 84 a 140 metros cuadrados.",
    "Todas las casas incluyen parqueadero privado.",
    "",
    "CONTACTO:",
    "Sala de ventas en el parque principal de Carepa.",
]
MASCOTAS_MD = """# Normativa de mascotas

El Proyecto X permite mascotas de hasta 15 kg, siempre con correa en zonas comunes.

Los apartamentos del Proyecto Villas de Carepa admiten hasta dos mascotas por unidad.

No se admiten mascotas en la piscina ni en el salon social.

## Multas

El incumplimiento genera llamado de atencion y, a la tercera reincidencia, multa de una cuota de administracion.
"""
ARRIENDO_TXT = """CONTRATO DE ARRENDAMIENTO - TERMINOS GENERALES

1. El canon de arrendamiento se paga los primeros cinco dias de cada mes.
2. El deposito equivale a un mes de canon.
3. El contrato tiene una duracion minima de 12 meses con renovacion automatica.
4. Las mascotas requieren autorizacion escrita del arrendador en todas las propiedades en arriendo.
5. El inmueble se entrega con lectura de servicios publicos y acta de entrega.
6. La financiacion del deposito en cuotas no esta disponible.
"""

def _generate_image(path: str, color: tuple[int, int, int], label: str) -> None:
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (640, 420), color)
        draw = ImageDraw.Draw(img)
        draw.rectangle([40, 40, 600, 380], outline=(255, 255, 255), width=6)
        draw.text((60, 190), label, fill=(255, 255, 255))
        img.save(path, "JPEG", quality=85)
    except Exception as e:  # Pillow missing → skip images (photos optional)
        log.warning("image_skipped error=%s", e)


def _write_documents() -> list[tuple[str, bytes, str]]:
    """Creates real seed document payloads in documents/inbox and returns them."""
    from app.rag.parsing import write_simple_docx, write_simple_pdf

    s = get_settings()
    inbox = s.documents_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    pdf_path = inbox / "reglamento_proyecto_x.pdf"
    write_simple_pdf(REGLAMENTO_LINES, str(pdf_path))
    docx_path = inbox / "ficha_villas_de_carepa.docx"
    write_simple_docx(FICHA_LINES, str(docx_path))
    md_path = inbox / "normativa_mascotas.md"
    md_path.write_text(MASCOTAS_MD, encoding="utf-8")
    txt_path = inbox / "contrato_arrendamiento.txt"
    txt_path.write_text(ARRIENDO_TXT, encoding="utf-8")

    payloads = [
        ("reglamento_proyecto_x.pdf", pdf_path.read_bytes(), "Reglamento Proyecto X"),
        ("ficha_villas_de_carepa.docx", docx_path.read_bytes(), "Ficha Villas de Carepa"),
        ("normativa_mascotas.md", md_path.read_bytes(), "Normativa de mascotas"),
        ("contrato_arrendamiento.txt", txt_path.read_bytes(), "Contrato de arrendamiento"),
    ]
    return payloads


def _assert_safe_to_wipe() -> None:
    """El seed VACÍA todas las tablas: nunca debe tocar una instalación real.

    Sin esta guardia, un ``python -m scripts.seed`` apuntando a la BD de
    producción borraría propiedades, leads, citas, conversaciones y eventos
    de IA reales sin previo aviso.
    """
    env = (get_settings().APP_ENV or "").strip().lower()
    if env in {"production", "prod"} and os.environ.get("SEED_ALLOW_PRODUCTION") != "1":
        raise SystemExit(
            "Seed abortado: APP_ENV=production.\n"
            "Este script BORRA todas las tablas (propiedades, leads, citas, "
            "conversaciones, eventos de IA, documentos y proyectos).\n"
            "Para sembrar datos de desarrollo usa una BD aparte y APP_ENV=development.\n"
            "Si de verdad quieres sembrar producción, exporta SEED_ALLOW_PRODUCTION=1."
        )


async def seed() -> dict:
    from app.rag.ingest import ingest_directory

    _assert_safe_to_wipe()
    setup_logging("INFO")
    set_embedding_provider(LocalHashEmbedding(get_settings().EMBEDDING_DIM))
    s = get_settings()
    async with AsyncSessionLocal() as session:
        # wipe (idempotent seed for dev)
        for model in (Message, AiEvent, Appointment, Favorite, SavedSearch, Lead,
                      UserPreference, Conversation, DocumentChunk, Document,
                      Property, Project):
            await session.execute(delete(model))
        await session.flush()

        projects = [Project(name=p["name"], city=p["city"], description=p["description"]) for p in PROJECTS]
        session.add_all(projects)
        await session.flush()

        count = 0
        for data in PROPERTIES:
            payload = dict(data)
            if payload.get("project") is not None:
                payload["project_id"] = projects[payload.pop("project")].id
            await create_property(session, payload)
            count += 1

        # images: real local JPEG files
        palette = [(91, 127, 179), (179, 127, 91), (91, 179, 127), (150, 150, 179),
                   (179, 150, 91), (127, 91, 179)]
        props = (await session.execute(select(Property))).scalars().all()
        for i, p in enumerate(props):
            pdir = s.storage_dir / "properties" / str(p.id)
            pdir.mkdir(parents=True, exist_ok=True)
            color = palette[i % len(palette)]
            _generate_image(str(pdir / "cover.jpg"), color, f"{p.code} — {p.title[:28]}")
            for n in range(1, min(3, 2 + i % 2)):
                _generate_image(str(pdir / f"{n:03d}.jpg"),
                                tuple(min(255, c + 30) for c in color), f"{p.code} foto {n}")
        await session.commit()

        # documents via the REAL ingestion pipeline
        payloads = _write_documents()
        report = await ingest_directory(session)

    return {"properties": count, "documents": len(payloads), "rag_report": report}


def main() -> None:
    result = asyncio.run(seed())
    log.info("seed_done properties=%s documents=%s", result["properties"], result["documents"])
    for row in result["rag_report"]:
        log.info("rag %s", row)


if __name__ == "__main__":
    main()



