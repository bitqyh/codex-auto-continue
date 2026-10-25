"""Tests for rollout parsing (usage-limit interruption detection)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from codex_auto_continue import rollouts


def _record(kind: str, payload: dict, ordinal: int, ts: str = "2026-10-23T12:00:00Z") -> str:
    return json.dumps({"timestamp": ts, "ordinal": ordinal, "type": kind, "payload": payload}, ensure_ascii=False)


def _user(text: str, ordinal: int) -> str:
    return _record(
        "response_item",
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]},
        ordinal,
    )


def _task_complete(error: str | None, ordinal: int) -> str:
    payload: dict = {"type": "task_complete", "turn_id": "t1"}
    if error is not None:
        payload["error"] = {"message": error}
    return _record("event_msg", payload, ordinal)


class RolloutParsingTests(unittest.TestCase):
    def _write(self, directory: str, records: list[str], name: str = "rollout-test.jsonl") -> Path:
        path = Path(directory) / name
        path.write_text("\n".join(records) + "\n", encoding="utf-8")
        return path

    def test_detects_usage_limit_interruption_and_reset_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = _record(
                "session_meta",
                {"id": "abc", "session_id": "abc", "cwd": "/tmp/project"},
                0,
            )
            path = self._write(
                tmp,
                [
                    meta,
                    _user("继续做余额校验", 1),
                    _task_complete(
                        "You’ve hit your usage limit. Upgrade to Pro or try again at Oct 24th, 2026 12:15 AM.",
                        2,
                    ),
                ],
            )
            info = rollouts.parse_rollout(path)
        self.assertTrue(info.interrupted)
        self.assertEqual(info.thread_id, "abc")
        self.assertEqual(info.cwd, "/tmp/project")
        self.assertIsNotNone(info.reset_hint)
        self.assertIn("2026-10-24T00:15", info.reset_hint)

    def test_user_message_after_error_means_not_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    _record("session_meta", {"id": "abc", "cwd": "/tmp/p"}, 0),
                    _task_complete("You’ve hit your usage limit.", 1),
                    _user("我回来了，继续", 2),
                ],
            )
            info = rollouts.parse_rollout(path)
        self.assertFalse(info.interrupted)
        self.assertEqual(info.last_user_text, "我回来了，继续")

    def test_non_usage_error_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    _record("session_meta", {"id": "abc", "cwd": "/tmp/p"}, 0),
                    _task_complete("context window exceeded", 1),
                ],
            )
            info = rollouts.parse_rollout(path)
        self.assertFalse(info.interrupted)
        self.assertIsNone(info.reset_hint)

    def test_subagent_sessions_are_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = _record(
                "session_meta",
                {"id": "child", "cwd": "/tmp/p", "parent_thread_id": "parent", "source": {"subagent": {}}},
                0,
            )
            path = self._write(tmp, [meta, _task_complete("usage limit reached", 1)])
            info = rollouts.parse_rollout(path)
        self.assertTrue(info.is_subagent)


if __name__ == "__main__":
    unittest.main()


class RolloutLookupTests(unittest.TestCase):
    def _sessions(self, tmp: str) -> Path:
        root = Path(tmp) / "sessions"
        root.mkdir()
        return root

    def _write_rollout(self, root: Path, name: str, thread_id: str, mtime: float,
                       records: list[str] | None = None) -> Path:
        path = root / name
        meta = _record("session_meta", {"id": thread_id, "session_id": thread_id, "cwd": "/tmp/p"}, 0)
        body = records or [meta, _user("hi", 1), _task_complete("You've hit your usage limit.", 2)]
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        os.utime(path, (mtime, mtime))
        return path

    def test_find_rollout_prefers_newest_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._sessions(tmp)
            tid = "aaaa1111-2222-3333-4444-555566667777"
            old = self._write_rollout(root, f"rollout-2026-10-01T10-00-00-{tid}.jsonl", tid, 1_700_000_000)
            new = self._write_rollout(root, f"rollout-2026-10-02T10-00-00-{tid}_deadbeef.jsonl", tid, 1_700_100_000)
            with mock.patch.object(rollouts.paths, "sessions_dir", return_value=root):
                found = rollouts.find_rollout(tid)
            self.assertEqual(found, new)
            self.assertNotEqual(found, old)

    def test_scan_keeps_newest_rollout_per_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._sessions(tmp)
            tid = "bbbb1111-2222-3333-4444-555566667777"
            self._write_rollout(root, f"rollout-2026-10-01T10-00-00-{tid}.jsonl", tid, 1_700_000_000)
            self._write_rollout(root, f"rollout-2026-10-02T10-00-00-{tid}_cafebabe.jsonl", tid, 1_700_100_000)
            with mock.patch.object(rollouts.paths, "sessions_dir", return_value=root), \
                    mock.patch.object(rollouts.threads, "load_thread_titles", return_value={}):
                infos = rollouts.scan(days=3650)
            self.assertEqual(len(infos), 1)
            self.assertTrue(infos[0].interrupted)
            self.assertIn("_cafebabe", infos[0].path.name)
