# Layer 1 preflight

Find out what adopting Layer 1 would report before changing your checkout or
adding a CI gate:

```bash
python3 "$BASELINE/scripts/preflight.py" /path/to/repo
python3 "$BASELINE/scripts/preflight.py" /path/to/repo --format json
```

Requires Python 3.12+. Each tool invocation has a 180-second limit; use
`--timeout 600` for a larger build. Usage errors, missing tools, malformed
configuration, findings and timeouts all exit **zero**. The report's `status`
is the outcome. The operating system must still be able to start Python; a
runner cancellation or an unavailable interpreter is outside this command.

## Prepare the toolchain

Use a checkout that builds normally, with its dependencies installed. Preflight
uses the tools already installed on your machine and the active Python
environment. It does not provision SDKs or install project dependencies.

| Language | Needed locally | Measured |
|---|---|---|
| TypeScript | Node, `npm ci` in **the baseline checkout**, project `node_modules` | ESLint, strict TypeScript compiler, Prettier |
| Python | `ruff` and `mypy` on PATH; project packages and stubs in that environment | Ruff, strict mypy, Ruff formatting |
| C# | .NET SDK compatible with the project | Roslyn compiler/analyzers through SARIF, whitespace formatting |
| Rust | Cargo, Clippy, rustfmt, a lockfile | Workspace Clippy and rustc diagnostics, formatting |
| Java | Maven and JDK compatible with the baseline (currently JDK 25) | Error Prone, NullAway, javac lint, Spotless |

For Python, the baseline's measured versions are in
[`samples/python/requirements-dev.txt`](../samples/python/requirements-dev.txt).
Install those into your analysis environment if needed. Maven and .NET may
restore analyzer packages as part of their normal build. Cargo may fetch
dependencies for the locked graph. None requires a paid service.

The command is suitable for a normal shell step in an existing workflow after
its toolchain setup. There is no `quality.yml` report-only input: setup failures
in that gating workflow would still turn CI red. The local command owns and
catches its analysis failures instead.

## Read the result

Each language has counts and individual checks, followed by a row for every
reported rule. Compiler and linter diagnostics are counted separately even if
they describe the same defect. Repeated compiler emissions of the same rule at
the same file, line and column are deduplicated. A formatter finding counts a
**file**, not each changed line. These are effort indicators, not estimates of
engineering hours or numbers of confirmed bugs.

- **complete** means the measured checks finished. Zero then means zero
  diagnostics in the scanned scope.
- **incomplete** means at least one check could not finish. Counts are lower
  bounds; zero never means the code is clean. Each check names its reason.
- **unavailable** on an individual check means it could not produce a usable
  report. Other languages still run.

Compiler failures are conservative: .NET, Cargo and Maven may stop before all
projects or source sets are analyzed. Java's `-Xlint` plus `-Werror` interaction
can stop Error Prone entirely; that condition gets its own explanation. Fix
the blocking compilation/configuration issue and rerun for the next findings.
An empty directory or unsupported-only checkout is incomplete, not clean.

## What is changed in the copy

The original source and config files are not edited. A temporary copy includes
uncommitted files and installed `node_modules`; it is deleted after reporting.
Git metadata, virtual environments, caches and common build directories
(`bin`, `obj`, `target`, `dist`, `build`, `coverage`) are excluded. Internal
symlinks are redirected into the copy; external symlinks are refused with an
incomplete report. Use a self-contained checkout when a project imports sibling
directories. The active Python environment supplies packages omitted from the
copy.

This is filesystem staging, not a security sandbox. Run it on code you trust
to build: custom build scripts, absolute output paths and toolchain caches keep
their normal effects. It installs no workflow, changes no policy and commits
nothing.

The preview applies the shipped baseline rather than trusting a permissive
existing linter configuration:

- TypeScript keeps project module/target/library/path choices (including inherited
  settings) and imposes the baseline's strict compiler flags. ESLint and Prettier
  use the baseline config. Prettier follows `.gitignore` and `.prettierignore`
  and includes its supported JSON, YAML, Markdown and other file types.
- Python uses the baseline Ruff and mypy configs explicitly. Local per-file
  waivers and mypy plugin/override sections are not composed automatically.
- C# imports the baseline into each copied project and supplies its editor
  settings. Each project/framework writes a distinct SARIF report.
- Rust passes the shipped lint levels to Clippy for every workspace target.
- Java uses the existing POM region merger. An existing compiler plugin outside
  the managed region, or no `<build><plugins>` insertion point, requires a manual
  merge in a disposable checkout; preflight says so and reports no clean verdict.
  NullAway retains the baseline's groupId-based annotated-package assumption.

Gradle, yarn and bun are explicitly unsupported. Optional knip/deptry checks and
dependency audits are outside these counts; they are separate adoption decisions.

## The classification is a policy, not severity

[`scripts/preflight-rules.json`](../scripts/preflight-rules.json) is the explicit
mapping. Every key is `tool/rule-id`; the runtime uses exact lookup only.

- **bug-class**: a possible correctness, safety or security defect, including
  unsafe typing. A warning can be bug-class; an error can be stylistic.
- **stylistic**: formatting, naming, consistency, unused code, modernization,
  maintainability and typing-coverage requirements. This category describes
  adoption work, not a claim that the rule is unimportant.
- **unclassified**: a rule without a mapping. It gets its own visible count and
  row. New analyzer rules cannot silently inflate either category.

For the pinned ESLint ecosystem, the starting point is the rule's documented
[`meta.type`](https://eslint.org/docs/latest/extend/custom-rules#rule-structure):
`problem` maps to bug-class; `suggestion` and `layout` map to stylistic.
Explicit judgement overrides include `eqeqeq` and promise-safety rules as
bug-class, and unused variables, `no-console` and explicit-any declarations as
stylistic. The table is committed, not recomputed from a future tool release.

Ruff starts from the selected families' purposes: security/async correctness,
Pyflakes and Bugbear defects versus naming/import order/simplification/upgrade
work. Individual exceptions such as unused imports, constant `getattr`, invalid
escape sequences and Ruff's mixed RUF family are mapped explicitly. Compiler,
mypy, Roslyn and Clippy mappings cover known diagnostics individually; unmapped
diagnostics remain visible. Rule descriptions are available in the tools'
official catalogs: [Ruff](https://docs.astral.sh/ruff/rules/),
[mypy](https://mypy.readthedocs.io/en/stable/error_code_list.html),
[Clippy](https://rust-lang.github.io/rust-clippy/master/),
[.NET](https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/overview),
[Error Prone](https://errorprone.info/bugpatterns).

The historical 0.7% / 7.9% adoption figures were manual classifications on
particular codebases. This rule-level taxonomy is not a reproduction of those
judgements, and its percentages should not be compared to them as if the
measurement method were identical.
