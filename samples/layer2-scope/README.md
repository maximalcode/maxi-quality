# Layer 2 Semgrep scope fixtures

`run.sh` drives the production scanner with pinned Semgrep 1.172.0. The
`samples/policy/exclude` fixture is executed with its directory policy enabled
and after that policy is removed: the observed `cli_exclude_flags_match` path
is counted as one `target_path` only while the policy is active. The committed
`default-ignore/` fixture exercises a `.semgrepignore` skip; its
`semgrepignore_patterns_match` evidence must leave policy exclusions at zero.

Counts are unique normalized target paths. A directory path emitted by Semgrep
remains one `target_path`; it is not expanded or relabelled as files. Missing,
malformed, or absent verbose skip evidence is retained as an explicit unknown.
Other scanners retain unknown `source_file` counts because their native output
does not establish that unit.
