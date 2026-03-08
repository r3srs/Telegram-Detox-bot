from __future__ import annotations


class DetoxError(Exception):
    """Base application error."""


class ConfigurationError(DetoxError):
    """Raised when onboarding or configuration is missing."""


class ForbiddenError(DetoxError):
    """Raised when a chat is not allowed to use admin commands."""


class StateConflictError(DetoxError):
    """Raised when a requested action conflicts with the current locker state."""


class ValidationError(DetoxError):
    """Raised for invalid command input."""


class PreflightError(DetoxError):
    """Raised when Telegram start constraints are not satisfied."""
