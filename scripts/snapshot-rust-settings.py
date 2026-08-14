#!/usr/bin/env python3
"""Snapshot what configs/rust/ RESOLVES TO, and fail when a setting silently
disappears.

The Rust twin of snapshot-eslint-rules.mjs, snapshot-tsconfig.mjs,
snapshot-msbuild-props.sh and snapshot-python-settings.py, for the same
measured reason (#8): the finding manifests pin what the fixtures BAIT, not
what the config ENABLES. samples/rust triggers 8 findings against a config
that turns on `clippy::all` + `clippy::pedantic` — hundreds of lints. Downgrade
`pedantic` to a hand-list of the baited lints and every manifest stays green.
`unsafe_code = "forbid"` versus "deny" is invisible to any fixture (both fail
the build); only the resolved level shows the difference — and forbid-vs-deny
is the whole point of that line, because only forbid resists a stray
`#[allow]`.

THE RESOLVERS, NOT THE TOML:

  - Lints: `cargo clippy -v` prints the clippy-driver argv, and the
    `--warn/--allow/--deny/--forbid` flags in it ARE cargo's resolution of the
    manifest's `[lints]` table — after group expansion order, after
    `priority`, after workspace inheritance. Reading lints.toml would assert
    what we wrote; this asserts what rustc is actually handed. Resolved
    against samples/rust-clean, whose `[lints]` block the drift check in
    ci.yml pins to configs/rust/lints.toml verbatim.
  - rustfmt: `rustfmt --print-config current` — the full resolved
    configuration, defaults included, so a rustfmt bump that changes a default
    we did not state arrives as a visible snapshot diff.
  - cargo-deny: has no resolver dump, so deny.toml is parsed structurally
    (tomllib) and the snapshot pins the keys that carry the posture. Weaker
    than the other two and stated as such; the fixture (RUSTSEC-2021-0003)
    covers the advisories path behaviourally.

FLAG ORDER IS PART OF THE SNAPSHOT. Lint flags apply left to right, so
`--warn=clippy::pedantic ... --allow=clippy::similar_names` and the reverse
are different configs. The list is kept in argv order, not sorted.

A toolchain bump CAN change this snapshot (a group gains a lint, rustfmt adds
an option). Intended, same policy as the other four: the bump PR is where a
human reads the diff. Regenerate with --write and say in the commit message
what moved and why.

Usage:
  scripts/snapshot-rust-settings.py --check    # CI: diff against the snapshot
  scripts/snapshot-rust-settings.py --write    # regenerate it deliberately

Exit codes: 0 snapshot matches · 1 drifted · 3 usage/tool error
"""

from __future__ import annotations

import json
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile

try:
    import tomllib  # 3.11+, what CI runs
except ModuleNotFoundError:  # an older local interpreter: pip install tomli
    import tomli as tomllib  # type: ignore[no-redef]

REPO = pathlib.Path(__file__).resolve().parent.parent
RUSTFMT_CONFIG = REPO / "configs" / "rust" / "rustfmt.toml"
DENY_CONFIG = REPO / "configs" / "rust" / "deny.toml"
TARGET = REPO / "samples" / "rust-clean"
SNAPSHOT = REPO / "configs" / "rust" / "settings.snapshot.json"


def lint_flags() -> list[str]:
    """The resolved lint argv, in application order, as `level=lint` strings."""
    with tempfile.TemporaryDirectory() as tmp:
        # A cached build prints no rustc invocation at all, and a snapshot
        # resolved from nothing would assert nothing. A throwaway target dir
        # forces the compile and keeps the repo's fixtures byte-identical.
        out = subprocess.run(
            ["cargo", "clippy", "--locked", "-v"],
            cwd=TARGET,
            env={**__import__("os").environ, "CARGO_TARGET_DIR": tmp},
            capture_output=True,
            text=True,
        )
    flags: list[str] = []
    for line in (out.stdout + out.stderr).splitlines():
        if "clippy-driver" not in line and "rustc" not in line:
            continue
        for tok in shlex.split(line.strip().removeprefix("Running `").removesuffix("`")):
            m = re.fullmatch(r"--(warn|allow|deny|forbid)=([A-Za-z0-9_:]+)", tok)
            if m:
                flags.append(f"{m.group(1)}={m.group(2)}")
        if flags:
            return flags
    return flags


def rustfmt_settings() -> dict[str, str]:
    out = subprocess.run(
        [
            "rustfmt",
            "--config-path",
            str(RUSTFMT_CONFIG),
            "--print-config",
            "current",
            str(TARGET / "src" / "main.rs"),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    settings = {}
    for line in out.splitlines():
        if " = " in line:
            key, _, value = line.partition(" = ")
            settings[key.strip()] = value.strip()
    return settings


def deny_settings() -> dict:
    data = tomllib.loads(DENY_CONFIG.read_text())
    adv = data.get("advisories", {})
    bans = data.get("bans", {})
    return {
        # `unmaintained` is snapshotted BECAUSE it was not: the key was absent,
        # the comment claimed a posture the tool no longer had, and nothing
        # compared the two (#105). A key left to a tool default is a key that
        # changes when the tool does, silently.
        "advisories.unmaintained": adv.get("unmaintained"),
        "advisories.unsound": adv.get("unsound"),
        "advisories.yanked": adv.get("yanked"),
        "advisories.ignore": adv.get("ignore"),
        "bans.multiple-versions": bans.get("multiple-versions"),
        "bans.wildcards": bans.get("wildcards"),
        "graph.targets": data.get("graph", {}).get("targets"),
        "licenses.allow": data.get("licenses", {}).get("allow"),
        "sources.unknown-git": data.get("sources", {}).get("unknown-git"),
        "sources.unknown-registry": data.get("sources", {}).get("unknown-registry"),
    }


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("--check", "--write"):
        print("usage: snapshot-rust-settings.py --check | --write", file=sys.stderr)
        return 3

    resolved = {
        "lints": lint_flags(),
        "rustfmt": rustfmt_settings(),
        "deny": deny_settings(),
    }
    # A resolver that returns nothing is a snapshot that asserts nothing, and
    # it would compare equal to itself forever.
    if not resolved["lints"]:
        print("::error::cargo resolved 0 lint flags — refusing to snapshot that", file=sys.stderr)
        return 3
    if len(resolved["rustfmt"]) < 10:
        print("::error::rustfmt resolved almost nothing — refusing to snapshot that", file=sys.stderr)
        return 3
    serialised = json.dumps(resolved, indent=2, sort_keys=True) + "\n"

    if mode == "--write":
        SNAPSHOT.write_text(serialised)
        print(
            f"wrote {SNAPSHOT.relative_to(REPO)} — {len(resolved['lints'])} lint flags, "
            f"{len(resolved['rustfmt'])} rustfmt settings, {len(resolved['deny'])} deny keys"
        )
        return 0

    if not SNAPSHOT.exists():
        print(
            f"::error::{SNAPSHOT.relative_to(REPO)} is missing. Run: "
            "scripts/snapshot-rust-settings.py --write",
            file=sys.stderr,
        )
        return 1

    committed = SNAPSHOT.read_text()
    if committed == serialised:
        print(
            f"rust settings snapshot matches — {len(resolved['lints'])} lint flags, "
            f"{len(resolved['rustfmt'])} rustfmt settings"
        )
        return 0

    # Name what moved — same reporting shape as snapshot-python-settings.py.
    before = json.loads(committed)
    print("::error::the resolved Rust settings drifted:", file=sys.stderr)
    for section in ("lints", "rustfmt", "deny"):
        b, a = before.get(section), resolved[section]
        if b == a:
            continue
        if isinstance(b, list) and isinstance(a, list):
            for gone in [x for x in b if x not in a]:
                print(f"  REMOVED  {section}: {gone}", file=sys.stderr)
            for new in [x for x in a if x not in b]:
                print(f"  ADDED    {section}: {new}", file=sys.stderr)
            if sorted(b) == sorted(a):
                print(f"  REORDERED {section}: lint flags apply left to right", file=sys.stderr)
        else:
            for key in sorted(set(b or {}) | set(a or {})):
                bv, av = (b or {}).get(key), (a or {}).get(key)
                if bv != av:
                    print(f"  CHANGED  {section}.{key}: {bv!r} -> {av!r}", file=sys.stderr)
    print(
        "If this was deliberate, regenerate with: scripts/snapshot-rust-settings.py --write",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
