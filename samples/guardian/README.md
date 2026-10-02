# Local Guardian subprocess fixtures

Run `python3 scripts/check-guardian.py`. The cases create invented Git projects,
with no CI configuration or agent host settings, and invoke the runner as a real
subprocess. They require only Python, Git and Bash (the existing gate shell).

`cases.json` pins passing execution, short-circuited compound failure, an absent
executable, misleading dependency text, a missing declaration, an invalid base,
and a gate that edits its input. Additional assertions cover human output,
unknown scope and attribution, retained failure output, later edits and commits,
Stop compatibility, and another checkout's inherited Git routing environment.

These prove the local mechanism, not adoption cost on a real consuming project
or enforcement inside an agent host. No tool-specific findings are parsed.

The setup cases additionally require Cargo with an installed toolchain and
exercise the dependency-free `rust-local/` crate offline through step 1. The
manifest and lockfile use `.fixture` suffixes and are materialized under their
Cargo names only in the temporary project, so this fixture does not become a
fourth project in the repository detection contract. Its lockfile and build-output ignore keep generated artifacts out of freshness
comparisons. Invented tagged baseline repositories exercise payload validation,
read-only previews, repeated application, native Codex wiring, retained unrelated
hooks, immutable updates and truthful post-update failure evidence. The tests
never launch an agent host or assert that hooks are trusted.

`skill-review.json` defines the invented named task, failing gate and scoped
repair for the installed skill's interface fixture. The test resolves a linked
skill to the same runner as the CLI, retains failed evidence across an external
human-decision note, and verifies freshness before and after repair. It does
not simulate an actual human decision or prove AI obedience. The interactive
[skill demo](../../docs/GUARDIAN-SKILL.md#evidence-limits-and-demo) covers the
reporting instructions separately.
