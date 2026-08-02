"""Deliberately CLEAN Python — the other half of the claim.

A gate that flags everything is as useless as one that flags nothing. This
fixture proves the baseline is survivable: idiomatic, fully-typed, modern
Python that a real project would actually write, passing ruff AND mypy strict
with zero findings.

If this file ever starts failing, the baseline became over-strict. Fix
configs/python/, do NOT add `# noqa` or `# type: ignore` here — a fixture that
needs suppressions to pass has stopped proving anything.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class User:
    """A user with a stable identity."""

    name: str
    tags: frozenset[str] = field(default_factory=frozenset)

    def labelled(self, prefix: str) -> str:
        """Return the name behind a prefix."""
        return f"{prefix}:{self.name}"


def first_name(users: Iterable[User], fallback: str = "none") -> str:
    """Return the first user's name, or the fallback when there are none."""
    return next((user.name for user in users), fallback)


def unique_tags(users: Iterable[User]) -> set[str]:
    """Collect every tag across the given users."""
    return {tag for user in users for tag in user.tags}


async def resolve(name: str) -> User:
    """Look a user up, asynchronously."""
    await asyncio.sleep(0)
    return User(name=name)


async def resolve_all(names: Iterable[str]) -> list[User]:
    """Resolve every name concurrently.

    Uses a gather rather than bare create_task so the tasks are referenced for
    their whole lifetime — the RUF006 failure mode the bad fixture plants.
    """
    return await asyncio.gather(*(resolve(name) for name in names))
