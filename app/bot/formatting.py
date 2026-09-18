"""Telegram text rendering. Deterministic, data-only: never invents values."""
from __future__ import annotations

from app.database.models import Property, PropertyStatus

STATUS_LABEL = {
    "AVAILABLE": "Disponible", "RESERVED": "Reservada", "SOLD": "Vendida", "INACTIVE": "Inactiva",
}
OPERATION_LABEL = {"SALE": "Venta", "RENT": "Arriendo"}


def fmt_money(value: float | None, currency: str = "COP") -> str:
    if value is None:
        return "No informado"
    return f"${value:,.0f}".replace(",", ".").replace("$", "$ ") + f" {currency}"


def fmt_opt(value) -> str:
    if value is None or value == "":
        return "No informado"
    return str(value)


def property_line(prop: Property, index: int | None = None) -> str:
    prefix = f"{index}. " if index else ""
    op = "🏗 " if prop.operation.value == "RENT" else ""
    return (
        f"{prefix}{op}**{prop.title}** — {fmt_money(float(prop.price) if prop.price else None, prop.currency)}\n"
        f"   {prop.property_type.value} · {prop.neighborhood or prop.city} · "
        f"{fmt_opt(prop.bedrooms)} hab · {fmt_opt(prop.bathrooms)} baños · código {prop.code}"
    )


def property_card(prop: Property) -> str:
    status = STATUS_LABEL.get(prop.status.value, prop.status.value)
    lines = [
        f"🏠 **{prop.title}**",
        f"💰 Precio: {fmt_money(float(prop.price) if prop.price else None, prop.currency)} ({OPERATION_LABEL.get(prop.operation.value, prop.operation.value)})",
        f"📐 Área: {fmt_opt(prop.area_m2)} m² · 🛏 {fmt_opt(prop.bedrooms)} hab · 🚿 {fmt_opt(prop.bathrooms)} baños · 🚗 {fmt_opt(prop.parking_spaces)} parqueaderos",
        f"📍 {fmt_opt(prop.neighborhood or None)}, {fmt_opt(prop.city)}",
        f"🏷 Código: {prop.code} · Estado: **{status}**",
    ]
    if prop.features:
        lines.append("✨ " + ", ".join(prop.features))
    if prop.description:
        desc = prop.description[:400]
        lines.append(f"\n{desc}{'…' if len(prop.description) > 400 else ''}")
    if prop.project:
        lines.append(f"🏗 Proyecto: {prop.project.name}")
    return "\n".join(lines)


def comparison_table(props: list[Property]) -> str:
    header = [fmt_opt(p.code) for p in props]
    rows: list[str] = []
    header_line = " | ".join(["Campo".ljust(14)] + [h.ljust(16)[:16] for h in header])
    rows.append(header_line)
    rows.append("-" * len(header_line))

    def row(label: str, values: list[str]) -> None:
        rows.append(" | ".join([label.ljust(14)] + [v.ljust(16)[:16] for v in values]))

    row("Precio", [fmt_money(float(p.price) if p.price else None, p.currency) for p in props])
    row("Área (m²)", [fmt_opt(p.area_m2) for p in props])
    row("Habitaciones", [fmt_opt(p.bedrooms) for p in props])
    row("Baños", [fmt_opt(p.bathrooms) for p in props])
    row("Parqueaderos", [fmt_opt(p.parking_spaces) for p in props])
    row("Ciudad", [fmt_opt(p.city) for p in props])
    row("Barrio", [fmt_opt(p.neighborhood) for p in props])
    row("Estado", [STATUS_LABEL.get(p.status.value, p.status.value) for p in props])
    row("Operación", [OPERATION_LABEL.get(p.operation.value) for p in props])
    return "```\n" + "\n".join(rows) + "\n```"


def citation_line(filename: str, page: int | None, title: str | None = None) -> str:
    src = title or filename
    return f"Fuente: {src}" + (f" · página {page}" if page else "")
