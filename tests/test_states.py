from __future__ import annotations

import pytest

from tg_detox_locker.enums import LockerState
from tg_detox_locker.states import DetoxStateMachine


def test_state_machine_happy_path() -> None:
    machine = DetoxStateMachine()
    assert machine.transition(LockerState.ARMING) == LockerState.ARMING
    assert machine.transition(LockerState.RUNNING) == LockerState.RUNNING
    assert machine.transition(LockerState.ENDING) == LockerState.ENDING
    assert machine.transition(LockerState.COMPLETED) == LockerState.COMPLETED


def test_state_machine_rejects_invalid_transition() -> None:
    machine = DetoxStateMachine(LockerState.RUNNING)
    with pytest.raises(ValueError):
        machine.transition(LockerState.ARMING)
