"""Raw HTML storage behind an interface.

Postgres only holds a reference. `NullHtmlStorage` keeps nothing (default),
`LocalHtmlStorage` writes to disk for development; an object-storage adapter
(S3/GCS) implements the same protocol later.
"""

import gzip
import uuid
from pathlib import Path
from typing import Protocol

from app.core.config import Settings


class HtmlStorage(Protocol):
    async def store(
        self, project_id: uuid.UUID, page_id: uuid.UUID, version_id: uuid.UUID, html: bytes
    ) -> str | None:
        """Persist raw HTML; return an opaque reference (or None if not stored)."""
        ...


class NullHtmlStorage:
    async def store(
        self, project_id: uuid.UUID, page_id: uuid.UUID, version_id: uuid.UUID, html: bytes
    ) -> str | None:
        return None


class LocalHtmlStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root)

    async def store(
        self, project_id: uuid.UUID, page_id: uuid.UUID, version_id: uuid.UUID, html: bytes
    ) -> str | None:
        rel = Path(str(project_id)) / str(page_id) / f"{version_id}.html.gz"
        path = self._root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(html))
        return f"local://{rel.as_posix()}"


def html_storage_from_settings(settings: Settings) -> HtmlStorage:
    if settings.crawl_html_storage == "local":
        return LocalHtmlStorage(settings.crawl_html_storage_path)
    return NullHtmlStorage()
