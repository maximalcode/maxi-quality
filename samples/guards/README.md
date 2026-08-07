# The supply-chain guards' test suite

`ci.yml`'s `workflow-lint` job bans fetch-and-execute shapes in everything that
runs in a consumer's CI. The two `.txt` files here are the corpus it is asserted
against on every run: `banned-fetch-exec.txt` must be caught in full,
`allowed-fetch-exec.txt` must be caught not at all.

## Why the corpus is not in `ci.yml`

It was, briefly, and it failed twice in the same commit:

1. A banned shape written inline is a **real hit in a scanned file**, so the
   guard failed on its own test data — the same way it used to fail on the
   comments explaining it.
2. `eval "$(curl …)"` inside single quotes is `SC2016` to `shellcheck`, which
   lints every workflow shell block. The test data was linted as code.

Both are the reason `samples/semgrep/` sits outside the language projects, and
the reason `.gitleaks.toml` allowlists the planted credentials: **bait belongs
where the scanner is not pointed.** The guard scans `.github/workflows/`,
`actions/`, `scripts/` and `.github/actions/` if it exists. `samples/` is
deliberately not in that list.

## Why the negative controls matter as much

This repo downloads things on purpose — actionlint, Gitleaks, OSV-Scanner — each
pinned and verified with `sha256sum -c`. A guard that cannot tell a
checksum-verified download from a `curl | sh` is a guard someone switches off,
and the real one lands the week after. `allowed-fetch-exec.txt` is what makes
the distinction testable rather than asserted.

## Measured, so the gap is on the record

Before 2026-08-03 the pattern matched **pipes only**. Against the eleven shapes
in `banned-fetch-exec.txt` and its history, five were invisible: `curl -o F &&
sh F`, its `;` variant, its `sudo` variant, `eval "$(curl …)"`, and
download-then-`chmod +x`. `scripts/` was not scanned at all — 895 lines,
including the `scan.sh` that `actions/layer2` executes on a consumer's runner.

One shape the issue listed was **already caught** and is kept here as a
regression test rather than described as a fix: `source <(curl …)`. The `<(`
alternation never cared which command consumed the substitution.

## Adding a shape

Add the line, watch CI fail, then widen the pattern in `ci.yml` until it passes.
A shape that is caught the moment you add it was already covered — say so rather
than counting it.
