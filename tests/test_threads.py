"""Tests for Codex session-name resolution from the state database."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_auto_continue import paths, rollouts, threads


def _make_db(root: Path, rows: list[tuple[str, str, str, str]]) -> Path:
    db = root / "state_5.sqlite"
    connection = sqlite3.connect(db)
    connection.execute(
        "CREATE TABLE threads (id TEXT PRIMARY KEY, name TEXT, title TEXT, cwd TEXT)"
    )
    connection.executemany("INSERT INTO threads (id, name, title, cwd) VALUES (?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()
    return db


class ThreadTitleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patch = mock.patch.object(paths, "codex_home", return_value=self.root)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def test_prefers_user_visible_name(self) -> None:
        _make_db(self.root, [("t1", "构建 PROJECT ALIBI 原型", "long raw title", "/tmp/a")])
        titles = threads.load_thread_titles(["t1"])
        self.assertEqual(titles["t1"], "构建 PROJECT ALIBI 原型")

    def test_falls_back_to_title_then_cwd(self) -> None:
        _make_db(
            self.root,
            [
                ("t1", "", "来自首条消息的标题", "/tmp/a"),
                ("t2", "", "", "/tmp/project-dir"),
            ],
        )
        titles = threads.load_thread_titles(["t1", "t2"])
        self.assertEqual(titles["t1"], "来自首条消息的标题")
        self.assertEqual(titles["t2"], "project-dir")

    def test_missing_database_returns_empty(self) -> None:
        self.assertEqual(threads.load_thread_titles(["nope"]), {})

    def test_scan_attaches_titles(self) -> None:
        sessions = self.root / "sessions"
        sessions.mkdir()
        rollout = sessions / "rollout-x-thread-1.jsonl"
        records = [
            {"timestamp": "2026-10-23T12:00:00Z", "ordinal": 0, "type": "session_meta",
             "payload": {"id": "thread-1", "session_id": "thread-1", "cwd": "/tmp/x"}},
            {"timestamp": "2026-10-23T12:05:00Z", "ordinal": 1, "type": "event_msg",
             "payload": {"type": "task_complete", "error": {"message": "You've hit your usage limit."}}},
        ]
        rollout.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
        _make_db(self.root, [("thread-1", "菜单里要显示的名字", "", "/tmp/x")])
        with mock.patch.object(paths, "sessions_dir", return_value=sessions):
            infos = rollouts.scan(days=7)
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0].title, "菜单里要显示的名字")


if __name__ == "__main__":
    unittest.main()
