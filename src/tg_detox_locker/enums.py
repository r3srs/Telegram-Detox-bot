from __future__ import annotations

from enum import Enum


class LockerState(str, Enum):
    IDLE = "idle"
    ARMING = "arming"
    RUNNING = "running"
    ENDING = "ending"
    COMPLETED = "completed"
    START_FAILED = "start_failed"
    DEGRADED_LOCKED = "degraded_locked"
    RESTORE_FAILED_LOCKED = "restore_failed_locked"


class PendingCommand(str, Enum):
    START_DETOX = "start_detox"
