# Layer 2 changed-only history and baseline filtering

Run from the repository root with Git, Python 3 and the native Semgrep version
pinned in `actions/layer2/action.yml` already installed:

```bash
bash samples/layer2-changed-only/run.sh
```

The fixture refuses a missing or different Semgrep version; it installs nothing.
It extracts and executes the production action's `scan` step, which invokes the
real `scripts/scan.sh` with `--require-tools --changed-only origin/main` and a
JSON output path. Git repositories and Semgrep results are real. Gitleaks and
OSV-Scanner are isolated with external-command shims (exit 0 and 128 respectively)
to keep this history/baseline fixture independent of unrelated tools and OSV
network requests. Their scanning behavior is not measured here. The action's
installation steps remain covered by the existing `layer2` CI matrix, which also
runs this fixture after installing the pinned tools on Linux and macOS.

## What it asserts

- A complete checkout with 205 reachable commits stays non-shallow, with every
  previously reachable commit still reachable after the production scan step.
- A synthesized PR merge changes `old.ts` harmlessly while retaining its existing
  `no-ambient-clock` finding on line 1. Complete and depth-one detached checkouts
  both complete with zero new findings and action exit 0.
- Adding `new.ts` with one new `no-ambient-clock` finding on line 1 makes both
  checkout shapes report exactly that finding and action exit 1. `old.ts:1`
  remains excluded. All successful scanner JSON must have an empty `errors` list.
- A full `scan.sh` control detects exactly `old.ts:1`, proving the existing
  violation is active. Each depth-one checkout starts with one reachable commit;
  its merge parents and base branch are absent until the action fetches them.
- A depth-two feature checkout followed by a local empty commit still fetches
  its baseline and excludes `old.ts:1`, with action exit 0 and no scanner errors.
  The local HEAD is unavailable at the remote; fetching it must not prevent
  the valid baseline fetch from succeeding.

Finding identities are `(rule id, path, start line)`, with Semgrep's config-path
prefix removed from the rule id, as in the repository's other finding assertions.
Failed runs retain the temporary repositories, action logs, outputs and JSON for
inspection; successful runs clean them up.

## Measurement — 2026-09-01, issue #240

Native Semgrep **1.172.0** (the action pin), Git **2.50.1 (Apple Git-155)**,
Python **3.14.7**, macOS. The Semgrep installation uses Python **3.12.13**.
Each red/green run used `bash samples/layer2-changed-only/run.sh` while adding
one assertion and its fix at a time.

| Stage | Observed result | Exit status |
| --- | --- | --- |
| Original action, complete checkout | `shallow=false` / 205 commits became `shallow=true` / 200 commits; Semgrep reported `clean` | action 0; fixture 1 |
| Depth guard added, complete checkout | `shallow=false`, 205 → 205 commits | action 0; fixture 0 |
| Full-scan control | Exactly `no-ambient-clock`, `old.ts`, line 1 | `scan.sh` 1 |
| Before shallow fix, complete PR checkout | Empty `results` and `errors`; `semgrep=clean` | action 0 |
| Before shallow fix, depth-one PR checkout | `semgrep=ERROR (semgrep exit 2)`; no exported JSON | Semgrep 2; `scan.sh` / action 1; fixture 1 |
| Both fixes, existing violation only | Complete and shallow: empty `results` and `errors`; `semgrep=clean` | action 0 for each |
| Both fixes, one new violation | Complete and shallow: exactly `no-ambient-clock`, `new.ts`, line 1; empty `errors`; `semgrep=FINDINGS` | action 1 for each; fixture 0 |
| Combined base/HEAD fetch, shallow feature checkout with a local commit | `origin/main` absent; `semgrep=ERROR (semgrep exit 2)`; no exported JSON | Semgrep 2; action 1; fixture 1 |
| Separate base/HEAD fetches, same local-commit fixture | Empty `results` and `errors`; `semgrep=clean` | action 0; complete fixture 0 |

The shallow measurement was taken after the complete-checkout guard went green
and before changing shallow preparation. That guard leaves the shallow fetch
identical to the original action:

```bash
git -C "$TARGET" fetch --no-tags --depth=200 origin main
```

Semgrep failed in `BaselineHandler` before scanning. Its logged Git command was:

```bash
git diff --cached --name-status --no-ext-diff -z --diff-filter=ACDMRTUXB \
  --ignore-submodules --relative origin/main --merge-base --
```

Git exited **128**, with `fatal: no merge base found`. This is a scanner error,
not backlog reclassification or a successful scan with no findings. Fetching the
current merge HEAD's ancestry as well as the base, with the same shallow-only
depth of 200, makes the same fixture pass. Complete checkouts use no depth limit.

The local-commit regression was observed failing at the production action seam
before splitting those fetches. A direct replay of the combined fetch exited
128 (`not our ref` for the local HEAD), leaving `origin/main` absent; fetching
the base alone exited 0 and created it. The action now fetches the base first
and the shallow HEAD ancestry in a separate request, so an unavailable local
HEAD cannot cancel a valid baseline fetch. The full fixture still preserves
205 complete-history commits and reports identical PR finding sets for complete
and shallow checkouts.

This change adds no fallback policy: a history deeper than that shallow fetch
can reach, an unavailable ref, or an unavailable remote can still make Semgrep
fail. This fixture proves the named topologies; it does not claim arbitrary
history depth or change Gitleaks' `BASE..HEAD` selection.

The local boundary check also runs the declared repository gate through its
recorder:

```bash
bash samples/layer2-changed-only/run.sh && python3 .claude/agent-guard/record-gate.py --gate
```
