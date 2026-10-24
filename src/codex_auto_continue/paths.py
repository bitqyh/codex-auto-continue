"""Platform paths and small filesystem helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "codex-auto-continue"


def _home() -> Path:
    return Path.home()


def data_dir() -> Path:
    """Per-user application data directory (config, state, logs)."""
    override = os.environ.get("CODEX_AUTO_CONTINUE_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("APPDATA") or (_home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or (_home() / ".local" / "share")
    return Path(base) / APP_NAME


def codex_home() -> Path:
    """Resolve CODEX_HOME the same way the Codex CLI does."""
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override).expanduser()
    return _home() / ".codex"


def sessions_dir() -> Path:
    return codex_home() / "sessions"


def codexbar_dashboard_path() -> Path | None:
    """CodexBar (macOS menu bar app) caches an account dashboard snapshot here."""
    if sys.platform != "darwin":
        return None
    return _home() / "Library" / "Application Support" / "com.steipete.codexbar" / "openai-dashboard.json"


def codexbar_snapshots_path() -> Path | None:
    if sys.platform != "darwin":
        return None
    return _home() / "Library" / "Application Support" / "CodexBar" / "codex-account-snapshots.json"


def launch_agents_dir() -> Path:
    return _home() / "Library" / "LaunchAgents"


def config_path() -> Path:
    return data_dir() / "config.json"


def state_path() -> Path:
    return data_dir() / "state.json"


def log_path() -> Path:
    return data_dir() / "run.log"


def ensure_data_dir() -> Path:
    path = data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def which(name: str) -> str | None:
    """Return an absolute path for an executable, or None."""
    import shutil

    return shutil.which(name)
