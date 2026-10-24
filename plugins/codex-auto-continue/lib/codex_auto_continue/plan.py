"""Decide when armed continuations should run."""

from __future__ import annotations

import datetime as dt

from .config import ArmedThread, Config, parse_iso
from .usage import QuotaSnapshot


def aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.astimezone()
    return value


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    return aware(value)


def next_reset_moment(snapshot: QuotaSnapshot | None, threads: list[ArmedThread]) -> dt.datetime | None:
    """The moment the account can be used again.

    Prefers the live quota snapshot (needs every exhausted window to roll over);
    falls back to reset hints embedded in the interrupted sessions' errors.
    """
    if snapshot is not None:
        if snapshot.has_capacity:
            return dt.datetime.now(dt.timezone.utc)
        moment = _aware(snapshot.next_reset())
        if moment is not None:
            return moment
    hints = []
    for thread in threads:
        hint = _aware(parse_iso(thread.reset_hint))
        if hint is not None:
            hints.append(hint)
    if hints:
        return max(hints)
    return None


def compute_fire_at(
    threads: list[ArmedThread],
    snapshot: QuotaSnapshot | None,
    config: Config,
    now: dt.datetime | None = None,
) -> dt.datetime:
    """When the scheduler should wake up (UTC-aware).

    - quota available now -> fire immediately (small delay so arming can finish)
    - exhausted -> earliest safe moment = latest exhausted window reset + grace
    - unknown -> periodic probe
    """
    now = _aware(now) or dt.datetime.now(dt.timezone.utc)
    if snapshot is not None and snapshot.has_capacity:
        return now + dt.timedelta(seconds=15)
    moment = next_reset_moment(snapshot, threads)
    if moment is None:
        return now + dt.timedelta(seconds=max(config.retry_seconds, 60))
    fire_at = moment + dt.timedelta(seconds=max(config.grace_seconds, 0))
    if fire_at <= now:
        return now + dt.timedelta(seconds=15)
    return fire_at


def is_due(thread: ArmedThread, now: dt.datetime | None = None, tolerance_seconds: int = 90) -> bool:
    if not thread.is_pending:
        return False
    fire_at = _aware(parse_iso(thread.fire_at))
    if fire_at is None:
        return True
    now = _aware(now) or dt.datetime.now(dt.timezone.utc)
    return fire_at <= now + dt.timedelta(seconds=tolerance_seconds)


def describe_quota(snapshot: QuotaSnapshot | None, now: dt.datetime | None = None) -> str:
    if snapshot is None:
        return "quota: unknown (app server and CodexBar cache unavailable)"
    now = _aware(now) or dt.datetime.now(dt.timezone.utc)
    parts = []
    for window in snapshot.windows:
        reset_in = ""
        if window.resets_at:
            seconds = (window.resets_at - now).total_seconds()
            if seconds <= 0:
                reset_in = ", reset passed"
            else:
                reset_in = f", resets in {int(seconds // 60)}m"
        marker = " (exhausted)" if window.exhausted else ""
        parts.append(
            f"{window.kind} {window.window_minutes}m used={window.used_percent:g}%{marker}{reset_in}"
        )
    return f"quota[{snapshot.source}]: " + "; ".join(parts)


def format_local(value: dt.datetime | None) -> str:
    if value is None:
        return "unknown"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
