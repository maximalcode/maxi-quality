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

There is deliberately no `.gitleaksignore`. It works by **fingerprint**
(`commit:file:rule:line`), so every entry is invalidated by any history rewrite
or line shift — a suppression file that silently stops suppressing is worse than
none. The path allowlist survives both.

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

  - `ci.yml` fails on `curl … | sh`, `wget … | bash`, and the `bash <(curl …)`
    form. That check exists because the `uses:` SHA guard did not catch a pipe:
    `quality.yml` carried an unpinned `curl … | sh` installer — in the workflow
    that runs in every consumer's CI — while CI cheerfully reported "every
    third-party action is pinned". A guard that passes while the thing it guards
    against sits in the same file is worse than no guard, because it gets quoted
    as evidence.
  - **A version is not a pin.** A git tag and a release asset are both mutable,
    which is the same argument this file makes about `uses:` tags. So the
    Gitleaks and OSV-Scanner binaries that `actions/layer2` installs into every
    consumer's runner carry a `sha256` pinned beside their version and verified
    before they execute, as does the actionlint binary `ci.yml` downloads for
    its own use. Semgrep comes from PyPI, where a version already binds to
    immutable artifacts.

  That second half was missing until 2026-08-02: the pipe guard cannot see
  `curl -o … && sudo install`, so two binaries were downloaded and run
  unverified while this section claimed otherwise. The lesson is the one above,
  repeated one layer up — the sentence was true of the shape the guard checked
  and false of the repository it described.
- **`workflow_run` jobs verify their trigger's origin, not just its outcome.**
  A `workflow_run` job runs in this repo's context with this repo's permissions
  regardless of who caused the run that woke it, and its `branches:` filter
  matches the *head branch name* — which for a fork PR is the branch name in the
  fork. `release-tag.yml` therefore requires `workflow_run.event == 'push'` and
  a matching `head_repository` before it will move the `v1` tag.
- Semgrep, Gitleaks and OSV-Scanner are pinned to exact versions in
  `actions/layer2/action.yml`, and `scripts/check-pins.sh` asserts the pins stay
  internally consistent.
- Dependabot proposes bumps; CI judges them against exact expected finding
  counts, so a bump that changes what fires cannot merge quietly.
