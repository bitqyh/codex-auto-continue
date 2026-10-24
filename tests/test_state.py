"""Tests for config/state persistence and the run lock."""

from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path

from codex_auto_continue import config as cfg, paths


class StateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CODEX_AUTO_CONTINUE_HOME"] = self.tmp.name

    def tearDown(self) -> None:
        os.environ.pop("CODEX_AUTO_CONTINUE_HOME", None)
        self.tmp.cleanup()

    def test_config_roundtrip(self) -> None:
        config = cfg.Config(message_template="继续干", grace_seconds=60, notify_local=False)
        cfg.save_config(config)
        loaded = cfg.load_config()
        self.assertEqual(loaded.message_template, "继续干")
        self.assertEqual(loaded.grace_seconds, 60)
        self.assertFalse(loaded.notify_local)

    def test_state_roundtrip(self) -> None:
        state = cfg.State()
        state.threads["abc"] = cfg.ArmedThread(
            thread_id="abc",
            rollout_path="/tmp/r.jsonl",
            cwd="/tmp",
            message="继续",
            armed_at=cfg.iso(dt.datetime.now(dt.timezone.utc)),
            baseline_lines=10,
        )
        cfg.save_state(state)
        loaded = cfg.load_state()
        self.assertEqual(loaded.threads["abc"].baseline_lines, 10)
        self.assertTrue(loaded.threads["abc"].is_pending)

    def test_set_thread_message_keeps_schedule(self) -> None:
        thread = cfg.ArmedThread(
            thread_id="abc",
            rollout_path="/tmp/r.jsonl",
            cwd="/tmp",
            message="旧消息",
            armed_at=cfg.iso(dt.datetime.now(dt.timezone.utc)),
            fire_at="2026-10-24T00:19:00+00:00",
            baseline_lines=7,
        )
        state = cfg.State(threads={"abc": thread})
        updated = cfg.set_thread_message(state, "abc", "新消息")
        assert updated is not None
        self.assertEqual(updated.message, "新消息")
        self.assertEqual(updated.fire_at, "2026-10-24T00:19:00+00:00")
        self.assertEqual(updated.baseline_lines, 7)
        self.assertIsNone(cfg.set_thread_message(state, "missing", "x"))

    def test_lock_is_exclusive_and_released(self) -> None:
        with cfg.run_lock():
            with self.assertRaises(RuntimeError):
                with cfg.run_lock():
                    pass
        with cfg.run_lock():
            pass

    def test_stale_dead_owner_lock_is_reclaimed(self) -> None:
        paths.ensure_data_dir()
        lock = paths.data_dir() / "run.lock"
        lock.write_text("999999999", encoding="utf-8")
        with cfg.run_lock():
            pass

    def test_corrupt_state_falls_back_to_empty(self) -> None:
        paths.ensure_data_dir()
        paths.state_path().write_text("{not json", encoding="utf-8")
        self.assertEqual(cfg.load_state().threads, {})


if __name__ == "__main__":
    unittest.main()
