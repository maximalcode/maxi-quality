# The supply-chain guards' test suite

`workflow-lint` also runs `scripts/check-action-pins.py`, which parses complete
`uses:` YAML values in the existing `.github/workflows/`, `actions/` and
`examples/` roots. A third-party reference passes only when the entire portion
after `@` is exactly 40 lowercase hexadecimal characters. YAML quoting and a
real trailing comment do not change the value; a `#` inside the value remains
part of it and is rejected. The test runs that `#inside` case in unquoted,
single-quoted, and double-quoted forms, each with a real outside trailing
comment. Local composite-action calls and `maximalcode/*`
calls retain their existing exemptions. The positive and negative corpora are
`action-pins-allowed.txt` and `action-pins-banned.txt`.

`test_action_pins.py` extracts that exact CI step from `ci.yml`, copies the
shared checker into temporary repositories, and runs it through all three scan
roots. It asserts both the exit status and the reported reference, so a failure
caused by an unrelated temporary-repository error cannot satisfy the test.
The historical corpus also recreates the three original `upload-artifact`
failures as separate labelled steps and requires three diagnostics from every
root.

`ci.yml`'s `workflow-lint` job bans fetch-and-execute shapes in everything that
runs in a consumer's CI. The fetch-and-execute corpus is asserted against on
every run: `banned-fetch-exec.txt` must be caught in full,
`allowed-fetch-exec.txt` must be caught not at all. The action-pin corpora are
listed above and exercised by the extracted-step test.

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

Add the line, watch CI fail, then widen the pattern in the corresponding guard
implementation until it passes.
A shape that is caught the moment you add it was already covered — say so rather
than counting it.
