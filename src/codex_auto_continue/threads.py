"""Read user-visible session names from the Codex app state database."""

from __future__ import annotations

import glob
import os
import sqlite3
from pathlib import Path

from . import paths

MAX_TITLE = 80


def _database_candidates() -> list[Path]:
    root = paths.codex_home()
    found = [Path(item) for item in glob.glob(str(root / "state_*.sqlite"))]
    legacy = root / "state.sqlite"
    if legacy.exists():
        found.append(legacy)

    def sort_key(path: Path) -> tuple[int, float]:
        digits = "".join(ch for ch in path.stem if ch.isdigit())
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (int(digits) if digits else 0, mtime)

    return sorted(found, key=sort_key, reverse=True)


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text[:MAX_TITLE]


def load_thread_titles(thread_ids: list[str] | None = None) -> dict[str, str]:
    """Map thread ids to the name shown in the Codex app session list.

    `threads.name` is the user-visible title (renames included); `threads.title`
    is a fallback derived from the first message. Returns {} when unavailable.
    """
    wanted = set(thread_ids) if thread_ids else None
    for database in _database_candidates():
        for uri in (f"file:{database}?mode=ro", f"file:{database}?immutable=1"):
            try:
                connection = sqlite3.connect(uri, uri=True, timeout=2)
            except sqlite3.Error:
                continue
            try:
                rows = connection.execute("SELECT id, name, title, cwd FROM threads").fetchall()
            except sqlite3.Error:
                connection.close()
                continue
            connection.close()
            titles: dict[str, str] = {}
            for thread_id, name, title, cwd in rows:
                if wanted is not None and thread_id not in wanted:
                    continue
                label = _clean(name) or _clean(title)
                if not label and cwd:
                    label = os.path.basename(str(cwd).rstrip("/")) or None
                if label:
                    titles[thread_id] = label
            if titles or wanted is None:
                return titles
    return {}


def thread_title(thread_id: str) -> str | None:
    return load_thread_titles([thread_id]).get(thread_id)
