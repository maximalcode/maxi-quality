# No in-editor Semgrep parity; `scripts/scan.sh` stays the policy-aware path

`adopt.sh --editor` writes neither `configs/editor/semgrep.settings.json` nor the
`Semgrep.semgrep` extension row into a consuming repo, and that is the settled
answer rather than an interim one. An Adopter gets Semgrep at PR time, gets
`scripts/scan.sh` locally, and gets a `.vscode/settings.json` that says in its
own header that this one row is missing and why.

This declines **one row of the editor contract**, and neither Semgrep — which is
Layer 2's first tool and still gates every PR — nor the contract itself. Of the
six verified extension-default divergences, this is one; Java's is out of reach
for an unrelated and architectural reason; the rest are what `--editor` writes.

## Why this was decided at all

The Semgrep extension reads its rules from `semgrep.scan.configuration`.
`scripts/scan.sh` passes the three directories under `semgrep/` as `--config`
arguments, and the fragment names those three paths — correct for a checkout of
this repository, which is the tree the parity run measures.

**A consuming repo contains none of them.** `adopt.sh` writes configs, a
`.maxi-quality.yml` policy file and a workflow call; the rules reach the scan
from inside the composite action. So the fragment copied into a consumer's tree
points the extension at paths that do not resolve, and the extension installed
*without* the fragment leaves `scan.configuration` at its default `[]` — which
scans with whatever the Semgrep CLI or app is configured for, producing findings
no gate here produces. Both halves are divergence, in opposite directions.

`configs/editor/README.md` §5 named this the largest gap in the contract and
said the step that writes the files would resolve it. That step ([#126]) did
not: it held both halves back and disclosed them. Honest, and not an answer —
which is what [#153] was opened to settle.

## Considered options

- **Copy `semgrep/` into the consuming repo.** Rejected. It gives the extension
  local paths, and the copy pattern is already established here — the
  `.editorconfig`, the Rust `[lints]` block and the Maven region are all copies,
  because their consumers cannot read a remote one. But every one of those is
  guarded by CI *in this repository*: `editorconfig-drift` diffs `samples/`
  against `configs/` because both live here. **Nothing in this repo can see a
  consuming tree**, so the drift guard [#153] asks for is not buildable for the
  artifact that would actually rot. The copy would be frozen at adopt time while
  the gate follows the moving `v1`, and the first symptom is the Problems panel
  and CI disagreeing about a rule id — the contract's own failure mode, shipped
  by the thing meant to close it. The existing copies are tens of lines that
  change about once a year; `semgrep/` is 12 files and 40 rule ids, and it
  changes whenever a convention gains a per-language id.
- **Point `scan.configuration` at URLs.** Rejected. No copy, and it could track
  the same tag adoption already pins. But `scan.configuration`'s directory form
  is a local one — over HTTP there is nothing for a directory to enumerate — so
  it is twelve URLs written into every consuming repo's settings file. A
  thirteenth rule file added here is then invisible to every tree already
  adopted — drift that produces no diff anywhere to review. It also puts a fetch
  in the typing loop, and it makes in-editor parity depend on this repository
  staying public, which `CLAUDE.md` §2 records as the owner's decision and
  effectively irreversible.
- **Decline, and write it down.** Chosen.

## What decided it

Not the rule paths. **The rule-level policy gap, which survives all three
options.**

`.maxi-quality.yml` has three knobs: `paths.exclude`, `rules.disable` and
`rules.warn`. Only the first has a settings equivalent — the extension's filters
are `semgrep.scan.exclude` and `semgrep.scan.include`, both path-based, checked
against its published manifest in [#120]. So a repo that switched a rule off in
policy, or demoted it to a warning, still sees it at full severity in the
editor, under every option above.

That is not partial parity, it is parity in the wrong direction. §1 of the
editor contract exists because a Problems panel quieter than the gate reads as
"nothing wrong". A panel *louder* than the gate reaches the same place from the
other side: findings the repo has deliberately switched off train people to
ignore the panel, and then the findings it gets right go unread too. Paying a
permanent drift surface for that is a bad trade at any price, and options 1 and
2 are not cheap.

## Consequences

- `configs/editor/README.md` §5 records a decision instead of listing
  candidates, and §8 no longer carries this as open. [#153] closes.
- `scripts/editor-settings.py` keeps its `NOT_PORTABLE` rule and cites this file
  rather than the issue. `scripts/check-editor-contract.py` G8 asserts both
  halves — that the citation resolves, and that `Semgrep.semgrep` is still held
  back. G7's bidirectional table check would not have caught the second: it
  asserts the identifier is known to the composer, and a language token is a
  well-formed value, so a one-word edit would ship the extension with no rules
  configured.
- **The policy gap is stated where an Adopter reads it, not only here** —
  `README.md`'s Limits, `docs/ADOPTION.md` §5b, and the generated header of the
  `.vscode/settings.json` they are handed. An Adopter who wires the extension up
  by hand anyway is entitled to know that their `rules.disable` will not be
  honoured; that is true whatever this repo decides to write.
- **`scripts/scan.sh` is the local answer, and stays policy-aware.** It resolves
  `.maxi-quality.yml` before it runs, which is the property no settings file can
  have. `--changed-only` is the closest thing to the extension's default
  behaviour for anyone who wants the fast loop.
- **What would reopen this: a rule-level filter in the extension**, not a
  solution to the rule paths. If `semgrep.scan.configuration` ever accepts a
  policy, or the extension grows a disable list, the ranking above changes and
  the copy-versus-URL argument becomes worth having. Until then a new proposal
  that only solves path resolution is re-running an argument that was not the
  blocker.
- Java and Semgrep are now the two rows with no in-editor parity, for unrelated
  reasons — Java's is architectural (Error Prone is a javac plugin, the
  extension compiles with ECJ) and this one is not. Neither is a defect in the
  five divergences the contract does close.

[#120]: https://github.com/maximalcode/maxi-quality/issues/120
[#126]: https://github.com/maximalcode/maxi-quality/issues/126
[#153]: https://github.com/maximalcode/maxi-quality/issues/153
