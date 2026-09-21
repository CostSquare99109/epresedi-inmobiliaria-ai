"""Probe: confirm what prepared_db's seed() leaves in the shared DB."""
from sqlalchemy import func, select

from app.database.models import Document


async def test_probe_document_count(session):
    total = (await session.execute(select(func.count()).select_from(Document))).scalar()
    rows = (await session.execute(select(Document.filename).order_by(Document.filename))).scalars().all()
    print(f"\nPROBE document_count={total} filenames={list(rows)}")
    assert total >= 4