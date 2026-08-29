#!/usr/bin/env python3
"""Install, refresh or check the maxi-quality agent-guard region in a CLAUDE.md.

WHY THIS EXISTS (#177)

`adopt.sh --agent` used to APPEND the fragment once and skip a region that was
already present. The scripts under `.claude/agent-guard/` and the merge into
`.claude/settings.json` both refresh on every run, so re-adoption was the
upgrade path for everything EXCEPT the one part that tells a session what the
rules are. A tree could end up refusing one thing while its `CLAUDE.md`
explained a different one, with nothing to signal the two had parted.

`scripts/pom-region.py` is the precedent and the shape is the same: replace
everything between the markers and NOTHING outside them, and edit the file as
text so the consumer's own prose comes back byte-identical.

WHY THE BEGIN MARKER CARRIES A CHECKSUM

Refreshing in place raises a question pom-region.py never had to answer: this
is the consumer's own CLAUDE.md, and a region that differs from the current
fragment is either an OLDER BASELINE (refresh it — that is the whole point) or
AN EDIT OF THEIR OWN (overwriting it destroys work nobody asked us to touch).
Those two are indistinguishable from the text alone.

So the region records what it was shipped as:

    <!-- BEGIN maxi-quality agent-guard sha256:abc123… -->

Body hash equal to the recorded one means untouched-since-install, and a
refresh is safe. Anything else is an edit, and an edit is REFUSED with the diff
printed — `--editor`'s refusal is the nearer precedent than `--force`'s
overwrite, and this file is more personal than a .vscode/ one.

A region with no checksum at all predates this and cannot be told apart from an
edit either. It is refused the same way, once, with a message that says so.

WHY THE FRAGMENT IS A TEMPLATE (#182, and then #184's fifth site)

Two of the five rules — `sample-guard.py` and `Edit(/samples/expected/**)` —
only fire in a tree that HAS expectation manifests, which is this repo and
essentially nothing else. Installing them anyway and describing them anyway
produced a consumer whose CLAUDE.md confidently stated it was protected by
three hooks and two deny rules, a third of which could never fire. The fragment
therefore carries `if-samples` / `unless-samples` blocks, and what lands
describes what was actually installed.

A SECOND AXIS, AND WHY IT IS DIFFERENT IN KIND

`--shared` (#193) puts one `shim.py` in the repo and the scripts themselves at
`~/.claude/agent-guard/`. The region went on saying

    python3 .claude/agent-guard/record-gate.py --gate

which in a shared tree is a file that does not exist. The rules were right, the
hooks resolved, the Stop hook even named the correct recorder at runtime —
because it DERIVES the path from `__file__` — and the one fixed string in the
one file whose job is telling a session what to run was wrong.

That is the difference worth keeping. `samples` changes which RULES are true.
`shared` changes which COMMANDS are true, and a command is checkable: the
`adopt` job now runs the recorder line out of the region it just wrote, in both
profiles, so this class cannot come back silently at this site.

Exit codes:
  0  applied / already current / check passed
  1  check failed — region missing or stale
  3  usage, unreadable file, or a malformed region
  4  refused — the region was edited since it was installed
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import os
import re
import sys

BEGIN = "<!-- BEGIN maxi-quality agent-guard"
END = "<!-- END maxi-quality agent-guard -->"

# The conditional blocks inside the fragment. Spelled as HTML comments so the
# fragment stays readable as Markdown on GitHub when nobody has rendered it.
#
# The axis name is captured rather than hardcoded, because there are now two
# and the second one arrived as a defect: with `--shared` the region told a
# session to run `.claude/agent-guard/record-gate.py`, which does not exist in
# a shared tree — only shim.py does. One axis was enough until an install shape
# changed which COMMANDS are true, not just which RULES are.
COND = re.compile(
    r"[ \t]*<!-- maxi-quality:(if|unless)-([a-z][a-z-]*) -->\n(.*?)"
    r"[ \t]*<!-- /maxi-quality:\1-\2 -->\n",
    re.S,
)

# Every axis the fragment may branch on, and what each one asks.
#
#   samples  does this tree have expectation manifests to guard? (#182)
#   shared   is this a `--agent --shared` install, where the scripts live at
#            ~/.claude/agent-guard/ and the repo holds only shim.py? (#193)
#
# An axis the renderer does not know is a REFUSAL rather than a silent drop:
# a typo'd block name would otherwise delete its own paragraph, and the whole
# failure this file guards is text quietly disagreeing with the install.
AXES = ("samples", "shared")


class Refused(Exception):
    """The target cannot be written. Nothing has been changed."""


def render(fragment: str, flags: dict[str, bool]) -> str:
    """The fragment with the conditional blocks resolved for one profile.

    Keeping BOTH spellings in one file rather than shipping two fragments is
    deliberate: two files drift, and the drift is invisible because no consumer
    holds both. `check-agent-contract.py` asserts every block has a partner and
    that both renderings still parse.
    """
    def pick(m: re.Match) -> str:
        kind, axis, body = m.group(1), m.group(2), m.group(3)
        if axis not in flags:
            raise Refused(
                f"the fragment branches on `{axis}`, which is not an axis this "
                f"renderer knows ({', '.join(sorted(flags))}). Refusing rather "
                "than dropping the block: a typo would otherwise delete its own "
                "paragraph and leave text that disagrees with the install.")
        return body if (kind == "if") == flags[axis] else ""

    return COND.sub(pick, fragment)


def resolve_write_target(path: str) -> str:
    """The file the bytes should land in, following a symlinked `path` (#198).

    A repo that wants one instruction file under two names symlinks one to the
    other, and the direction is a free choice. `os.replace` replaces the LINK,
    so writing naively deletes that arrangement, leaves two copies to diverge,
    puts the region in the file the repo does NOT treat as canonical, and exits
    0 — every property that made this worth trusting failing at once, quietly.

    Reading already follows the link, so resolving here makes the write agree
    with the read rather than changing what the run means.

    Two edges are decided rather than discovered:

      outside the tree  a link resolving out of the target's own directory is
                        REFUSED. "Adopt this repo" must not write elsewhere,
                        and no legitimate layout needs it.
      dangling          also refused. Materialising the far end of a broken
                        link is a repair nobody asked for, and the broken link
                        is the thing worth reporting.
    """
    if not os.path.islink(path):
        return path
    real = os.path.realpath(path)
    if not os.path.exists(real):
        raise Refused(
            f"{path} is a symlink to {os.readlink(path)}, which does not exist. "
            "Nothing was written — fix the link first, so the write lands in a "
            "file the repo actually has.")
    base = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    try:
        inside = os.path.commonpath([real, base]) == base
    except ValueError:
        inside = False
    if not inside:
        raise Refused(
            f"{path} is a symlink to {real}, which is outside {base}. Adopting "
            "this repo must not write outside it, so nothing was written.")
    return real


def body_of(fragment: str) -> str:
    """Everything between the markers, markers excluded, of a RENDERED text."""
    i, j = fragment.find(BEGIN), fragment.find(END)
    if i < 0 or j < 0 or j < i:
        raise Refused("the fragment has no complete agent-guard region")
    i = fragment.index("-->", i) + len("-->")
    return fragment[i:j]


def digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def block(body: str) -> str:
    """A full region, checksum embedded, ready to write."""
    return f"{BEGIN} sha256:{digest(body)} -->{body}{END}\n"


def find_region(text: str) -> tuple[int, int, str, str | None]:
    """(start, end, body, recorded-checksum-or-None) of the region in `text`.

    Raises Refused on a half-region. A BEGIN with no END, or the two the wrong
    way round, is not something to replace half of — there is no way to know
    where the consumer meant the region to stop, and guessing edits prose we
    were told not to touch.
    """
    i, j = text.find(BEGIN), text.find(END)
    if i < 0 and j < 0:
        return (-1, -1, "", None)
    if i < 0:
        raise Refused(f"{END} is present with no BEGIN marker")
    if j < 0:
        raise Refused(f"{BEGIN} ...--> is present with no END marker")
    if j < i:
        raise Refused("the END marker comes before the BEGIN marker")
    close = text.find("-->", i)
    if close < 0 or close > j:
        raise Refused("the BEGIN marker is not closed")
    opening = text[i:close + len("-->")]
    m = re.search(r"sha256:([0-9a-f]{8,64})", opening)
    return (i, j + len(END) + 1, text[close + len("-->"):j], m.group(1) if m else None)


def apply(path: str, fragment: str, flags: dict[str, bool], force: bool) -> tuple[str, str, str]:
    """(verdict, detail, written-path). Verdicts: created, refreshed, current, stamped.

    The third element is where the bytes went, which is not always `path` — see
    resolve_write_target.
    """
    wanted = body_of(render(fragment, flags))
    # Before the read, not just before the write: a resolved path that differs
    # from the argument is the file this run is actually about, and every later
    # message naming `path` would otherwise name the link instead of it.
    path = resolve_write_target(path)
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = ""
    except OSError as exc:
        raise Refused(f"cannot read {path}: {exc}") from exc

    start, stop, body, recorded = find_region(text)

    if start < 0:
        # Terminate an unterminated last line, then separate with a blank one:
        # appending onto someone's final paragraph puts an HTML comment inside
        # it, and a heading that continues the previous line is not a heading.
        head = text
        if head and not head.endswith("\n"):
            head += "\n"
        if head:
            head += "\n"
        new = head + block(wanted)
    else:
        if body == wanted and recorded == digest(body):
            return ("current", "", path)
        if body == wanted:
            # The text is current but the marker cannot vouch for it — either
            # it predates checksums or someone rewrote the marker. Stamping it
            # is a no-op on content and the only way a region installed before
            # this check ever becomes verifiable. Without this branch such a
            # region is stuck: never refreshed because it is current, never
            # stamped because it is never refreshed.
            new = text[:start] + block(wanted) + text[stop:]
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(new)
            os.replace(tmp, path)
            return ("stamped", "", path)
        if not force:
            if recorded is None:
                raise Refused(
                    f"{path}'s agent-guard region carries no checksum, so it "
                    "cannot be told apart from one you edited yourself. It "
                    "predates this check. Replace the text between the markers "
                    "with the current fragment by hand, or re-run with --force."
                )
            if recorded != digest(body):
                raise Refused(
                    f"{path}'s agent-guard region has been edited since it was "
                    "installed. Refreshing it would discard that edit, so this "
                    "run wrote nothing. Move what you want to keep outside the "
                    "markers, or re-run with --force.\n\n"
                    + diff(body, wanted)
                )
        new = text[:start] + block(wanted) + text[stop:]

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(new)
    os.replace(tmp, path)
    return ("created" if start < 0 else "refreshed", diff(body, wanted), path)


def diff(old: str, new: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile="installed", tofile="current", n=1))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("mode", choices=("apply", "check", "render"))
    p.add_argument("--fragment", required=True)
    p.add_argument("--target", help="the consumer's CLAUDE.md (apply/check)")
    p.add_argument("--samples", choices=("yes", "no"), required=True,
                   help="does the target have expectation manifests to guard?")
    # Required, not defaulted. A caller that forgets which install shape it is
    # writing for is the whole of this bug: the default would have been `no`,
    # which is right for eight callers out of nine and silently wrong for the
    # ninth. A loud missing-argument beats a quiet wrong rendering.
    p.add_argument("--shared", choices=("yes", "no"), required=True,
                   help="is this a --shared install, where the scripts live at "
                        "~/.claude/agent-guard/ and the repo holds only shim.py?")
    p.add_argument("--force", action="store_true",
                   help="overwrite a region that was edited since install")
    a = p.parse_args(argv)

    try:
        with open(a.fragment, encoding="utf-8") as fh:
            fragment = fh.read()
    except OSError as exc:
        print(f"agent-region: cannot read {a.fragment}: {exc}", file=sys.stderr)
        return 3

    # Built FROM AXES, so adding an axis means adding one argument and one
    # tuple entry rather than an argument and a dict literal that can
    # disagree with it.
    flags = {axis: getattr(a, axis.replace("-", "_")) == "yes" for axis in AXES}
    if a.mode == "render":
        # Inside its own try: this mode returns before the block below, so an
        # unknown-axis Refused escaped as a traceback — a refusal that reads as
        # a crash gets treated as one, and the exit code was 0 besides.
        try:
            sys.stdout.write(render(fragment, flags))
        except Refused as exc:
            print(f"agent-region: {exc}", file=sys.stderr)
            return 4
        return 0

    if not a.target:
        print("agent-region: --target is required for apply and check",
              file=sys.stderr)
        return 3

    try:
        if a.mode == "check":
            wanted = body_of(render(fragment, flags))
            # check follows the link for the same reason apply does: a repo
            # whose CLAUDE.md is a link is correctly adopted, and a check that
            # cannot see that would fail a tree that is right.
            try:
                with open(resolve_write_target(a.target), encoding="utf-8") as fh:
                    text = fh.read()
            except OSError as exc:
                raise Refused(f"cannot read {a.target}: {exc}") from exc
            start, _stop, body, _rec = find_region(text)
            if start < 0:
                print(f"agent-region: {a.target} has no agent-guard region",
                      file=sys.stderr)
                return 1
            if body != wanted:
                print(f"agent-region: {a.target}'s region is stale\n"
                      + diff(body, wanted), file=sys.stderr)
                return 1
            return 0

        verdict, detail, written = apply(a.target, fragment, flags, a.force)
    except Refused as exc:
        print(f"agent-region: {exc}", file=sys.stderr)
        return 4
    except OSError as exc:
        print(f"agent-region: {exc}", file=sys.stderr)
        return 3

    # The resolved path, not the argument: a success line naming the link
    # while the bytes went to its target is the same silent lie #198 was.
    print(f"{verdict} {written}" if written != a.target
          else f"{verdict} {a.target}")
    if detail and verdict == "refreshed":
        sys.stdout.write(detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
