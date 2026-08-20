# TypeScript, npm

```bash
"$BASELINE"/scripts/adopt.sh .    # writes eslint.base.mjs + tsconfig.base.json
npm i -D eslint @eslint/js typescript-eslint typescript @types/node eslint-plugin-sonarjs
npm run lint
```

Everything in this directory is what *you* write. `eslint.base.mjs` and
`tsconfig.base.json` are copies of the baseline — `adopt.sh` puts them here, and
re-running it refreshes them. Do not hand-edit them.

`--max-warnings 0` in the lint script is not decoration: `no-console` is a
warning, and without that flag it never gates.

Type-aware linting needs every linted file covered by a `tsconfig.json`. That is
what `tsconfigRootDir` is for when yours is not at the project root.


## Coverage

`.github/workflows/quality.yml` here gates coverage, and the wiring is worth
reading in full because it is the one part that lives in **your** file rather
than in the baseline:

- a `test` job of your own runs the suite and uploads the report as an
  artifact — the baseline never runs your tests;
- `coverage-report: coverage` names **that artifact**, not a path. What is
  inside it is found by content, so lcov and Cobertura are both picked up
  wherever they sit and whatever they are called;
- `needs: test` is the edge with no other reason to exist. Leave it out and the
  gate can start before the upload finishes, then fail on a missing artifact —
  the wrong error for the right reason.

**There is no `.maxi-quality/coverage.json` in this directory, on purpose.** The
floor is a number about *your* repo, and the first run without one fails
deliberately: a ratchet with nothing to compare against reports ok at any
coverage at all. Uncomment `coverage-raise: 'true'`, push once, commit what the
log prints under **RECORDED FLOOR**, then remove the line. It will not commit
for you — that is a write to your default branch.

Two gates come from that one line: the aggregate ratchet (*did this change make
it worse?*) and the patch gate over the lines the change adds, which is the one
the aggregate cannot see — a single new untested function inside a large
well-covered repo moves the aggregate by rounding error. The patch bar defaults
to 50% and is `coverage-patch-threshold`; `0` keeps the measurement and drops
the gate.
