# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

This repo is **single-context**: one `CONTEXT.md` and one `docs/adr/` at the root.

## Before exploring, read these

- **`docs/CONCEPT.md`** — the existing source of truth for what this repo is, what
  it contains, and the order things get built in (`CLAUDE.md` §3). Read it first.
  It predates this setup and outranks anything below it: do not create a
  `CONTEXT.md` that contradicts it, and if a glossary term and `CONCEPT.md`
  disagree, `CONCEPT.md` wins until the user says otherwise.
- **`CONTEXT.md`** at the repo root, if it exists — the domain glossary.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

If any of these don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

Two more standing documents worth reading before proposing changes, both of which
carry measured evidence rather than opinion:

- **`docs/STATUS.md`** — what has been measured, with numbers.
- **`docs/EVAL-vs-oss-tools.md`** and **`docs/EVAL-vs-sonarqube.md`** — tools that
  were evaluated and why they were adopted or declined. A proposal to adopt
  something already declined there needs *new measured evidence*, not a rerun of
  the old argument.

## File structure

```
/
├── CONTEXT.md
├── docs/
│   ├── CONCEPT.md      ← source of truth, predates this layout
│   └── adr/
│       ├── 0001-....md
│       └── 0002-....md
└── configs/, samples/, semgrep/, actions/
```

If this repo ever grows genuine multiple contexts, the multi-context layout is a
root `CONTEXT-MAP.md` pointing at one `CONTEXT.md` per context, with
context-scoped `docs/adr/` alongside each. It does not apply today — the
`workspaces` field in `package.json` lists `samples/` test fixtures, not
independent packages.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

One piece of vocabulary is load-bearing and non-negotiable: consuming projects are
named **Consumer A / B / C / D / E**, never by their real repo names. See
`CLAUDE.md` §2 and `docs/agents/issue-tracker.md`.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_
