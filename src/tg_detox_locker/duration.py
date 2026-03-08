from __future__ import annotations

import re
from datetime import timedelta

from tg_detox_locker.errors import ValidationError

_PART_RE = re.compile(r"(?P<value>\d+)(?P<unit>[smhd])", re.IGNORECASE)
_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
}
_MIN_DURATION = timedelta(minutes=5)
_MAX_DURATION = timedelta(days=30)


def parse_duration(value: str) -> timedelta:
    text = value.strip().lower()
    if not text:
        raise ValidationError("Duration must not be empty.")
    index = 0
    total_seconds = 0
    for match in _PART_RE.finditer(text):
        if match.start() != index:
            raise ValidationError("Duration format is invalid. Use values like 30m, 4h, or 1d12h.")
        index = match.end()
        total_seconds += int(match.group("value")) * _UNIT_SECONDS[match.group("unit")]
    if index != len(text):
        raise ValidationError("Duration format is invalid. Use values like 30m, 4h, or 1d12h.")
    duration = timedelta(seconds=total_seconds)
    if duration < _MIN_DURATION or duration > _MAX_DURATION:
        raise ValidationError("Duration must be between 5 minutes and 30 days.")
    return duration


def format_duration(duration: timedelta) -> str:
    total_seconds = int(duration.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds and not parts:
        parts.append(f"{seconds}s")
    return "".join(parts) or "0s"
