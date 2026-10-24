"""Tests for message resolution and editing."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from codex_auto_continue import config as cfg, messages


class MessageResolutionTests(unittest.TestCase):
    def test_explicit_message_wins(self) -> None:
        config = cfg.Config(message_template="默认", project_templates={"/tmp/proj": "项目模板"})
        self.assertEqual(messages.resolve_message(config, "/tmp/proj", "手写"), "手写")

    def test_longest_project_prefix_wins(self) -> None:
        config = cfg.Config(
            message_template="默认",
            project_templates={"/tmp": "外层", "/tmp/proj": "内层"},
        )
        self.assertEqual(messages.resolve_message(config, "/tmp/proj/work"), "内层")
        self.assertEqual(messages.resolve_message(config, "/tmp/other"), "外层")

    def test_falls_back_to_global_template(self) -> None:
        config = cfg.Config(message_template="默认消息")
        self.assertEqual(messages.resolve_message(config, "/elsewhere"), "默认消息")

    def test_thread_id_placeholder(self) -> None:
        config = cfg.Config(message_template="继续 {thread_id}")
        self.assertEqual(messages.resolve_message(config, None, thread_id="abc"), "继续 abc")

    def test_edit_message_uses_editor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            editor = Path(tmp) / "fake_editor.sh"
            editor.write_text('#!/bin/sh\nprintf "edited text\\n" > "$1"\n', encoding="utf-8")
            editor.chmod(editor.stat().st_mode | stat.S_IEXEC)
            old = os.environ.get("EDITOR")
            os.environ["EDITOR"] = str(editor)
            try:
                self.assertEqual(messages.edit_message("原始"), "edited text")
            finally:
                if old is None:
                    os.environ.pop("EDITOR", None)
                else:
                    os.environ["EDITOR"] = old

    def test_edit_message_without_editor_returns_none(self) -> None:
        old_visual, old_editor = os.environ.pop("VISUAL", None), os.environ.pop("EDITOR", None)
        try:
            self.assertIsNone(messages.edit_message("原始"))
        finally:
            if old_visual is not None:
                os.environ["VISUAL"] = old_visual
            if old_editor is not None:
                os.environ["EDITOR"] = old_editor


if __name__ == "__main__":
    unittest.main()
