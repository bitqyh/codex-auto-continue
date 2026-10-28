"""Configuration, persistent state, locking and logging."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from . import paths

DEFAULT_MESSAGE = (
    "上一轮因 usage limit 中断。请从中断处继续未完成的工作，完成后简要汇报结果和未完成项；"
    "不要重复已完成的部分。"
)

LOCK_STALE_SECONDS = 6 * 3600
LOG_ROTATE_BYTES = 256 * 1024
LOG_BACKUPS = 3

STATUS_ARMED = "armed"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_SUPERSEDED = "superseded"
STATUS_DISARMED = "disarmed"


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(dt.timezone.utc).isoformat()


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _atomic_write(path: Path, payload: str) -> None:
    paths.ensure_data_dir()
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


@dataclass
class Config:
    version: int = 1
    message_template: str = DEFAULT_MESSAGE
    grace_seconds: int = 180
    max_attempts: int = 6
    retry_seconds: int = 600
    queue_verify_seconds: int = 120
    quota_cache_seconds: int = 300
    notify_local: bool = True
    notify_email: bool = False
    webhook_url: str | None = None
    email_endpoint: str | None = None
    email_secret_file: str | None = None
    codex_path: str | None = None
    model: str | None = None
    proxy: str | None = None
    project_templates: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "message_template": self.message_template,
            "grace_seconds": self.grace_seconds,
            "max_attempts": self.max_attempts,
            "retry_seconds": self.retry_seconds,
            "queue_verify_seconds": self.queue_verify_seconds,
            "quota_cache_seconds": self.quota_cache_seconds,
            "notifications": {
                "local": self.notify_local,
                "email": self.notify_email,
                "email_endpoint": self.email_endpoint,
                "email_secret_file": self.email_secret_file,
            },
            "webhook_url": self.webhook_url,
            "codex_path": self.codex_path,
            "model": self.model,
            "proxy": self.proxy,
            "project_templates": dict(self.project_templates),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        notifications = raw.get("notifications") or {}
        return cls(
            version=int(raw.get("version", 1)),
            message_template=str(raw.get("message_template") or DEFAULT_MESSAGE),
            grace_seconds=int(raw.get("grace_seconds", 180)),
            max_attempts=int(raw.get("max_attempts", 6)),
            retry_seconds=int(raw.get("retry_seconds", 600)),
            queue_verify_seconds=int(raw.get("queue_verify_seconds", 120)),
            quota_cache_seconds=int(raw.get("quota_cache_seconds", 300)),
            notify_local=bool(notifications.get("local", True)),
            notify_email=bool(notifications.get("email", False)),
            webhook_url=raw.get("webhook_url"),
            email_endpoint=notifications.get("email_endpoint") or raw.get("email_endpoint"),
            email_secret_file=notifications.get("email_secret_file") or raw.get("email_secret_file"),
            codex_path=raw.get("codex_path"),
            model=raw.get("model"),
            proxy=raw.get("proxy"),
            project_templates={
                str(key): str(value)
                for key, value in (raw.get("project_templates") or {}).items()
            },
        )


@dataclass
class ArmedThread:
    thread_id: str
    rollout_path: str
    cwd: str
    message: str
    armed_at: str
    status: str = STATUS_ARMED
    fire_at: str | None = None
    baseline_lines: int = 0
    attempts: int = 0
    last_error: str | None = None
    completed_at: str | None = None
    reset_hint: str | None = None
    forced: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "rollout_path": self.rollout_path,
            "cwd": self.cwd,
            "message": self.message,
            "armed_at": self.armed_at,
            "status": self.status,
            "fire_at": self.fire_at,
            "baseline_lines": self.baseline_lines,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "completed_at": self.completed_at,
            "reset_hint": self.reset_hint,
            "forced": self.forced,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ArmedThread":
        return cls(**{key: raw.get(key) for key in cls.__dataclass_fields__})  # type: ignore[arg-type]

    @property
    def is_pending(self) -> bool:
        # "failed" is terminal: max_attempts is exhausted, so the runner must
        # stop rescheduling it (otherwise Windows Task Scheduler would retry a
        # permanently broken thread every retry_seconds forever).
        return self.status in (STATUS_ARMED, STATUS_RUNNING)


@dataclass
class State:
    version: int = 1
    threads: dict[str, ArmedThread] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "threads": {key: value.to_dict() for key, value in self.threads.items()},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "State":
        threads = {
            key: ArmedThread.from_dict(value)
            for key, value in (raw.get("threads") or {}).items()
        }
        return cls(version=int(raw.get("version", 1)), threads=threads)


def set_thread_message(state: State, thread_id: str, message: str) -> ArmedThread | None:
    """Update the continuation message without touching the schedule."""
    thread = state.threads.get(thread_id)
    if thread is None:
        return None
    thread.message = message
    return thread


def load_config() -> Config:
    path = paths.config_path()
    if not path.exists():
        return Config()
    try:
        return Config.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return Config()


def save_config(config: Config) -> None:
    _atomic_write(paths.config_path(), json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n")


def load_state() -> State:
    path = paths.state_path()
    if not path.exists():
        return State()
    try:
        return State.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        # Never lose armed threads silently: keep the unreadable file for
        # diagnosis (UTF-8 BOM and hand edits are the usual culprits) and leave
        # a trace in run.log so a scheduled run does not look like it never ran.
        stamp = int(dt.datetime.now().timestamp())
        backup = path.with_name(f"state.json.corrupt-{stamp}")
        try:
            path.replace(backup)
            append_log(f"state.json unreadable ({type(exc).__name__}: {exc}); moved to {backup.name}")
        except OSError:
            append_log(f"state.json unreadable ({type(exc).__name__}: {exc}); continuing with empty state")
        return State()


def save_state(state: State) -> None:
    _atomic_write(paths.state_path(), json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            # ERROR_ACCESS_DENIED means it exists but belongs to another user.
            return ctypes.windll.kernel32.GetLastError() == 5
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _lock_is_stale(lock: Path) -> bool:
    """A lock is stale when its owner died (the scheduler may kill the job that wrote it)."""
    try:
        raw = lock.read_text(encoding="utf-8").strip()
        pid = int(raw) if raw else 0
    except (OSError, ValueError):
        pid = 0
    if pid and not _pid_alive(pid):
        return True
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return False
    return age > LOCK_STALE_SECONDS


@contextlib.contextmanager
def run_lock() -> Iterator[None]:
    """Exclusive lock for the runner; dead-owner and 6h-old locks are reclaimed."""
    paths.ensure_data_dir()
    lock = paths.data_dir() / "run.lock"
    acquired = False
    for _attempt in range(3):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            if _lock_is_stale(lock):
                with contextlib.suppress(OSError):
                    lock.unlink()
                continue
            break
    if not acquired:
        raise RuntimeError("another codex-continue run is in progress")
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def append_log(message: str) -> None:
    paths.ensure_data_dir()
    log = paths.log_path()
    if log.exists() and log.stat().st_size > LOG_ROTATE_BYTES:
        for index in range(LOG_BACKUPS - 1, 0, -1):
            older = log.with_name(f"{log.name}.{index}")
            newer = log.with_name(f"{log.name}.{index - 1}") if index > 1 else log
            if newer.exists():
                with contextlib.suppress(OSError):
                    os.replace(newer, older)
    stamp = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")


def read_log_tail(lines: int = 50) -> list[str]:
    path = paths.log_path()
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read().splitlines()[-lines:]
