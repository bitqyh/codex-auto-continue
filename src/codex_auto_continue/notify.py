"""Notifications: local OS notifications by default, optional webhook hook."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import Config, append_log


def _run(command: list[str], timeout: float = 10.0) -> bool:
    try:
        result = subprocess.run(command, timeout=timeout, capture_output=True, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def local_notify(title: str, body: str) -> bool:
    """Best-effort desktop notification on macOS, Windows and Linux."""
    if sys.platform == "darwin":
        script = (
            'display notification ' + _applescript_string(body) + ' with title ' + _applescript_string(title)
        )
        if _run(["osascript", "-e", script]):
            return True
        notifier = shutil.which("terminal-notifier")
        if notifier:
            return _run([notifier, "-title", title, "-message", body])
        return False
    if os.name == "nt":
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            "$text = $template.GetElementsByTagName('text');"
            f"$text.Item(0).AppendChild($template.CreateTextNode({_powershell_string(title)})) > $null;"
            f"$text.Item(1).AppendChild($template.CreateTextNode({_powershell_string(body)})) > $null;"
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($template);"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('codex-auto-continue').Show($toast);"
        )
        return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    notifier = shutil.which("notify-send")
    if notifier:
        return _run([notifier, title, body])
    return False


def _applescript_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _powershell_string(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _email_endpoint(config: Config) -> str | None:
    return os.environ.get("CODEX_AUTO_CONTINUE_EMAIL_ENDPOINT") or getattr(config, "email_endpoint", None)


def _email_secret(config: Config) -> str | None:
    direct = os.environ.get("CODEX_AUTO_CONTINUE_EMAIL_SECRET")
    if direct:
        return direct if len(direct) >= 32 else None
    path = os.environ.get("CODEX_AUTO_CONTINUE_EMAIL_SECRET_FILE") or getattr(config, "email_secret_file", None)
    if not path:
        return None
    try:
        path = os.path.expanduser(path)
        if os.name != "nt" and os.stat(path).st_mode & 0o077:
            return None
        with open(path, encoding="utf-8") as handle:
            secret = handle.read().strip()
    except OSError:
        return None
    return secret if len(secret) >= 32 else None


def email_notify(config: Config, event: str, title: str, body: str) -> bool:
    """POST a notification to the email relay (Cloudflare Worker in this setup)."""
    endpoint = _email_endpoint(config)
    secret = _email_secret(config)
    if not endpoint or not secret:
        return False
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        return False

    event_id = hashlib.sha256(
        f"{event}\0{title}\0{body}\0{time.time_ns()}".encode("utf-8")
    ).hexdigest()
    data = json.dumps(
        {
            "event_id": event_id,
            "event": event,
            "title": title[:200],
            "body": body[:4000],
            "observed_at": int(time.time()),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + secret,
            "User-Agent": "codex-auto-continue/0.6.0",
        },
        method="POST",
    )

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # noqa: ANN002,ANN003
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler(), _NoRedirect())
    try:
        with opener.open(request, timeout=10) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def webhook_notify(config: Config, event: str, payload: dict[str, Any]) -> bool:
    """Optional generic webhook (mail relay, ntfy, Slack, ...). Disabled by default."""
    url = os.environ.get("CODEX_AUTO_CONTINUE_WEBHOOK") or getattr(config, "webhook_url", None)
    if not url:
        return False
    data = json.dumps({"event": event, **payload}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "codex-auto-continue/0.1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return 200 <= response.status < 300
    except Exception:  # noqa: BLE001 - notifications must never break the runner
        return False


def notify(config: Config, title: str, body: str, event: str, payload: dict[str, Any] | None = None) -> None:
    if config.notify_local:
        local_notify(title, body)
    if config.notify_email:
        if _email_endpoint(config):
            if not email_notify(config, event, title, body):
                try:
                    append_log(f"email notification failed (event={event}); check email_endpoint/email_secret_file")
                except OSError:
                    pass
        elif getattr(config, "webhook_url", None):
            webhook_notify(config, event, payload or {"title": title, "body": body})
        else:
            try:
                append_log("notify_email enabled but neither email_endpoint nor webhook_url is configured")
            except OSError:
                pass
