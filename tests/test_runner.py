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

if "--help" in args:
    if args and args[0] == "queue":
        print("Usage: codex queue --thread <id> --message <text>")
    else:
        print("Usage: codex exec [OPTIONS]")
        print("  --sandbox <SANDBOX_MODE>")
        print("  --skip-git-repo-check")
    sys.exit(0)

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
        queue_calls = [call for call in calls if "--thread" in call]
        self.assertEqual(len(queue_calls), 1)
        self.assertIn("--thread", queue_calls[0])
        self.assertFalse(any("resume" in call for call in calls))

    def test_resume_fallback_when_queue_fails(self) -> None:
        os.environ["FAKE_MODE"] = "queue_fail_resume_ok"
        thread = self._thread()
        outcome = runner.continue_thread(thread, self.config, str(self.fake))
        self.assertTrue(outcome["ok"])
        self.assertEqual(thread.status, cfg.STATUS_DONE)
        calls = [json.loads(line) for line in self.call_log.read_text().splitlines()]
        self.assertTrue(any("--thread" in call for call in calls))
        self.assertTrue(any("resume" in call for call in calls))

    def test_queue_supported_detection(self) -> None:
        runner._QUEUE_SUPPORT_CACHE.clear()
        with mock.patch.object(
            runner, "_run_codex", return_value=(0, "Usage: codex queue --thread <id> --message <text>")
        ):
            self.assertTrue(runner.queue_supported("codex-test-with-queue"))
        with mock.patch.object(runner, "_run_codex", return_value=(0, "Usage: codex [OPTIONS] [PROMPT]")):
            self.assertFalse(runner.queue_supported("codex-test-without-queue"))

    def test_queue_unsupported_skips_straight_to_resume(self) -> None:
        runner._QUEUE_SUPPORT_CACHE.clear()
        with mock.patch.object(runner, "_help_output", side_effect=lambda codex, *args: ""):
            thread = self._thread()
            outcome = runner.continue_thread(thread, self.config, str(self.fake))
        self.assertTrue(outcome["ok"])
        calls = [json.loads(line) for line in self.call_log.read_text().splitlines()]
        self.assertFalse(any("--thread" in call for call in calls))
        self.assertTrue(any("resume" in call for call in calls))

    def test_resume_args_use_legacy_approve_flag_when_supported(self) -> None:
        with mock.patch.object(
            runner,
            "_help_output",
            return_value="Usage: codex exec --approve-for-me --skip-git-repo-check",
        ):
            args = runner._resume_exec_args(str(self.fake), self.home / "last.txt", self._thread(), "继续")
        self.assertIn("--approve-for-me", args)
        self.assertIn("--skip-git-repo-check", args)
        self.assertNotIn("--sandbox", args)

    def test_resume_args_use_sandbox_for_modern_cli(self) -> None:
        with mock.patch.object(
            runner,
            "_help_output",
            return_value="Usage: codex exec --sandbox <SANDBOX_MODE> --skip-git-repo-check",
        ):
            args = runner._resume_exec_args(str(self.fake), self.home / "last.txt", self._thread(), "继续")
        self.assertIn("--sandbox", args)
        self.assertIn("workspace-write", args)
        self.assertNotIn("--approve-for-me", args)

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
                    self.rollout.write_text(_rollout_lines(False), encoding="utf-8")
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


    def test_run_logs_missing_codex(self) -> None:
        cfg.save_state(cfg.State(threads={"test-thread": self._thread()}))
        with mock.patch.object(runner.usage, "find_codex", return_value=None):
            summary = runner.run(self.config, scheduler=NullScheduler(), notify_results=False)
        self.assertEqual(summary["status"], "error")
        log = (self.home / "data" / "run.log").read_text(encoding="utf-8")
        self.assertIn("codex CLI not found", log)

    def test_forced_thread_skips_interrupted_guard(self) -> None:
        other = self.home / "rollout-not-interrupted.jsonl"
        other.write_text(_rollout_lines(interrupted=False), encoding="utf-8")
        info = rollouts.parse_rollout(other)
        self.assertFalse(info.interrupted)
        thread = cfg.ArmedThread(
            thread_id=info.thread_id,
            rollout_path=str(info.path),
            cwd=info.cwd,
            message="继续",
            armed_at=cfg.iso(dt.datetime.now(dt.timezone.utc)),
            baseline_lines=info.lines,
            forced=True,
        )
        with mock.patch.object(runner, "_send_via_queue", return_value=(True, "queued")):
            outcome = runner.continue_thread(thread, self.config, str(self.fake))
        self.assertTrue(outcome["ok"])
        self.assertEqual(thread.status, cfg.STATUS_DONE)

    def test_resume_args_include_configured_model(self) -> None:
        args = runner._resume_exec_args(
            str(self.fake), self.home / "last.txt", self._thread(), "继续", "gpt-6.1-sol"
        )
        self.assertIn("-m", args)
        self.assertEqual(args[args.index("-m") + 1], "gpt-6.1-sol")

    def test_resume_args_omit_model_by_default(self) -> None:
        args = runner._resume_exec_args(str(self.fake), self.home / "last.txt", self._thread(), "继续")
        self.assertNotIn("-m", args)

    def test_proxy_env_helper(self) -> None:
        self.assertIsNone(runner._env_with_proxy(None))
        env = runner._env_with_proxy("http://127.0.0.1:7890")
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:7890")
        self.assertEqual(env["HTTP_PROXY"], "http://127.0.0.1:7890")


if __name__ == "__main__":
    unittest.main()

    def test_preflight_failure_keeps_armed_without_attempt(self) -> None:
        self.config.proxy = "http://127.0.0.1:7897"
        thread = self._thread()
        with mock.patch.object(runner, "_network_preflight", return_value=(False, "network preflight failed: timed out")):
            outcome = runner.continue_thread(thread, self.config, str(self.fake))
        self.assertFalse(outcome["ok"])
        self.assertTrue(outcome["transient"])
        self.assertEqual(thread.status, cfg.STATUS_ARMED)
        self.assertEqual(thread.attempts, 0)

    def test_transient_send_failure_does_not_consume_attempt(self) -> None:
        thread = self._thread()
        with mock.patch.object(runner, "_send_via_queue", return_value=(False, "queue failed (exit 1): timed out")), \
             mock.patch.object(runner, "_send_via_resume", return_value=(False, "resume failed (exit 1): connection reset")):
            outcome = runner.continue_thread(thread, self.config, str(self.fake))
        self.assertFalse(outcome["ok"])
        self.assertTrue(outcome["transient"])
        self.assertEqual(thread.status, cfg.STATUS_ARMED)
        self.assertEqual(thread.attempts, 0)

    def test_refresh_schedule_moves_ready_threads_to_near_future(self) -> None:
        thread = self._thread()
        thread.status = cfg.STATUS_ARMED
        state = cfg.State(threads={thread.thread_id: thread})
        snapshot = mock.Mock(has_capacity=True)
        scheduler = mock.Mock()
        now = dt.datetime.now(dt.timezone.utc)
        fire = runner.refresh_schedule(state, self.config, snapshot, scheduler, now=now)
        self.assertIsNotNone(fire)
        self.assertLess(abs((fire - now).total_seconds() - 15), 2)
        self.assertEqual(thread.fire_at, cfg.iso(fire))
        scheduler.install_interval.assert_called_once()

    def test_transient_classifier(self) -> None:
        self.assertTrue(runner._is_transient_error("resume failed: connection reset by peer"))
        self.assertTrue(runner._is_transient_error("queue failed: timed out"))
        self.assertFalse(runner._is_transient_error("active writer"))
