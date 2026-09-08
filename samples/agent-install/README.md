# Agent contract installation

Run `python3 samples/agent-install/test_install.py`. These checks exercise the
installation interface with real temporary Git repositories and an isolated
home directory; they import no installation helpers.

- The installer alone can install both copied and shared profiles, with and
  without expectation manifests. Each generated recorder command is executed,
  and the installed Stop hook must accept its receipt.
- Adopting a repository never publishes or refreshes the shared runtime.
  Only an explicit `--install-shared` does, preserving unrelated files.
- A shared dry run leaves both an absent and an existing runtime unchanged.
- Appending state exclusions preserves existing `.gitignore` bytes, including
  non-UTF-8 comments and line endings, and remains idempotent.
- Undecodable settings still refuse before writes with exit 6; undecodable
  instructions remain intact while enforcement installs, with exit 7.

The existing `adopt` job's shell scenarios remain the regression coverage for
settings conflicts, instruction edits, symlinks, mode transitions, idempotence
and the public adoption command's summaries and exit codes. This is additional
coverage of installation ownership, not a replacement for those assertions or
for `samples/agent-guard/`'s runtime corpus.
