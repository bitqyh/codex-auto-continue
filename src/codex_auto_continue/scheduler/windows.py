"""Windows Task Scheduler adapter (roadmap; not used by the macOS-first MVP)."""

from __future__ import annotations

import datetime as dt

from .base import Scheduler, SchedulerError


class WindowsScheduler(Scheduler):
    name = "task-scheduler"

    def install_calendar(self, run_at: dt.datetime, argv: list[str], env: dict[str, str], workdir: str | None) -> None:
        raise SchedulerError(
            "Windows Task Scheduler adapter is not implemented in v0.1. Run `codex-continue run` from Task Scheduler manually until it lands."
        )

    def install_interval(self, seconds: int, argv: list[str], env: dict[str, str], workdir: str | None) -> None:
        raise SchedulerError(
            "Windows Task Scheduler adapter is not implemented in v0.1. Run `codex-continue run` from Task Scheduler manually until it lands."
        )

    def remove(self) -> None:
        return None

    def describe(self) -> str:
        return "task-scheduler: not implemented"
