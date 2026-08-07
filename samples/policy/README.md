# `samples/policy/` — the policy file's test suite

Fixtures for `.maxi-quality.yml`, exercised by the `policy` job in
[`ci.yml`](../../.github/workflows/ci.yml). Each directory is a miniature
consuming repo: a policy file plus just enough code to violate something.

## Every fixture is asserted twice

Once with its policy in place, and once with the policy **moved out of the way**.
The second run is the assertion that means anything.

That is not caution for its own sake. The `exclude/` fixture originally excluded
a directory called `vendor/`, and it passed — it also passed with the policy
deleted, because semgrep skips `vendor/` by default. The fixture proved nothing
and looked exactly like one that worked. Renamed to `legacy/`, which semgrep does
not ignore, and now the ablation run reports 2 findings against the policy run's
1. Same shape as the `noImplicitReturns` fixture in `samples/typescript-strict/`
that really failed on `strictNullChecks`: **a fixture proves *an* outcome, never
*which setting caused it*.**

| Fixture | Policy | With it | Ablated |
|---|---|--:|--:|
| `disable/` | `disable: [no-ambient-clock]` | 1 gating (`todo-without-issue`) | 2 gating |
| `warn/` | `warn: [todo-without-issue]` | 0 gating, 1 warn, **exit 0** | 1 gating, exit 1 |
| `exclude/` | `exclude: [legacy/]` | 1 gating | 2 gating |
| `extends/` | `extends: .maxi-quality/rules` | 1 gating (the consumer's own rule) | 0 gating |
| `groups/` | `groups: [security]` | 1 gating (`weak-crypto`) | 2 gating |

`disable/` and `groups/` each carry a **control** — a second violation that must
keep firing. Without one, a policy that switched everything off would pass just
as happily as one that switched off the right thing.

`extends/`'s ablated count is 0 on purpose: its source violates only the
consumer's own rule, so if the baseline started flagging it something has gone
wrong somewhere else.

## `invalid/`

Eight policies that must each exit **3**. They are the point of the whole file:
an unknown key, an unknown rule id, an unknown group, a rule in both `disable`
and `warn`, an `extends` pointing nowhere, a `groups: []` that would run no rules
at all, an unsupported `version`, and a `paths.exclude` written as `legacy/**`.

That last one is measured rather than stylistic. Semgrep's `--exclude` matches
path components, so the glob spelling every other tool accepts excludes nothing
and says nothing about it — see `docs/STATUS.md` §4.

## Why these are excluded from this repo's own scan

They contain deliberate violations, so a plain `semgrep --config semgrep` over
the repo would fold them into `samples/expected/semgrep.json` and couple the rule
manifest to the policy fixtures — edit one, regenerate the other. The repo's own
[`.maxi-quality.yml`](../../.maxi-quality.yml) excludes this directory, which is
the same separation `samples/semgrep/` gets by sitting outside the TypeScript and
.NET projects.

A `.semgrepignore` would have been the obvious alternative and is wrong: a custom
one **replaces** semgrep's built-in ignore list rather than extending it, and
this repo has a `node_modules/` full of TypeScript.
