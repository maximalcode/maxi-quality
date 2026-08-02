# These credentials are fake, and they are supposed to be here

Every secret-shaped string in this directory is **planted bait**. Not one has
ever been valid anywhere.

They exist because `semgrep/security/hardcoded-secret-*.yaml` has to be proven
against something. CI asserts that those rules fire on these files with an exact
count — so if a scanner ever *stops* flagging this directory, the baseline has
regressed and the fix is the rule, not the fixture.

Which means: **a secret scanner run against this repository will report
findings, and that is the intended state.**

## If your scanner flags this directory

- **Gitleaks** — nothing to do. `.gitleaks.toml` in the repo root
  path-allowlists exactly this directory, and Gitleaks loads it automatically
  from the scan root.
- **Anything else** — exclude `samples/`. That is the whole story; there is no
  bait anywhere else in the tree.

There is deliberately no `.gitleaksignore`: it suppresses by **fingerprint**
(`commit:file:rule:line`), so every entry dies on any history rewrite or line
shift, and a suppression file that has quietly stopped suppressing is worse than
no suppression file. A path allowlist survives both.

## Why these files sit outside the language projects

`samples/typescript/` and `samples/dotnet/` have exact expected finding counts of
their own. Keeping the Semgrep bait out of those projects means adding a rule
fixture can never shift a Layer 1 count. Nothing here is ever compiled or linted
— Semgrep only parses it.

## Negative controls

Each file also carries cases that **must stay silent**, so the rules are provably
matching behaviour rather than names — a tracked `TODO(#412)`, a mutation that
does call its authz gate, a read that is not a mutation, a `decimal` used for
money, a bare endpoint URL in a secret-named variable.

The exemptions are themselves gated: a `connectionString` holding real-looking
credentials **must** fire in both languages, which proves the URL exemption is
credential-aware rather than a blanket hole. One exemption plus one must-fire
counterexample is what makes a guard safe to have.
