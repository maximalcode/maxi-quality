#!/usr/bin/env python3
"""Diff a VS Code Problems panel against the committed expectation manifests.

WHY THIS EXISTS — THE RUN IS HAND-WORK, AND HAND-WORK INVENTS CELLS

`configs/editor/` is the one directory here that no sample can prove: there is
no headless VS Code, so what a settings file does to a Problems panel can only
be observed by a person at an editor (`CLAUDE.md` §5, and the exception is paid
for by `scripts/check-editor-contract.py`). #121's parity run is that
observation — every sample in README §3's table, in two conditions, with the
`.vscode/` files and without them.

The observing is irreducibly manual. The *diffing* is not, and that is the half
that goes wrong: README §3's table is twenty rows over nineteen manifests, and
six of those rows use a different path base from the other fourteen — clippy,
knip and deptry are fixture-relative because their tools run from inside the
fixture, everything else is repo-relative. A rule id read off a panel and
compared by eye is how a cell comes to read "assumed", which #121's first
acceptance criterion forbids.

So this script takes the panel dump as data and computes the cell. It does not
observe anything and it cannot: a human still opens the window, applies or
removes the settings, and copies the panel out.

WHAT IT READS

VS Code's Problems panel copies as JSON — right-click, "Copy All" — an array of
marker objects carrying `resource`, `code`, `severity`, `source` and
`startLineNumber`. `code` is a bare string for some extensions and
`{"value": ...}` for others; both are handled, and a marker with neither is
counted as UNIDENTIFIED rather than dropped, because a diagnostic whose rule id
cannot be read is a fact about the run, not noise.

**That input shape is the one assumption this corpus cannot check.** Every
`panel.json` under `samples/editor-parity/` was written here, not copied out of
a running editor, so the fixtures prove what the differ does with markers of
that shape and not that VS Code emits it. The first real run confirms or refutes
it, loudly — a dump in some other shape exits 3 rather than computing a cell
from nothing. `configs/editor/README.md` §1 draws the same line between what its
evidence does and does not cover.

WHY THE PAIR LIST IS NOT IN THIS FILE

It is parsed out of `configs/editor/README.md` §3 at run time, the same table
`check-editor-contract.py` G3 guards. A second copy of "which samples matter"
would drift from the contract, and the contract is what step 1 froze. The tool
key comes from the manifest's own `"tool"` field rather than from the table's
prose label, so a renamed column cannot silently repoint a row either.

WHY A DIVERGENCE IS NOT A NON-ZERO EXIT

The ablation column is *supposed* to diverge — that is the measurement, not a
failure. A tool that exited non-zero on divergence would make the ablation
unrunnable in any CI-shaped harness and would tempt whoever ran it to record
the condition that exits clean. Exit 0 means "the cell was computed"; the
verdict is in the output.

Does no network I/O. Writes only under `--run-dir`, and under `--update` in
`selftest`, which CI never passes — a corpus that can rewrite its own
expectations is not a corpus (`check-expected.py` makes the same point).

Exit codes: 0 cell computed / all cases pass · 1 a selftest case drifted
            · 3 unreadable input, unparseable panel, or a §3 row this tool
              cannot anchor. Bad argv exits 2, from argparse.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

CONTRACT = pathlib.Path("configs/editor/README.md")
SECTION_3 = "## 3. The authoritative expectation source"

# VS Code's MarkerSeverity, from its own API: the panel shows all four, the gate
# only ever produces the first. A finding present at 4 is SHOWN and DEMOTED, not
# missing — a distinction a count of rows in the panel cannot make.
SEVERITY = {8: "error", 4: "warning", 2: "info", 1: "hint"}

# Three manifests are written relative to the fixture rather than to the repo,
# because their tools run from inside it (check-expected.py's parse_clippy and
# parse_knip say so at the seam). This table is ASSERTED against every non-empty
# manifest by `check_bases()` rather than trusted — a wrong base does not fail
# loudly, it reports every finding as both missing and extra.
FIXTURE_RELATIVE = {"clippy", "knip", "deptry"}

# §3's Semgrep row names no sample folder: Layer 2 scans the whole tree, so its
# "sample" cell is prose rather than a path. That row still has to be measurable
# — it is the one place the rule paths in semgrep.settings.json resolve at all —
# so its findings are rebased by anchoring on the longest suffix of the panel's
# path that exists in this checkout, rather than on a folder name.
WHOLE_TREE = "the whole tree"

# README §3, "The rows that are deliberately not in that table": JDT's own null
# analysis is a real bug-finder that no gate here produces, so its diagnostics
# are excluded from the diff instead of being switched off in the editor. It is
# matched on message text because JDT publishes numeric problem ids, not names.
#
# PROVISIONAL. These phrasings are JDT's published ones, but nothing here has
# watched them arrive in a panel — that is exactly what #151 row 6 exists to
# settle. Until it does, a Java marker that misses these patterns is reported as
# an ordinary extra, so the failure mode is a cell a human must classify rather
# than a finding silently swallowed.
JDT_NULL_ANALYSIS = re.compile(
    r"Null type safety|Potential null pointer access|Null comparison always yields"
    r"|Redundant null check|unchecked conversion to conform to '@NonNull",
)


class ParityError(Exception):
    """Usage, input, or contract problem. Exit 3."""


# --- the contract is the source of the pair list ---------------------------

def load_table(contract: pathlib.Path = CONTRACT) -> list[dict]:
    """Parse README §3's table into rows. Never invents a row."""
    try:
        text = contract.read_text(encoding="utf-8")
    except OSError as exc:
        raise ParityError(f"cannot read the contract at {contract}: {exc}") from exc
    try:
        body = text.split(SECTION_3, 1)[1].split("\n## ", 1)[0]
    except IndexError:
        raise ParityError(f"{contract} has no §3 — the expectation-source table is gone") from None

    rows = []
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5 or cells[0] in ("Language / layer", "") or set(cells[1]) <= set("-: "):
            continue
        language, sample_cell, tool_cell, expectation, _asserted = cells
        sample = _backticked(sample_cell)
        if sample is None:
            # A sample cell that is prose rather than a path has exactly one
            # legitimate form today. Refuse rather than guess: silently treating
            # unknown prose as a folder name is how the Semgrep row came to
            # report every finding as OUTSIDE while still printing a cell.
            if sample_cell != WHOLE_TREE:
                raise ParityError(f"§3 row {language!r} names its sample as {sample_cell!r}, "
                          f"which is neither a `path` nor {WHOLE_TREE!r} — teach "
                          "rebase() how to anchor it before adding such a row")
            sample = WHOLE_TREE
        manifest = re.search(r"samples/expected/[A-Za-z0-9._-]+\.json", expectation)
        rows.append({
            "language": language,
            "sample": sample,
            "manifest": manifest.group(0) if manifest else None,
            "label": tool_cell,
        })
    if not rows:
        raise ParityError(f"{contract} §3 has no table rows — nothing to measure against")
    return rows


def _backticked(cell: str) -> str | None:
    m = re.search(r"`([^`]+)`", cell)
    return m.group(1) if m else None


def tools_for(row: dict) -> list[str]:
    """The tool key comes from the manifest itself, never from the table's prose."""
    if row["manifest"]:
        return [json.loads(pathlib.Path(row["manifest"]).read_text(encoding="utf-8"))["tool"]]
    # The one row with no manifest — its assertion is "zero findings", by exit
    # code. README §3 says step 3 has to treat it as its own kind of assertion,
    # and it is still a perfectly measurable parity claim.
    return [t.strip().lower() for t in re.split(r"[,/]", row["label"]) if t.strip()]


def resolve(sample: str, tool: str, table: list[dict]) -> str | None:
    for row in table:
        if row["sample"] == sample and tool in tools_for(row):
            return row["manifest"]
    known = sorted({(r["sample"], t) for r in table for t in tools_for(r)})
    raise ParityError(f"no §3 row for sample={sample!r} tool={tool!r}. Known pairs: "
              + ", ".join(f"{s}:{t}" for s, t in known))


def check_bases(table: list[dict]) -> list[str]:
    """FIXTURE_RELATIVE must agree with what the manifests actually contain."""
    problems = []
    for row in table:
        if not row["manifest"]:
            continue
        data = json.loads(pathlib.Path(row["manifest"]).read_text(encoding="utf-8"))
        findings = data.get("findings") if isinstance(data, dict) else None
        if not findings:
            continue                      # an empty manifest states no convention
        tool = data["tool"]
        repo_rel = all(f["file"].startswith("samples/") for f in findings)
        if repo_rel and tool in FIXTURE_RELATIVE:
            problems.append(f"{row['manifest']} is repo-relative but {tool} is in FIXTURE_RELATIVE")
        if not repo_rel and tool not in FIXTURE_RELATIVE:
            problems.append(f"{row['manifest']} is fixture-relative but {tool} is not in FIXTURE_RELATIVE")
    return problems


# --- the panel -------------------------------------------------------------

def parse_panel(text: str) -> list[dict]:
    """VS Code 'Copy All' output → markers. Raises Bad on anything else."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParityError("the panel dump is not JSON. In VS Code, right-click inside the "
                  f"Problems panel and choose 'Copy All' — that copies JSON ({exc})") from exc
    if not isinstance(data, list):
        raise ParityError("the panel dump is JSON but not an array of markers — "
                  "'Copy All' on the Problems panel produces an array")
    for m in data:
        if not isinstance(m, dict) or "resource" not in m:
            raise ParityError(f"not a Problems-panel marker: {m!r}")
    return data


def rule_of(marker: dict) -> str | None:
    code = marker.get("code")
    if isinstance(code, dict):
        code = code.get("value")
    if code is None or code == "":
        return None
    return str(code)


def rebase(resource: str, sample: str, tool: str) -> str | None:
    """Absolute panel path → the manifest's path base. None if outside the sample."""
    norm = resource.replace("\\", "/")
    if sample == WHOLE_TREE:
        # No folder to anchor on, so anchor on the checkout: the longest suffix
        # of the path that actually exists here. A path from some other tree
        # matches nothing and is reported as OUTSIDE, which is the honest answer.
        parts = norm.lstrip("/").split("/")
        for i in range(len(parts)):
            candidate = "/".join(parts[i:])
            if pathlib.Path(candidate).exists():
                return candidate
        return None
    idx = norm.find(sample + "/")
    if idx < 0:
        return None
    repo_rel = norm[idx:]
    if tool in FIXTURE_RELATIVE:
        # Slice, not os.path.relpath: relpath re-emits os.sep, which would undo
        # the normalisation two lines up on any platform where sep is not "/".
        return repo_rel[len(sample) + 1:]
    return repo_rel


def classify(markers: list[dict], sample: str, tool: str) -> dict:
    """Split a panel dump into the things a cell has to distinguish.

    Severity is resolved per KEY, not per marker. Two extensions can publish the
    same rule id on the same line at different severities, and a finding present
    at error severity is not demoted just because something else also reported it
    as a warning — so the strongest severity seen for a key wins. Counting
    markers instead of keys put `demoted` and `shown` in different units, which
    made a present-at-error finding read as demoted and double-counted an extra
    warning in two columns at once.
    """
    observed, unidentified, outside, excluded = {}, [], [], []
    for m in markers:
        if m.get("source") == "Java" and JDT_NULL_ANALYSIS.search(m.get("message", "")):
            excluded.append(m)
            continue
        rel = rebase(m["resource"], sample, tool)
        if rel is None:
            outside.append(m)
            continue
        rule = rule_of(m)
        if rule is None:
            unidentified.append(m)
            continue
        k = (rel, int(m.get("startLineNumber", 0)), rule)
        prev = observed.get(k)
        if prev is None or _sev(m) > _sev(prev):
            observed[k] = m
    return {"observed": observed, "unidentified": unidentified,
            "outside": outside, "excluded": excluded}


def _sev(marker: dict) -> int:
    return marker.get("severity") if isinstance(marker.get("severity"), int) else 0


def load_manifest(path: str | None) -> set[tuple]:
    if path is None:
        return set()                      # the no-manifest row: zero findings expected
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return {(f["file"], int(f["line"]), f["rule"]) for f in data["findings"]}
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        # An unreadable manifest is NOT "nothing expected" — that would make a
        # deleted manifest read as perfect parity.
        raise ParityError(f"manifest {path} is unusable: {exc}") from exc


# --- one cell --------------------------------------------------------------

def compute(sample: str, tool: str, condition: str, panel_text: str,
            manifest: str | None) -> tuple[dict, list[str]]:
    expected = load_manifest(manifest)
    split = classify(parse_panel(panel_text), sample, tool)
    observed = set(split["observed"])
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    # Demotion is only meaningful for a finding the gate expects: an extra shown
    # as a warning is already counted as an extra, and counting it again here
    # would put one marker in two columns that mean different things.
    demoted = sorted(k for k in (expected & observed) if _sev(split["observed"][k]) != 8)
    split["demoted"] = demoted
    cell = {
        "sample": sample, "tool": tool, "condition": condition,
        "manifest": manifest,
        "expected": len(expected), "shown": len(expected & observed),
        "missing": len(missing), "extra": len(extra),
        "demoted": len(demoted), "unidentified": len(split["unidentified"]),
        "outside": len(split["outside"]), "excluded": len(split["excluded"]),
        "missing_rows": [list(k) for k in missing],
        "extra_rows": [list(k) for k in extra],
        "demoted_rows": [list(k) for k in demoted],
    }
    cell["verdict"] = "PARITY" if not (missing or extra or demoted
                                       or split["unidentified"]) else "DIVERGES"
    detail = []
    for f, ln, rule in missing:
        detail.append(f"  MISSING       {rule:<44} {f}:{ln}")
    for f, ln, rule in extra:
        detail.append(f"  EXTRA         {rule:<44} {f}:{ln}")
    for f, ln, rule in demoted:
        sev = SEVERITY.get(split["observed"][(f, ln, rule)].get("severity"), "?")
        detail.append(f"  DEMOTED({sev:<7}) {rule:<44} {f}:{ln}")
    for m in split["unidentified"]:
        detail.append(f"  UNIDENTIFIED  {'<no code published>':<44} "
                      f"{m['resource']}:{m.get('startLineNumber', 0)}")
    for m in split["outside"]:
        detail.append(f"  OUTSIDE       {str(rule_of(m)):<44} {m['resource']}")
    for m in split["excluded"]:
        detail.append(f"  EXCLUDED(§3)  {'JDT null analysis':<44} "
                      f"{m['resource']}:{m.get('startLineNumber', 0)}")
    return cell, detail


ORDER = ("sample", "tool", "condition", "expected", "shown", "missing", "extra",
         "demoted", "unidentified", "outside", "excluded", "verdict")


def cell_name(sample: str, tool: str, condition: str) -> str:
    """The recorded cell's filename. One definition: `matrix` finds a cell by
    globbing the run directory, so a second spelling here would not error — it
    would quietly leave cells out of the matrix."""
    return f"{sample.replace('/', '_')}__{tool}__{condition}.json"


def table_or_die(contract: pathlib.Path = CONTRACT) -> list[dict]:
    """§3's rows, with the path-base table checked against the manifests."""
    table = load_table(contract)
    problems = check_bases(table)
    if problems:
        raise ParityError("FIXTURE_RELATIVE disagrees with the manifests: "
                          + "; ".join(problems))
    return table


def emit(cell: dict) -> str:
    return "".join(f"{k}={cell[k]}\n" for k in ORDER)


def read_text_arg(path: str) -> str:
    try:
        return sys.stdin.read() if path == "-" else pathlib.Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ParityError(f"cannot read {path}: {exc}") from exc


def cmd_cell(args) -> int:
    table = table_or_die(pathlib.Path(args.contract) if args.contract else CONTRACT)
    manifest = args.manifest if args.manifest else resolve(args.sample, args.tool, table)
    cell, detail = compute(args.sample, args.tool, args.condition,
                           read_text_arg(args.panel), manifest)
    sys.stdout.write(emit(cell))
    for line in detail:
        print(line, file=sys.stderr)
    if args.run_dir:
        d = pathlib.Path(args.run_dir)
        d.mkdir(parents=True, exist_ok=True)
        name = cell_name(args.sample, args.tool, args.condition)
        (d / name).write_text(json.dumps(cell, indent=2) + "\n", encoding="utf-8")
        print(f"recorded {d / name}", file=sys.stderr)
    return 0


# --- the matrix ------------------------------------------------------------

MATRIX_HEAD = ("| Language | Sample | Tool | Cond. | Expected | Shown | Missing | "
               "Extra | Demoted | Verdict |\n"
               "|---|---|---|---|---:|---:|---:|---:|---:|---|\n")


def cmd_matrix(args) -> int:
    table = load_table()
    lang = {(r["sample"], t): r["language"] for r in table for t in tools_for(r)}
    cells = []
    for p in sorted(pathlib.Path(args.run_dir).glob("*.json")):
        cells.append(json.loads(p.read_text(encoding="utf-8")))
    if not cells:
        raise ParityError(f"{args.run_dir} holds no recorded cells — run `cell --run-dir` first")

    by_key = {(c["sample"], c["tool"], c["condition"]): c for c in cells}
    wanted = {(s, t, cond) for (s, t) in lang for cond in ("with", "without")}
    gaps = sorted(wanted - set(by_key))

    # #121's first acceptance criterion is that no cell reads "assumed", and an
    # un-run cell IS that cell. So every wanted row is rendered, un-run ones as
    # **not run** — a table that simply omitted them would be pasted into the
    # eval doc looking complete, which is the same failure in nicer clothes.
    out = [MATRIX_HEAD]
    for key in sorted(wanted | set(by_key),
                      key=lambda k: (lang.get((k[0], k[1]), ""), k[0], k[1], k[2])):
        sample, tool, condition = key
        c = by_key.get(key)
        name = sample if sample == WHOLE_TREE else f"`{sample}`"
        nums = ([c["expected"], c["shown"], c["missing"], c["extra"], c["demoted"]]
                if c else ["—"] * 5)
        out.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |\n".format(
            lang.get((sample, tool), "?"), name, tool, condition, *nums,
            c["verdict"] if c else "**not run**"))
    sys.stdout.write("".join(out))
    for sample, tool, condition in gaps:
        print(f"::warning::not run: {sample} {tool} {condition}", file=sys.stderr)
    print(f"\ncells={len(cells)} missing_cells={len(gaps)}", file=sys.stderr)
    return 0


# --- the wizard ------------------------------------------------------------

CLIPBOARD = (["pbpaste"], ["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"])


def clipboard() -> str | None:
    for cmd in CLIPBOARD:
        if shutil.which(cmd[0]):
            try:
                return subprocess.run(cmd, check=True, text=True, capture_output=True).stdout
            except (OSError, subprocess.CalledProcessError):
                return None
    return None


SETUP = """\
  1. Open ONLY {sample} as the workspace folder. A wider folder puts other
     samples' findings in the panel; they are reported as OUTSIDE, not counted.
  2. Condition '{condition}': {action}
  3. Install the recommended extensions, then reload the window and wait for
     the language server to settle. For TypeScript, accept the workspace
     compiler prompt — configs/editor/README.md §6 explains why no settings
     file can accept it for you.
  4. Right-click inside the Problems panel and choose 'Copy All'.
"""

ACTION = {
    "with": "the composed .vscode/settings.json IS in place.",
    "without": "DELETE .vscode/ entirely. This is the ablation — what an "
               "adopter who installed the extensions unaided actually sees.",
}


def cmd_run(args) -> int:
    table = table_or_die()
    pairs = [(r, t) for r in table for t in tools_for(r)]
    run_dir = pathlib.Path(args.run_dir)
    todo = [(r, t, c) for r, t in pairs for c in ("with", "without")]
    print(f"{len(todo)} cells across {len(pairs)} pairs. Recording into {run_dir}.")
    print("Ctrl-C stops; already-recorded cells are skipped on the next run.\n")

    for row, tool, condition in todo:
        name = cell_name(row["sample"], tool, condition)
        if (run_dir / name).exists() and not args.redo:
            print(f"[done] {row['sample']} {tool} {condition}")
            continue
        print(f"\n=== {row['language']} · {row['sample']} · {tool} · {condition} ===")
        print(SETUP.format(sample=row["sample"], condition=condition,
                           action=ACTION[condition]))
        print(f"  Expectation: {row['manifest'] or 'zero findings (README §3 has no manifest for this row)'}")
        reply = input("  [Enter] read the clipboard · [path] a saved dump · [s] skip · [q] quit: ").strip()
        if reply.lower() == "q":
            break
        if reply.lower() == "s":
            continue
        text = read_text_arg(reply) if reply else clipboard()
        if text is None:
            print("  no clipboard tool found (pbpaste/wl-paste/xclip) — save the "
                  "dump to a file and give the path", file=sys.stderr)
            continue
        try:
            cell, detail = compute(row["sample"], tool, condition, text, row["manifest"])
        except ParityError as exc:
            print(f"  {exc}", file=sys.stderr)
            continue
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / name).write_text(json.dumps(cell, indent=2) + "\n", encoding="utf-8")
        print(f"  {cell['verdict']}: shown={cell['shown']}/{cell['expected']} "
              f"missing={cell['missing']} extra={cell['extra']} demoted={cell['demoted']}")
        for line in detail:
            print(line)
    print(f"\nNow render it:  scripts/editor-parity.py matrix --run-dir {run_dir}")
    return 0


# --- the fixture corpus ----------------------------------------------------

def cmd_selftest(args) -> int:
    root = pathlib.Path(args.cases)
    dirs = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if not dirs:
        raise ParityError(f"{root} holds no cases — this corpus stopped guarding")
    failed = 0
    for case in dirs:
        # A case holding `cells/` exercises the renderer instead of the differ.
        # `matrix` is what actually produces #121's deliverable, so leaving it
        # uncovered would make this corpus claim more than it proves.
        if (case / "cells").is_dir():
            argv = ["matrix", "--run-dir", str(case / "cells")]
        else:
            # shlex, not split(): §3's Semgrep row has no sample folder, so its
            # identifier is the quoted phrase "the whole tree".
            argv = ["cell", "--panel", str(case / "panel.json"),
                    *shlex.split((case / "cmd").read_text(encoding="utf-8"))]
        want_rc = int((case / "expected.rc").read_text(encoding="utf-8").strip())
        proc = subprocess.run([sys.executable, __file__, *argv],
                              text=True, capture_output=True, check=False)
        out_file, err_file = case / "expected.out", case / "expected.err"
        if args.update:
            out_file.write_text(proc.stdout, encoding="utf-8")
            (case / "expected.rc").write_text(f"{proc.returncode}\n", encoding="utf-8")
            if err_file.exists():
                err_file.write_text(proc.stderr, encoding="utf-8")
            continue
        want_out = out_file.read_text(encoding="utf-8") if out_file.exists() else ""
        # expected.err is OPTIONAL, and present exactly where stderr carries
        # something stdout does not: the severity a finding was demoted to, which
        # path fell outside the sample, which rows were never run. Without it the
        # counts would be pinned and the detail behind them would not.
        want_err = err_file.read_text(encoding="utf-8") if err_file.exists() else None
        drifted = (proc.returncode != want_rc or proc.stdout != want_out
                   or (want_err is not None and proc.stderr != want_err))
        if drifted:
            failed += 1
            print(f"::error::case {case.name} drifted", file=sys.stderr)
            print(f"  rc: want {want_rc}, got {proc.returncode}", file=sys.stderr)
            for line in _diff_lines(want_out, proc.stdout):
                print(f"  out: {line}", file=sys.stderr)
            if want_err is not None:
                for line in _diff_lines(want_err, proc.stderr):
                    print(f"  err: {line}", file=sys.stderr)
            elif proc.stderr.strip():
                print("  stderr: " + proc.stderr.strip().replace("\n", "\n          "),
                      file=sys.stderr)
        else:
            print(f"  ok  {case.name}")
    if args.update:
        print(f"rewrote {len(dirs)} cases. Never in CI — a corpus that can rewrite "
              "its own expectations is not a corpus.", file=sys.stderr)
        return 0
    print(f"cases={len(dirs)} failed={failed}")
    return 1 if failed else 0


def _diff_lines(want: str, got: str) -> list[str]:
    w, g = want.splitlines(), got.splitlines()
    out = []
    for i in range(max(len(w), len(g))):
        a = w[i] if i < len(w) else "<absent>"
        b = g[i] if i < len(g) else "<absent>"
        if a != b:
            out.append(f"want {a!r} got {b!r}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("cell", help="compute one cell from one panel dump")
    c.add_argument("--sample", required=True, help="e.g. samples/rust, as README §3 names it")
    c.add_argument("--tool", required=True, help="the manifest's own tool key, e.g. clippy")
    c.add_argument("--condition", required=True, choices=("with", "without"))
    c.add_argument("--panel", required=True, metavar="FILE", help="the 'Copy All' dump ('-' for stdin)")
    c.add_argument("--manifest", help="override README §3's expectation (the fixture corpus uses this)")
    c.add_argument("--contract", help="read §3 from this file instead of the real contract "
                                      "(the fixture corpus uses this to feed it a bad row)")
    c.add_argument("--run-dir", help="also record the cell here, for `matrix`")
    c.set_defaults(fn=cmd_cell)

    m = sub.add_parser("matrix", help="render the recorded cells as markdown")
    m.add_argument("--run-dir", required=True)
    m.set_defaults(fn=cmd_matrix)

    r = sub.add_parser("run", help="walk a human through every cell")
    r.add_argument("--run-dir", required=True)
    r.add_argument("--redo", action="store_true", help="re-ask cells already recorded")
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("selftest", help="run the committed fixture corpus")
    s.add_argument("--cases", default="samples/editor-parity/cases")
    s.add_argument("--update", action="store_true",
                   help="rewrite every case's expectation from this run. Never in CI.")
    s.set_defaults(fn=cmd_selftest)

    args = ap.parse_args()
    try:
        return args.fn(args)
    except ParityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
