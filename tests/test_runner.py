"""End-to-end tests of the runner with a fake `codex` executable."""

from __future__ import annotations

import datetime as dt
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_auto_continue import config as cfg, rollouts, runner
from codex_auto_continue.scheduler import NullScheduler

FAKE_CODEX = r'''#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
with open(os.environ["FAKE_CALL_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\n")

mode = os.environ.get("FAKE_MODE", "ok")
if args and args[0] == "queue":
    if mode.startswith("queue_fail"):
        print("Error: thread queue rejected", file=sys.stderr)
        sys.exit(1)
    with open(os.environ["FAKE_ROLLOUT"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user",
                       "content": [{"type": "text", "text": "继续"}]}}) + "\n")
    print("Queued message abc for thread test")
    sys.exit(0)
if "resume" in args:
    if mode == "queue_fail_resume_ok" or mode == "ok":
        sys.exit(0)
    sys.exit(1)
sys.exit(1)
'''


def _rollout_lines(interrupted: bool = True) -> str:
    meta = json.dumps(
        {"timestamp": "2026-10-23T12:00:00Z", "ordinal": 0, "type": "session_meta",
         "payload": {"id": "test-thread", "session_id": "test-thread", "cwd": "/tmp"}},
        ensure_ascii=False,
    )
    user = json.dumps(
        {"timestamp": "2026-10-23T12:00:00Z", "ordinal": 1, "type": "response_item",
         "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "继续任务"}]}},
        ensure_ascii=False,
    )
    complete = json.dumps(
        {"timestamp": "2026-10-23T12:05:00Z", "ordinal": 2, "type": "event_msg",
         "payload": {"type": "task_complete", "error": {"message": "You’ve hit your usage limit."} if interrupted else None}},
        ensure_ascii=False,
    )
    return "\n".join([meta, user, complete]) + "\n"


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        os.environ["CODEX_AUTO_CONTINUE_HOME"] = str(self.home / "data")
        os.environ["CODEX_AUTO_CONTINUE_DISABLE_SCHED"] = "1"
        os.environ["CODEX_AUTO_CONTINUE_POLL"] = "0.2"
        os.environ["CODEX_AUTO_CONTINUE_SKIP_QUOTA"] = "1"
        self.rollout = self.home / "rollout-test-thread.jsonl"
        self.rollout.write_text(_rollout_lines(), encoding="utf-8")
        self.call_log = self.home / "calls.jsonl"
        os.environ["FAKE_CALL_LOG"] = str(self.call_log)
        os.environ["FAKE_ROLLOUT"] = str(self.rollout)
        script = self.home / "fake_codex.py"
        script.write_text(FAKE_CODEX, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        if os.name == "nt":
            self.fake = self.home / "codex.cmd"
            self.fake.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        else:
            self.fake = self.home / "codex"
            self.fake.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
            self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.config = cfg.Config(codex_path=str(self.fake), queue_verify_seconds=2, notify_local=False)

    def tearDown(self) -> None:
        for key in (
            "CODEX_AUTO_CONTINUE_HOME",
            "CODEX_AUTO_CONTINUE_DISABLE_SCHED",
            "CODEX_AUTO_CONTINUE_POLL",
            "CODEX_AUTO_CONTINUE_SKIP_QUOTA",
            "FAKE_CALL_LOG",
            "FAKE_ROLLOUT",
            "FAKE_MODE",
        ):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def _thread(self) -> cfg.ArmedThread:
        info = rollouts.parse_rollout(self.rollout)
        self.assertTrue(info.interrupted)
        return cfg.ArmedThread(
            thread_id=info.thread_id,
            rollout_path=str(info.path),
            cwd=info.cwd,
            message="继续",
            armed_at=cfg.iso(dt.datetime.now(dt.timezone.utc)),
            baseline_lines=info.lines,
            fire_at=cfg.iso(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)),
        )

    def test_queue_path_marks_done(self) -> None:
        thread = self._thread()
        outcome = runner.continue_thread(thread, self.config, str(self.fake))
        self.assertTrue(outcome["ok"])
        self.assertEqual(thread.status, cfg.STATUS_DONE)
        calls = [json.loads(line) for line in self.call_log.read_text().splitlines()]
        self.assertEqual(calls[0][0], "queue")
        self.assertIn("--thread", calls[0])

    def test_resume_fallback_when_queue_fails(self) -> None:
        os.environ["FAKE_MODE"] = "queue_fail_resume_ok"
        thread = self._thread()
        outcome = runner.continue_thread(thread, self.config, str(self.fake))
        self.assertTrue(outcome["ok"])
        self.assertEqual(thread.status, cfg.STATUS_DONE)
        calls = [json.loads(line) for line in self.call_log.read_text().splitlines()]
        self.assertEqual(calls[0][0], "queue")
        self.assertIn("resume", calls[1])

    def test_thread_that_moved_on_is_superseded(self) -> None:
        with open(self.rollout, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user",
                              "content": [{"type": "text", "text": "我回来了"}]}}) + "\n")
        info = rollouts.parse_rollout(self.rollout)
        thread = cfg.ArmedThread(
            thread_id=info.thread_id,
            rollout_path=str(info.path),
            cwd=info.cwd,
            message="继续",
            armed_at=cfg.iso(dt.datetime.now(dt.timezone.utc)),
            baseline_lines=3,
        )
        outcome = runner.continue_thread(thread, self.config, str(self.fake))
        self.assertFalse(outcome["ok"])
        self.assertEqual(thread.status, cfg.STATUS_SUPERSEDED)

    def test_run_processes_due_threads_and_clears_scheduler(self) -> None:
        state = cfg.State()
        state.threads["test-thread"] = self._thread()
        cfg.save_state(state)
        scheduler = NullScheduler()
        summary = runner.run(self.config, scheduler=scheduler, notify_results=False)
        self.assertEqual(summary["status"], "done")
        self.assertTrue(summary["processed"][0]["ok"])
        self.assertEqual(cfg.load_state().threads["test-thread"].status, cfg.STATUS_DONE)
        self.assertEqual(scheduler.state, "disabled")

    def test_dry_run_idle_does_not_create_data_or_touch_scheduler(self) -> None:
        scheduler = NullScheduler()
        scheduler.state = "existing job"
        summary = runner.run(self.config, dry_run=True, scheduler=scheduler)
        self.assertEqual(summary["status"], "idle")
        self.assertFalse((self.home / "data").exists())
        self.assertEqual(scheduler.state, "existing job")

    def test_dry_run_due_thread_preserves_files_and_scheduler(self) -> None:
        cfg.save_state(cfg.State(threads={"test-thread": self._thread()}))
        before = {p.relative_to(self.home): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.home.rglob("*") if p.is_file()}
        scheduler = NullScheduler()
        scheduler.state = "existing job"
        summary = runner.run(self.config, dry_run=True, scheduler=scheduler)
        self.assertEqual(len(summary["processed"]), 1)
        self.assertIn("dry-run", summary["processed"][0]["detail"])
        after = {p.relative_to(self.home): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(scheduler.state, "existing job")

    def test_dry_run_single_thread_does_not_mutate_input(self) -> None:
        thread = self._thread()
        thread.baseline_lines = 1
        for scenario in ("interrupted", "continued", "missing"):
            with self.subTest(scenario=scenario):
                if scenario == "continued":
                    self.rollout.write_text(_rollout_lines(False))
                elif scenario == "missing":
                    self.rollout.unlink()
                before = thread.to_dict()
                outcome = runner.continue_thread(thread, self.config, str(self.fake), dry_run=True)
                self.assertEqual(outcome["ok"], scenario == "interrupted")
                self.assertEqual(thread.to_dict(), before)
        self.assertFalse(self.call_log.exists())

    def test_dry_run_exhausted_quota_only_previews_schedule(self) -> None:
        from codex_auto_continue import usage

        os.environ.pop("CODEX_AUTO_CONTINUE_SKIP_QUOTA")
        now = dt.datetime.now(dt.timezone.utc)
        cfg.save_state(cfg.State(threads={"test-thread": self._thread()}))
        usage._write_cache(usage.QuotaSnapshot(
            source="test", account_email=None,
            windows=[usage.QuotaWindow("primary", 300, 100, now + dt.timedelta(hours=1))],
            fetched_at=now,
        ))
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in (self.home / "data").iterdir()}
        scheduler = NullScheduler()
        scheduler.state = "existing job"
        with mock.patch.object(usage, "fetch_from_app_server", side_effect=AssertionError("RPC in preview")), \
             mock.patch.object(usage, "fetch_from_codexbar", return_value=None):
            summary = runner.run(self.config, dry_run=True, scheduler=scheduler, now=now)
        self.assertEqual(summary["status"], "waiting")
        self.assertEqual(summary["fire_at"], cfg.iso(now + dt.timedelta(hours=1, seconds=180)))
        self.assertEqual(scheduler.state, "existing job")
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in (self.home / "data").iterdir()})


if __name__ == "__main__":
    unittest.main()
