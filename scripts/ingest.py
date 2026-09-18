"""Document ingestion CLI: python -m scripts.ingest [--path DIR]

Scans DOCUMENTS_PATH/inbox (or --path), dedupes by hash, parses, chunks,
embeds and stores. Safe to re-run: only new/changed files are processed."""
from __future__ import annotations

import asyncio
import sys

from app.core.logging import get_logger, setup_logging
from app.database.base import AsyncSessionLocal
from app.rag.ingest import ingest_directory

log = get_logger("ingest")


def main() -> None:
    setup_logging("INFO")
    path = None
    if "--path" in sys.argv:
        path = sys.argv[sys.argv.index("--path") + 1]

    async def _run() -> list[dict]:
        async with AsyncSessionLocal() as session:
            return await ingest_directory(session, path)

    report = asyncio.run(_run())
    if not report:
        log.info("ingest: no hay archivos nuevos en el inbox")
        return
    ok = sum(1 for r in report if r.get("ok"))
    failed = len(report) - ok
    for row in report:
        if row.get("ok"):
            log.info("OK  %-40s chunks=%s %s", row["file"], row.get("chunks", "-"), row.get("skipped", ""))
        else:
            log.error("ERR %-40s %s", row["file"], row.get("error"))
    log.info("ingest_done ok=%s failed=%s", ok, failed)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
