from __future__ import annotations

from tg_detox_locker.enums import LockerState

_ALLOWED_TRANSITIONS: dict[LockerState, set[LockerState]] = {
    LockerState.IDLE: {LockerState.ARMING},
    LockerState.ARMING: {LockerState.RUNNING, LockerState.START_FAILED},
    LockerState.RUNNING: {LockerState.ENDING, LockerState.DEGRADED_LOCKED, LockerState.RESTORE_FAILED_LOCKED},
    LockerState.DEGRADED_LOCKED: {LockerState.RUNNING, LockerState.ENDING, LockerState.RESTORE_FAILED_LOCKED},
    LockerState.ENDING: {LockerState.COMPLETED, LockerState.RESTORE_FAILED_LOCKED},
    LockerState.RESTORE_FAILED_LOCKED: {LockerState.COMPLETED},
    LockerState.START_FAILED: {LockerState.IDLE},
    LockerState.COMPLETED: {LockerState.IDLE},
}


class DetoxStateMachine:
    def __init__(self, current: LockerState = LockerState.IDLE) -> None:
        self.current = current

    def transition(self, next_state: LockerState) -> LockerState:
        if next_state not in _ALLOWED_TRANSITIONS[self.current]:
            raise ValueError(f"Invalid transition: {self.current.value} -> {next_state.value}")
        self.current = next_state
        return self.current
