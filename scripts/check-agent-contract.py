#!/usr/bin/env python3
"""Assert that the agent contract's four parts still say the same thing.

WHY THIS EXISTS

`configs/agent/` is a contract spread over four places that a single edit can
put out of step, with nothing red in between:

  * `configs/agent/settings.json` — the wiring Claude Code actually reads
  * `scripts/agent-guard/*.py` — the executables that wiring points at
  * `samples/agent-guard/` — the corpus that proves they still block
  * `configs/agent/README.md` — the prose a consumer decides to trust

None of those disagreements is visible in a diff of any ONE of them. Rename a
hook script and `settings.json` still parses, `selftest.py` still passes
(it addresses the scripts by its own constant), and the only symptom is a hook
that silently stopped firing in every consumer's tree. Add a case and the
README's count is off by one — the same rot that put "27 required checks" in
CLAUDE.md twice. Narrow a matcher from `Edit|Write|MultiEdit` to `Edit|Write`
and every sample still passes, because the samples invoke the hook directly and
never route through the matcher at all.

That last one is the shape worth naming: **the samples prove the hooks, and
nothing proves the wiring.** `samples/agent-guard/` runs each script as a
subprocess on a real payload, which is exactly why it cannot see a `matcher`
that no longer selects the tool, a `command` that names a moved file, or a deny
rule the README no longer describes. This is the guard for the seams between
the parts, not for the parts.

WHAT IT REFUSES TO DO

**It reads the README's numbers and never writes them.** A checker that
updates its own expectations is not a checker — the same argument
`check-expected.py` and `editor-parity.py --update` make about their corpora.
When the count is wrong, one of the two is wrong on purpose and a human decides
which. This script writes nothing, anywhere, in either mode.

**It does not re-run the mutations.** `configs/agent/README.md` §5's tables are
a recorded measurement, not a gate; the cost argument is in that section. What
is checked here is that every row still names a file that exists, so a table
about scripts that were renamed away cannot keep reading as evidence.

**It does not check `adopt.sh`'s output.** That is its own assertion in the
`adopt` job.

WHY IT HAS A SELFTEST MODE

Every guard below is a claim that some edit turns CI red. A guard that quietly
stopped guarding makes exactly the same green run as a contract that holds, and
this script is the only thing standing between the two. So `selftest` copies
the contract into a temp tree, applies one mutation, and asserts the run fails
naming the thing that moved. The first three are #163's first three acceptance
criteria, executable rather than recorded; its fourth — that `ci.yml` gains no
new job — is `workflow-lint`'s to assert and not this script's.

`editor-parity.py` is the precedent for HAVING a selftest mode and is not the
precedent for this one's shape: its corpus is fourteen committed case files, and
this one's is the real contract with one thing broken. The difference is not
preference. A case file can describe a panel dump, which is data this repo
invents; it cannot describe "the README and the fragment disagree", which is a
relationship between two files that both have to exist. Staging the real tree is
the only corpus that can express the mutation. It is the `editor-parity.py selftest` precedent, and the
corpus is the real contract because the real contract is what the mutations are
about.

Reads only committed files. Does no network I/O and writes nothing outside the
temp tree `selftest` builds and removes.

Exit codes: 0 the contract holds · 1 it drifted · 3 the contract is unreadable,
            so nothing was checked. Bad argv exits 2, from argparse.
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import shlex
import shutil
import sys
import tempfile


class CorpusError(Exception):
    """The contract could not be read at all — exit 3, never a clean run."""


# The hook command Claude Code runs is a path in the CONSUMER's tree, not in
# this repo: §7 step 1 copies the scripts to `.claude/agent-guard/`. Pinning the
# prefix is half the value of the command check — a command that grew a second
# path segment, or lost `${CLAUDE_PROJECT_DIR}`, resolves against whatever the
# session's cwd happens to be and fails open in a way nothing here would see.
COMMAND_PREFIX = "${CLAUDE_PROJECT_DIR}/.claude/agent-guard/"

# Not every file under scripts/agent-guard/ is a hook, so the orphan check needs
# an exclusion set. It is an explicit list rather than a pattern for the reason
# check-editor-contract.py's NOT_LANGUAGES is: a NEW hook script that nobody
# wired up must still fail here, and the only way past this guard is to type a
# name into this line, which is a reviewable act. Each name must still exist —
# an exclusion for a deleted file is an exclusion that has started covering
# something else.
NOT_HOOKS = {
    "guard.py": "the shared module the hooks import; nothing invokes it",
    "record-gate.py": "the gate wrapper a human or CI runs, not a hook event",
    "selftest.py": "the corpus runner; ci.yml invokes it, settings.json does not",
}

ONES = ("zero one two three four five six seven eight nine ten eleven twelve "
        "thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
        "seventy": 70, "eighty": 80, "ninety": 90}


def word_to_int(word: str) -> int | None:
    """`Fifty-two` -> 52, `one` -> 1, anything else -> None.

    The two READMEs spell the same count two different ways — one in digits,
    one in words — and a spelled-out number rots exactly as quietly as a digit.
    """
    w = word.strip().lower()
    if w.isdigit():
        return int(w)
    if w in ONES:
        return ONES.index(w)
    if w in TENS:
        return TENS[w]
    if "-" in w:
        tens, _, unit = w.partition("-")
        if tens in TENS and unit in ONES[1:10]:
            return TENS[tens] + ONES.index(unit)
    return None


def _documented_count(text: str, pattern: str, actual: int, gone: str,
                      says, truth) -> list[str]:
    """Problems with a count a document states, in words or in digits.

    Three places state a count that something else decides — the wiring row's
    matchers, and the case count in each of the two READMEs. All three fail the
    same three ways (the sentence is gone, the number is not a number, the
    number is wrong), so they share this rather than three near-copies.
    """
    hit = re.search(pattern, text, re.M)
    if not hit:
        return [gone]
    word = hit.group(1)
    said = word_to_int(word)
    if said is None:
        return [f"{says(word)}, which is not a number"]
    if said != actual:
        # Both spellings when they differ: quoting only the parsed number hides
        # what to edit ("Fifty-one" is not greppable as 51), and quoting only
        # the word makes the reader do the arithmetic to see the disagreement.
        shown = word if word.lower() == str(said) else f"{word!r} ({said})"
        return [f"{says(shown)}; {truth(actual)}"]
    return []


def read(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CorpusError(f"{path} cannot be read: {exc}") from exc


def check(root: pathlib.Path, today: datetime.date) -> list[str]:
    """Return every way the contract's four parts disagree. Empty means it holds.

    `today` is passed in rather than read here, and deliberately has no default:
    a default is the ambient clock one layer down. G6 rejects a reference dated
    in the future, and that branch is only testable if the caller decides what
    "now" is — with a real clock read inside, the mutation for it would work
    only for as long as the date it hard-codes stays far away, which is a test
    that expires. `semgrep/conventions/no-ambient-clock.yaml` made this point
    about this very line; it was right.
    """
    fail: list[str] = []

    def bad(msg: str) -> None:
        # Order-preserving dedupe: §5 names the same script in several rows, and
        # one fact reported twice reads as two problems.
        if msg not in fail:
            fail.append(msg)

    cfg = root / "configs" / "agent"
    settings_path = cfg / "settings.json"
    readme_path = cfg / "README.md"
    fragment_path = cfg / "CLAUDE.fragment.md"
    hooks_dir = root / "scripts" / "agent-guard"
    samples = root / "samples" / "agent-guard"
    cases_dir = samples / "cases"
    samples_readme_path = samples / "README.md"

    for required in (settings_path, readme_path, fragment_path,
                     samples_readme_path):
        if not required.is_file():
            raise CorpusError(f"{required} does not exist — the contract cannot "
                              "be checked against a part that is missing")
    if not hooks_dir.is_dir():
        raise CorpusError(f"{hooks_dir} does not exist — every hook command "
                          "would dangle, and reporting that as drift would bury "
                          "the real problem in noise")

    raw = read(settings_path)
    try:
        settings = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CorpusError(f"{settings_path} does not parse as JSON ({exc}) — "
                          "Claude Code would ignore the whole file") from exc

    readme = read(readme_path)
    samples_readme = read(samples_readme_path)
    fragment = read(fragment_path)

    cases = sorted(p.name for p in cases_dir.glob("*.json"))
    if not cases:
        raise CorpusError(f"{cases_dir} holds no cases — the count this checks "
                          "the README against would be zero, and zero agrees "
                          "with nothing on purpose")

    # --- G1: every command names a script, and every script is named ---------
    #
    # The failure this catches is the one nothing else can see. selftest.py
    # addresses the scripts through its OWN constant, so a renamed hook leaves
    # the corpus green; settings.json still parses; and the only symptom is a
    # hook that stopped firing in every tree that adopted it.
    named: set[str] = set()
    events: dict[str, list] = {}
    groups_seen: dict[str, int] = {}
    hooks_block = settings.get("hooks")
    if not isinstance(hooks_block, dict) or not hooks_block:
        bad("configs/agent/settings.json has no `hooks` object — the wiring "
            "half of the contract is gone")
        hooks_block = {}
    for event, groups in hooks_block.items():
        if not isinstance(groups, list):
            bad(f"settings.json: hooks.{event} is not a list")
            continue
        events[event] = []
        groups_seen[event] = 0
        for group in groups:
            if not isinstance(group, dict):
                bad(f"settings.json: an entry under hooks.{event} is not an object")
                continue
            groups_seen[event] += 1
            if "matcher" in group:
                events[event].append(group["matcher"])
            for hook in group.get("hooks") or []:
                if not isinstance(hook, dict):
                    bad(f"settings.json: a hook under {event} is not an object")
                    continue
                if hook.get("type") != "command":
                    bad(f"settings.json: a hook under {event} has type "
                        f"{hook.get('type')!r}; this contract ships commands only")
                    continue
                command = hook.get("command")
                if not isinstance(command, str):
                    bad(f"settings.json: a command hook under {event} has no "
                        "`command` string")
                    continue
                try:
                    tokens = shlex.split(command)
                except ValueError as exc:
                    bad(f"settings.json: {command!r} does not tokenise ({exc})")
                    continue
                if len(tokens) != 2 or tokens[0] != "python3":
                    bad(f"settings.json: {command!r} is not `python3 <script>` — "
                        "every hook here is one Python file and the shape is "
                        "what makes the script name readable at all")
                    continue
                target = tokens[1]
                if not target.startswith(COMMAND_PREFIX):
                    bad(f"settings.json: {command!r} does not run a script under "
                        f"{COMMAND_PREFIX!r}, so it resolves against whatever "
                        "directory the session happens to be in")
                    continue
                name = target[len(COMMAND_PREFIX):]
                if "/" in name or not name.endswith(".py"):
                    bad(f"settings.json: {target!r} does not name a single "
                        "Python file directly under the hook directory")
                    continue
                named.add(name)
                if not (hooks_dir / name).is_file():
                    bad(f"settings.json runs `{name}` on {event}, and "
                        f"scripts/agent-guard/{name} does not exist — that hook "
                        "silently stops firing in every tree that adopted it")

    if not named:
        bad("settings.json names no hook script at all — this guard stopped "
            "guarding")

    for name, why in sorted(NOT_HOOKS.items()):
        if not (hooks_dir / name).is_file():
            bad(f"scripts/agent-guard/{name} does not exist, and this checker "
                f"excuses it from the orphan check as {why} — an exclusion for "
                "a file that is gone has started covering something else")
        elif name in named:
            bad(f"settings.json runs `{name}` as a hook, and this checker "
                f"excuses it from the orphan check as {why} — one of the two "
                "is wrong")
    for script in sorted(hooks_dir.glob("*.py")):
        if script.name in NOT_HOOKS or script.name in named:
            continue
        bad(f"scripts/agent-guard/{script.name} is a hook script no `command` "
            "in settings.json names — it is either dead code or a guard nobody "
            "wired up, and both read as protection from a directory listing")

    # --- G2: the matchers in the fragment are the matchers in the prose ------
    #
    # Bidirectional, because the two directions are different failures. A
    # fragment matcher missing from the README is a rule nobody documented; a
    # README matcher missing from the fragment is prose describing protection
    # that is not wired. Neither shows up in samples/: the corpus invokes each
    # hook directly and never routes through a matcher at all.
    documented = set(re.findall(r"`PreToolUse` on `([^`]+)`", readme))
    wired = set(events.get("PreToolUse", []))
    for m in sorted(wired - documented):
        bad(f"settings.json routes PreToolUse on {m!r}, and configs/agent/"
            f"README.md documents {sorted(documented)} — the wiring and the "
            "prose disagree about what the guard sees")
    for m in sorted(documented - wired):
        bad(f"configs/agent/README.md documents a PreToolUse matcher {m!r} that "
            f"settings.json does not wire; it wires {sorted(wired)}")
    if "Stop" not in events:
        bad("settings.json wires no `Stop` hook — the gate-has-run half of the "
            "contract is gone")

    # The top table's wiring row counts the matchers in words. A third matcher
    # added without touching that row is a contract whose own summary is wrong,
    # and the summary is the part a consumer reads before the sections.
    gone = ("configs/agent/README.md no longer counts the wiring in its first "
            "table — this guard stopped guarding")
    for pattern, actual, label in (
            (r"(\w+) `PreToolUse` matchers?, \w+ `Stop`",
             len(events.get("PreToolUse", [])), "`PreToolUse` matchers"),
            (r"\w+ `PreToolUse` matchers?, (\w+) `Stop`",
             groups_seen.get("Stop", 0), "`Stop` hooks")):
        for problem in _documented_count(
                readme, pattern, actual, gone,
                lambda v, label=label: f"configs/agent/README.md's wiring row "
                                       f"says {v!r} for {label}",
                lambda v: f"settings.json wires {v}"):
            bad(problem)

    # --- G3: the case count, in both spellings ------------------------------
    #
    # This is the "27 required checks" rot, which landed twice in CLAUDE.md
    # before anyone noticed. The number is the README's to state and this
    # script's to read: it is never rewritten here, because a guard that
    # updates its own expectation agrees with itself forever.
    n = len(cases)
    for problem in _documented_count(
            readme, r"`samples/agent-guard/` is (\S+) cases", n,
            "configs/agent/README.md no longer states how many cases "
            "samples/agent-guard/ holds — this guard stopped guarding",
            lambda v: f"configs/agent/README.md §5 says samples/agent-guard/ "
                      f"is {v} cases",
            lambda v: f"cases/ holds {v}"):
        bad(problem)
    for problem in _documented_count(
            samples_readme, r"^(\S+) cases, one JSON file each", n,
            "samples/agent-guard/README.md no longer opens with its case count "
            "— this guard stopped guarding",
            lambda v: f"samples/agent-guard/README.md says {v} cases",
            lambda v: f"cases/ holds {v}"):
        bad(problem)

    # --- G4: every row, citation and link in the prose resolves --------------
    #
    # §5's mutation tables are a RECORDED measurement rather than a gate — the
    # cost argument for not re-running them is in that section. What can still
    # be asserted for free is that they are a measurement OF SOMETHING: a table
    # whose rows name scripts that were renamed away keeps reading as evidence
    # and is evidence of nothing.
    section5 = _section(readme, "## 5. Evidence")
    rows = [line for line in section5.splitlines()
            if line.startswith("|") and "---" not in line]
    if len(rows) < 10:
        bad(f"configs/agent/README.md §5 holds only {len(rows)} table rows — "
            "the mutation tables are the evidence this section claims, and "
            "this guard stopped guarding")
    # Scoped to `*.py` names resolved against scripts/agent-guard/, and NOT to
    # every backticked token in a row, which would be the broader reading of
    # "names a file that exists". Deliberate: §5a's rows name paths in a
    # CONSUMER's tree — `.claude/agent-guard-receipt.json` is runtime state that
    # is gitignored here and `sub/samples/expected/eslint.json` never existed
    # anywhere — so resolving every token against this repo would report a
    # correct table as broken. A guard that overstates itself is worse than
    # none; this one covers the scripts, and says so.
    for line in rows:
        for script in re.findall(r"`([A-Za-z0-9_-]+\.py)`", line):
            if not (hooks_dir / script).is_file():
                bad(f"configs/agent/README.md §5 has a mutation row for "
                    f"`{script}`, which does not exist under "
                    "scripts/agent-guard/ — a table about a script that is "
                    "gone still reads as measured teeth")

    # A case name is cited the way a section number is, and rots the same way:
    # the sentence still reads fine and points at nothing.
    stems = {name[:-len(".json")] for name in cases}
    cite_targets = [readme_path, fragment_path, samples_readme_path]
    cite_targets += sorted(hooks_dir.glob("*.py"))
    for cited_in in cite_targets:
        text = read(cited_in)
        for stem in sorted(set(re.findall(
                r"\b((?:stop|edit|noverify|changed|deny)-\d{2}-[a-z0-9-]+)", text))):
            if stem not in stems:
                bad(f"{_rel(cited_in, root)} cites the case `{stem}`, which "
                    "is not in samples/agent-guard/cases/")

    # A relative link is the one citation form a reader clicks, so a dangling
    # one is the loudest kind of quiet rot. Anchors and URLs are somebody
    # else's problem; a path in this tree is this checker's.
    for doc in (readme_path, fragment_path, samples_readme_path):
        for target in re.findall(r"\]\(([^)\s]+)\)", read(doc)):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            resolved = (doc.parent / target.split("#", 1)[0]).resolve()
            if not resolved.exists():
                bad(f"{_rel(doc, root)} links to {target!r}, which does not "
                    "exist")

    # --- G5: the deny rules, verbatim, in both places ------------------------
    #
    # The fragment is the SOURCE — it is the file Claude Code reads — so the
    # README's block is checked against it rather than the other way round. And
    # §5a is checked too, because §5a is a LIVE OBSERVATION of two specific
    # strings: a rule edited without re-observing it leaves a table that
    # measured something else entirely.
    deny = ((settings.get("permissions") or {}).get("deny"))
    if not isinstance(deny, list) or not deny:
        bad("configs/agent/settings.json has no non-empty `permissions.deny` "
            "array — the half of the contract with no runtime evidence that it "
            "is missing")
        deny = []
    block = _deny_block(readme)
    if block is None:
        bad("configs/agent/README.md no longer quotes the `deny` array in a "
            "json block — this guard has nothing to compare the fragment to")
    elif block != deny:
        bad(f"configs/agent/settings.json denies {deny}; configs/agent/"
            f"README.md quotes {block}")
    section5a = _section(readme, "### 5a. The deny rules, observed live")
    for rule in deny:
        if isinstance(rule, str) and f"`{rule}`" not in section5a:
            bad(f"the deny rule `{rule}` is not in configs/agent/README.md "
                "§5a's table — the live observation was made against a "
                "different rule than the one that ships")

    # --- G6: every reference carries its own date ---------------------------
    #
    # §6 is explicit that there is no schema version for either the hooks format
    # or the permissions one, so the date the reference was READ is the whole
    # version statement. Checking "built against" and "as of <date>" as two
    # independent substrings is not enough and was the first version of this
    # guard: §6 names two references, and dropping the date from one of them
    # left the other's date satisfying the check while a reference silently
    # lost its only version statement. So the two are checked as a PAIR — every
    # backticked reference in §6 must be followed by its own `as of <date>`.
    section6 = _section(readme, "## 6. What has NOT been measured")
    flat6 = " ".join(section6.split())
    if "built against" not in flat6:
        bad("configs/agent/README.md §6 no longer says what reference the "
            "contract was built against — §6 is itself explicit that the date "
            "is the only version statement available, so losing the sentence "
            "loses the claim")
    references = re.findall(r"against `([^`]+)`(?: as of \*\*([^*]+)\*\*)?",
                            flat6)
    if not references:
        bad("configs/agent/README.md §6 names no reference the contract was "
            "built against — this guard stopped guarding")
    for reference, value in references:
        if not value:
            bad(f"configs/agent/README.md §6 says the contract was built "
                f"against `{reference}` and gives no `as of <date>` for it — "
                "that date is the only version statement this contract has")
            continue
        try:
            when = datetime.date.fromisoformat(value)
        except ValueError:
            bad(f"configs/agent/README.md §6 dates `{reference}` at {value!r}, "
                "which is not a date")
            continue
        if when > today:
            bad(f"configs/agent/README.md §6 dates `{reference}` at {value}, "
                "which is in the future — a version statement nobody could "
                "have made")

    # --- G7: the managed region's markers -----------------------------------
    #
    # The markers are how the fragment is upgraded in a consumer's CLAUDE.md
    # without a merge, which is the same mechanism scripts/pom-region.py uses
    # for Maven. Exactly once each: a second BEGIN makes the region ambiguous,
    # and an upgrade that cannot tell where the region ends rewrites the wrong
    # bytes of somebody else's file.
    for marker in ("BEGIN maxi-quality agent-guard", "END maxi-quality agent-guard"):
        count = fragment.count(marker)
        if count != 1:
            bad(f"configs/agent/CLAUDE.fragment.md holds {count} "
                f"`{marker}` markers, expected exactly 1 — the managed region "
                "cannot be upgraded without them")
    if (fragment.find("BEGIN maxi-quality agent-guard")
            > fragment.find("END maxi-quality agent-guard")):
        bad("configs/agent/CLAUDE.fragment.md's END marker comes before its "
            "BEGIN marker")

    # --- G8: every §N citation on this surface resolves ----------------------
    #
    # Scoped to the agent surface rather than repo-wide, unlike
    # check-editor-contract.py's ADR sweep, and the difference is the citation
    # form: `docs/adr/NNNN-*.md` names its target unambiguously anywhere in the
    # tree, and a bare `§5` does not — CLAUDE.md, CONTRIBUTING.md and
    # configs/editor/ all have a §5 of their own.
    headings = set(re.findall(r"^## (\d+)\.", readme, re.M))
    headings |= set(re.findall(r"^### (\d+[a-z])\.", readme, re.M))
    if not headings:
        bad("configs/agent/README.md has no numbered sections — this guard "
            "stopped guarding")
    for cited_in in cite_targets:
        text = read(cited_in)
        for cited in sorted(set(re.findall(r"\u00a7(\d+[a-z]?)", text))):
            if cited not in headings:
                bad(f"{_rel(cited_in, root)} cites configs/agent/README.md "
                    f"\u00a7{cited}, which is not a section")

    # --- G9: the adopted copy under .claude/ still matches the source --------
    #
    # This repo runs its own contract (#166), and it runs it from a COPY under
    # .claude/agent-guard/ rather than a symlink to scripts/agent-guard/. That
    # is deliberate: a consumer gets a copy, because a hook `command` is a path
    # on disk and Claude Code has no remote consumption, so re-running
    # `adopt.sh --agent` is the only upgrade path there is. A symlink here would
    # make this the one tree in the world that cannot drift, which is the one
    # property a dogfood must not have.
    #
    # So the drift is real and it arrives the first time someone edits a hook
    # and does not re-adopt. What the copy then enforces is the OLD rule, in the
    # repo that ships the new one, and every fixture still passes because
    # samples/agent-guard/ runs the source.
    #
    # __pycache__ is excluded: it is a build artifact of whichever directory
    # last imported guard.py, it is gitignored on both sides, and comparing it
    # would report the checker's own last run as drift.
    adopted = root / ".claude" / "agent-guard"
    if not adopted.is_dir():
        bad(".claude/agent-guard/ does not exist — this repo stopped running "
            "the contract it ships (#166). Re-run `scripts/adopt.sh . --agent`.")
    else:
        want = {f.name: f.read_bytes() for f in hooks_dir.glob("*.py")}
        have = {f.name: f.read_bytes() for f in adopted.glob("*.py")}
        for name in sorted(set(want) - set(have)):
            bad(f".claude/agent-guard/{name} is missing — scripts/agent-guard/ "
                "has it and the adopted copy does not, so this repo runs a "
                "contract with a hole its own fixtures cannot see. Re-run "
                "`scripts/adopt.sh . --agent`.")
        for name in sorted(set(have) - set(want)):
            bad(f".claude/agent-guard/{name} has no source under "
                "scripts/agent-guard/ — it is either a script that was deleted "
                "from the baseline and left running here, or one that never "
                "came from it")
        for name in sorted(set(want) & set(have)):
            if want[name] != have[name]:
                bad(f".claude/agent-guard/{name} has drifted from "
                    f"scripts/agent-guard/{name} — this repo is enforcing an "
                    "older copy of a rule it has already changed. Re-run "
                    "`scripts/adopt.sh . --agent`.")

    return fail


def _rel(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _section(readme: str, heading: str) -> str:
    """The text under `heading`, up to the next heading of the same level."""
    if heading not in readme:
        return ""
    body = readme.split(heading, 1)[1]
    depth = heading.split(" ", 1)[0]
    return body.split("\n" + depth + " ", 1)[0]


def _deny_block(readme: str):
    """The `deny` array as the README quotes it, or None if it stopped quoting one.

    Parsed rather than string-matched so the comparison is between two LISTS:
    a reordering, a duplicate, or a rule quoted with different whitespace are
    all things a substring check would call agreement.
    """
    for block in re.findall(r"```json\n(.*?)```", readme, re.S):
        if '"deny"' not in block:
            continue
        try:
            return json.loads("{" + block.strip().rstrip(",") + "}")["deny"]
        except (ValueError, KeyError):
            return None
    return None


# --- selftest ---------------------------------------------------------------
#
# Each mutation is one acceptance criterion from #163, or one guard below that
# would otherwise be a claim nothing tests. `expect` is every substring the run
# must name: asserting merely that the run FAILED would pass for a checker that
# fails on everything, which is the useless-guard end of the same problem. Where
# #163 says the failure must name BOTH sides — both counts, both matcher
# strings — the tuple has both, because a message that names only the new value
# leaves the reader to go and find what it used to be.
#
# WHAT NO MUTATION BELOW REACHES, kept and marked rather than left looking
# tested, for the reason configs/agent/README.md §5 publishes its zero rows:
#
#   * the "this guard stopped guarding" floors — an empty `hooks` block, a
#     README with no numbered sections, a §5 with fewer than ten table rows, a
#     `deny` block the README stopped quoting. Each fires only when a whole
#     part of the contract is deleted, which is a diff nobody merges by
#     accident; they are here so a SILENT emptying cannot read as agreement.
#   * the command-shape rejections other than the prefix one — a hook whose
#     `type` is not `command`, a command that does not tokenise, a command that
#     is not `python3 <script>`. They guard the parser that makes every other
#     command message readable.
#   * the END-before-BEGIN ordering check. Losing a marker is mutated below;
#     swapping them is a hand-edit no upgrade path produces.

SURFACES = ("configs/agent", "scripts/agent-guard", "samples/agent-guard",
            ".claude/agent-guard")


def _stage(root: pathlib.Path, copy: pathlib.Path) -> None:
    """A tree a mutation can edit, with the rest of the repo symlinked in place.

    Only the three surfaces are copied — copying the repo would mean copying
    node_modules and .git for every mutation. But everything ELSE is linked in
    rather than left absent, because the link check resolves paths: a legitimate
    link from the contract to somewhere outside these three directories would
    otherwise fail on the unmutated baseline and read as a broken checker rather
    than as a temp tree missing a file.
    """
    surfaces = {pathlib.PurePath(rel) for rel in SURFACES}
    parents = {rel.parent for rel in surfaces}
    copy.mkdir(parents=True)
    for entry in root.iterdir():
        here = pathlib.PurePath(entry.name)
        if here not in parents:
            (copy / entry.name).symlink_to(entry)
            continue
        (copy / entry.name).mkdir()
        for child in entry.iterdir():
            target = copy / entry.name / child.name
            if here / child.name in surfaces:
                shutil.copytree(child, target)
            else:
                target.symlink_to(child)


def _edit(root: pathlib.Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise CorpusError(f"selftest cannot mutate {rel}: {old!r} is not in it")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _edit_re(root: pathlib.Path, rel: str, pattern: str, new: str) -> None:
    """Replace the first match of `pattern`, or say why the mutation is stale.

    By SHAPE rather than by literal text wherever the text is expected to
    change: two mutations below move the reference date, and pinning today's
    date in this file would turn an ordinary date bump into an exit-3 "cannot
    mutate" report on a contract that is perfectly fine.
    """
    path = root / rel
    text = path.read_text(encoding="utf-8")
    edited, count = re.subn(pattern, new, text, count=1)
    if not count:
        raise CorpusError(f"selftest cannot mutate {rel}: nothing matches "
                          f"{pattern!r}")
    path.write_text(edited, encoding="utf-8")


def _edit_date(root: pathlib.Path, new: str) -> None:
    """Rewrite the first `as of **<date>**` in the README to `new`."""
    _edit_re(root, "configs/agent/README.md",
             r"(?<= as of \*\*)\d{4}-\d{2}-\d{2}(?=\*\*)", new)


def mutations(cases: int, today: datetime.date) -> list[tuple]:
    return [
        # AC1 — a hook that silently stopped firing because its script moved.
        ("a hook script is renamed and settings.json is not",
         lambda r: (r / "scripts/agent-guard/stop-gate.py").rename(
             r / "scripts/agent-guard/stop-gate2.py"),
         ("stop-gate.py",)),
        # AC2 — the README's count rotting the way "27 required checks" did.
        ("a 53rd case file arrives and the README still says 52",
         lambda r: (r / "samples/agent-guard/cases/zz-99-extra.json").write_text(
             "{}", encoding="utf-8"),
         (str(cases), str(cases + 1))),
        # AC3 — a silent narrowing of what the guard sees.
        ("the PreToolUse matcher is narrowed in the fragment only",
         lambda r: _edit(r, "configs/agent/settings.json",
                         '"Edit|Write|MultiEdit"', '"Edit|Write"'),
         ("Edit|Write|MultiEdit", "Edit|Write")),
        ("a hook script exists that no command names",
         lambda r: (r / "scripts/agent-guard/rogue-guard.py").write_text(
             "#\n", encoding="utf-8"),
         ("rogue-guard.py",)),
        ("a deny rule is widened in the fragment only",
         lambda r: _edit(r, "configs/agent/settings.json",
                         "/samples/expected/**", "/samples/**"),
         ("/samples/**", "/samples/expected/**")),
        ("the fragment loses its BEGIN marker",
         lambda r: _edit(r, "configs/agent/CLAUDE.fragment.md",
                         "<!-- BEGIN maxi-quality agent-guard -->\n", ""),
         ("BEGIN maxi-quality agent-guard",)),
        ("the reference date is not a date",
         lambda r: _edit_date(r, "2026-13-45"),
         ("2026-13-45",)),
        # The failure the spec review found in the first version of G6: two
        # references, one date between them, and the guard exited 0.
        ("a reference loses its date and the other keeps one",
         lambda r: _edit_re(r, "configs/agent/README.md",
                            r" as of \*\*\d{4}-\d{2}-\d{2}\*\*", ""),
         ("only version statement",)),
        # AC (#166) — the dogfood copy enforcing a rule the source has moved
        # past, which every fixture still passes because they run the source.
        ("the adopted copy under .claude/ drifts from its source",
         lambda r: _edit(r, ".claude/agent-guard/stop-gate.py",
                         "stop_hook_active", "stop_hook_inactive"),
         ("drifted", "stop-gate.py")),
        # The set difference, isolated. Deleting from the ADOPTED side rather
        # than adding to the source, because adding to the source also trips G1
        # ("a hook script exists that no command names") and the mutation would
        # pass on the wrong guard's message.
        ("the adopted copy is missing a script the source has",
         lambda r: (r / ".claude/agent-guard/record-gate.py").unlink(),
         ("record-gate.py", "is missing")),
        ("a mutation row names a script that does not exist",
         lambda r: _edit(r, "configs/agent/README.md",
                         "| `stop-gate.py` ignores the fingerprint |",
                         "| `stop-gatee.py` ignores the fingerprint |"),
         ("stop-gatee.py",)),
        ("a cited case name no longer exists",
         lambda r: _edit(r, "configs/agent/README.md",
                         "stop-02-receipt-pass-fresh",
                         "stop-02-receipt-pass-stale"),
         ("stop-02-receipt-pass-stale",)),
        ("a cited section does not exist",
         lambda r: _edit(r, "samples/agent-guard/README.md", "§5.", "§9."),
         ("§9",)),
        ("the samples README's spelled-out count drifts",
         lambda r: _edit(r, "samples/agent-guard/README.md",
                         "Fifty-two cases", "Fifty-one cases"),
         (str(cases), str(cases - 1))),
        ("a link in the contract points at nothing",
         lambda r: _edit(r, "configs/agent/README.md",
                         "(../../scripts/agent-guard/record-gate.py)",
                         "(../../scripts/agent-guard/record-gate2.py)"),
         ("record-gate2.py",)),
        ("a hook command loses ${CLAUDE_PROJECT_DIR}",
         lambda r: _edit(r, "configs/agent/settings.json",
                         "${CLAUDE_PROJECT_DIR}/.claude/agent-guard/stop-gate.py",
                         ".claude/agent-guard/stop-gate.py"),
         ("CLAUDE_PROJECT_DIR",)),
        ("a hook command runs a script the orphan check excuses",
         lambda r: _edit(r, "configs/agent/settings.json",
                         "agent-guard/stop-gate.py", "agent-guard/guard.py"),
         ("guard.py", "stop-gate.py")),
        ("the Stop hook is unwired",
         lambda r: _edit(r, "configs/agent/settings.json", '"Stop"', '"Unstop"'),
         ("Stop",)),
        ("a deny rule is dropped from the fragment",
         lambda r: _edit(r, "configs/agent/settings.json",
                         '"Edit(/.claude/agent-guard-receipt.json)",', ""),
         ("Edit(/.claude/agent-guard-receipt.json)",)),
        ("the deny array is emptied",
         lambda r: _edit(
             r, "configs/agent/settings.json",
             '"Edit(/.claude/agent-guard-receipt.json)",\n'
             '      "Edit(/samples/expected/**)"', ""),
         ("permissions.deny",)),
        ("the wiring row miscounts the matchers",
         lambda r: _edit(r, "configs/agent/README.md",
                         "two `PreToolUse` matchers", "three `PreToolUse` matchers"),
         ("three", "wires 2")),
        ("the README documents a matcher nothing wires",
         lambda r: _edit(r, "configs/agent/README.md",
                         "`PreToolUse` on `Bash`", "`PreToolUse` on `Task`"),
         ("Task",)),
        # Relative to the injected instant, not a hard-coded far-future year:
        # "2099" would quietly stop being in the future, and the mutation would
        # pass by testing nothing.
        ("a reference is dated in the future",
         lambda r, when=str(today + datetime.timedelta(days=365)):
             _edit_date(r, when),
         (str(today + datetime.timedelta(days=365)),)),
    ]


def selftest(root: pathlib.Path, today: datetime.date) -> int:
    cases = len(list((root / "samples/agent-guard/cases").glob("*.json")))
    baseline = check(root, today)
    if baseline:
        for f in baseline:
            print(f"     {f}")
        print("::error::the UNMUTATED contract already fails — fix that first")
        return 1

    plan = mutations(cases, today)
    failed = 0
    for name, mutate, expect in plan:
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="agent-contract-"))
        try:
            copy = tmp / "repo"
            _stage(root, copy)
            mutate(copy)
            problems = check(copy, today)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        if not problems:
            failed += 1
            print(f"FAIL {name}")
            print("     the mutated contract passed — this guard stopped guarding")
        else:
            missing = [want for want in expect
                       if not any(want in p for p in problems)]
            if missing:
                failed += 1
                print(f"FAIL {name}")
                print(f"     nothing named {missing}; got {problems}")
            else:
                print(f"ok   {name}")

    print(f"\nmutations={len(plan)} failed={failed}")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", nargs="?", default="check",
                    choices=("check", "selftest"))
    args = ap.parse_args()
    # Derived from this file rather than the cwd: a contract checker that
    # silently checks nothing because it was invoked from a subdirectory is the
    # failure mode it exists to refuse.
    root = pathlib.Path(__file__).resolve().parent.parent

    # The single clock read, at the edge, so everything below takes the instant
    # as data. nosemgrep because this is the injection POINT the convention asks
    # for — the rule's own comment says a one-off site takes an inline waiver.
    today = datetime.date.today()  # nosemgrep: no-ambient-clock-python — the one read, at the edge

    try:
        if args.mode == "selftest":
            return selftest(root, today)
        problems = check(root, today)
    except CorpusError as exc:
        print(f"::error::{exc}")
        return 3

    if problems:
        for p in problems:
            print(f"::error::{p}")
        return 1
    print("OK: the agent contract's four parts agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
