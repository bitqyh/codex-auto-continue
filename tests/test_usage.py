"""Tests for quota windows and CodexBar parsing."""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_auto_continue import paths, usage


def _epoch(value: dt.datetime) -> int:
    return int(value.timestamp())


class RateLimitParsingTests(unittest.TestCase):
    def _limits(self, primary_used: float, secondary_used: float, reset: dt.datetime) -> dict:
        return {
            "rateLimitsByLimitId": {
                "codex": {
                    "primary": {
                        "usedPercent": primary_used,
                        "windowDurationMins": 300,
                        "resetsAt": _epoch(reset),
                    },
                    "secondary": {
                        "usedPercent": secondary_used,
                        "windowDurationMins": 10080,
                        "resetsAt": _epoch(reset + dt.timedelta(days=6)),
                    },
                }
            }
        }

    def test_parses_windows_and_next_reset(self) -> None:
        reset = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
        account = {"account": {"type": "chatgpt", "email": "a@example.com"}}
        snapshot = usage.parse_rate_limits(account, self._limits(100, 47, reset))
        self.assertEqual(snapshot.source, "app-server")
        self.assertEqual(snapshot.account_email, "a@example.com")
        self.assertFalse(snapshot.has_capacity)
        self.assertEqual([window.window_minutes for window in snapshot.windows], [300, 10080])
        self.assertEqual(int(snapshot.next_reset().timestamp()), int(reset.timestamp()))

    def test_capacity_when_no_window_exhausted(self) -> None:
        reset = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
        snapshot = usage.parse_rate_limits({"account": {"type": "chatgpt"}}, self._limits(40, 27, reset))
        self.assertTrue(snapshot.has_capacity)
        self.assertIsNone(snapshot.next_reset())

    def test_both_windows_exhausted_waits_for_latest_reset(self) -> None:
        reset = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
        snapshot = usage.parse_rate_limits({"account": {"type": "chatgpt"}}, self._limits(100, 100, reset))
        self.assertEqual(int(snapshot.next_reset().timestamp()), int((reset + dt.timedelta(days=6)).timestamp()))

    def test_invalid_payload_raises(self) -> None:
        with self.assertRaises(ValueError):
            usage.parse_rate_limits({"account": {"type": "chatgpt"}}, {"rateLimits": {}})


class CodexBarParsingTests(unittest.TestCase):
    def test_reads_dashboard_snapshot(self) -> None:
        payload = {
            "accountEmail": "a@example.com",
            "snapshot": {
                "primaryLimit": {
                    "usedPercent": 100,
                    "windowMinutes": 300,
                    "resetsAt": "2026-10-23T16:15:25Z",
                },
                "secondaryLimit": {
                    "usedPercent": 47,
                    "windowMinutes": 10080,
                    "resetsAt": "2026-10-30T01:08:57Z",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "openai-dashboard.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(paths, "codexbar_dashboard_path", return_value=path), mock.patch.object(
                paths, "codexbar_snapshots_path", return_value=None
            ):
                snapshot = usage.fetch_from_codexbar()
        assert snapshot is not None
        self.assertEqual(snapshot.source, "codexbar")
        self.assertEqual(snapshot.account_email, "a@example.com")
        self.assertEqual(snapshot.exhausted_windows[0].window_minutes, 300)
        self.assertEqual(snapshot.next_reset().year, 2026)

    def test_reads_account_snapshot_records(self) -> None:
        payload = {
            "records": [
                {
                    "snapshot": {
                        "primary": {
                            "usedPercent": 80,
                            "windowMinutes": 300,
                            "resetsAt": 1761303000,
                        }
                    }
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "codex-account-snapshots.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(paths, "codexbar_dashboard_path", return_value=None), mock.patch.object(
                paths, "codexbar_snapshots_path", return_value=path
            ):
                snapshot = usage.fetch_from_codexbar()
        assert snapshot is not None
        self.assertTrue(snapshot.has_capacity)
        self.assertEqual(snapshot.windows[0].used_percent, 80)


class QuotaCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(paths, "data_dir", return_value=Path(self.tmp.name))
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def _snapshot(self) -> usage.QuotaSnapshot:
        reset = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
        return usage.QuotaSnapshot(
            source="app-server",
            account_email="a@example.com",
            windows=[usage.QuotaWindow("primary", 300, 100.0, reset)],
            fetched_at=dt.datetime.now(dt.timezone.utc),
        )

    def test_fresh_cache_is_used_without_fetching(self) -> None:
        usage._write_cache(self._snapshot())
        with mock.patch.object(usage, "fetch_from_app_server", side_effect=AssertionError("must not fetch")), mock.patch.object(
            usage, "fetch_from_codexbar", side_effect=AssertionError("must not fetch")
        ):
            cached = usage.snapshot(max_age=120)
        assert cached is not None
        self.assertIn("cached", cached.source)

    def test_cache_expiry_and_force(self) -> None:
        stale = self._snapshot()
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)).isoformat()
        usage._write_cache(stale)
        raw = json.loads(usage._cache_path().read_text())
        raw["fetched_at"] = old
        usage._cache_path().write_text(json.dumps(raw), encoding="utf-8")
        self.assertIsNone(usage._read_cache(120))
        with mock.patch.object(usage, "fetch_from_app_server", side_effect=RuntimeError("down")), mock.patch.object(
            usage, "fetch_from_codexbar", return_value=None
        ):
            self.assertIsNone(usage.snapshot(max_age=120, force=True))
            fallback = usage.snapshot(max_age=120)
        assert fallback is not None

    def test_write_cache_survives(self) -> None:
        usage._write_cache(self._snapshot())
        self.assertTrue(usage._cache_path().exists())
        data = json.loads(usage._cache_path().read_text())
        self.assertIn("windows", data)

    def test_read_only_codexbar_does_not_write_cache(self) -> None:
        with mock.patch.object(usage, "fetch_from_codexbar", return_value=self._snapshot()):
            result = usage.snapshot(max_age=300, read_only=True)
        self.assertIsNotNone(result)
        self.assertFalse(usage._cache_path().exists())

    def test_read_only_without_cache_does_not_start_app_server(self) -> None:
        with mock.patch.object(usage, "fetch_from_codexbar", return_value=None), \
             mock.patch.object(usage, "fetch_from_app_server", side_effect=AssertionError("RPC in preview")):
            result = usage.snapshot(max_age=300, read_only=True)
        self.assertIsNone(result)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_read_only_rejects_stale_codexbar_with_missing_or_invalid_timestamp(self) -> None:
        import os

        dashboard = Path(self.tmp.name) / "dashboard.json"
        now = dt.datetime.now(dt.timezone.utc)
        old = now - dt.timedelta(hours=1)
        for timestamp in (None, "invalid", old.isoformat()):
            with self.subTest(updated_at=timestamp):
                payload = {"snapshot": {
                    "updatedAt": timestamp,
                    "primaryLimit": {"usedPercent": 100, "windowMinutes": 300,
                                     "resetsAt": "2020-01-01T00:00:00Z"},
                }}
                dashboard.write_text(json.dumps(payload), encoding="utf-8")
                os.utime(dashboard, (old.timestamp(), old.timestamp()))
                before = (dashboard.read_bytes(), dashboard.stat().st_mtime_ns)
                with mock.patch.object(paths, "codexbar_dashboard_path", return_value=dashboard), \
                     mock.patch.object(paths, "codexbar_snapshots_path", return_value=None):
                    self.assertIsNone(usage.snapshot(max_age=300, read_only=True))
                self.assertEqual(before, (dashboard.read_bytes(), dashboard.stat().st_mtime_ns))
                self.assertFalse(usage._cache_path().exists())


class FindCodexTests(unittest.TestCase):
    """The Codex App on Windows keeps its CLI outside PATH."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_windows_candidates_prefer_bundled_cli(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "USERPROFILE": str(self.root),
                "APPDATA": str(self.root / "roaming"),
                "LOCALAPPDATA": str(self.root / "local"),
            },
            clear=False,
        ):
            candidates = usage._windows_codex_candidates()
        self.assertEqual(candidates[0], self.root / ".codex" / ".sandbox-bin" / "codex.exe")
        self.assertIn(self.root / "roaming" / "npm" / "codex.cmd", candidates)

    def test_find_codex_discovers_bundled_windows_cli(self) -> None:
        bundled = self.root / ".codex" / ".sandbox-bin" / "codex.exe"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("", encoding="utf-8")
        with mock.patch.dict(os.environ, {"USERPROFILE": str(self.root)}, clear=False), \
             mock.patch.object(usage, "_is_windows", return_value=True), \
             mock.patch.object(usage, "_windows_codex_candidates", return_value=[bundled]), \
             mock.patch.object(usage.shutil, "which", return_value=None):
            self.assertEqual(usage.find_codex(), str(bundled))

    def test_find_codex_prefers_explicit_config_path(self) -> None:
        explicit = self.root / "custom-codex.exe"
        explicit.write_text("", encoding="utf-8")
        self.assertEqual(usage.find_codex(str(explicit)), str(explicit))


class AppServerArgvTests(unittest.TestCase):
    def test_legacy_cli_gets_stdio_flag(self) -> None:
        usage._APP_SERVER_ARGV_CACHE.clear()
        completed = mock.Mock(returncode=0, stdout="Usage: codex app-server --stdio", stderr="")
        with mock.patch.object(usage.subprocess, "run", return_value=completed):
            argv = usage._app_server_argv("codex-old")
        self.assertEqual(argv, ["codex-old", "app-server", "--stdio"])

    def test_modern_cli_runs_stdio_by_default(self) -> None:
        usage._APP_SERVER_ARGV_CACHE.clear()
        completed = mock.Mock(returncode=0, stdout="Usage: codex app-server [OPTIONS] [COMMAND]", stderr="")
        with mock.patch.object(usage.subprocess, "run", return_value=completed):
            argv = usage._app_server_argv("codex-new")
        self.assertEqual(argv, ["codex-new", "app-server"])


if __name__ == "__main__":
    unittest.main()
