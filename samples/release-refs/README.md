# Release-reference fixtures

`test_release_refs.py` builds an anonymous, temporary git repository and proves
the release wrapper contract. It covers every first-party `uses:` line in two
reusable workflows, quoted YAML values, a mutable tag, a stale immutable SHA,
and an unrelated local workflow that must remain unchanged by the rewriter.

The final cases create a payload commit and its immediate wrapper. They prove a
wrapper can only change its reference metadata and that first-party references
inside the pinned payload are checked recursively.
