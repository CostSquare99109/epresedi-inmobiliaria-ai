"""Restrict property types to casa/apartamento.

Revision ID: 0006_restrict_property_types
Revises: 0005_floor_offer
Create Date: 2026-09-25

Elimina del inventario las propiedades con tipos fuera del catálogo vigente
(lote, local, oficina, finca, proyecto). Solo casa y apartamento son tipos
válidos (ver app/database/models.py::PropertyType).

La columna properties.property_type es VARCHAR (native_enum=False), por lo
que no hay CHECK constraint ni tipo PostgreSQL que alterar: basta con
retirar las filas obsoletas. Las tablas dependientes (property_images,
appointments, favorites) tienen ondelete=CASCADE y se limpian solas.

NOTA: no se migran filas antiguas a casa/apartamento porque no existe una
regla de negocio que justifique esa reclasificación; los registros
eliminados eran datos sintéticos de demostración (seed PROP-0010..0013),
no inventario real de clientes. Los archivos huérfanos que queden en
storage/ pueden purgarse con scripts/sync_images.py.
"""

revision: str = '0006_restrict_property_types'
down_revision: str = '0005_floor_offer'

from alembic import op


def upgrade() -> None:
    op.execute(
        "DELETE FROM properties WHERE property_type IN "
        "('lote', 'local', 'oficina', 'finca', 'proyecto')"
    )


def downgrade() -> None:
    # Los registros eliminados no se pueden restaurar (no hay respaldo).
    pass
