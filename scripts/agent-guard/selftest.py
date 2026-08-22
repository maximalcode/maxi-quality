#!/usr/bin/env python3
"""Run the agent-guard hooks against samples/agent-guard/ and assert the verdicts.

Every case in `samples/agent-guard/cases/*.json` is a real invocation: a real
git repository is built in a temp directory, the real hook script is executed
as a subprocess with the case's payload on stdin, and its stdout is parsed the
way Claude Code parses it. Nothing here imports the hook and calls a function —
the thing under test is the executable, including its exit code and the shape
of what it prints, because those are the parts of the contract that are easy to
break and invisible when broken.

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
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from guard import CONFIG, RECEIPT, changed_files, fingerprint  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
CASES = os.path.join(REPO, "samples", "agent-guard", "cases")
HOOKS = {"stop": "stop-gate.py", "sample": "sample-guard.py"}


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


def run_case(path: str) -> list[str]:
    """Returns a list of failure messages; empty means the case passed."""
    with open(path, encoding="utf-8") as fh:
        case = json.load(fh)

    hook = case["hook"]

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
