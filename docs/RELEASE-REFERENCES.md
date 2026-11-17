# Closed release references

The reusable workflows are the public entry points, but their `uses:` steps
execute composite actions and scripts from another checkout. A moving `@v1`
inside either workflow would therefore let a release wrapper resolve a payload
other than the one reviewed with it.

Each new closed release uses two commits in one ancestry chain:

1. The payload commit contains all executable changes.
2. A later wrapper records the payload SHA in
   `release-payload.sha` and points every first-party `uses:` reference in a
   reusable workflow at that SHA.

`scripts/release-refs.py verify-wrapper` verifies this relationship locally. It
requires full lowercase commit SHAs, follows first-party references recursively
through the payload tree, and refuses a release revision that differs from its
payload in `actions/`, `scripts/`, `configs/`, or `semgrep/`. Other merged
changes may exist; they cannot change the executable delivery closure named by
the release record.

When development resumes after a release, remove `release-payload.sha` before
changing anything under those four directories, including their documentation.
The inherited record describes the previous release's payload, not the new
development tree. CI treats a tree without that record as payload development;
the release-tag workflow still requires a valid record before publishing.
Keep the existing immutable workflow references until release finalization,
when `record --payload <payload-sha>` creates the new record alongside the
rewritten references.

During release finalization, use `rewrite --payload <payload-sha>` followed by
`check --payload <payload-sha>` before creating the wrapper commit, then run
`verify-wrapper --revision <wrapper-sha>` on the resulting release revision.
The helper has no network dependency and changes only first-party `uses:`
values in reusable workflows; it leaves
consumer examples and unrelated local workflows alone.

Dependabot updates third-party actions, but excludes this repository's own
actions and reusable workflows. Those references move together with the
recorded payload during release finalization. If an older dependency PR already
changed them, restore them with `rewrite --payload <recorded-payload-sha>` and
verify the resulting commit; do not remove or weaken the release check to
accept an independent first-party bump.

It uses a deliberately narrow, line-preserving grammar for `uses:`. A quoted
key, folded value, or any other non-comment first-party reference it cannot
parse is an error, never an omitted reference. That keeps a new YAML spelling
from creating a false green release check.
