"""Read Codex quota windows (read-only) from the local app server or CodexBar."""

from __future__ import annotations

import datetime as dt
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths

FIVE_HOUR_MINUTES = 300
WEEKLY_MINUTES = 10080


@dataclass
class QuotaWindow:
    kind: str
    window_minutes: int
    used_percent: float
    resets_at: dt.datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "window_minutes": self.window_minutes,
            "used_percent": self.used_percent,
            "resets_at": self.resets_at.isoformat() if self.resets_at else None,
        }

    @property
    def exhausted(self) -> bool:
        return self.used_percent >= 100.0


@dataclass
class QuotaSnapshot:
    source: str
    account_email: str | None
    windows: list[QuotaWindow] = field(default_factory=list)
    fetched_at: dt.datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "account_email": self.account_email,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "windows": [window.to_dict() for window in self.windows],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "QuotaSnapshot":
        windows = []
        for item in raw.get("windows") or []:
            resets = _from_iso(item.get("resets_at"))
            windows.append(
                _io_window(
                    str(item.get("kind", "primary")),
                    int(item.get("window_minutes", 0)),
                    float(item.get("used_percent", 0)),
                    resets,
                )
            )
        return cls(
            source=str(raw.get("source", "cache")),
            account_email=raw.get("account_email"),
            windows=windows,
            fetched_at=_from_iso(raw.get("fetched_at")),
        )

    @property
    def exhausted_windows(self) -> list[QuotaWindow]:
        return [window for window in self.windows if window.exhausted]

    @property
    def has_capacity(self) -> bool:
        return bool(self.windows) and not self.exhausted_windows

    def next_reset(self) -> dt.datetime | None:
        """Earliest moment every currently exhausted window has reset."""
        moments = [window.resets_at for window in self.exhausted_windows if window.resets_at]
        if not moments:
            return None
        # The session can only resume after *all* exhausted windows roll over.
        return max(moments)


def _windows_codex_candidates() -> list[Path]:
    """Common install locations for the Codex CLI/App on Windows.

    The Codex App for Windows does not add its bundled CLI to PATH; it ships a
    full CLI binary under ``%USERPROFILE%\\.codex\\.sandbox-bin\\codex.exe``.
    npm installs land in ``%APPDATA%\\npm``; standalone installs under
    ``%LOCALAPPDATA%\\Programs``.
    """
    candidates: list[Path] = []
    home = Path(os.environ["USERPROFILE"]) if os.environ.get("USERPROFILE") else Path.home()
    candidates.append(home / ".codex" / ".sandbox-bin" / "codex.exe")
    candidates.append(home / ".codex" / "bin" / "codex.exe")
    roaming = os.environ.get("APPDATA")
    if roaming:
        candidates.append(Path(roaming) / "npm" / "codex.cmd")
        candidates.append(Path(roaming) / "npm" / "codex.exe")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "Codex" / "codex.exe")
        candidates.append(Path(local) / "Programs" / "codex" / "codex.exe")
        candidates.append(Path(local) / "Microsoft" / "WindowsApps" / "codex.exe")
    candidates.append(Path(r"C:\Program Files\Codex\codex.exe"))
    return candidates


def find_codex(config_codex_path: str | None = None) -> str | None:
    if config_codex_path and Path(config_codex_path).exists():
        return config_codex_path
    env = shutil.which("codex")
    if env:
        return env
    if os.name == "nt":
        candidates = _windows_codex_candidates()
    else:
        candidates = [
            Path("/opt/homebrew/bin/codex"),
            Path("/usr/local/bin/codex"),
            paths.codex_home() / "packages" / "standalone" / "current" / "codex",
        ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _io_window(kind: str, minutes: int, used_percent: float, resets_at: dt.datetime | None) -> QuotaWindow:
    return QuotaWindow(kind=kind, window_minutes=int(minutes), used_percent=float(used_percent), resets_at=resets_at)


def _from_epoch(value: Any) -> dt.datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return dt.datetime.fromtimestamp(value, dt.timezone.utc)


def _from_iso(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def parse_rate_limits(account: dict[str, Any], limits: dict[str, Any]) -> QuotaSnapshot:
    """Convert app-server RPC payloads into a QuotaSnapshot (raises ValueError)."""
    identity = account.get("account")
    email = None
    if isinstance(identity, dict) and identity.get("type") == "chatgpt":
        email = identity.get("email")
    buckets = limits.get("rateLimitsByLimitId") or {}
    bucket = buckets.get("codex") if isinstance(buckets, dict) else None
    if not isinstance(bucket, dict):
        bucket = limits.get("rateLimits")
    if not isinstance(bucket, dict):
        raise ValueError("missing codex rate limit bucket")
    windows: list[QuotaWindow] = []
    for kind, raw in (("primary", bucket.get("primary")), ("secondary", bucket.get("secondary"))):
        if not isinstance(raw, dict):
            continue
        minutes = raw.get("windowDurationMins") or raw.get("windowMinutes")
        used = raw.get("usedPercent")
        resets = _from_epoch(raw.get("resetsAt"))
        if not isinstance(minutes, (int, float)) or not isinstance(used, (int, float)) or resets is None:
            raise ValueError("invalid rate limit window")
        windows.append(_io_window(kind, int(minutes), float(used), resets))
    if not windows:
        raise ValueError("no rate limit windows")
    windows.sort(key=lambda window: window.window_minutes)
    return QuotaSnapshot(source="app-server", account_email=email, windows=windows, fetched_at=dt.datetime.now(dt.timezone.utc))


_APP_SERVER_ARGV_CACHE: dict[str, list[str]] = {}


def _app_server_argv(codex_path: str) -> list[str]:
    """Pick the app-server invocation the installed Codex CLI understands.

    Older Codex builds only spoke stdio via ``app-server --stdio``; current
    builds run stdio by default and reject ``--stdio`` with exit code 2 (which
    made every quota read fail before the RPC even started).
    """
    cached = _APP_SERVER_ARGV_CACHE.get(codex_path)
    if cached is not None:
        return list(cached)
    try:
        result = subprocess.run(
            [codex_path, "app-server", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        help_text = (result.stdout or "") + (result.stderr or "")
    except (OSError, subprocess.SubprocessError):
        help_text = ""
    argv = [codex_path, "app-server", "--stdio"] if "--stdio" in help_text else [codex_path, "app-server"]
    _APP_SERVER_ARGV_CACHE[codex_path] = list(argv)
    return argv


def fetch_from_app_server(codex_path: str, timeout_seconds: float = 30.0) -> QuotaSnapshot:
    process = subprocess.Popen(
        _app_server_argv(codex_path),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    responses: "queue.Queue[dict[str, Any] | None]" = queue.Queue(maxsize=512)

    def reader() -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    try:
                        responses.put_nowait(payload)
                    except queue.Full:
                        pass
        finally:
            try:
                responses.put_nowait(None)
            except queue.Full:
                pass

    threading.Thread(target=reader, daemon=True).start()
    deadline = time.monotonic() + timeout_seconds

    def send(message: dict[str, Any]) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def call(request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
        send({"id": request_id, "method": method, "params": params})
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(method)
            try:
                message = responses.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(method)
            if message is None:
                raise RuntimeError(f"app server closed during {method}")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(json.dumps(message.get("error"), ensure_ascii=False))
            result = message.get("result")
            return result if isinstance(result, dict) else {}

    try:
        call(
            1,
            "initialize",
            {
                "clientInfo": {"name": "codex-auto-continue", "version": "0.1.0"},
                "capabilities": {},
            },
        )
        send({"method": "initialized", "params": {}})
        account = call(2, "account/read", {"refreshToken": False})
        limits = call(3, "account/rateLimits/read", {})
        return parse_rate_limits(account, limits)
    finally:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:  # noqa: BLE001 - best effort cleanup
            try:
                process.kill()
            except Exception:  # noqa: BLE001
                pass


def _windows_from_codexbar(container: dict[str, Any]) -> list[QuotaWindow]:
    windows: list[QuotaWindow] = []
    for kind, key in (("primary", "primaryLimit"), ("secondary", "secondaryLimit"), ("primary", "primary"), ("secondary", "secondary")):
        item = container.get(key)
        if not isinstance(item, dict):
            continue
        resets = _from_iso(item.get("resetsAt")) or _from_epoch(item.get("resetsAt"))
        minutes = item.get("windowMinutes") or item.get("windowDurationMins")
        used = item.get("usedPercent")
        if resets is None or not isinstance(minutes, (int, float)) or not isinstance(used, (int, float)):
            continue
        if any(window.window_minutes == int(minutes) for window in windows):
            continue
        windows.append(_io_window(kind, int(minutes), float(used), resets))
    return windows


def fetch_from_codexbar() -> QuotaSnapshot | None:
    """Read CodexBar's cached dashboard (fast, no subprocess). macOS only."""
    dashboard = paths.codexbar_dashboard_path()
    snapshots = paths.codexbar_snapshots_path()
    candidates: list[Path] = []
    for candidate in (dashboard, snapshots):
        if candidate is not None:
            candidates.append(candidate)
    for path in candidates:
        if path is None or not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        containers: list[dict[str, Any]] = []
        if isinstance(raw, dict):
            containers.append(raw)
            if isinstance(raw.get("snapshot"), dict):
                containers.append(raw["snapshot"])
            records = raw.get("records")
            if isinstance(records, list):
                for record in records[:3]:
                    if isinstance(record, dict) and isinstance(record.get("snapshot"), dict):
                        containers.append(record["snapshot"])
        for container in containers:
            windows = _windows_from_codexbar(container)
            if windows:
                windows.sort(key=lambda window: window.window_minutes)
                email = raw.get("accountEmail") if isinstance(raw, dict) else None
                updated = _from_iso(container.get("updatedAt")) if isinstance(container, dict) else None
                if updated is None:
                    try:
                        updated = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
                    except OSError:
                        pass
                return QuotaSnapshot(
                    source="codexbar",
                    account_email=email if isinstance(email, str) else None,
                    windows=windows,
                    fetched_at=updated,
                )
    return None


def _cache_path():
    from . import paths

    return paths.data_dir() / "quota-cache.json"


def _fresh_enough(snapshot: QuotaSnapshot, max_age: float) -> bool:
    fetched = snapshot.fetched_at
    if fetched is None:
        return False
    age = (dt.datetime.now(dt.timezone.utc) - fetched).total_seconds()
    return 0 <= age <= max_age


def _read_cache(max_age: float) -> QuotaSnapshot | None:
    if max_age <= 0:
        return None
    path = _cache_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        fetched = _from_iso(raw.get("fetched_at"))
        if fetched is None:
            return None
        age = (dt.datetime.now(dt.timezone.utc) - fetched).total_seconds()
        if age < 0 or age > max_age:
            return None
        snapshot = QuotaSnapshot.from_dict(raw)
        snapshot.source = f"{snapshot.source} (cached {int(age)}s)"
        return snapshot
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _write_cache(snapshot: QuotaSnapshot) -> None:
    from . import paths

    try:
        paths.ensure_data_dir()
        payload = snapshot.to_dict()
        payload["fetched_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        target = _cache_path()
        tmp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


def snapshot(
    codex_path: str | None = None,
    allow_codexbar: bool = True,
    max_age: float = 0,
    force: bool = False,
    read_only: bool = False,
) -> QuotaSnapshot | None:
    """Read quota; read_only uses fresh local caches without writing or starting RPC."""
    if not force:
        cached = _read_cache(max_age)
        if cached is not None:
            return cached
        # CodexBar refreshes its own cache on macOS; use it while fresh to avoid
        # spawning an app server process for every menu bar refresh.
        if allow_codexbar:
            bar = fetch_from_codexbar()
            if bar is not None and _fresh_enough(bar, max(max_age, 300)):
                if not read_only:
                    _write_cache(bar)
                return bar
    if read_only:
        return None
    codex = find_codex(codex_path)
    if codex:
        try:
            fresh = fetch_from_app_server(codex)
            _write_cache(fresh)
            return fresh
        except Exception:  # noqa: BLE001 - fall through to cache
            pass
    if allow_codexbar:
        cached = fetch_from_codexbar()
        if cached is not None:
            _write_cache(cached)
            return cached
    if force:
        return None
    return _read_cache(86400)

