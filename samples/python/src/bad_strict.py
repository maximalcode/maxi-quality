# Intentionally-bad TYPES, targeting `strict = True` specifically (#8).
#
# WHY THIS FILE IS SEPARATE FROM bad_types.py
#
# `strict` is an ALIAS, not a setting — one line in mypy.ini that expands to
# fourteen booleans in the resolver. Every finding bad_types.py produces comes
# from base type checking or from `warn_unreachable`, which the config sets
# explicitly. Not one of them proves `warn_return_any`, `disallow_any_generics`,
# `strict_equality` or `disallow_untyped_calls` is on. Downgrade `strict` to a
# hand-picked list of the checks bad_types.py happens to exercise and every
# fixture stays green.
#
# configs/python/settings.snapshot.json proves the alias EXPANDS. This file
# proves the expansion does something — the same division of labour as
# samples/typescript-strict and configs/typescript/tsconfig.snapshot.json.
#
# Nothing here is a ruff finding. Run ruff over this file and it passes clean,
# which keeps the two tools' manifests independent.

from typing import Any


def _from_json() -> Any:
    return {"count": 1}


def warn_return_any() -> int:
    # `Any` laundered into a declared `int`. Without warn_return_any this is
    # silent, and every caller downstream believes the annotation.
    return _from_json()


def disallow_any_generics(items: list) -> int:
    # A bare `list` is `list[Any]`. The annotation looks like typing and is not:
    # `items[0].nonexistent_method()` would type-check fine.
    return len(items)


def strict_equality(name: str, count: int) -> bool:
    # Comparing str with int is always False. Not a type error in plain mypy —
    # strict_equality is what makes a comparison that cannot succeed an error,
    # and it is the Python twin of the `eqeqeq` bug samples/typescript baits.
    return name == count


def _untyped_helper(value):  # deliberately unannotated — the point of the fixture
    return value


def disallow_untyped_calls() -> int:
    # Calling an untyped function from typed code. The call site is where the
    # type information dies, and without this check it dies silently.
    return _untyped_helper(1)
