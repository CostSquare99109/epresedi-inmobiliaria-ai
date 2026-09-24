"""Sync existing filesystem images to PropertyImage database table."""
from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from app.api.files import list_property_images, property_images_dir
from app.core.settings import get_settings
from app.database.base import AsyncSessionLocal
from app.database.models import Property, PropertyImage


async def sync_existing_images():
    """Create PropertyImage records for existing filesystem images."""
    settings = get_settings()
    storage_dir = settings.storage_dir / "properties"

    if not storage_dir.exists():
        print("No storage directory found")
        return

    async with AsyncSessionLocal() as session:
        # Get all properties
        props = (await session.execute(select(Property))).scalars().all()
        print(f"Found {len(props)} properties")

        total_synced = 0

        for prop in props:
            prop_id = str(prop.id)
            base_dir = property_images_dir(prop_id)

            if not base_dir.exists():
                continue

            # Get existing filesystem images
            fs_images = list_property_images(prop_id)
            if not fs_images:
                continue

            # Check which images already have DB records
            existing_db = (await session.execute(
                select(PropertyImage).where(PropertyImage.property_id == prop.id)
            )).scalars().all()
            existing_filenames = {img.filename for img in existing_db}

            # Create records for missing images
            for i, filename in enumerate(fs_images):
                if filename in existing_filenames:
                    continue

                file_path = base_dir / filename
                file_size = file_path.stat().st_size if file_path.exists() else 0
                ext = Path(filename).suffix.lower()
                mime_type = f"image/{ext[1:]}" if ext in (".jpg", ".jpeg", ".png", ".webp") else ""

                is_cover = (i == 0)
                sort_order = i

                # Try to extract name from filename (without extension)
                name = Path(filename).stem.replace("_", " ").replace("-", " ").title()

                img = PropertyImage(
                    property_id=prop.id,
                    filename=filename,
                    is_cover=is_cover,
                    sort_order=sort_order,
                    alt_text=name,
                    file_size=file_size,
                    mime_type=mime_type,
                    name=name,
                    description="",
                )
                session.add(img)
                total_synced += 1
                print(f"  Synced: {prop.code} - {filename}")

        if total_synced > 0:
            await session.commit()
            print(f"\nTotal images synced: {total_synced}")
        else:
            print("No new images to sync")


if __name__ == "__main__":
    asyncio.run(sync_existing_images())