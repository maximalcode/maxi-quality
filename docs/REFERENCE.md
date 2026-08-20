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
| `languages` | `auto` | `auto` detects by lockfile/project glob. A CSV subset of `ts,dotnet,python,rust,java` forces it. `none` runs **Layer 2 only** — the adoption entry point for a repo that wants secrets, vulns and conventions gated before taking on Layer 1 |
| `node-version` | `24` | |
| `dotnet-version` | `10.0.x` | |
| `python-version` | `3.12` | |
| `rust-version` | `1.97.1` | Pinned toolchain for the `rust` job. Same argument as `uv-version` — hold or advance it without waiting on this repo, but the default is a **pin**, never `stable`: with `RUSTFLAGS=-Dwarnings`, a toolchain that adds a clippy lint is a breaking change |
| `java-version` | `25` | Pinned JDK for the `java` job. A **pin** for the same reason `rust-version` is one, only more so: Error Prone reaches into javac internals that move between releases, and with `-Werror` in the compiler args a JDK that adds an `-Xlint` category is a breaking change |
| `uv-version` | `0.12.3` | Pinned uv for lockfile-based Python projects. Exposed so a consumer can hold or advance it without waiting on this repo — but it has a **pin** as a default, never `latest` |
| `changed-only` | *(empty)* | Base ref for new-code-only Layer 2, and the ratchet for the dead-code gate. Empty = full scan |
| `dead-code` | `auto` | knip on TypeScript packages, deptry on Python ones. `auto` runs each where the project has it installed and **warns loudly** where it does not; `require` makes a missing tool a failure; `off` skips it. See below for why the default is the soft one |
| `dead-code-exports` | `false` | Also gate unused exports and types (knip). **Application code only** — in a published library an unreferenced export is public API |
| `licenses` | *(empty)* | Comma-separated SPDX allowlist. Anything outside it fails. **No default allowlist**, deliberately |
| `annotate` | `true` | Render Semgrep findings on the pull-request diff, not only in the job log. Additive — emitted after the verdict, cannot change it |
| `max-annotations` | `50` | Cap per run. GitHub drops them past an undocumented limit; the omitted count is always stated |
| `runner` | `ubuntu-latest` | The `runs-on` label for every job. Point it at `self-hosted` when GitHub-hosted minutes are the thing that can make the gate go dark |
| `coverage-report` | *(empty)* | **Name of an artifact** uploaded earlier in the same run. Set it and the coverage gate runs — the aggregate ratchet plus the patch gate. Empty means there is no coverage job in the graph at all. Requires `needs:` from your test job |
| `coverage-floor-file` | `.maxi-quality/coverage.json` | The committed floor, in **your** repo |
| `coverage-patch-threshold` | `50` | Minimum coverage of the lines the change **adds**. `0` keeps the measurement and drops the gate |
| `coverage-raise` | `false` | One-time bootstrap: record the floor instead of demanding one, and print the file to commit. It does **not** commit for you |

Detection **fails loud rather than skipping**: a `package.json` with no lockfile
at or above it, a `.csproj` no solution references, or a `Cargo.toml` with no
`Cargo.lock` at or above it stops the run. All three used to detect as "no such
language here" and go green over code nothing had opened.

Java adds two of the same shape. A **`build.gradle[.kts]` with no `pom.xml`**
stops the run — the Java layer is Maven-only in v1, and "no Java here" is a lie
about a repo that plainly has some. And a **`pom.xml` carrying no
`maxi-quality:begin` region** stops it too: that project builds perfectly and
analyses nothing, so `mvn compile` would be green over code Error Prone never
opened. Both are escapable the same way every other loud check is — pass
`languages:` without `java` to skip them deliberately.

The Java matrix unit is a **root POM**, meaning one that no other POM lists in
its `<modules>`. Maven builds an aggregator and its modules in one reactor, and
`<build><plugins>` in an aggregator is inherited by its modules, so keying on
every `pom.xml` would analyse the same tree once per module.

The workflow also **outputs what it detected**, so a caller can assert detection
actually fired. Without that, a run is green in two very different cases — the
gate ran and passed, or every language job silently skipped.

---

## The dead-code gate — `actions/deadcode`

Runs inside the `typescript` and `python` jobs. Two tools, each adopted with a
measured condition attached, and the conditions are what this action encodes.

| Tool | Language | Gates | Reports but does not gate |
|---|---|---|---|
| knip | TypeScript | `files`, `dependencies`, `unlisted` | `exports`, `types` (unless `dead-code-exports: true`), and every other issue type knip reports |
| deptry | Python | `DEP001` (imported, not declared), `DEP002` (declared, not imported) | `DEP003`, `DEP004` |

The gating sets are deliberately narrower than what each tool reports: they are
exactly the issue types the evaluation measured. Widening one is a decision with
a measurement attached, not an edit.

**It is not an AI-slop detector.** There is no mechanical signature for model
authorship, and every check here names a falsifiable failure instead. What the
evaluation did observe is that every *other* gate in this baseline answers "is
this code wrong?", and a file nobody imports compiles, type-checks, passes
clippy and ships.

### What it refuses to do

| Situation | What happens |
|---|---|
| knip older than `6.31.0` | **Hard error, in every mode.** 5.64.3 reported signature-only types as unused exports; a gate that fails on a finding which is not real is one people learn to ignore |
| No knip config in the package | **Hard error.** A zero-config run on a non-default layout reports your layout, not your defects. `adopt.sh` writes a `knip.json` stub; the entry points are yours to declare |
| The tool is not installed | `auto` warns and passes · `require` fails |
| No Python package under the directory declares dependencies | Same as above — never a clean scan. "Nothing was examined" and "nothing was found" must not render identically |
| `changed-only` base ref cannot be resolved | **Hard error.** Gating everything would fail the build on the backlog the ratchet exists to grandfather; gating nothing would be a switched-off check. Both are wrong answers, so it stops |

### Why the default is `auto`

`v1` is a moving tag: a merge to `main` ships to every consumer pinning it. A
gate that arrived as a hard requirement would red every already-adopted repo the
morning it landed, for a tool they had no reason to have installed. So the
default warns, `require` is the opt-out, and a green build under `auto` with the
tool absent says nothing about dead code — which the warning states in those
words.

### The ratchet

`changed-only` filters the **results**, not the inputs. Neither tool takes a
file list — reachability is a whole-graph question — so the scan is always full,
everything is reported, and only findings in files changed since the base ref can
fail the build.

The honest limit: deleting the last import of an untouched file makes that file
dead without changing it, so under `changed-only` that finding is advisory. It is
the trade-off Layer 2's `--baseline-commit` already makes, one graph edge further
out.

### Python granularity

deptry runs **per package, never at a workspace root** — measured at a monorepo
root it reported 125 findings, 118 of them one first-party artifact, versus 3 at
the granularity it is designed for. `scripts/deptry-targets.py` enumerates the
packages under the detected directory and excludes each package's nested
packages from its own scan; `samples/deptry-workspace/` proves both halves,
including the ablation that a naive root run is *not* clean.

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
| `osv-scanner-version` | `v2.5.0` | |
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

## The ruleset — 12 conventions, 40 rule ids

Semgrep patterns are language-specific, so a convention whose C#, TypeScript,
Python and Java syntax differ needs one rule id per language with an identical
message.
That is why 12 conventions produce 40 ids. **The cap is on conventions, and it is
12, hard** — new ones get added when a real bug slips through, never
speculatively.

**The Py and Java columns are not pure Semgrep columns.** Ruff already covers
half of these conventions for Python, and Error Prone covers three of them for
Java. A Semgrep rule for something Layer 1 already catches is a second finding on
one line, not more coverage — so where the Layer 1 analyzer has it, the cell
names that check and there is no Semgrep id. The Java column was decided by
planting each shape and reading Error Prone's actual output (2026-08-09), not by
reading its check list.

| Convention | Rule id(s) | TS | C# | Py | Java |
|---|---|:--:|:--:|:--|:--|
| **general** | | | | | |
| TODO without a tracked issue | `todo-without-issue` | ✅ | ✅ | ✅ | ✅ |
| Empty catch block | `catch-and-swallow-{ts,dotnet}` | ✅ | ✅ | ruff `SIM105` | EP `EmptyCatch` |
| Printf-debugging left behind | `debug-print-left-behind-{ts,dotnet,java}` | ✅ | ✅ | ruff `T201` | ✅ |
| Blocking on async work | `sync-over-async`, `sync-over-async-java` | — | ✅ | ruff `ASYNC251` | ✅ |
| **security** | | | | | |
| SQL built by concat/interpolation | `sql-string-concat-{ts,dotnet,java}`, `sql-string-concat-builder-{ts,dotnet,java}` | ✅ | ✅ | ruff `S608` | ✅ |
| Shell command from interpolation | `command-injection-{ts,dotnet,java}`, `command-injection-indirect-{ts,dotnet,java}` | ✅ | ✅ | ruff `S602` | ✅ |
| MD5/SHA1/DES/RC4, any case, all DES variants | `weak-crypto`, `weak-crypto-java` | ✅ | ✅ | ruff `S324` | ✅ |
| Secret-named var assigned a literal | `hardcoded-secret-{ts,dotnet,python,java}` | ✅ | ✅ | ✅ | ✅ |
| **conventions** (mine) | | | | | |
| Ambient clock instead of injected | `no-ambient-clock`, `no-ambient-clock-{python,java}` | ✅ | ✅ | ✅ | partly ✅, partly EP |
| Mutation without an authz gate | `mutation-requires-authz-{ts,dotnet,python,java}` | ✅ | ✅ | ✅ | ✅ |
| 403 for an invisible resource | `no-permission-denied-for-invisible-resource-{ts,dotnet,python,java}` | ✅ | ✅ | ✅ | ✅ |
| double/float for money | `no-float-for-money`, `no-float-for-money-{python,java}` | — | ✅ | ✅ | ✅ |

**The two split cells in the Java column are the overlap audit, measured.**
Error Prone's `EmptyCatch` is on by default, so `catch-and-swallow-java` was not
written — the compiler already fails the build on that line. The ambient-clock
row is split because Error Prone covers only *part* of the convention:
`new Date()` is `JavaUtilDate` and `LocalDate.now()` / `LocalDateTime.now()` are
`JavaTimeDefaultTimeZone`, while `Instant.now()` (zone-independent, so
`JavaTimeDefaultTimeZone` allows it) and `System.currentTimeMillis()` are covered
by nothing. `no-ambient-clock-java` matches exactly those two and deliberately
not the other three.

**`mutation-requires-authz-java` exempts `@PreAuthorize`, `@Secured` and
`@RolesAllowed`, and that is load-bearing rather than convenient.** In a Spring
codebase the annotation *is* the authorisation check — enforced by a method
interceptor before the body runs — so a rule that only knew about an explicit
gate call would fire on every correctly-secured service in the repo. Each
exemption has a counterexample in `samples/semgrep/UserService.java` that must
stay silent, and a sibling that must fire.

**`sync-over-async-java` has two branches with different precision, on purpose.**
`.block()` / `.blockFirst()` / `.blockLast()` exist on Reactor types and nowhere
else, so they carry no guard. `.join()` and `.get()` are guarded by a regex on
the receiver's *name*, because `Optional.get()`, `Map.get()` and `Thread.join()`
are everywhere and an unguarded rule would fire on most lines of most Java files.
That is a heuristic, and it is stated as one: it catches `resultFuture.get()` and
misses `f.get()`. The precise version needs type information Semgrep OSS does not
have.

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

Two gates, one action. The **aggregate ratchet** asks *did this change make it
worse?* The **patch gate** asks *are the lines this change added tested?* — the
question the aggregate structurally cannot answer, because one new untested
function inside a large well-covered repo moves the aggregate by rounding error.

| Input | Default | What it does |
|---|---|---|
| `report` | *(required)* | One or more paths/globs. lcov and Cobertura, detected **by content, not filename** |
| `floor-file` | `.maxi-quality/coverage.json` | The committed floor the aggregate is compared against |
| `tolerance` | `0.1` | Percentage points of slack on the aggregate, for rounding noise between runs |
| `raise` | `false` | Rewrite the floor file when coverage improved. Does **not** commit it |
| `patch-threshold` | `50` | Minimum coverage of the added lines. `0` keeps the measurement and drops the gate |
| `base-ref` | *(empty)* | What the change is measured against. Empty auto-detects the PR base. A shallow checkout is deepened rather than reported as "no base" |

Outputs: `coverage`, `floor` (`none` when there was none), `raised`,
`patch-coverage`, `patch-status`.

`patch-status` is the one to read: `ok`, `below`, `off` (threshold `0`), `n/a`
(nothing measurable changed) or `no-base` (the base could not be resolved).

**A change with no measurable added lines is `n/a`, never 0% and never 100%.** A
docs-only PR has no denominator, and a percentage is not an answer to that
question: 0% gates on something no test can fix, 100% gates on a lie.

Four things are errors rather than passes, because each one turns the ratchet
permanently green: zero measurable lines, a missing report, an unparseable floor,
and no floor at all.

---

## Where the numbers live

- Adoption cost measured on real codebases — [`STATUS.md`](STATUS.md) §5
- Decisions and gotchas worth not rediscovering — [`STATUS.md`](STATUS.md) §4
- This baseline vs the free field, ten tools scored — [`EVAL-vs-oss-tools.md`](EVAL-vs-oss-tools.md)
- This baseline vs a Sonar server — [`EVAL-vs-sonarqube.md`](EVAL-vs-sonarqube.md)
