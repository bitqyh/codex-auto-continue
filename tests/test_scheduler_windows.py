"""Tests for the Windows Task Scheduler adapter (schtasks is mocked)."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_auto_continue import paths
from codex_auto_continue.scheduler.windows import TASK_NAME, WindowsScheduler


class _Result:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class WindowsSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(paths, "data_dir", return_value=self.root / "data"),
        ]
        for patch in self.patches:
            patch.start()
        (self.root / "data").mkdir()
        (self.root / "bin").mkdir()
        (self.root / "bin" / "codex-continue.cmd").write_text("@echo off\n", encoding="utf-8")
        self.calls: list[list[str]] = []

    def tearDown(self) -> None:
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def _fake_schtasks(self, returncode: int = 0, stdout: str = ""):
        def run(args, timeout=60.0):
            self.calls.append(args)
            return _Result(returncode, stdout)
        return run

    def _install(self, scheduler: WindowsScheduler, interval: int | None = None) -> str:
        with mock.patch("codex_auto_continue.scheduler.windows._run_schtasks", side_effect=self._fake_schtasks()):
            if interval is None:
                scheduler.install_calendar(
                    dt.datetime.now().astimezone() + dt.timedelta(hours=2), [], {}, str(self.root)
                )
            else:
                scheduler.install_interval(interval, [], {}, str(self.root))
        xml_path = self.root / "data" / "task-scheduler.xml"
        return xml_path.read_text(encoding="utf-16")

    def test_install_calendar_writes_wake_ready_task(self) -> None:
        scheduler = WindowsScheduler()
        xml = self._install(scheduler)
        self.assertIn("<WakeToRun>true</WakeToRun>", xml)
        self.assertIn("<StartWhenAvailable>true</StartWhenAvailable>", xml)
        self.assertIn("<LogonType>InteractiveToken</LogonType>", xml)
        self.assertIn("codex-continue", xml)
        self.assertIn("run --scheduled", xml)
        self.assertIn("TimeTrigger", xml)
        self.assertNotIn("Repetition", xml)
        self.assertEqual(self.calls[0][:4], ["/Create", "/TN", TASK_NAME, "/XML"])

    def test_install_interval_adds_repetition(self) -> None:
        scheduler = WindowsScheduler()
        xml = self._install(scheduler, interval=600)
        self.assertIn("<Interval>PT10M</Interval>", xml)
        self.assertIn("<StopAtDurationEnd>false</StopAtDurationEnd>", xml)

    def test_remove_deletes_task(self) -> None:
        scheduler = WindowsScheduler()
        with mock.patch("codex_auto_continue.scheduler.windows._run_schtasks", side_effect=self._fake_schtasks()):
            scheduler.remove()
        self.assertEqual(self.calls[0][:3], ["/Delete", "/TN", TASK_NAME])

    def test_describe_reports_next_run(self) -> None:
        scheduler = WindowsScheduler()
        output = "TaskName: \\CodexAutoContinue\nNext Run Time: 10/25/2026 12:19:00 AM\n"
        with mock.patch(
            "codex_auto_continue.scheduler.windows._run_schtasks",
            side_effect=self._fake_schtasks(stdout=output),
        ):
            text = scheduler.describe()
        self.assertIn("installed", text)
        self.assertIn("Next Run Time", text)

    def test_describe_when_missing(self) -> None:
        scheduler = WindowsScheduler()
        with mock.patch(
            "codex_auto_continue.scheduler.windows._run_schtasks",
            side_effect=self._fake_schtasks(returncode=1, stdout="ERROR: The system cannot find the file specified."),
        ):
            self.assertEqual(scheduler.describe(), "task-scheduler: not installed")

    def test_create_failure_raises(self) -> None:
        scheduler = WindowsScheduler()
        with mock.patch(
            "codex_auto_continue.scheduler.windows._run_schtasks",
            side_effect=self._fake_schtasks(returncode=1, stdout="ERROR"),
        ):
            with self.assertRaises(Exception):
                scheduler.install_interval(600, [], {}, str(self.root))


if __name__ == "__main__":
    unittest.main()
