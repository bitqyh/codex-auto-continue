"""Resolve and edit the continuation message."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from .config import Config


def normalize_cwd(path: str | None) -> str:
    if not path:
        return ""
    return str(Path(path).expanduser()).rstrip("/") or "/"


def resolve_message(
    config: Config,
    cwd: str | None = None,
    explicit: str | None = None,
    thread_id: str | None = None,
) -> str:
    """Pick the message: explicit > longest matching project template > global template."""
    if explicit:
        text = explicit
    else:
        text = None
        current = normalize_cwd(cwd)
        best_length = -1
        for prefix, template in config.project_templates.items():
            candidate = normalize_cwd(prefix)
            matches = current == candidate or current.startswith(candidate + os.sep) or (
                candidate == "/" and current.startswith("/")
            )
            if matches and len(candidate) > best_length:
                best_length = len(candidate)
                text = template
        if text is None:
            text = config.message_template
    if thread_id:
        text = text.replace("{thread_id}", thread_id)
    return text


def edit_message(initial: str) -> str | None:
    """Open $VISUAL/$EDITOR on the message; returns None when unavailable or cancelled."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        return None
    handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    handle.write(initial + "\n")
    handle.close()
    path = Path(handle.name)
    try:
        subprocess.run([*shlex.split(editor), str(path)], check=False)
        edited = path.read_text(encoding="utf-8").strip()
        return edited or None
    except OSError:
        return None
    finally:
        try:
            path.unlink()
        except OSError:
            pass
