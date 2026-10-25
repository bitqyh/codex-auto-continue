"""Scan Codex rollout files to find sessions interrupted by usage limits."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import paths, threads

USAGE_LIMIT_PATTERN = re.compile(
    r"usage limit|rate[\s_-]?limit|too many requests|hit your limit",
    re.IGNORECASE,
)
RESET_HINT_PATTERN = re.compile(
    r"try again at\s+([A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,\s*\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM))",
    re.IGNORECASE,
)


@dataclass
class RolloutInfo:
    thread_id: str
    path: Path
    cwd: str
    lines: int
    mtime: float
    last_timestamp: str | None = None
    interrupted: bool = False
    error_message: str | None = None
    reset_hint: str | None = None
    last_user_text: str | None = None
    last_assistant_text: str | None = None
    is_subagent: bool = False
    title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "path": str(self.path),
            "cwd": self.cwd,
            "lines": self.lines,
            "mtime": self.mtime,
            "last_timestamp": self.last_timestamp,
            "interrupted": self.interrupted,
            "error_message": self.error_message,
            "reset_hint": self.reset_hint,
            "last_user_text": self.last_user_text,
            "last_assistant_text": self.last_assistant_text,
            "is_subagent": self.is_subagent,
            "title": self.title,
        }


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def _parse_reset_hint(message: str) -> str | None:
    match = RESET_HINT_PATTERN.search(message)
    if not match:
        return None
    raw = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", match.group(1))
    raw = re.sub(r"\s+", " ", raw.strip())
    for fmt in ("%b %d, %Y %I:%M %p", "%B %d, %Y %I:%M %p"):
        try:
            parsed = dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
            return parsed.isoformat()
        except ValueError:
            continue
    return None


def _iter_records(handle: Iterable[str]) -> Iterable[dict[str, Any]]:
    for line in handle:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            yield record


def parse_rollout(path: Path) -> RolloutInfo:
    """Parse one rollout file, streaming over its records."""
    session_meta: dict[str, Any] = {}
    cwd = ""
    subagent = False
    lines = 0
    last_ts: str | None = None
    last_error: str | None = None
    error_ordinal = -1
    last_user_text: str | None = None
    last_assistant_text: str | None = None
    user_after_error = False
    ordinal = -1

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for record in _iter_records(handle):
            lines += 1
            ordinal = record.get("ordinal", ordinal + 1)
            ts = record.get("timestamp")
            if isinstance(ts, str):
                last_ts = ts
            kind = record.get("type")
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue

            if kind == "session_meta":
                session_meta = payload
                cwd = str(payload.get("cwd") or "")
                if payload.get("parent_thread_id") or payload.get("source") and isinstance(payload.get("source"), dict) and payload["source"].get("subagent"):
                    subagent = True
            elif kind == "turn_context":
                turn_cwd = payload.get("cwd")
                if isinstance(turn_cwd, str) and turn_cwd:
                    cwd = turn_cwd
            elif kind == "response_item":
                if payload.get("type") == "message":
                    role = payload.get("role")
                    text = _text_of(payload.get("content"))
                    if role == "user" and text:
                        last_user_text = text
                        if ordinal > error_ordinal:
                            user_after_error = True
                    elif role == "assistant" and text:
                        last_assistant_text = text
            elif kind == "event_msg" and payload.get("type") == "task_complete":
                error = payload.get("error")
                message = None
                if isinstance(error, dict):
                    message = error.get("message")
                elif isinstance(error, str):
                    message = error
                if isinstance(message, str) and message.strip():
                    last_error = message.strip()
                    error_ordinal = ordinal
                    user_after_error = False

    thread_id = str(session_meta.get("session_id") or session_meta.get("id") or path.stem)
    interrupted = bool(last_error and USAGE_LIMIT_PATTERN.search(last_error) and not user_after_error)
    reset_hint = _parse_reset_hint(last_error) if last_error else None
    return RolloutInfo(
        thread_id=thread_id,
        path=path,
        cwd=cwd,
        lines=lines,
        mtime=path.stat().st_mtime,
        last_timestamp=last_ts,
        interrupted=interrupted,
        error_message=last_error,
        reset_hint=reset_hint,
        last_user_text=last_user_text,
        last_assistant_text=last_assistant_text,
        is_subagent=subagent,
    )


def iter_rollouts(days: int = 7, include_subagents: bool = False) -> list[Path]:
    root = paths.sessions_dir()
    if not root.exists():
        return []
    cutoff = dt.datetime.now().timestamp() - days * 86400
    found: list[Path] = []
    for path in root.rglob("rollout-*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        found.append(path)
    return found


def scan(days: int = 7, include_subagents: bool = False) -> list[RolloutInfo]:
    infos: list[RolloutInfo] = []
    for path in iter_rollouts(days=days, include_subagents=include_subagents):
        try:
            info = parse_rollout(path)
        except OSError:
            continue
        if info.is_subagent and not include_subagents:
            continue
        infos.append(info)
    infos.sort(key=lambda item: item.mtime, reverse=True)
    if not include_subagents:
        # Codex writes a fresh rollout file per continuation of the same thread
        # (``<thread-id>_<turn-id>.jsonl``). Keep only the newest one per thread
        # so menus/armers do not act on a stale file whose tail already moved on.
        newest: dict[str, RolloutInfo] = {}
        for info in infos:
            newest.setdefault(info.thread_id, info)
        infos = list(newest.values())
    titles = threads.load_thread_titles([info.thread_id for info in infos])
    for info in infos:
        info.title = titles.get(info.thread_id)
    return infos


def interrupted(days: int = 7, include_subagents: bool = False) -> list[RolloutInfo]:
    return [info for info in scan(days=days, include_subagents=include_subagents) if info.interrupted]


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def find_rollout(thread_id: str) -> Path | None:
    """Resolve a thread id to its most recent rollout file.

    Codex appends continuations as a separate file named
    ``<thread-id>_<turn-id>.jsonl``, so a plain ``*<thread-id>.jsonl`` glob
    silently returns the *original* (stale) rollout. Match any rollout whose
    name contains the id and prefer the newest by mtime.
    """
    root = paths.sessions_dir()
    if not root.exists():
        return None
    candidates = [p for p in root.rglob("rollout-*.jsonl") if thread_id in p.name]
    if not candidates:
        return None
    return max(candidates, key=_mtime)


def line_count(path: Path) -> int:
    try:
        with open(path, "rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0
