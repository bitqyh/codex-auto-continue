"""Windows Task Scheduler adapter.

Creates a single named task ``CodexAutoContinue`` from a UTF-16 Task Scheduler
XML definition. One-time tasks wake the machine and run after sleep; interval
tasks keep polling until the runner removes the task.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from .. import paths
from .base import Scheduler, SchedulerError

TASK_NAME = "CodexAutoContinue"


def _run_schtasks(args: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["schtasks", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # noqa: BLE001
        raise SchedulerError(f"schtasks failed: {exc}") from exc


def _quote(value: str) -> str:
    return f'"{value}"'


class WindowsScheduler(Scheduler):
    name = "task-scheduler"

    def __init__(self) -> None:
        self.task_name = TASK_NAME
        paths.ensure_data_dir()

    # -- helpers ---------------------------------------------------------
    def _xml_path(self) -> Path:
        return paths.data_dir() / "task-scheduler.xml"

    def _action(self, workdir: str | None) -> tuple[str, str, str]:
        """Prefer a silent launcher shipped in the repository."""
        root = Path(workdir) if workdir else Path(sys.executable).parent
        hidden = root / "bin" / "codex-continue-hidden.vbs"
        if hidden.exists():
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            wscript = str(Path(system_root) / "System32" / "wscript.exe")
            return wscript, f'{_quote(str(hidden))} run --scheduled', str(root)
        launcher = root / "bin" / "codex-continue.cmd"
        if launcher.exists():
            return str(launcher), "run --scheduled", str(root)
        return sys.executable, "-m codex_auto_continue run --scheduled", str(root)

    def _render(self, start: dt.datetime, interval_seconds: int | None, workdir: str | None) -> str:
        command, arguments, directory = self._action(workdir)
        repetition = ""
        if interval_seconds:
            minutes = max(int(interval_seconds) // 60, 1)
            repetition = (
                "      <Repetition>\n"
                f"        <Interval>PT{minutes}M</Interval>\n"
                "        <StopAtDurationEnd>false</StopAtDurationEnd>\n"
                "      </Repetition>\n"
            )
        return (
            '<?xml version="1.0" encoding="UTF-16"?>\n'
            '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
            "  <RegistrationInfo>\n"
            "    <Author>codex-auto-continue</Author>\n"
            "    <Description>Codex Auto Continue: resume interrupted Codex sessions after a usage limit resets.</Description>\n"
            "  </RegistrationInfo>\n"
            "  <Triggers>\n"
            "    <TimeTrigger>\n"
            f"      <StartBoundary>{start.strftime('%Y-%m-%dT%H:%M:%S')}</StartBoundary>\n"
            "      <Enabled>true</Enabled>\n"
            f"{repetition}"
            "    </TimeTrigger>\n"
            "  </Triggers>\n"
            "  <Principals>\n"
            '    <Principal id="Author">\n'
            "      <LogonType>InteractiveToken</LogonType>\n"
            "      <RunLevel>LeastPrivilege</RunLevel>\n"
            "    </Principal>\n"
            "  </Principals>\n"
            "  <Settings>\n"
            "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
            "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
            "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
            "    <AllowHardTerminate>true</AllowHardTerminate>\n"
            "    <StartWhenAvailable>true</StartWhenAvailable>\n"
            "    <WakeToRun>true</WakeToRun>\n"
            "    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>\n"
            "    <Enabled>true</Enabled>\n"
            "  </Settings>\n"
            '  <Actions Context="Author">\n'
            "    <Exec>\n"
            f"      <Command>{escape(command)}</Command>\n"
            f"      <Arguments>{escape(arguments)}</Arguments>\n"
            f"      <WorkingDirectory>{escape(directory)}</WorkingDirectory>\n"
            "    </Exec>\n"
            "  </Actions>\n"
            "</Task>\n"
        )

    def _install(self, start: dt.datetime, interval_seconds: int | None, workdir: str | None) -> None:
        xml_path = self._xml_path()
        try:
            xml_path.write_text(self._render(start, interval_seconds, workdir), encoding="utf-16")
        except OSError as exc:
            raise SchedulerError(f"cannot write {xml_path}: {exc}") from exc
        result = _run_schtasks(["/Create", "/TN", self.task_name, "/XML", str(xml_path), "/F"])
        if result.returncode != 0:
            raise SchedulerError(
                "schtasks /Create failed "
                f"(exit {result.returncode}): {(result.stderr or result.stdout).strip()[:400]}"
            )

    # -- Scheduler API ---------------------------------------------------
    def install_calendar(self, run_at: dt.datetime, argv: list[str], env: dict[str, str], workdir: str | None) -> None:
        local = run_at.astimezone()
        if local <= dt.datetime.now().astimezone():
            local = dt.datetime.now().astimezone() + dt.timedelta(minutes=1)
        self._install(local.replace(microsecond=0), None, workdir)

    def install_interval(self, seconds: int, argv: list[str], env: dict[str, str], workdir: str | None) -> None:
        start = dt.datetime.now().astimezone() + dt.timedelta(minutes=1)
        self._install(start.replace(microsecond=0), max(int(seconds), 60), workdir)

    def remove(self) -> None:
        _run_schtasks(["/Delete", "/TN", self.task_name, "/F"])
        try:
            self._xml_path().unlink()
        except OSError:
            pass

    def describe(self) -> str:
        result = _run_schtasks(["/Query", "/TN", self.task_name, "/FO", "LIST"])
        if result.returncode != 0:
            return "task-scheduler: not installed"
        detail = ""
        for line in (result.stdout or "").splitlines():
            if "Next Run Time" in line:
                detail = line.strip()
                break
        return f"task-scheduler: installed ({self.task_name})" + (f" · {detail}" if detail else "")
