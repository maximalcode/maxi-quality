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

## One fixture per rule branch

A rule branch with no bait is untested by definition, and it fails silently: it
can stop matching without any count moving, because nothing ever made it match.
That is not hypothetical — `sql-string-concat-ts` shipped with only its
double-quoted branch and the suite was green over the gap for months, and
`command-injection-ts` carried the same hole for as long again.

So every branch of every rule has a fixture here, and every branch of every
`pattern-not` exemption has a counterexample. `samples/expected/semgrep.json`
records each one by rule id, file and line, which is what makes a branch going
quiet show up as a **named missing finding** instead of as a total that still
looks about right.

Adding a branch means adding bait for it in the same change. Do not add one
without.

## Duplication controls

`QueryBuilder.cs` and `query-builder.ts` carry a third kind of case, and it is
not a negative control: lines that **must fire exactly once**. Two conventions
now have a second rule id for the same bug away from the sink, and the two ids
overlap on the inline form — `cmd.CommandText = "SELECT ..." + id`,
`` exec(`ls -la ${dir}`) ``. Each of those is held to one id by a `pattern-not`
or a `metavariable-regex`, and each has a fixture here. The manifest records one
finding on those lines; a second one appearing is the exclusion having gone, and
it fails CI the same way a missing finding does.

The same files also carry **a fixture that is expected to stay silent** —
`exec(buildCommand(dir))`, the cross-function case that Semgrep OSS's
intraprocedural taint does not reach. It sits with the working bait rather than
in a `-clean` file because it is not clean code; it is a known gap, and the day
a Semgrep release closes it the manifest is what says so.
