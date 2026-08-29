# `samples/editor-parity` — the fixture corpus for `scripts/editor-parity.py`

This directory proves the *differ*, not the editor.

`configs/editor/` is the one place in this repo where a config cannot be proven
by a sample, because there is no headless VS Code (`CLAUDE.md` §5). That
exemption covers **what the settings do inside an editor** and nothing else, so
the arithmetic performed on an observation is ordinary code with an ordinary
fixture corpus — which is what this is.

Most cases exercise the differ. Each is a directory holding five files:

| File | What it is |
|---|---|
| `panel.json` | a VS Code Problems-panel dump, as "Copy All" produces it |
| `expected.json` | the manifest that dump is diffed against (hermetic — see below) |
| `cmd` | the arguments passed after `editor-parity.py cell --panel …` |
| `expected.out` | the exact stdout the run must produce |
| `expected.rc` | the exact exit code |

`expected.err` is optional and present only where stderr carries something
stdout does not — the severity a finding was demoted to, which path fell outside
the sample, which marker published no rule id. Without it the counts would be
pinned and the detail behind them would not.

**A case holding a `cells/` directory exercises the renderer instead**, with
`matrix --run-dir cells/` and the same two expectation files. `matrix` is what
produces #121's actual deliverable, so a corpus that only covered the arithmetic
would claim more than it proves.

Run them:

```bash
python3 scripts/editor-parity.py selftest
```

## Why most cases carry their own manifest

`expected.json` inside a case is a two-or-three-finding manifest written for
that case, not one of the real `samples/expected/` files. That is deliberate:
otherwise editing `samples/rust` — which `CONTRIBUTING.md` expects to happen and
`--update` exists to absorb — would break this corpus for a reason that has
nothing to do with the differ.

**`table-resolution` is the deliberate exception.** It passes no `--manifest` at
all, so it resolves `samples/rust` + `clippy` out of `configs/editor/README.md`
§3 and diffs against the real `samples/expected/clippy.json`. Its `expected.out`
therefore names the real finding count, and a change to the Rust fixture *will*
break it. That is the point — it is the one case proving the contract table is
read live rather than hardcoded, and the fix is one number in one file.

## What each case pins

| Case | The bug it catches |
|---|---|
| `parity` | the baseline: a panel matching the manifest reads `PARITY` |
| `ablation` | the settings removed — every finding missing, the measurement #121 is for |
| `demoted` | a finding present at **warning** severity. It is shown *and* demoted; a count of panel rows cannot tell those apart |
| `extra` | a finding the gate never produces — the "panel louder than the gate" direction ADR 0002 turns on |
| `unidentified` | a marker whose extension published no rule id. Counted, never dropped |
| `outside` | a marker from a different sample folder. Reported, not folded into this pair's diff |
| `jdt-excluded` | JDT's own null analysis, which README §3 excludes by name. It must not become an `extra`, and the real NullAway finding must still read as missing (§4) |
| `malformed` | a dump that is not a "Copy All" JSON array — exit 3, never a silent empty panel |
| `repo-relative` | the fourteen §3 rows written repo-relative, against the six written fixture-relative (three tools: clippy, knip, deptry) |
| `whole-tree` | §3's Semgrep row names no sample folder — its cell has to anchor on the checkout instead, and a path from some other tree must read as `outside` rather than as a finding |
| `duplicate-severity` | the same rule id published twice at two severities. Present at error is not demoted because something else also warned, and an extra shown as a warning is not counted in two columns at once |
| `unanchorable-sample` | a §3 row whose sample cell is prose this tool cannot anchor. Exit 3, rather than a cell computed against nothing |
| `table-resolution` | §3 is parsed live; a stubbed resolver fails here |
| `matrix-render` | the rendered table: language grouping, row order, and the verdict column — a renderer that printed `PARITY` for every row would read as a finished, successful run |

Every one of these was verified by deliberately breaking the code and
confirming the case turns red — including the base-convention guard, which is
the failure that does *not* announce itself: a wrong path base reports every
finding as both missing and extra, which reads like a total parity failure
rather than like a bug in the tool.
