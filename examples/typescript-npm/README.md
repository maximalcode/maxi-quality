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
