"""Scheduler adapters. macOS (launchd) is implemented first; others follow."""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod


class SchedulerError(RuntimeError):
    pass


class Scheduler(ABC):
    """Platform scheduler abstraction (launchd / systemd / Task Scheduler)."""

    name: str = "none"

    @abstractmethod
    def install_calendar(self, run_at: dt.datetime, argv: list[str], env: dict[str, str], workdir: str | None) -> None:
        """Run once at the given local time."""

    @abstractmethod
    def install_interval(self, seconds: int, argv: list[str], env: dict[str, str], workdir: str | None) -> None:
        """Poll every N seconds until the job removes itself."""

    @abstractmethod
    def remove(self) -> None:
        """Remove any installed job."""

    @abstractmethod
    def describe(self) -> str:
        """Human readable state for `status`."""

    def refresh(self, run_at: dt.datetime | None, interval_seconds: int | None, argv: list[str], env: dict[str, str], workdir: str | None) -> None:
        """Ensure the scheduler shows exactly one job (calendar or interval)."""
        self.remove()
        if run_at is not None:
            self.install_calendar(run_at, argv, env, workdir)
        elif interval_seconds is not None:
            self.install_interval(interval_seconds, argv, env, workdir)


class NullScheduler(Scheduler):
    name = "none"
    state: str = "disabled"

    def install_calendar(self, run_at, argv, env, workdir) -> None:  # noqa: D401, ANN001
        self.state = f"calendar {run_at.isoformat()}"

    def install_interval(self, seconds, argv, env, workdir) -> None:  # noqa: D401, ANN001
        self.state = f"interval {seconds}s"

    def remove(self) -> None:
        self.state = "disabled"

    def describe(self) -> str:
        return self.state


def for_platform() -> Scheduler:
    import os
    import sys

    if os.environ.get("CODEX_AUTO_CONTINUE_DISABLE_SCHED") == "1":
        return NullScheduler()
    if sys.platform == "darwin":
        from .launchd import LaunchdScheduler

        return LaunchdScheduler()
    if sys.platform.startswith("linux"):
        from .systemd import SystemdScheduler

        return SystemdScheduler()
    if os.name == "nt":
        from .windows import WindowsScheduler

        return WindowsScheduler()
    raise SchedulerError(f"unsupported platform: {sys.platform}")
