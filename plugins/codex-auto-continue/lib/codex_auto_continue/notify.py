"""Notifications: local OS notifications by default, optional webhook hook."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from typing import Any

from .config import Config


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
        webhook_notify(config, event, payload or {"title": title, "body": body})
