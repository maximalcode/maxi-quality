# Contributing

This is a personal baseline that happens to be public. Issues and discussion are
welcome; please read the three hard rules first. The first two are why the
project has stayed useful rather than growing into a rule zoo. The third is why
a merge here does not surprise anyone downstream.

## Rule 1 — the ruleset is capped at 12 conventions

Twelve. Not "twelve for now". The budget is **fully spent**, and the inventory
is in the README.

Adding a thirteenth convention means **removing one**. This is not gatekeeping
for its own sake: rule-writing is infinitely expandable and feels productive, so
without a hard cap the ruleset grows until it produces more noise than signal
and someone switches it off. A cap forces every rule to keep earning its place.

A new rule is justified by **a real bug that slipped through** — a link to the
incident, the PR, or the outage. It is never justified by "this would be nice to
catch". If your rule is genuinely better than one of the twelve, say which one it
replaces and why.

Note the distinction: **12 conventions, currently 28 rule ids.** Semgrep patterns
are language-specific, so one convention needs a separate id per language when
the syntax differs. Splitting an existing convention into a per-language id is
not new scope. Inventing a new convention is.

## Rule 2 — `samples/` is the test suite, and you may not weaken it

Every config is proven by an intentionally-bad sample that must fail, with an
**exact expected set of findings**, plus a `-clean` counterpart that must pass with zero
findings. Both halves matter: a config that flags everything is as useless as one
that flags nothing.

If a sample stops failing, **the config regressed — fix the config.** Never make
a sample pass by adding a disable comment, a `NoWarn`, or a suppression inside
the fixture. Never adjust an expected count to match new output without saying,
in the commit message, what changed and why the new number is correct.

The same applies to a rule's escape hatch. If a rule's message tells you how to
satisfy it, there must be a fixture proving that instruction actually works. This
is not hypothetical: `catch-and-swallow` told people to explain the silence in a
comment, comments are not AST nodes, and following the instruction verbatim did
not clear the finding — 4 out of 4 real-world hits were false positives.

**A fixture cannot prove a configuration**, only the part of it the fixture
happens to reach, so every config also has a snapshot of what it *resolves to*.
All four must be regenerated deliberately when a tool is bumped:

```bash
node scripts/snapshot-eslint-rules.mjs --check     # the enabled ESLint rule set
node scripts/snapshot-tsconfig.mjs --check         # tsc --showConfig
./scripts/snapshot-msbuild-props.sh --check        # dotnet msbuild -getProperty
python3 scripts/snapshot-python-settings.py --check # ruff + mypy's own resolvers
```

Each asks the **tool's own resolver**, never the config file — the file says
what we wrote, the resolver says what survived `extends`, conditions, defaults
and alias expansion. For mypy that gap is the whole point: `strict = True` is
one line in the ini and fourteen booleans in the resolver.

They exist because the gap was measured, not imagined. 94% of the ESLint
baseline could be deleted with every finding assertion green. Every flag in
`tsconfig.strict.json` could be deleted with no job running `tsc` at all. And
the three `dotnet_naming_rule` blocks shipped enforcing nothing, because the
severity that governs the build was never set — a config can be **switched
off**, not merely unbaited, and those two look identical from outside.

**When you add a compiler flag, ablate its fixture.** Turn that one flag off and
confirm your new error is the one that disappears. An error attributed to the
wrong flag leaves CI red for a reason that survives deleting the flag you meant
to test — which has already happened once, and is written up in
[`samples/typescript-strict/README.md`](samples/typescript-strict/README.md).

## Rule 3 — PRs go to `develop`, never to `main`

`main` is not a checkpoint, it is a **release**. The moving `v1` tag follows it
automatically, so anything that lands on `main` is running in every consuming
repo that pinned `@v1` within about a minute.

So the flow is:

```
  feature branch ──PR──▶ develop ──PR──▶ main ──▶ v1 moves
     your work            default        maintainer   consumers
                          branch         decides      pick it up
```

`develop` is the default branch, so `gh pr create` and the web UI already target
it — you should not have to change the base. Both branches carry the same
protection: 18 required checks, admins included, branch must be up to date, no
force-pushes, no direct commits.

Promoting `develop` to `main` is a maintainer decision, because it is where the
version gets chosen. It is not part of a contribution, and a PR that targets
`main` will be asked to retarget rather than merged.

## Practical

- **Conventional commits**: `feat:`, `fix:`, `chore:`, `docs:`, `ci:`. One
  logical commit per unit of work.
- **Branch off `develop`, then PR back into it.** CI is the gate; nothing lands
  on either long-lived branch directly.
- **Third-party actions are pinned to a full commit SHA**, never a tag, and CI
  fails if one is not. Keep the tag as a trailing comment so Dependabot can still
  bump it.
- **Everything is free/OSS.** Zero spend is a success criterion, not a
  preference. A change that requires a paid tier will be declined regardless of
  merit.
- **Claims get measured.** The comparisons in `docs/` exist because assertions
  in this repo have been wrong before and were caught by running them. If you
  argue a tool or rule is better, bring the numbers.

## Running the test suite

See the **Verify** section of the README. It runs in about two minutes and
requires Node, the .NET SDK, Python, and either the Layer 2 tools natively or
Docker.
