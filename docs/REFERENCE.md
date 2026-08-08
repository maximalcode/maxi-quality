# Reference

Every input, flag, exit code and rule id. For *how to adopt*, read
[`ADOPTION.md`](ADOPTION.md); for *why any of it is shaped this way*, read
[`CONCEPT.md`](CONCEPT.md).

---

## The reusable workflow — `quality.yml`

```yaml
jobs:
  quality:
    uses: maximalcode/maxi-quality/.github/workflows/quality.yml@v1
    with:
      changed-only: origin/main
```

| Input | Default | What it does |
|---|---|---|
| `languages` | `auto` | `auto` detects by lockfile/project glob. A CSV subset of `ts,dotnet,python,rust` forces it. `none` runs **Layer 2 only** — the adoption entry point for a repo that wants secrets, vulns and conventions gated before taking on Layer 1 |
| `node-version` | `24` | |
| `dotnet-version` | `10.0.x` | |
| `python-version` | `3.12` | |
| `rust-version` | `1.97.1` | Pinned toolchain for the `rust` job. Same argument as `uv-version` — hold or advance it without waiting on this repo, but the default is a **pin**, never `stable`: with `RUSTFLAGS=-Dwarnings`, a toolchain that adds a clippy lint is a breaking change |
| `uv-version` | `0.12.1` | Pinned uv for lockfile-based Python projects. Exposed so a consumer can hold or advance it without waiting on this repo — but it has a **pin** as a default, never `latest` |
| `changed-only` | *(empty)* | Base ref for new-code-only Layer 2. Empty = full scan |
| `licenses` | *(empty)* | Comma-separated SPDX allowlist. Anything outside it fails. **No default allowlist**, deliberately |
| `annotate` | `true` | Render Semgrep findings on the pull-request diff, not only in the job log. Additive — emitted after the verdict, cannot change it |
| `max-annotations` | `50` | Cap per run. GitHub drops them past an undocumented limit; the omitted count is always stated |

Detection **fails loud rather than skipping**: a `package.json` with no lockfile
at or above it, a `.csproj` no solution references, or a `Cargo.toml` with no
`Cargo.lock` at or above it stops the run. All three used to detect as "no such
language here" and go green over code nothing had opened.

The workflow also **outputs what it detected**, so a caller can assert detection
actually fired. Without that, a run is green in two very different cases — the
gate ran and passed, or every language job silently skipped.

---

## The Layer 2 action — `actions/layer2`

Used directly when you want the umbrella without the language jobs.

| Input | Default | What it does |
|---|---|---|
| `target` | `${{ github.workspace }}` | Directory to scan |
| `changed-only` | *(empty)* | Base ref; empty = full scan |
| `json-out` | *(empty)* | Also write Semgrep's JSON results here |
| `sbom-out` | *(empty)* | Write a CycloneDX 1.6 SBOM here |
| `licenses` | *(empty)* | SPDX allowlist; **fails** the scan on a violation |
| `no-fail` | `false` | Report everything, exit 0. For the standing **report**. Never set it on a gate — a gate that cannot fail is not a gate |
| `annotate` | `true` | Findings on the PR diff. `quality-report.yml` sets it `false`: that run has no pull request, and annotating a weekly full scan would attach the whole backlog to whatever commit is at HEAD |
| `max-annotations` | `50` | Cap per run, omitted count always stated |
| `semgrep-version` | `1.172.0` | |
| `gitleaks-version` | `8.30.1` | |
| `osv-scanner-version` | `v2.4.0` | |
| `gitleaks-sha256`, `osv-scanner-sha256` | *(pinned)* | **A version is not a pin.** A git tag and a release asset are both mutable, and these binaries execute in every consumer's CI. Overriding a version without its digest fails loudly on purpose |

Outputs: `semgrep`, `gitleaks`, `osv`, `licenses`, `sbom` — each the status line
from the scan summary. They read `not run` rather than empty when absent, because
an empty output renders as a blank cell in the report, which reads as *clean*.

---

## `scripts/scan.sh`

```bash
./scripts/scan.sh [TARGET_REPO] [options]
```

| Flag | What it does |
|---|---|
| `--changed-only [REF]` | New-code-only. Semgrep gets `--baseline-commit`, Gitleaks is limited to commits since REF. Default REF `origin/main` |
| `--json-out FILE` | Write Semgrep's JSON results to FILE as well |
| `--sbom FILE` | CycloneDX 1.6 SBOM. Never gates |
| `--licenses LIST` | Fail on any dependency outside this SPDX allowlist |
| `--no-fail` | Report everything, always exit 0 |
| `--annotate` | Emit GitHub workflow commands so findings render on the PR diff. Additive; cannot change the exit code |
| `--max-annotations N` | Cap the annotations (default 50). The omitted count is always reported |
| `--annotate-prefix P` | Prepended to annotated paths, for a target below the workspace root |
| `--require-tools` | Exit non-zero if a tool is unavailable instead of warning. Use in CI |
| `--skip TOOL` | Skip `semgrep`, `gitleaks` or `osv`. Repeatable |

| Exit | Meaning |
|---|---|
| `0` | clean |
| `1` | findings |
| `2` | a tool was unavailable under `--require-tools` |
| `3` | usage error, **or an unusable policy file** |

Each tool resolves as **native binary → `uvx`/`docker` → skipped with a loud
warning**. Nothing is ever silently not-run; the summary names every tool and its
verdict.

**The `uvx` and `docker` fallbacks are pinned to the same Semgrep the CI action
installs**, and `check-pins.sh` asserts all three sites agree. They were not
pinned at all before #43 — a bare `uvx semgrep` and `returntocorp/semgrep:latest`
— which is why a parse failure could be irreproducible between two local runs
minutes apart. A **native** `semgrep` already on `PATH` is whatever the machine
has and cannot be pinned from here; the scan warns when its version differs from
the baseline's.

---

## The policy file

`.maxi-quality.yml` at the root of the consuming repo. Entirely optional — with
no policy file nothing changes and no YAML parser is needed.

```yaml
version: 1                                   # optional; 1 is the only value
rules:
  groups: [general, security, conventions]   # default: all three
  disable: [no-float-for-money]              # never runs, never reports
  warn:    [todo-without-issue]              # reported, does not fail the build
paths:
  exclude: [legacy]                          # semgrep skips these
extends: .maxi-quality/rules                 # your own rules, same gate
```

| Key | Type | Default |
|---|---|---|
| `version` | int | `1` |
| `rules.groups` | list of `general` \| `security` \| `conventions` | all three |
| `rules.disable` | list of rule ids | `[]` |
| `rules.warn` | list of rule ids | `[]` |
| `paths.exclude` | list of patterns | `[]` |
| `extends` | path relative to the repo root | *(none)* |

### What is a hard error

Every one of these stops the run with exit 3 rather than being applied partially:

- an unknown key at any level
- an unknown rule id in `disable` or `warn`, or one belonging to a group that is
  not selected
- an unknown group name
- the same rule id in both `disable` and `warn`
- `extends` pointing at a directory that does not exist, or outside the repo
- `groups: []` with no `extends` — that would run no rules at all
- a `version` other than `1`
- a `paths.exclude` entry containing `**` (see below)

That strictness is the whole design. Every silent-knob bug this repo has shipped
looked identical to a working config from the outside.

### Two gotchas, both measured

**Write `legacy`, not `legacy/**`.** Semgrep's `--exclude` matches path
components, not globs. The glob spelling every other tool accepts excludes nothing
and reports nothing about it, so the policy file rejects it and names the working
form. `legacy`, `legacy/` and `samples/policy` all work; `./legacy` and
`*/legacy/*` do not.

**A disabled rule is verified to have actually gone.** `--exclude-rule` matches
the full path-prefixed `check_id`, and the prefix follows the `--config` path — so
the string differs between the native and docker code paths for the very same
rule. The resolver computes it and then asserts, after the scan, that no disabled
rule survived into the results. If that assertion trips the run fails rather than
applying half a policy.

### What is deliberately not configurable

Gitleaks and OSV-Scanner. A leaked credential and a known CVE are not matters of
local policy. There is likewise no key that makes the gate advisory — `--no-fail`
exists for the standing report, and only for that.

### `scripts/policy.py`

| Command | What it does |
|---|---|
| `resolve --target T --baseline B [--baseline-path P] [--explain] [--out F]` | Validate and write the resolved policy. `--explain` adds the effective gate/warn rule id sets — the snapshot form |
| `args --resolved F --baseline-path P --target-path P` | Print the semgrep arguments, one per line |
| `classify --resolved F --results F [--annotate] [--max-annotations N] [--annotate-prefix P]` | Split findings into gating and warn-only; exit 1 if anything gates. `--annotate` additionally prints GitHub workflow commands — after the verdict is decided, from the same classification, so it cannot reach the exit code |

Exit codes: `0` clean/valid · `1` gate findings · `2` a mechanism failed
(unreadable results, a semgrep error that is not a per-file parse failure, every
file unparseable, an exclusion that did not take) · `3` usage or policy error.

### Files Semgrep cannot parse

A parse failure is **a coverage gap, not a scan failure** (#43). The two used to
be the same thing, and a codebase using C# 12 primary constructors —
`public sealed class Thing(Dep dep)`, which Semgrep's C# parser rejects — turned
a clean scan into a red gate:

```
Ran 22 rules on 29 files: 0 findings.
error: semgrep reported 6 error(s); refusing to treat the result as a finding set
```

Red on green code, for a reason no consumer can fix. And the worse half had no
output at all: **a file that does not parse has no rule run against it**, so
those files were contributing 0 to every number while looking like a failure
rather than a hole.

Now they are listed by name, counted as `semgrep_unparsed=N`, carried onto the
scan summary line (`semgrep  clean (3 file(s) UNPARSED)`) and given their own
section in the standing report — and they do not gate.

Two guards stop that becoming the silent pass it would otherwise be:

- **The recognised list is an allowlist.** `PartialParsing`, `SyntaxError`,
  `LexicalError`, `Timeout`, `OutOfMemory` and the interfile variants are
  per-file. Anything else — a rule that would not load, an unknown language, a
  failure type a future Semgrep invents — is still exit 2.
- **If every file Semgrep looked at failed to parse, the run exits 2.**
  `results: []` then means "nobody looked", which is precisely the shape that
  must never read as clean.

Measured 2026-08-05: semgrep `1.172.0` is the newest release on PyPI and
`1.145.0` behaves identically, so upgrading is not an available fix.

---

## The ruleset — 12 conventions, 28 rule ids

Semgrep patterns are language-specific, so a convention whose C#, TypeScript and
Python syntax differ needs one rule id per language with an identical message.
That is why 12 conventions produce 28 ids. **The cap is on conventions, and it is
12, hard** — new ones get added when a real bug slips through, never
speculatively.

The **Py** column is not a Semgrep column. Ruff already covers half of these
conventions outright, and a Semgrep rule for something Layer 1 already catches is
a second finding on one line, not more coverage — so where Ruff has it, the cell
names the Ruff rule and there is no Semgrep id.

| Convention | Rule id(s) | TS | C# | Py |
|---|---|:--:|:--:|:--|
| **general** | | | | |
| TODO without a tracked issue | `todo-without-issue` | ✅ | ✅ | ✅ |
| Empty catch block | `catch-and-swallow-{ts,dotnet}` | ✅ | ✅ | ruff `SIM105` |
| Printf-debugging left behind | `debug-print-left-behind-{ts,dotnet}` | ✅ | ✅ | ruff `T201` |
| Blocking on a Task | `sync-over-async` | — | ✅ | ruff `ASYNC251` |
| **security** | | | | |
| SQL built by concat/interpolation | `sql-string-concat-{ts,dotnet}`, `sql-string-concat-builder-{ts,dotnet}` | ✅ | ✅ | ruff `S608` |
| Shell command from interpolation | `command-injection-{ts,dotnet}`, `command-injection-indirect-{ts,dotnet}` | ✅ | ✅ | ruff `S602` |
| MD5/SHA1/DES/RC4, any case, all DES variants | `weak-crypto` | ✅ | ✅ | ruff `S324` |
| Secret-named var assigned a literal | `hardcoded-secret-{ts,dotnet,python}` | ✅ | ✅ | ✅ |
| **conventions** (mine) | | | | |
| Ambient clock instead of injected | `no-ambient-clock`, `no-ambient-clock-python` | ✅ | ✅ | ✅ |
| Mutation without an authz gate | `mutation-requires-authz-{ts,dotnet,python}` | ✅ | ✅ | ✅ |
| 403 for an invisible resource | `no-permission-denied-for-invisible-resource-{ts,dotnet,python}` | ✅ | ✅ | ✅ |
| double/float for money | `no-float-for-money`, `no-float-for-money-python` | — | ✅ | ✅ |

`no-ambient-clock` and `weak-crypto` are single rule ids covering TypeScript and
C# together — that is the concept §10 criterion (*the same rule fires in a TS and
a C# sample*). Python does not join them in one id: every pattern in a rule must
parse in every language it declares, and `DateTime.UtcNow` is not Python.

**`hardcoded-secret-python` is the one Python rule that overlaps Ruff on
purpose.** S105 covers most of the convention, with one measured hole —
`CONNECTION_STRING = "postgres://admin:pw@host"` — which is exactly the shape the
TS and C# value guard was built to keep firing. It carries a **fourth** value
guard the other two do not: measured over 4,133 files of Django, Celery,
SQLAlchemy, Flask and httpx, prose in a secret-named constant was the largest
false-positive class the first three guards left, and a credential does not
contain a space.

**A ✅ means every shape the rule advertises, and that is measured.** These rules
match raw source text in places, so quote style is not interchangeable:
`sql-string-concat-ts` and `command-injection-ts` each cover backtick,
double-quoted and single-quoted forms, `sql-string-concat-ts` covers Prisma's
`$queryRawUnsafe` and `$executeRawUnsafe` alongside `.query` / `.execute` /
`.raw`, and `sql-string-concat-dotnet` covers Dapper's four entry points and
`CommandText` as well as `new SqlCommand`. Each of those branches has its own
fixture, so one going quiet shows up as a named missing finding rather than as a
total that still looks about right.

**Two conventions carry a second rule id for the same bug one step away from the
sink.** The sink-anchored rules require the concatenation to sit syntactically
inside the query or exec call, so binding it to a local variable one line up
silenced all of them. The two halves close it differently, and the difference is
the point:

- **SQL** drops the sink and matches the *string* — a literal carrying a SQL
  keyword, concatenated or interpolated, wherever it is built. That reaches a
  helper function as well as a local.
- **Commands** cannot do that: `"ls -la " + dir` and `"Hello " + name` are the
  same shape, so a sink-free command rule is a rule against string concatenation
  and gets switched off. It uses Semgrep's taint mode instead, keeping the sink.

Which leaves one measured gap, stated rather than papered over: **Semgrep OSS
taint is intraprocedural.** It crosses a local variable and not a function call,
so `exec(buildCommand(dir))` is still silent. Interprocedural taint is a Semgrep
Pro feature, and the one free tool in the eval that reached it — CodeQL — cannot
run against a private repo at all
([`EVAL-vs-oss-tools.md`](EVAL-vs-oss-tools.md) §0). The gap has a fixture of its
own in `samples/semgrep/`, kept silent on purpose, so the day something free does
reach it the manifest is where that shows up.

**Division of labour with Gitleaks:** Gitleaks catches secrets whose *shape* is a
known token (AWS keys, GitHub PATs, JWTs). `hardcoded-secret-*` catches the
homegrown ones it cannot fingerprint, by matching the variable **name** instead.

---

## The coverage action — `actions/coverage`

| Input | Default | What it does |
|---|---|---|
| `report` | *(required)* | One or more paths/globs. lcov and Cobertura, detected **by content, not filename** |
| `raise` | `false` | Rewrite the floor file when coverage improved. Does **not** commit it |

Outputs: `coverage`, `floor` (`none` when there was none), `raised`.

Four things are errors rather than passes, because each one turns the ratchet
permanently green: zero measurable lines, a missing report, an unparseable floor,
and no floor at all.

---

## Where the numbers live

- Adoption cost measured on real codebases — [`STATUS.md`](STATUS.md) §5
- Decisions and gotchas worth not rediscovering — [`STATUS.md`](STATUS.md) §4
- This baseline vs the free field, ten tools scored — [`EVAL-vs-oss-tools.md`](EVAL-vs-oss-tools.md)
- This baseline vs a Sonar server — [`EVAL-vs-sonarqube.md`](EVAL-vs-sonarqube.md)
