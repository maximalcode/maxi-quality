#!/usr/bin/env python3
"""Install the agent contract, including its files, wiring and instructions.

adopt.sh owns argument routing and its overall summary. This module owns the
installation: derive the profile once, refuse unreadable settings before any
write, refresh only baseline-owned files, preserve edited instructions, merge
the settings and verify the installed wiring. A refused region still leaves
enforcement installed and returns 7; refused settings return 6 without writes.

The shared body is a separate, explicit operation. Adopting a repository must
never update code used by other repositories as a side effect.
"""

from __future__ import annotations

import argparse
import importlib
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Installation must not leave its own import artifacts in a baseline checkout,
# including on a dry run. Keep the existing helper CLIs and use their same
# implementation in-process; importlib accepts their hyphenated module names.
sys.dont_write_bytecode = True
settings = importlib.import_module("agent-settings")
region = importlib.import_module("agent-region")

BASELINE = Path(__file__).resolve().parent.parent
IGNORES = (
    ".claude/agent-guard-receipt.json",
    ".claude/agent-guard/__pycache__/",
    ".claude/agent-guard-ledger.jsonl",
)


@dataclass
class _Profile:
    """Internal agreement between the wiring, installed files and region."""

    wiring: dict
    files: list[Path]
    flags: dict[str, bool]

    @classmethod
    def for_repo(cls, root: Path, shared: bool) -> _Profile:
        flags = {"samples": (root / "samples/expected").is_dir(), "shared": shared}
        wiring = settings.load(str(BASELINE / "configs/agent/settings.json"))
        if not wiring:
            raise settings.Refused("the baseline settings are missing or empty")
        if not flags["samples"]:
            wiring = settings.without_samples(wiring)
        if flags["shared"]:
            wiring = settings.shared(wiring)
            files = [BASELINE / "configs/agent" / settings.SHIM]
        else:
            files = [BASELINE / "scripts/agent-guard" / name
                     for name in settings.scripts_for(wiring)]
        return cls(wiring, files, flags)


def _message(kind: str, text: str) -> None:
    colors = {"write": 32, "skip": 33, "warn": 33, "error": 31, "›": 36}
    print(f"\033[{colors[kind]}m{kind}\033[0m {text}",
          file=sys.stderr if kind in {"warn", "error"} else sys.stdout)


def _copy(files: list[Path], destination: Path, dry_run: bool) -> None:
    for source in files:
        target = destination / source.name
        _message("write", f"{target} (refreshed)")
        if not dry_run:
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, target)
            if not target.is_file():
                raise OSError(f"the installed script is missing: {target}")


def _prune(destination: Path, wanted: list[Path], dry_run: bool) -> None:
    # Only filenames the baseline owns may be removed. This includes an old
    # selftest.py or shim, but never an Adopter's own file beside the scripts.
    owned = [*sorted((BASELINE / "scripts/agent-guard").glob("*.py")),
             BASELINE / "configs/agent" / settings.SHIM]
    keep = {path.name for path in wanted}
    for source in owned:
        target = destination / source.name
        if source.name not in keep and target.exists():
            _message("write", f"{target} (removed — this tree does not wire it)")
            if not dry_run:
                target.unlink()


def _ignore_state(root: Path, dry_run: bool) -> None:
    path = root / ".gitignore"
    # The old shell appended bytes. Do not impose an encoding or normalise the
    # Adopter's existing line endings just to add the guard's state entries.
    text = path.read_bytes() if path.exists() else b""
    missing = [entry.encode("ascii") for entry in IGNORES
               if entry.encode("ascii") not in text.split(b"\n")]
    if not missing:
        _message("skip", f"{path} — already ignores the guard's own state")
        return
    _message("write", f"{path} (append)")
    if dry_run:
        return
    addition = b"\n" if text and not text.endswith(b"\n") else b""
    if b"maxi-quality agent guard" not in text:
        if text:
            addition += b"\n"
        addition += "# maxi-quality agent guard — per-checkout state, never committed\n".encode("utf-8")
    addition += b"".join(entry + b"\n" for entry in missing)
    with path.open("ab") as stream:
        stream.write(addition)


def install_repo(root: Path, *, shared: bool, force: bool, dry_run: bool,
                 adopt_command: str) -> int:
    """Install and verify one repository; expose outcomes, not an execution plan."""
    settings_path = str(root / ".claude/settings.json")
    try:
        profile = _Profile.for_repo(root, shared)
        merged, changed = settings.prepare_merge(settings_path, profile.wiring)
    except (settings.Refused, UnicodeError) as exc:
        _message("warn", f"agent-settings: refused. {exc}")
        return 6

    if subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        _message("warn", f"--agent: {root} is not a git working tree. The Stop gate "
                 "fingerprints `git status`, so outside one it allows every stop and "
                 "says nothing. Installing anyway; run `git init` before you rely on it.")
    shared_dir = Path.home() / ".claude/agent-guard"
    if shared and not shared_dir.is_dir() and not dry_run:
        _message("warn", f"--shared: {shared_dir} does not exist yet. The wiring will be "
                 "installed and will REFUSE until you run:")
        _message("warn", f"  {shlex.quote(adopt_command)} --install-shared")

    destination = root / ".claude/agent-guard"
    _copy(profile.files, destination, dry_run)
    _prune(destination, profile.files, dry_run)

    # Preserve the asymmetric refusal: bad settings mean no installation;
    # edited prose means enforcement is updated while the prose stays intact.
    refused = False
    instruction_path = str(root / "CLAUDE.md")
    if dry_run:
        _message("›", f"{instruction_path} (dry run) — the region would be checked and refreshed")
    else:
        try:
            fragment = (BASELINE / "configs/agent/CLAUDE.fragment.md").read_text(encoding="utf-8")
            verdict, detail, written = region.apply(instruction_path, fragment, profile.flags, force)
            print(f"    {verdict} {written}")
            if detail and verdict == "refreshed":
                print(detail, end="")
        except (region.Refused, OSError, UnicodeError) as exc:
            _message("warn", f"agent-region: {exc}")
            _message("warn", f"--agent: {instruction_path} was left alone (see above). "
                     "The rules are installed; the text describing them is not current.")
            refused = True

    _ignore_state(root, dry_run)
    _message("›" if dry_run else "write", f"{settings_path} "
             + ("(dry run) — the merge would apply:" if dry_run else "(merge)"))
    for line in changed or ["already merged — no change"]:
        print(f"    {line}")
    if not dry_run:
        if changed:
            settings.write_atomically(settings_path, settings.render(merged))
        if settings.verify(settings_path, str(root)):
            _message("error", "the wiring names a file that does not exist. Nothing further "
                     "was written; this is a bug in maxi-quality, not in your repo")
            return 3
    return 7 if refused else 0


def install_shared(*, dry_run: bool) -> int:
    """Publish the full runtime explicitly; leave unrelated shared files alone."""
    destination = Path.home() / ".claude/agent-guard"
    _message("›", f"shared agent guard -> {destination}")
    # Unlike a repository profile this serves BOTH sample shapes. The corpus
    # runner alone is excluded: its fixtures do not travel with the runtime.
    files = [path for path in sorted((BASELINE / "scripts/agent-guard").glob("*.py"))
             if path.name != "selftest.py"]
    if not files:
        raise OSError("the shared agent guard has no runtime scripts to install")
    _copy(files, destination, dry_run)
    print()
    _message("›", "every repo adopted with --agent --shared now runs this copy.")
    _message("›", "re-run this after pulling maxi-quality to update all of them at once.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = parser.add_subparsers(dest="mode", required=True)
    repo = modes.add_parser("repo", help="install the contract into one repository")
    repo.add_argument("target", type=Path)
    repo.add_argument("--shared", action="store_true")
    repo.add_argument("--force", action="store_true")
    repo.add_argument("--adopt-command", default=str(BASELINE / "scripts/adopt.sh"))
    shared = modes.add_parser("shared", help="explicitly install the shared runtime")
    for mode in (repo, shared):
        mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.mode == "shared":
            return install_shared(dry_run=args.dry_run)
        root = args.target.resolve(strict=True)
        if not root.is_dir():
            raise OSError(f"not a directory: {root}")
        return install_repo(root, shared=args.shared, force=args.force,
                            dry_run=args.dry_run, adopt_command=args.adopt_command)
    except (OSError, settings.Refused) as exc:
        _message("error", f"agent-install: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
