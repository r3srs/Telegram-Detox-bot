from __future__ import annotations

from datetime import timedelta

import pytest

from tg_detox_locker.duration import parse_duration
from tg_detox_locker.errors import ValidationError


def test_parse_duration_accepts_compound_values() -> None:
    assert parse_duration("1d12h") == timedelta(days=1, hours=12)


def test_parse_duration_rejects_too_short_values() -> None:
    with pytest.raises(ValidationError):
        parse_duration("4m")


def test_parse_duration_rejects_bad_format() -> None:
    with pytest.raises(ValidationError):
        parse_duration("two hours")
