# Security

## The fake credentials in `samples/` are deliberate

`samples/semgrep/` contains **planted, non-functional secrets**. They are bait
for the `hardcoded-secret-*` Semgrep rules, and CI asserts that those rules fire
on them — if a scanner stops flagging that directory, this baseline has
regressed.

So: **a secret scanner run against this repository will report findings, and
that is the intended state.** Every one of them is in `samples/`. None has ever
been valid anywhere.

If you scan a clone with Gitleaks, `.gitleaks.toml` in the repo root
path-allowlists exactly that directory and Gitleaks loads it automatically. For
other scanners, exclude `samples/` — that is the whole story.

GitHub's own secret scanning is told the same thing by
[`.github/secret_scanning.yml`](.github/secret_scanning.yml), because one of the
fakes is deliberately written in GitHub's `ghp_` provider shape. That file
governs **alerts only**; push protection is a separate setting and still
evaluates every push, so an edit that moves one of those strings can be blocked
at push time and has to be allowed explicitly.

There is deliberately no `.gitleaksignore`. It works by **fingerprint**
(`commit:file:rule:line`), so every entry is invalidated by any history rewrite
or line shift — a suppression file that silently stops suppressing is worse than
none. The path allowlist survives both.

## The vulnerable dependency in `samples/rust/` is deliberate

`samples/rust/Cargo.lock` pins `smallvec 1.6.0`, which carries
**RUSTSEC-2021-0003** (buffer overflow in `insert_many`, fixed in 1.6.1). It is
bait for the cargo-deny advisories gate, and CI asserts that exact id fires —
same contract as the fake credentials above. Two things make it safe: the
dependency sits behind a `cfg(windows)` target gate, so no CI run ever
downloads or compiles it (the lockfile entry alone is what cargo-deny reads),
and nothing in this repository executes any code from it. OSV-Scanner needs no
action — `samples/rust/osv-scanner.toml` ignores exactly that advisory, scoped
to the fixture directory, and is loaded automatically (the `.gitleaks.toml`
pattern). Other dependency scanners **will** report it; that is the intended
state, and the same advice applies — exclude `samples/`.

## Reporting a vulnerability

Open a **private security advisory** through the repository's Security tab. That
keeps the report non-public until there is something to say.

Please do not open a public issue for a vulnerability in the rules themselves —
notably a Semgrep pattern that can be trivially evaded, since publishing the
evasion before the fix helps nobody.

A **false negative in a rule is a security bug here.** This project exists to
catch things; a convention that quietly stops matching is the failure mode that
matters most, and it is the reason every rule has a sample that must fail.

## What this project does and does not claim

It is a **baseline**, not an assurance. It runs Semgrep, Gitleaks, OSV-Scanner
and the per-language analyzers with opinionated configuration, and it proves
against committed fixtures that those configurations still reject what they are
supposed to reject.

It does not claim completeness. The measured comparison in
[`docs/EVAL-vs-sonarqube.md`](docs/EVAL-vs-sonarqube.md) is deliberately public
about where it wins and where it does not.

## Supply chain

Everything third-party that runs in CI is pinned:

- GitHub Actions are pinned to a **full commit SHA**, never a tag, and
  `ci.yml` fails if one is not. A tag is mutable; whoever controls it can point
  it at new code that then runs in every consumer's CI with their token.
- **Nothing is fetched from the network and executed without a pin and a
  checksum.** Two halves, because one guard covers only one of them:

  - `ci.yml` fails on the fetch-and-execute shapes: `curl … | sh`, the
    `bash <(curl …)` and `source <(curl …)` process substitutions,
    `eval "$(curl …)"`, a fetch and a `sh` joined by `&&` or `;` with or without
    `sudo`, and a fetch followed by `chmod +x`. That check exists because the
    `uses:` SHA guard did not catch a pipe: `quality.yml` carried an unpinned
    `curl … | sh` installer — in the workflow that runs in every consumer's CI —
    while CI cheerfully reported "every third-party action is pinned". A guard
    that passes while the thing it guards against sits in the same file is worse
    than no guard, because it gets quoted as evidence.

    It scans `.github/workflows/`, `actions/` and `scripts/`. The corpus of
    shapes it must catch, and the downloads it must *not* flag, are committed in
    `samples/guards/` and asserted on every run — so the guard going quiet is a
    named CI failure rather than a clean-looking scan.
  - **A version is not a pin.** A git tag and a release asset are both mutable,
    which is the same argument this file makes about `uses:` tags. So the
    Gitleaks and OSV-Scanner binaries that `actions/layer2` installs into every
    consumer's runner carry a `sha256` pinned beside their version and verified
    before they execute, as does the actionlint binary `ci.yml` downloads for
    its own use. Semgrep comes from PyPI, where a version already binds to
    immutable artifacts.

  That second half was missing until 2026-08-02: the guard then matched **pipes
  only**, so it could not see `curl -o … && sudo install`, and two binaries were
  downloaded and run unverified while this section claimed otherwise. The lesson
  is the one above, repeated one layer up — the sentence was true of the shape
  the guard checked and false of the repository it described.

  The guard was widened on 2026-08-03 to cover that shape and four others.
  Measured before the change, five of eleven planted shapes were invisible to
  it, and `scripts/` — which `actions/layer2` executes in every consumer's CI —
  was not scanned at all.
- **`workflow_run` jobs verify their trigger's origin, not just its outcome.**
  A `workflow_run` job runs in this repo's context with this repo's permissions
  regardless of who caused the run that woke it, and its `branches:` filter
  matches the *head branch name* — which for a fork PR is the branch name in the
  fork. `release-tag.yml` therefore requires `workflow_run.event == 'push'` and
  a matching `head_repository` before it will move the `v1` tag.
- Semgrep, Gitleaks and OSV-Scanner are pinned to exact versions in
  `actions/layer2/action.yml`, and `scripts/check-pins.sh` asserts the pins stay
  internally consistent.
- **Everything that executes in a consumer's CI is linted.** `ci.yml` extracts
  and `shellcheck`s every shell block embedded in a workflow or composite
  action, and since 2026-08-03 also lints `scripts/*.sh` directly — 895 lines,
  including the `scan.sh` that `actions/layer2` runs on someone else's runner
  with their token.
- Dependabot proposes bumps; CI judges them against exact expected finding
  counts, so a bump that changes what fires cannot merge quietly.
