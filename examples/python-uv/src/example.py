"""A minimal, clean module."""

from datetime import datetime


def is_expired(at: datetime, now: datetime) -> bool:
    """Compare against an injected clock rather than an ambient one."""
    return at <= now
