"""Tests for the launchd adapter (plist rendering + generation labels, no real launchd)."""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_auto_continue import paths
from codex_auto_continue.scheduler import launchd


class LaunchdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.agents = self.root / "LaunchAgents"
        self.data = self.root / "data"
        self.agents.mkdir()
        self.data.mkdir()
        self.patches = [
            mock.patch.object(paths, "launch_agents_dir", return_value=self.agents),
            mock.patch.object(paths, "data_dir", return_value=self.data),
            mock.patch.object(launchd, "_launchctl", return_value=0),
        ]
        for patch in self.patches:
            patch.start()
        self.scheduler = launchd.LaunchdScheduler()

    def tearDown(self) -> None:
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def test_install_creates_generation_labels_and_cleanup_removes_old(self) -> None:
        argv = ["python3", "-m", "codex_auto_continue", "run"]
        env = {"PYTHONPATH": "/tmp/src"}
        run_at = dt.datetime.now().astimezone().replace(second=0, microsecond=0) + dt.timedelta(hours=2)
        self.scheduler.install_calendar(run_at, argv, env, None)
        first = sorted(self.agents.glob("*.plist"))
        self.assertEqual(len(first), 1)
        self.assertIn(".g1.plist", first[0].name)
        self.scheduler.install_interval(600, argv, env, None)
        second = sorted(self.agents.glob("*.plist"))
        self.assertEqual(len(second), 2)
        self.scheduler.cleanup_stale()
        remaining = sorted(self.agents.glob("*.plist"))
        self.assertEqual(len(remaining), 1)
        self.assertIn(".g2.plist", remaining[0].name)
        text = remaining[0].read_text()
        self.assertIn("StartInterval", text)
        self.assertIn("PYTHONPATH", text)
        self.assertIn("launchd: interval", self.scheduler.describe())

    def test_remove_deletes_everything(self) -> None:
        self.scheduler.install_interval(60, ["python3", "run"], {}, None)
        self.scheduler.remove()
        self.assertEqual(list(self.agents.glob("*.plist")), [])
        self.assertFalse((self.data / "scheduler.json").exists())
        self.assertEqual(self.scheduler.describe(), "launchd: not installed")


if __name__ == "__main__":
    unittest.main()
