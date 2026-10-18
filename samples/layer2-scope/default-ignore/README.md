# Semgrep default ignore control

This committed fixture separates Semgrep's own `.semgrepignore` attribution
from a project policy exclusion. `ignored/lib.ts` is skipped by the local
ignore file, while `src/app.ts` remains an attempted target. The scope
artifact must report an observed policy exclusion count of zero: the skip
reason is `semgrepignore_patterns_match`, not `cli_exclude_flags_match`.
