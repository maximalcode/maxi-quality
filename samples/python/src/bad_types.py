# Intentionally-bad TYPES. `mypy` MUST fail here — that IS the test.
#
# Split from bad.py on purpose: ruff and mypy find genuinely different classes
# of bug, and keeping the fixtures separate stops a change to one tool's config
# from being masked by the other's findings.
#
# Nothing here is a lint error. Run ruff over this file and it passes clean —
# which is exactly the point. Without mypy, every bug below ships.


def add(a: int, b: int) -> int:
    return a + b


def untyped(x):  # disallow_untyped_defs — no annotations at all
    return x * 2


def wrong_return(name: str) -> int:
    # Returning str where int is declared.
    return name


def bad_call() -> int:
    # Passing str to a parameter typed int.
    return add("1", 2)


def optional_misuse(name: str | None) -> int:
    # `name` may be None here — no narrowing before use.
    return len(name)


def unreachable(flag: bool) -> str:
    if flag:
        return "yes"
    return "no"
    # warn_unreachable — nothing can ever run this.
    return "never"
