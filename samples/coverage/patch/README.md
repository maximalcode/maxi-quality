# samples/coverage/patch — the change the aggregate ratchet cannot see

One commit's worth of a well-covered module, its coverage reports, and the
floor the ratchet compares them against. The change adds a function no test
calls. **The ratchet passes.** That is not a bug in the ratchet — it answers
"did the aggregate get worse?", and the honest answer here is "not measurably".
It is the reason a second number is needed, and it is issue #112 made
reproducible.

Everything below is hand-counted. `scripts/patch-coverage-demo.sh` checks both
implementations against these numbers, not against each other.

## The change

`src/rollup.ts` is the post-change file. `changed.diff` is the change that
produced it: a new `medianAbsoluteDeviation`, exported, documented, and called
by nothing.

## The aggregate, before and after

|                      | before | after |
| -------------------- | -----: | ----: |
| lines measured       |  8,000 | 8,004 |
| lines hit            |  7,600 | 7,600 |
| line coverage        | 95.00% | **94.95%** |

`floor.json` holds `95.00` — the value measured immediately before the change,
which is the tightest floor a repo can hold. The drop is 0.05pp; the ratchet's
own tolerance is 0.1pp, and it exists so that small refactors do not fire it.
So `scripts/coverage.py` prints `status=ok` and exits 0, and it would do the
same on a repo that ran `--write` after every single merge.

## The changed lines, counted by hand

`changed.diff` adds nine lines. Four of them are in the coverage reports:

| added line | text                                     | in the report? | hits |
| ---------: | ---------------------------------------- | -------------- | ---: |
| 59–61      | the JSDoc comment                        | no             |    — |
| 62         | `export function medianAbsoluteDeviation`| yes            |    0 |
| 63         | `const middle = …`                       | yes            |    0 |
| 64         | `const spread = …`                       | yes            |    0 |
| 65         | `return percentile(spread, 50);`         | yes            |    0 |
| 66         | the closing brace                        | no             |    — |
| 67         | the blank line after it                  | no             |    — |

**Patch coverage = 0 of 4 = 0.00%.** The five unmeasured lines are in neither
half of the ratio: counting a comment as uncovered would put a floor under the
score that no test could lift.

## The other three inputs

| file             | what it is | measured added lines | covered |
| ---------------- | ---------- | -------------------: | ------: |
| `changed.diff`   | the defect above | 4 | 0 |
| `partial.diff`   | the same function, plus two rewritten lines that *are* covered (50–51) | 6 | 2 |
| `docs-only.diff` | a change to this README | 0 | — |
| `/dev/null`      | a change that added nothing | 0 | — |

`partial.diff` is not decoration. Against `changed.diff` alone, an
implementation that returns 0% unconditionally passes every check — the
fixture would prove the tool runs, not that it computes. 2 of 6 is the case
that separates them.

The last two must report **not applicable**. Not 0%, which gates on something
nobody can fix, and not 100%, which gates on a lie.

## Why the reports look like this

Both formats are committed because `scripts/coverage.py` parses both, and a
cross-check against one parse path proves half of what it claims.

The fixture needs an aggregate large enough that four uncovered lines land
inside the ratchet's tolerance: 8,000 measured lines. Writing out 7,973 `DA:`
entries for the rest of that repo would add nothing a reader could check, so
the rest of the repo is one summary-only lcov record — the `LF:`/`LH:` pair
that `coverage.py` prefers anyway and that `diff-cover` ignores. Per-line data
is only ever needed for files in the diff.

`cobertura.xml` does the same thing the way Cobertura does it: the root
`lines-valid`/`lines-covered` attributes carry the whole run and the `<line>`
elements carry the one touched file. `samples/coverage/cobertura.xml` already
relies on that distinction for a different reason, and `scripts/coverage.py`
documents why it trusts the root attributes.

Inside `rollup.ts`, lines 31 and 38 — the `return 0` guards for empty input —
are the only pre-existing uncovered lines. That is what "well covered, not
perfect" looks like, and it keeps the before-number off a suspiciously round
100%.

## Do not weaken this

`samples/` is the test suite (`CLAUDE.md` §5). If the demo starts disagreeing
with the table above, the code regressed — fix the code. The one change this
fixture may not survive is a `scripts/coverage.py` that reports something other
than `ok` on the aggregate: the whole point is that it passes.
