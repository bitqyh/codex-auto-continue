"""macOS launchd adapter.

Each (re)schedule installs a new one-shot job under a fresh generation label, then
removes stale labels. Ordering matters: the runner may itself be running *inside*
the currently installed job, so state is persisted and the new job is bootstrapped
before any `launchctl bootout` happens.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from .. import paths
from .base import Scheduler, SchedulerError

BASE_LABEL = "local.codex-auto-continue"


def _launchctl(*args: str, timeout: float = 15.0) -> int:
    try:
        result = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=timeout)
        return result.returncode
    except (OSError, subprocess.SubprocessError) as exc:  # noqa: BLE001
        raise SchedulerError(f"launchctl failed: {exc}") from exc


class LaunchdScheduler(Scheduler):
    name = "launchd"

    def __init__(self) -> None:
        self.base_label = BASE_LABEL
        self.meta_path = paths.data_dir() / "scheduler.json"
        paths.ensure_data_dir()

    # -- metadata --------------------------------------------------------
    def _read_meta(self) -> dict:
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_meta(self, meta: dict) -> None:
        tmp = self.meta_path.with_name(f".{self.meta_path.name}.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.meta_path)

    def _labels_on_disk(self) -> list[str]:
        directory = paths.launch_agents_dir()
        if not directory.exists():
            return []
        return sorted(
            path.stem for path in directory.glob(f"{self.base_label}*.plist") if path.is_file()
        )

    def _bootout(self, label: str) -> None:
        _launchctl("bootout", f"gui/{os.getuid()}/{label}")

    # -- plist rendering -------------------------------------------------
    def _render(
        self,
        label: str,
        argv: list[str],
        env: dict[str, str],
        workdir: str | None,
        calendar: dt.datetime | None,
        interval: int | None,
    ) -> str:
        arguments = "".join(f"    <string>{escape(part)}</string>\n" for part in argv)
        environment = "".join(
            f"    <key>{escape(key)}</key><string>{escape(value)}</string>\n"
            for key, value in sorted(env.items())
        )
        if calendar is not None:
            schedule = (
                "    <key>StartCalendarInterval</key>\n"
                "    <dict>\n"
                f"      <key>Month</key><integer>{calendar.month}</integer>\n"
                f"      <key>Day</key><integer>{calendar.day}</integer>\n"
                f"      <key>Hour</key><integer>{calendar.hour}</integer>\n"
                f"      <key>Minute</key><integer>{calendar.minute}</integer>\n"
                "    </dict>\n"
            )
        else:
            schedule = f"    <key>StartInterval</key><integer>{int(interval or 60)}</integer>\n"
        working = f"    <key>WorkingDirectory</key><string>{escape(workdir)}</string>\n" if workdir else ""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            "<dict>\n"
            f"    <key>Label</key><string>{label}</string>\n"
            "    <key>ProgramArguments</key>\n"
            "    <array>\n"
            f"{arguments}"
            "    </array>\n"
            f"{working}"
            "    <key>EnvironmentVariables</key>\n"
            "    <dict>\n"
            f"{environment}"
            "    </dict>\n"
            f"{schedule}"
            f"    <key>StandardOutPath</key><string>{escape(str(paths.data_dir() / 'launchd.out.log'))}</string>\n"
            f"    <key>StandardErrorPath</key><string>{escape(str(paths.data_dir() / 'launchd.err.log'))}</string>\n"
            "    <key>ProcessType</key><string>Background</string>\n"
            "</dict>\n"
            "</plist>\n"
        )

    def next_label(self) -> str:
        meta = self._read_meta()
        generation = int(meta.get("generation", 0)) + 1
        return f"{self.base_label}.g{generation}"

    def _install(
        self,
        argv: list[str],
        env: dict[str, str],
        workdir: str | None,
        calendar: dt.datetime | None,
        interval: int | None,
    ) -> str:
        label = self.next_label()
        plist_path = paths.launch_agents_dir() / f"{label}.plist"
        try:
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(self._render(label, argv, env, workdir, calendar, interval), encoding="utf-8")
        except OSError as exc:
            raise SchedulerError(f"cannot write {plist_path}: {exc}") from exc
        self._write_meta(
            {
                "generation": int(label.rsplit(".g", 1)[1]),
                "label": label,
                "kind": "calendar" if calendar is not None else "interval",
                "installed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
        )
        code = _launchctl("bootstrap", f"gui/{os.getuid()}", str(plist_path))
        if code != 0:
            raise SchedulerError(f"launchctl bootstrap failed (exit {code}) for {plist_path}")
        return label

    def cleanup_stale(self, keep: str | None = None) -> None:
        """Remove older generation plists/jobs.

        Plists are unlinked *before* booting out, because booting out the job this
        process is currently running under terminates it immediately.
        """
        current = keep or self._read_meta().get("label")
        stale = [label for label in self._labels_on_disk() if label != current]
        if not stale:
            return
        for label in stale:
            try:
                (paths.launch_agents_dir() / f"{label}.plist").unlink()
            except OSError:
                pass
        for label in stale:
            try:
                self._bootout(label)
            except SchedulerError:
                pass

    # -- Scheduler API ---------------------------------------------------
    def install_calendar(self, run_at: dt.datetime, argv: list[str], env: dict[str, str], workdir: str | None) -> None:
        local = run_at.astimezone()
        if local.second or local.microsecond:
            local = local.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
        if local <= dt.datetime.now().astimezone():
            local = dt.datetime.now().astimezone().replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
        self._install(argv, env, workdir, calendar=local, interval=None)

    def install_interval(self, seconds: int, argv: list[str], env: dict[str, str], workdir: str | None) -> None:
        self._install(argv, env, workdir, calendar=None, interval=max(int(seconds), 30))

    def remove(self) -> None:
        meta_label = self._read_meta().get("label")
        labels = set(self._labels_on_disk())
        if meta_label:
            labels.add(meta_label)
        # Unlink plists and metadata *before* bootout: booting out the job this
        # process runs under terminates it immediately.
        try:
            self.meta_path.unlink()
        except OSError:
            pass
        for label in labels:
            try:
                (paths.launch_agents_dir() / f"{label}.plist").unlink()
            except OSError:
                pass
        for label in labels:
            try:
                self._bootout(label)
            except SchedulerError:
                pass

    def describe(self) -> str:
        meta = self._read_meta()
        label = meta.get("label")
        if not label:
            return "launchd: not installed"
        plist = paths.launch_agents_dir() / f"{label}.plist"
        if not plist.exists():
            return "launchd: not installed"
        text = plist.read_text(encoding="utf-8", errors="replace")
        if "StartCalendarInterval" in text:
            try:
                hour = _plist_int(text, "Hour")
                minute = _plist_int(text, "Minute")
                day = _plist_int(text, "Day")
                month = _plist_int(text, "Month")
                return f"launchd: one-shot {month:02d}-{day:02d} {hour:02d}:{minute:02d} ({label})"
            except Exception:  # noqa: BLE001
                return f"launchd: one-shot ({label})"
        return f"launchd: interval {_plist_int(text, 'StartInterval')}s ({label})"


def _plist_int(text: str, key: str) -> int:
    marker = f"<key>{key}</key><integer>"
    start = text.find(marker)
    if start < 0:
        return 0
    start += len(marker)
    end = text.find("<", start)
    return int(text[start:end])


def python_argv(extra: list[str] | None = None) -> list[str]:
    return [sys.executable, "-m", "codex_auto_continue", "run", "--scheduled", *(extra or [])]


def scheduled_env(workdir: str) -> dict[str, str]:
    env = {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": str(Path(workdir) / "src"),
        "PYTHONUNBUFFERED": "1",
    }
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        env["CODEX_HOME"] = codex_home
    return env
