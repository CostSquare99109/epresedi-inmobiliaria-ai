"""merge_cms_and_settings

Revision ID: 5935871c4e4b
Revises: 1988f6b5fe93, c4f8a2d6b0e2
Create Date: 2026-09-18 09:07:53.827834

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5935871c4e4b'
down_revision: Union[str, None] = ('1988f6b5fe93', 'c4f8a2d6b0e2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
