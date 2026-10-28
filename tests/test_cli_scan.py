"""scan --json exposes the latest six threads for the menu bar."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from codex_auto_continue import cli


def _info(index: int, interrupted: bool = False):
    return SimpleNamespace(
        thread_id=f"t{index}",
        interrupted=interrupted,
        to_dict=lambda: {"thread_id": f"t{index}", "interrupted": interrupted, "mtime": float(index)},
    )


class ScanJsonTests(unittest.TestCase):
    def test_recent_contains_latest_six(self) -> None:
        infos = [_info(i, interrupted=(i == 0)) for i in range(10)]
        args = SimpleNamespace(days=7, include_subagents=False, json=True)
        out = io.StringIO()
        with mock.patch.object(cli.rollouts, "scan", return_value=infos), redirect_stdout(out):
            self.assertEqual(cli.cmd_scan(args), 0)
        payload = json.loads(out.getvalue())
        self.assertEqual([item["thread_id"] for item in payload["recent"]], [f"t{i}" for i in range(6)])
        self.assertEqual([item["thread_id"] for item in payload["interrupted"]], ["t0"])


if __name__ == "__main__":
    unittest.main()
