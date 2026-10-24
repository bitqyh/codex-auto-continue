"""Tests for fire-time planning."""

from __future__ import annotations

import datetime as dt
import unittest

from codex_auto_continue import config as cfg, plan, usage


def _thread(fire_at: dt.datetime | None = None, reset_hint: dt.datetime | None = None) -> cfg.ArmedThread:
    return cfg.ArmedThread(
        thread_id="t",
        rollout_path="/tmp/rollout.jsonl",
        cwd="/tmp",
        message="继续",
        armed_at=cfg.iso(dt.datetime.now(dt.timezone.utc)),
        fire_at=cfg.iso(fire_at) if fire_at else None,
        reset_hint=cfg.iso(reset_hint) if reset_hint else None,
    )


def _snapshot(primary_used: float, secondary_used: float, reset: dt.datetime) -> usage.QuotaSnapshot:
    return usage.QuotaSnapshot(
        source="test",
        account_email=None,
        windows=[
            usage.QuotaWindow("primary", 300, primary_used, reset),
            usage.QuotaWindow("secondary", 10080, secondary_used, reset + dt.timedelta(days=6)),
        ],
    )


class FireTimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = cfg.Config(grace_seconds=180, retry_seconds=600)
        self.now = dt.datetime.now(dt.timezone.utc)

    def test_exhausted_snapshot_waits_for_reset_plus_grace(self) -> None:
        reset = self.now + dt.timedelta(hours=2)
        snapshot = _snapshot(100, 47, reset)
        fire = plan.compute_fire_at([_thread()], snapshot, self.config, now=self.now)
        self.assertEqual(fire, reset + dt.timedelta(seconds=180))

    def test_available_quota_fires_soon(self) -> None:
        snapshot = _snapshot(40, 20, self.now + dt.timedelta(hours=2))
        fire = plan.compute_fire_at([_thread()], snapshot, self.config, now=self.now)
        self.assertLess(fire - self.now, dt.timedelta(minutes=1))

    def test_unknown_quota_uses_reset_hint(self) -> None:
        hint = self.now + dt.timedelta(hours=1)
        fire = plan.compute_fire_at([_thread(reset_hint=hint)], None, self.config, now=self.now)
        self.assertEqual(fire, hint + dt.timedelta(seconds=180))

    def test_unknown_quota_without_hints_polls(self) -> None:
        fire = plan.compute_fire_at([_thread()], None, self.config, now=self.now)
        self.assertEqual(fire, self.now + dt.timedelta(seconds=600))

    def test_past_reset_fires_soon(self) -> None:
        snapshot = _snapshot(100, 47, self.now - dt.timedelta(hours=1))
        fire = plan.compute_fire_at([_thread()], snapshot, self.config, now=self.now)
        self.assertLess(fire - self.now, dt.timedelta(minutes=1))

    def test_is_due(self) -> None:
        self.assertTrue(plan.is_due(_thread(fire_at=self.now - dt.timedelta(minutes=1)), now=self.now))
        self.assertFalse(plan.is_due(_thread(fire_at=self.now + dt.timedelta(hours=1)), now=self.now))


if __name__ == "__main__":
    unittest.main()
