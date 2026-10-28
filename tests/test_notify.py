"""Email relay notifications (Cloudflare Worker route)."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from codex_auto_continue import notify
from codex_auto_continue.config import Config


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class EmailNotifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.secret_path = self.root / "secret"
        self.secret_path.write_text("s" * 40, encoding="utf-8")
        self.secret_path.chmod(0o600)
        self.config = Config(
            notify_local=False,
            notify_email=True,
            email_endpoint="https://notify.example.invalid/auto-continue",
            email_secret_file=str(self.secret_path),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _patch_opener(self, response: _Response | Exception):
        opener = mock.Mock()
        if isinstance(response, Exception):
            opener.open.side_effect = response
        else:
            opener.open.return_value = response
        return mock.patch.object(notify.urllib.request, "build_opener", return_value=opener), opener

    def test_posts_authenticated_payload(self) -> None:
        patcher, opener = self._patch_opener(_Response())
        with patcher:
            self.assertTrue(notify.email_notify(self.config, "thread-result", "续跑成功", "thread 01a1 ok"))
        request = opener.open.call_args[0][0]
        self.assertEqual(request.get_header("Authorization"), "Bearer " + "s" * 40)
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["event"], "thread-result")
        self.assertEqual(payload["title"], "续跑成功")
        self.assertIn("thread 01a1", payload["body"])
        self.assertRegex(payload["event_id"], r"^[a-f0-9]{64}$")

    def test_rejects_http_and_query(self) -> None:
        bad = Config(notify_email=True, email_endpoint="http://notify.example.invalid/auto-continue", email_secret_file=str(self.secret_path))
        self.assertFalse(notify.email_notify(bad, "test", "t", "b"))
        query = Config(notify_email=True, email_endpoint="https://notify.example.invalid/auto-continue?x=1", email_secret_file=str(self.secret_path))
        self.assertFalse(notify.email_notify(query, "test", "t", "b"))

    def test_requires_secret(self) -> None:
        missing = Config(notify_email=True, email_endpoint=self.config.email_endpoint)
        self.assertFalse(notify.email_notify(missing, "test", "t", "b"))

    @unittest.skipIf(os.name == "nt", "POSIX permissions only")
    def test_rejects_group_readable_secret(self) -> None:
        self.secret_path.chmod(0o644)
        self.assertFalse(notify.email_notify(self.config, "test", "t", "b"))

    def test_failure_is_swallowed(self) -> None:
        patcher, _ = self._patch_opener(urllib.error.URLError("down"))
        with patcher:
            self.assertFalse(notify.email_notify(self.config, "test", "t", "b"))

    def test_notify_prefers_email_endpoint(self) -> None:
        with mock.patch.object(notify, "local_notify") as local, \
             mock.patch.object(notify, "email_notify", return_value=True) as email, \
             mock.patch.object(notify, "webhook_notify") as webhook:
            notify.notify(self.config, "title", "body", "summary")
        local.assert_not_called()
        email.assert_called_once_with(self.config, "summary", "title", "body")
        webhook.assert_not_called()

    def test_notify_falls_back_to_webhook(self) -> None:
        config = Config(notify_local=False, notify_email=True, webhook_url="https://example.invalid/hook")
        with mock.patch.object(notify, "email_notify") as email, \
             mock.patch.object(notify, "webhook_notify", return_value=True) as webhook:
            notify.notify(config, "title", "body", "summary")
        email.assert_not_called()
        webhook.assert_called_once()

    def test_config_roundtrip_keeps_email_fields(self) -> None:
        raw = self.config.to_dict()
        loaded = Config.from_dict(raw)
        self.assertEqual(loaded.email_endpoint, self.config.email_endpoint)
        self.assertEqual(loaded.email_secret_file, str(self.secret_path))


if __name__ == "__main__":
    unittest.main()
