"""Publishing finished documents to the external GitHub Pages documents site.

Not yet implemented — this is a deliberate stub seam. `publish`/`unpublish`
currently no-op so the rest of the filing flow (render, save locally, review,
forum post) works end to end while the actual GitHub push integration (token
storage, target repo, Contents API calls) is designed in a later session.
"""
from __future__ import annotations
from pathlib import Path


class DocumentPublisher:
    async def publish(self, local_path: Path, output_dir: str) -> str | None:
        """Publish a rendered document to the documents site.

        Returns the document's live URL, or None if publishing isn't wired
        up yet (current behavior) — callers must handle the None case.
        """
        return None

    async def unpublish(self, output_dir: str, filename: str) -> bool:
        """Remove a previously published document from the documents site."""
        return False
