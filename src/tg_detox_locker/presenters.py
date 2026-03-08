from __future__ import annotations

from datetime import timedelta
from typing import Sequence

from tg_detox_locker.duration import format_duration
from tg_detox_locker.models import DetoxRun, Settings


def format_status(settings: Settings, run: DetoxRun | None) -> str:
    lines = [
        f"state: {settings.current_state.value}",
        f"telegram_ok: {'yes' if settings.telegram_ok else 'no'}",
        f"last_heartbeat_at: {settings.last_heartbeat_at.isoformat() if settings.last_heartbeat_at else 'n/a'}",
    ]
    if run:
        lines.extend(
            [
                f"run_id: {run.id}",
                f"planned_end_at: {run.planned_end_at.isoformat()}",
                f"attempt_count: {run.attempt_count}",
            ]
        )
    return "\n".join(lines)


def format_history(runs: Sequence[DetoxRun]) -> str:
    if not runs:
        return "No detox runs recorded yet."
    lines = []
    for run in runs:
        duration = format_duration(timedelta(seconds=run.requested_duration_seconds))
        lines.append(
            f"{run.created_at.isoformat()} | {run.state.value} | duration={duration} | attempts={run.attempt_count}"
        )
    return "\n".join(lines)


def format_health(settings: Settings) -> str:
    return "\n".join(
        [
            "db_ok: yes",
            f"telegram_ok: {'yes' if settings.telegram_ok else 'no'}",
            f"current_state: {settings.current_state.value}",
            f"last_reconcile_at: {settings.last_reconcile_at.isoformat() if settings.last_reconcile_at else 'n/a'}",
            f"last_update_at: {settings.last_update_at.isoformat() if settings.last_update_at else 'n/a'}",
            f"last_error: {settings.last_error or 'n/a'}",
        ]
    )


def format_completion_report(run: DetoxRun) -> str:
    actual_end = run.actual_end_at.isoformat() if run.actual_end_at else "n/a"
    planned = run.planned_end_at.isoformat()
    duration = format_duration(timedelta(seconds=run.requested_duration_seconds))
    return "\n".join(
        [
            "Detox finished.",
            f"duration: {duration}",
            f"planned_end_at: {planned}",
            f"actual_end_at: {actual_end}",
            f"attempts_blocked: {run.attempt_count}",
            f"end_reason: {run.end_reason or 'completed'}",
        ]
    )
