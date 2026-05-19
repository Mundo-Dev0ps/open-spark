"""Overlay storage. One HTML file per overlay, plus a JSON index."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import overlays_dir

_INDEX_NAME = "_index.json"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, max_len: int = 32) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return (s[:max_len] or "overlay").rstrip("-") or "overlay"


@dataclass
class Overlay:
    id: str
    slug: str
    prompt: str
    model: str
    created_at: str
    width: int = 1920
    height: int = 1080
    title: str = ""

    def filename(self) -> str:
        return f"{self.id}.html"


@dataclass
class OverlayStore:
    """File-backed registry. Cheap; we don't expect millions of overlays."""

    root: Path = field(default_factory=overlays_dir)

    def _index_path(self) -> Path:
        return self.root / _INDEX_NAME

    def _read_index(self) -> list[dict]:
        p = self._index_path()
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _write_index(self, entries: list[dict]) -> None:
        self._index_path().write_text(
            json.dumps(entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def save(
        self,
        *,
        prompt: str,
        html: str,
        model: str,
        title: str = "",
        width: int = 1920,
        height: int = 1080,
    ) -> Overlay:
        oid = uuid.uuid4().hex[:12]
        ov = Overlay(
            id=oid,
            slug=_slug(title or prompt),
            prompt=prompt,
            model=model,
            created_at=datetime.now(UTC).isoformat(),
            width=width,
            height=height,
            title=title or prompt[:80],
        )
        (self.root / ov.filename()).write_text(html, encoding="utf-8")
        entries = self._read_index()
        entries.insert(0, asdict(ov))
        self._write_index(entries)
        return ov

    def list(self) -> list[Overlay]:
        return [Overlay(**e) for e in self._read_index()]

    def get(self, overlay_id: str) -> Overlay | None:
        for e in self._read_index():
            if e["id"] == overlay_id:
                return Overlay(**e)
        return None

    def html_path(self, overlay_id: str) -> Path | None:
        ov = self.get(overlay_id)
        return self.root / ov.filename() if ov else None

    def update_html(
        self,
        overlay_id: str,
        *,
        html: str,
        model: str | None = None,
        prompt: str | None = None,
    ) -> Overlay | None:
        """Overwrite an existing overlay's HTML in place.

        URL stays the same, so OBS Browser Sources pointing at it can be
        refreshed without recreating the source.
        """
        entries = self._read_index()
        target: dict | None = None
        for e in entries:
            if e["id"] == overlay_id:
                target = e
                break
        if target is None:
            return None
        if model:
            target["model"] = model
        if prompt:
            target["prompt"] = prompt
        (self.root / f"{overlay_id}.html").write_text(html, encoding="utf-8")
        self._write_index(entries)
        return Overlay(**target)

    def delete(self, overlay_id: str) -> bool:
        entries = self._read_index()
        remaining = [e for e in entries if e["id"] != overlay_id]
        if len(remaining) == len(entries):
            return False
        path = self.root / f"{overlay_id}.html"
        path.unlink(missing_ok=True)
        self._write_index(remaining)
        return True

    def clear(self) -> int:
        """Remove every overlay (.html files + index). Returns the count
        of overlays that existed before the wipe.
        """
        entries = self._read_index()
        for e in entries:
            (self.root / f"{e['id']}.html").unlink(missing_ok=True)
        self._write_index([])
        return len(entries)
