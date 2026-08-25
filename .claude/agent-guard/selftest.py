#!/usr/bin/env python3
"""Run the agent-guard hooks against samples/agent-guard/ and assert the verdicts.

Most cases in `samples/agent-guard/cases/*.json` are a real invocation: the real
hook script is executed as a subprocess with the case's payload on stdin, and
its stdout is parsed the way Claude Code parses it. Nothing there imports the
hook and calls a function — the thing under test is the executable, including
its exit code and the shape of what it prints, because those are the parts of
the contract that are easy to break and invisible when broken. The `stop-` and
`edit-` cases build a real git repository first; the `noverify-` cases do not,
because a command guard reads a string and has no opinion about the repository
it stands in.

TWO KINDS OF CASE ARE NOT AN INVOCATION, AND BOTH SAY SO

`changed-` calls `changed_files()` directly, because a fingerprint over the
wrong file set is still "some hash" and no hook decision can tell those apart.
`permissions` runs nothing at all — a `permissions.deny` rule is enforced
inside Claude Code and cannot be made to fire from a fixture; the comment block
above `deny_rules()` says what is asserted instead and what that costs.

WHY THE ASSERTION IS THE DECISION AND NOT THE EXIT CODE

Both hooks always exit 0 and carry their verdict in JSON, for reasons the hook
docstrings give. So "exit 0" is true of a hook that blocks, a hook that allows,
and a hook that silently did nothing at all. Asserting on the parsed decision —
and asserting that an ALLOW prints nothing whatsoever — is what tells those
three apart. A hook that starts printing a stray line still exits 0; here it
fails.

Exit codes: 0 every case matched · 1 a case failed · 3 usage/corpus error
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from guard import CONFIG, RECEIPT, changed_files, fingerprint  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
CASES = os.path.join(REPO, "samples", "agent-guard", "cases")
HOOKS = {"stop": "stop-gate.py", "sample": "sample-guard.py",
         "noverify": "no-verify-guard.py"}
FRAGMENT = os.path.join(REPO, "configs", "agent", "settings.json")

# The only two tool names Claude Code consults a PATH rule for. Everything
# else in this position is the trap the `permissions` mode exists to catch.
PATH_RULE_TOOLS = ("Edit", "Read")


def run_git(root: str, *args: str) -> None:
    subprocess.run(
        ("git", *args), cwd=root, check=True, capture_output=True, text=True,
        # A committer identity the ambient config cannot supply is set per
        # invocation: a CI runner has no user.email, and the failure would
        # read as a broken fixture rather than a missing global config.
        env={**os.environ,
             "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "f@x",
             "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "f@x"},
    )


def write_tree(root: str, files: dict) -> None:
    for rel, content in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if content is None:
            if os.path.exists(path):
                os.remove(path)
            continue
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)


def build(root: str, setup: dict) -> None:
    """Materialise the case's repository."""
    if setup.get("git", True):
        run_git(root, "init", "--quiet", "--initial-branch=main")
        write_tree(root, setup.get("committed", {}))
        run_git(root, "add", "-A")
        run_git(root, "commit", "--quiet", "-m", "fixture base")
    write_tree(root, setup.get("worktree", {}))
    if setup.get("stage"):
        # Rename detection only produces an 'R' entry for a STAGED rename;
        # unstaged, git reports a delete and an untracked file. Both paths must
        # survive either spelling, so one case stages and one does not.
        run_git(root, "add", "-A")

    if setup.get("config"):
        path = os.path.join(root, CONFIG)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(setup["config"], fh)

    # A REAL run of record-gate.py, so the wrapper is covered end to end
    # rather than by fixtures that hand-write the receipt it is supposed to
    # produce. `after` edits the tree once the receipt exists, which is the
    # only way to build a genuinely stale one without copying a hash.
    record = setup.get("record")
    if record is not None:
        proc = subprocess.run(
            (sys.executable, os.path.join(HERE, "record-gate.py"), "--",
             *record["command"]),
            cwd=root, capture_output=True, text=True, timeout=60,
        )
        setup["_record_exit"] = proc.returncode
        write_tree(root, record.get("after", {}))

    receipt = setup.get("receipt")
    if receipt is not None:
        # "current" is computed AFTER the tree is final, so a fresh receipt is
        # genuinely fresh rather than a value copied into the fixture — which
        # would rot the moment a fixture file changed by one byte.
        fp = (fingerprint(root) if receipt.get("fingerprint") == "current"
              else "0" * 64)
        path = os.path.join(root, RECEIPT)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"fingerprint": fp,
                       "verdict": receipt.get("verdict", "pass"),
                       "exit_code": 0 if receipt.get("verdict") == "pass" else 1,
                       "command": receipt.get("command", "fixture gate")}, fh)


def decision_of(hook: str, stdout: str) -> tuple[str, str]:
    """(verdict, reason) as Claude Code would read it."""
    text = stdout.strip()
    if not text:
        return "allow", ""
    if not text.startswith("{"):
        return "unparsed", text
    try:
        doc = json.loads(text)
    except ValueError:
        return "unparsed", text
    if hook == "stop":
        return (("block", doc.get("reason", ""))
                if doc.get("decision") == "block" else ("allow", ""))
    hso = doc.get("hookSpecificOutput") or {}
    if hso.get("hookEventName") != "PreToolUse":
        return "unparsed", text
    return (("deny", hso.get("permissionDecisionReason", ""))
            if hso.get("permissionDecision") == "deny" else ("allow", ""))


# --- the permissions.deny mode ----------------------------------------------
#
# WHY THIS IS STRUCTURAL AND NOT A REAL DENIAL
#
# A `permissions.deny` rule is enforced inside Claude Code. There is no
# headless way to make it fire, the way `selftest.py` makes a hook fire by
# running it as a subprocess — which is exactly the shape CONTRIBUTING.md's
# "samples/ is the test suite" rule exists to refuse, and exactly the shape
# configs/editor/ already had. So the exemption is paid for the same way it is
# there: this asserts the rule's INTERNAL CONSISTENCY — that it is spelled
# with a tool whose path rules are consulted at all, that it parses, and that
# it covers the literal paths it names and no others — and configs/agent/
# README.md §5 states what evidence the claim rests on, including the one
# dated live observation in §5a that is not mechanisable.
#
# It is not a precedent. A config that COULD have a failing sample and does
# not is still a violation.


def deny_rules() -> list:
    """The fragment's `permissions.deny` array, exactly as written.

    Non-string entries are returned rather than filtered out. Dropping them
    here would turn "somebody wrote an object into the deny array" into a
    shorter list and a green run, which is the same silence this whole mode
    exists to break.
    """
    with open(FRAGMENT, encoding="utf-8") as fh:
        doc = json.load(fh)
    return list(((doc.get("permissions") or {}).get("deny")) or [])


def split_rule(rule) -> tuple[str, str]:
    """(tool, specifier), or raise ValueError with the reason it is unusable."""
    if not isinstance(rule, str):
        raise ValueError(f"{rule!r} is not a string; a deny rule is one")
    if not rule.endswith(")") or "(" not in rule:
        # A bare `Edit` deny is legal and matches the tool EVERYWHERE — the
        # docs say so and say Claude Code does not warn about it. Silently
        # disabling every edit in the repo is not what any rule here means.
        raise ValueError(f"{rule!r} names no path; a bare tool-name deny "
                         "matches that tool everywhere")
    tool, spec = rule[:rule.index("(")], rule[rule.index("(") + 1:-1]
    if tool not in PATH_RULE_TOOLS:
        raise ValueError(
            f"{rule!r} is a {tool}(path) rule. Claude Code checks file "
            f"permissions against {' and '.join(PATH_RULE_TOOLS)} rules only; "
            "a path rule for Write, MultiEdit, NotebookEdit or Glob is "
            "accepted, never consulted, and warns once at startup."
        )
    if not spec:
        raise ValueError(f"{rule!r} has an empty pattern")
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:", spec):
        raise ValueError(
            f"{rule!r} is a parameter-match rule. The primary content field — "
            "`file_path` for Edit and Read — cannot be matched that way; "
            "Claude Code ignores the rule and warns at startup."
        )
    if "\\" in spec:
        raise ValueError(f"{rule!r} contains a backslash; gitignore patterns "
                         "use forward slashes on every platform")
    if spec.endswith("/"):
        raise ValueError(f"{rule!r} ends in a slash, so it names a directory "
                         "and matches no file the tools can edit")
    if spec.count("[") != spec.count("]"):
        raise ValueError(f"{rule!r} has an unbalanced character class")
    return tool, spec


def glob_regex(pattern: str) -> str:
    """gitignore glob -> regex. `*` stays inside one segment, `**` crosses."""
    out, i, n = [], 0, len(pattern)
    while i < n:
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == n:
            out.append("/.*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


def rule_matcher(spec: str, root: str) -> re.Pattern:
    """The absolute-path regex a deny specifier resolves to.

    The four anchors are the permissions reference's own table, and getting
    them wrong is the failure this mode is for: `//x` is the filesystem root,
    `~/x` is home, `/x` is the SETTINGS SOURCE — the project root, for the
    project settings this fragment becomes — and a bare `x` is relative to the
    current directory. A pattern with no slash in it is a gitignore bare name
    and matches at any depth; anything else matches only where it is anchored.

    Today's rules use the `/` anchor and nothing else, so three of these four
    branches — and `glob_regex()`'s `?` — are reached by no fixture. They are
    not kept out of generality. A checker that models three anchors does not
    REJECT the fourth; it resolves it quietly against the wrong base and
    reports a clean run, which is the anchor-slip bug this whole mode exists
    to catch, one level up.
    """
    if spec.startswith("//"):
        base, rest, anchored = "", spec[1:].lstrip("/"), True
    elif spec.startswith("~/"):
        base, rest, anchored = os.path.expanduser("~"), spec[2:], True
    elif spec.startswith("/"):
        base, rest, anchored = root, spec[1:], True
    else:
        rest = spec[2:] if spec.startswith("./") else spec
        # A session starts at the repo root, so cwd and the settings source
        # are the same directory here. The DEPTH is what differs, and that is
        # what the fixture asserts.
        base, anchored = root, "/" in rest
    depth = "" if anchored else "(?:.*/)?"
    return re.compile("^" + re.escape(base.rstrip("/")) + "/" + depth
                      + glob_regex(rest) + "$")


def run_permissions_case(case: dict) -> list[str]:
    fails: list[str] = []
    rules = deny_rules()

    # Shape is asserted for EVERY rule on every permissions case, not only on
    # the one that pins the list: a rule added later must not be able to
    # arrive in the trap spelling just because nobody updated a fixture.
    for rule in rules:
        try:
            split_rule(rule)
        except ValueError as exc:
            fails.append(str(exc))

    expect = case.get("expect", {})
    if "rules" in expect:
        if rules != expect["rules"]:
            fails.append(f"permissions.deny is {rules}, expected "
                         f"{expect['rules']}")
        if not rules:
            fails.append("permissions.deny is empty — this contract stopped "
                         "denying anything")

    if "rule" not in case:
        return fails

    rule = case["rule"]
    if rule not in rules:
        return fails + [f"{rule!r} is not in the fragment's permissions.deny"]
    try:
        _tool, spec = split_rule(rule)
    except ValueError:
        return fails  # already reported above

    tmp = tempfile.mkdtemp(prefix="agent-guard-")
    try:
        # A real tree, realpath-resolved for the same reason every other case
        # here resolves one: a pattern asserted against a path that does not
        # exist is a pattern asserted against a typo.
        root = os.path.realpath(os.path.join(tmp, "repo"))
        planted = sorted(case.get("tree", []))
        for rel in planted:
            full = os.path.join(root, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write("planted\n")

        denied = sorted(expect.get("denied", []))
        allowed = sorted(expect.get("allowed", []))
        # Exhaustive on purpose. A planted path that is in neither list is a
        # path the case has no opinion about, and a case with no opinion is
        # how a rule's blast radius grows without a diff.
        #
        # NO MUTATION REACHES THIS. It guards the next fixture author, not the
        # rules, and there is no case shape for "this case must fail" — so
        # removing it fails nothing. Kept and marked; README §5 says so too.
        if sorted(denied + allowed) != planted:
            fails.append("denied+allowed must be exactly the planted tree; "
                         f"planted={planted} listed={sorted(denied + allowed)}")

        matcher = rule_matcher(spec, root)
        for rel in denied:
            if not matcher.match(os.path.join(root, rel)):
                fails.append(f"{rule} does NOT match {rel}, and must")
        for rel in allowed:
            if matcher.match(os.path.join(root, rel)):
                fails.append(f"{rule} matches {rel}, and must not")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return fails


def run_case(path: str) -> list[str]:
    """Returns a list of failure messages; empty means the case passed."""
    with open(path, encoding="utf-8") as fh:
        case = json.load(fh)

    hook = case["hook"]

    if hook == "permissions":
        return run_permissions_case(case)

    # A direct assertion on the shared module rather than on a hook decision.
    # It exists because a decision cannot see the difference: two fingerprints
    # over different file sets are both "some hash", and a path silently
    # dropped from the set produces a hook that behaves plausibly and gates
    # less. The rename mutation survived the whole suite until this was added.
    if hook == "changed":
        tmp = tempfile.mkdtemp(prefix="agent-guard-")
        try:
            root = os.path.realpath(tmp)
            build(root, dict(case.get("setup", {})))
            got = changed_files(root)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        want = case["expect"]["files"]
        return ([] if got == want
                else [f"changed_files() returned {got}, expected {want}"])

    if hook not in HOOKS:
        return [f"unknown hook {hook!r}"]

    tmp = tempfile.mkdtemp(prefix="agent-guard-")
    try:
        # The realpath matters: on macOS the temp dir is under a symlink, and
        # a hook that compares paths without resolving both sides passes here
        # and fails on a developer's machine. Resolving it in the FIXTURE is
        # what makes that a real test rather than a coincidence.
        root = os.path.realpath(os.path.join(tmp, "repo"))
        os.makedirs(root, exist_ok=True)
        setup = dict(case.get("setup", {}))
        build(root, setup)

        event = dict(case.get("event", {}))
        # A case may hand the hook a path that reaches the repo through a
        # symlink. Constructed here rather than relying on the OS providing
        # one: /tmp is a symlink to /private/tmp on macOS and is not on a
        # Linux runner, so a test that depends on that is a test that only
        # runs on someone's laptop.
        if setup.get("symlink"):
            link = os.path.join(os.path.dirname(root), "link")
            os.symlink(root, link)
            event.setdefault("cwd", link)
        event.setdefault("cwd", root)
        for key in ("file_path",):
            ti = event.get("tool_input")
            if isinstance(ti, dict) and isinstance(ti.get(key), str):
                ti[key] = ti[key].replace("{{ROOT}}", root)

        proc = subprocess.run(
            (sys.executable, os.path.join(HERE, HOOKS[hook])),
            input=json.dumps(event), cwd=root,
            capture_output=True, text=True, timeout=60,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    fails: list[str] = []
    expect = case["expect"]

    # record-gate.py must hand the gate's own exit code back untouched, or
    # putting the wrapper in front of a command changes what CI and a human
    # see — which would be a reason not to use it.
    if "record_exit" in expect:
        got = setup.get("_record_exit")
        if got != expect["record_exit"]:
            fails.append(f"record-gate exited {got}, expected "
                         f"{expect['record_exit']}")

    # Always 0. A hook that exits non-zero on a blocking event blocks with a
    # worse message, and on a non-blocking one it is a broken install.
    if proc.returncode != 0:
        fails.append(f"exit {proc.returncode}, expected 0 "
                     f"(stderr: {proc.stderr.strip()[:200]})")

    verdict, reason = decision_of(hook, proc.stdout)
    if verdict != expect["decision"]:
        fails.append(f"decision {verdict!r}, expected {expect['decision']!r} "
                     f"(stdout: {proc.stdout.strip()[:200]!r})")

    for needle in expect.get("reason_contains", []):
        if needle not in reason:
            fails.append(f"reason never mentioned {needle!r}; got {reason[:200]!r}")

    for needle in expect.get("stderr_contains", []):
        if needle not in proc.stderr:
            fails.append(f"stderr never mentioned {needle!r}")

    return fails


def main() -> int:
    files = sorted(pathlib.Path(CASES).glob("*.json"))
    # A glob that stops matching is silence, and silence reads as success —
    # the same guard workflow-lint puts on its own corpus.
    if not files:
        print(f"::error::{CASES} holds no cases — this suite stopped testing")
        return 3

    failed = 0
    for path in files:
        problems = run_case(str(path))
        if problems:
            failed += 1
            print(f"FAIL {path.stem}")
            for p in problems:
                print(f"     {p}")
        else:
            print(f"ok   {path.stem}")

    print(f"\ncases={len(files)} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
