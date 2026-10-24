"""Execute armed continuations: quota check, queue message, verify, reschedule."""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import config as cfg
from . import paths, plan, rollouts, threads, usage
from .notify import notify
from .scheduler import Scheduler, SchedulerError, for_platform
from .scheduler.launchd import python_argv, scheduled_env

SOURCE_ROOT = Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    return SOURCE_ROOT.parent if SOURCE_ROOT.name == "src" else SOURCE_ROOT.parent


def _schedule_parts() -> tuple[list[str], dict[str, str], str]:
    workdir = str(repo_root())
    return python_argv(), scheduled_env(workdir), workdir


@contextlib.contextmanager
def _hold_awake():
    """Keep the Mac from idle-sleeping while this run is active. No-op elsewhere."""
    process = None
    if sys.platform == "darwin":
        caffeinate = shutil.which("caffeinate")
        if caffeinate:
            try:
                process = subprocess.Popen(
                    [caffeinate, "-i", "-w", str(os.getpid())],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                process = None
    try:
        yield
    finally:
        if process is not None:
            with contextlib.suppress(Exception):
                process.terminate()
                process.wait(timeout=5)


def refresh_schedule(
    state: cfg.State,
    config: cfg.Config,
    snapshot: usage.QuotaSnapshot | None,
    scheduler: Scheduler,
    now: dt.datetime | None = None,
) -> dt.datetime | None:
    """Point the platform scheduler at the next useful moment (or remove it).

    State is persisted *before* touching launchd: the runner may be executing
    inside the very job it is about to replace, and `launchctl bootout` of that
    label terminates the current process.
    """
    pending = [thread for thread in state.threads.values() if thread.is_pending]
    if not pending:
        cfg.save_state(state)
        scheduler.remove()
        return None
    argv, env, workdir = _schedule_parts()
    ready_now = snapshot is not None and snapshot.has_capacity
    fire_at: dt.datetime | None = None
    if not ready_now:
        fire_at = plan.compute_fire_at(pending, snapshot, config, now=now)
        for thread in pending:
            thread.fire_at = cfg.iso(fire_at)
    cfg.save_state(state)
    if ready_now:
        scheduler.install_interval(60, argv, env, workdir)
    elif snapshot is None:
        scheduler.install_interval(config.retry_seconds, argv, env, workdir)
    else:
        scheduler.install_calendar(fire_at, argv, env, workdir)  # type: ignore[arg-type]
    cleanup = getattr(scheduler, "cleanup_stale", None)
    if callable(cleanup):
        cfg.append_log("scheduler refreshed; cleaning older generation jobs")
        cleanup()
    return fire_at


def _safe_cwd(cwd: str | None) -> str | None:
    """launchd jobs may not be allowed into protected folders (macOS TCC); fall back to $HOME."""
    if not cwd:
        return None
    path = Path(cwd)
    try:
        if path.is_dir() and os.access(path, os.R_OK | os.X_OK):
            return str(path)
    except OSError:
        pass
    home = Path.home()
    return str(home) if home.is_dir() else None


def _run_codex(args: list[str], cwd: str | None, timeout: float) -> tuple[int, str]:
    try:
        result = subprocess.run(
            args,
            cwd=_safe_cwd(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode, output.strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as exc:
        return 127, str(exc)


def _wait_for_rollout_growth(path: Path, baseline: int, seconds: int) -> bool:
    import os as _os

    poll = float(_os.environ.get("CODEX_AUTO_CONTINUE_POLL", "5") or 5)
    deadline = time.monotonic() + max(seconds, 1)
    while time.monotonic() < deadline:
        time.sleep(poll)
        if rollouts.line_count(path) > baseline:
            return True
    return False


def _send_via_queue(codex: str, thread: cfg.ArmedThread, message: str, verify_seconds: int) -> tuple[bool, str]:
    # `queue` talks to the app server and does not need a working directory;
    # avoiding it keeps the launchd job clear of protected folders (macOS TCC).
    code, output = _run_codex(
        [codex, "queue", "--thread", thread.thread_id, "--message", message], None, 60
    )
    if code != 0:
        return False, f"queue failed (exit {code}): {output[-400:]}"
    if _wait_for_rollout_growth(Path(thread.rollout_path), thread.baseline_lines, verify_seconds):
        return True, "queue accepted and a new turn started (App visible)"
    return False, "queue accepted but no new turn appeared in time"


def _send_via_resume(codex: str, thread: cfg.ArmedThread, message: str) -> tuple[bool, str]:
    last_message = paths.data_dir() / f"last-message-{thread.thread_id}.txt"
    code, output = _run_codex(
        [
            codex,
            "exec",
            "--approve-for-me",
            "--skip-git-repo-check",
            "-o",
            str(last_message),
            "resume",
            thread.thread_id,
            message,
        ],
        thread.cwd,
        timeout=3600,
    )
    if code == 0:
        return True, f"resume completed, last message: {last_message}"
    if "active writer" in output:
        return False, "resume refused: the Codex app still owns this thread (it will resume in-app instead)"
    return False, f"resume failed (exit {code}): {output[-400:]}"


def continue_thread(
    thread: cfg.ArmedThread,
    config: cfg.Config,
    codex_path: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Try to continue one armed thread; previews leave the input unchanged."""
    if dry_run:
        thread = replace(thread)
    rollout = Path(thread.rollout_path)
    if not rollout.exists():
        thread.status = cfg.STATUS_FAILED
        thread.last_error = "rollout file not found"
        return {"thread_id": thread.thread_id, "ok": False, "detail": thread.last_error}

    info = rollouts.parse_rollout(rollout)
    if info.lines > thread.baseline_lines and not info.interrupted:
        thread.status = cfg.STATUS_SUPERSEDED
        thread.last_error = "session moved on after arming"
        return {"thread_id": thread.thread_id, "ok": False, "detail": thread.last_error}
    if not info.interrupted:
        thread.status = cfg.STATUS_SUPERSEDED
        thread.last_error = "session is no longer waiting on a usage limit"
        return {"thread_id": thread.thread_id, "ok": False, "detail": thread.last_error}

    thread.baseline_lines = info.lines
    message = (thread.message or config.message_template).replace("{thread_id}", thread.thread_id)
    if dry_run:
        return {"thread_id": thread.thread_id, "ok": True, "detail": f"dry-run: would queue '{message}'"}

    thread.status = cfg.STATUS_RUNNING
    thread.attempts += 1
    ok, detail = _send_via_queue(codex_path, thread, message, config.queue_verify_seconds)
    if not ok:
        cfg.append_log(f"queue path failed for {thread.thread_id}: {detail}; trying resume")
        ok, detail = _send_via_resume(codex_path, thread, message)
    if ok:
        thread.status = cfg.STATUS_DONE
        thread.completed_at = cfg.iso(dt.datetime.now(dt.timezone.utc))
        thread.last_error = None
    else:
        thread.last_error = detail
        if thread.attempts >= max(config.max_attempts, 1):
            thread.status = cfg.STATUS_FAILED
        else:
            thread.status = cfg.STATUS_ARMED
    return {"thread_id": thread.thread_id, "ok": ok, "detail": detail}


def run(
    config: cfg.Config | None = None,
    dry_run: bool = False,
    now: dt.datetime | None = None,
    scheduler: Scheduler | None = None,
    codex_path: str | None = None,
    notify_results: bool = True,
) -> dict[str, Any]:
    """One scheduler tick."""
    config = config or cfg.load_config()
    if dry_run:
        return _preview(config, now, codex_path)
    scheduler = scheduler or for_platform()
    summary: dict[str, Any] = {"status": "ok", "processed": [], "scheduled": None}

    try:
        lock_context = cfg.run_lock()
        lock_context.__enter__()
    except RuntimeError as exc:
        summary.update(status="locked", detail=str(exc))
        return summary

    try:
        with _hold_awake():
            return _run_locked(config, dry_run, now, scheduler, codex_path, notify_results, summary)
    finally:
        lock_context.__exit__(None, None, None)


def _preview(config: cfg.Config, now: dt.datetime | None, codex_path: str | None) -> dict[str, Any]:
    """Read-only preview: no lock, scheduler, notifications, RPC or state writes."""
    state = cfg.load_state()
    pending = [thread for thread in state.threads.values() if thread.is_pending]
    summary: dict[str, Any] = {"status": "idle", "dry_run": True, "processed": [], "scheduled": None}
    if not pending:
        return summary
    snapshot = None if os.environ.get("CODEX_AUTO_CONTINUE_SKIP_QUOTA") == "1" else usage.snapshot(
        config.codex_path, max_age=config.quota_cache_seconds, read_only=True
    )
    summary["quota_source"] = snapshot.source if snapshot else "unavailable (execution will refresh)"
    if snapshot is not None and not snapshot.has_capacity:
        fire_at = plan.compute_fire_at(pending, snapshot, config, now=now)
        summary.update(status="waiting", fire_at=cfg.iso(fire_at))
        return summary
    for thread in sorted(pending, key=lambda item: item.fire_at or ""):
        if plan.is_due(thread, now=now):
            summary["processed"].append(continue_thread(
                thread, config, codex_path or config.codex_path or "", dry_run=True
            ))
    scheduled = [plan.aware(cfg.parse_iso(thread.fire_at)) for thread in pending if thread.fire_at]
    summary.update(status="dry-run", scheduled=cfg.iso(min(scheduled)) if scheduled else None)
    return summary


def _run_locked(
    config: cfg.Config,
    dry_run: bool,
    now: dt.datetime | None,
    scheduler: Scheduler,
    codex_path: str | None,
    notify_results: bool,
    summary: dict[str, Any],
) -> dict[str, Any]:
    if True:
        state = cfg.load_state()
        pending = [thread for thread in state.threads.values() if thread.is_pending]
        if not pending:
            cfg.save_state(state)
            scheduler.remove()
            summary["status"] = "idle"
            return summary

        snapshot = None if os.environ.get("CODEX_AUTO_CONTINUE_SKIP_QUOTA") == "1" else usage.snapshot(
            config.codex_path, force=True
        )
        if snapshot is not None:
            summary["quota_source"] = snapshot.source

        if snapshot is not None and not snapshot.has_capacity:
            fire_at = refresh_schedule(state, config, snapshot, scheduler, now=now)
            cfg.save_state(state)
            cfg.append_log(
                f"quota still exhausted; next attempt at {plan.format_local(fire_at)} "
                f"({plan.describe_quota(snapshot)})"
            )
            summary.update(status="waiting", fire_at=cfg.iso(fire_at))
            return summary

        codex = usage.find_codex(config.codex_path)
        if not codex:
            summary.update(status="error", detail="codex CLI not found")
            return summary
        summary["codex"] = codex

        due = [thread for thread in pending if plan.is_due(thread, now=now)]
        for thread in sorted(due, key=lambda item: item.fire_at or ""):
            outcome = continue_thread(thread, config, codex, dry_run=dry_run)
            summary["processed"].append(outcome)
            label = threads.thread_title(thread.thread_id) or thread.thread_id
            cfg.append_log(f"thread {label} ({outcome['thread_id']}): {outcome['detail']}")
            if notify_results and not dry_run:
                title = "Codex 已恢复续跑" if outcome["ok"] else "Codex 续跑失败"
                notify(config, title, f"{outcome['thread_id']}: {outcome['detail']}", "thread-result", outcome)

        remaining = [thread for thread in state.threads.values() if thread.is_pending]
        fire_at = None
        if remaining:
            fire_at = refresh_schedule(state, config, snapshot, scheduler, now=now)
            summary["scheduled"] = cfg.iso(fire_at)
        else:
            cfg.save_state(state)
            cfg.append_log("all armed threads finished; removing scheduler job")
            scheduler.remove()
        cfg.save_state(state)
        summary["status"] = "done" if not remaining else "rescheduled"
        return summary


def notify_summary(config: cfg.Config, title: str, body: str, summary: dict[str, Any]) -> None:
    if config.notify_local:
        notify(config, title, body, "summary", summary)
