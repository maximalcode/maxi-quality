# Native Codex guard fixtures

Run `python3 samples/codex-agent-guard/test_codex.py` from the baseline checkout.
Python and Git are sufficient; the fixture needs neither agent CLI nor a login.
Every project, cache and release is temporary. No real Adopter is inspected.

The public seams are native hook JSON in/verdict out, migration and diagnosis
commands, generated shell hooks, and the shared immutable runtime launcher.

Bad patch cases include a hand-written receipt, manifest deletion at depth,
a cited fixture shrinking or being deleted, overwrites through Add File and
Move to, a move out of the cited path, a later file in a multi-file patch,
relative and symlinked paths, and unreadable patch input. Clean controls add a
file or a finding, replace a fixture without shrinking it, or move/delete an
uncited file. Same-size semantic weakening is deliberately left to CI.

The generated hooks are executed from a nested working directory with an
incorrect Claude project environment variable. Bash blocks skipping Git
verification and accepts ordinary work. Patch decisions reach the caller.
Stop blocks unrecorded work, accepts a real successful recorder run, and blocks
again after a subsequent edit. Neither test nor adapter writes a fake receipt.

Migration retains Claude settings, preserves existing agent instructions, and
is idempotent. Diagnosis distinguishes configured hooks from unverified live
enforcement and fails on a disabled native feature or mismatched matcher.
Format-1 and format-2 pins share a cache without rewriting the older entry;
the old pin still runs the Claude guard and explicitly rejects the unavailable
Codex adapter.

These are protocol and installation fixtures. They do not run a Codex model,
prove host discovery, trust a hook, or establish that a real host honored a
block. The repository's native configuration has separate contract checks and
mutations in `scripts/check-agent-contract.py`, run in the existing
`agent-guard` CI context.
