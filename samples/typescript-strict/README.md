# This project must not compile

`configs/typescript/tsconfig.strict.json` ships to every consumer and, until
this directory existed, **`tsc` was run by nothing in CI** (issue #7). Thirteen
of its fourteen hand-written flags had no test at all: any of them could be
deleted and every job would stay green, because ESLint's findings do not depend
on the compiler options and nothing else looked.

So this is the compiler's `samples/typescript`. Every file plants one error, the
error is named after the flag that causes it, and
`samples/expected/tsc.json` pins the exact set — rule, file and line — the same
way every other gate in this repo is asserted.

Nothing here is linted. There is no `eslint.config.mjs` and no `lint` script:
this project exists to prove the compiler configuration, and keeping ESLint out
means adding a flag fixture can never shift the ESLint counts.

## Flag → error, verified by ablation

Each row was checked by turning that one flag off and confirming **that** error
is the one that disappears. That is not ceremony — it caught a real mistake.
`no-implicit-returns.ts` was first written returning `string`, which fails with
TS2366 from `strictNullChecks`, not TS7030 from `noImplicitReturns`. CI would
have been red for the wrong reason, and deleting `noImplicitReturns` would have
left it red and looking fine.

| Flag | Fixture | Error |
|---|---|---|
| `strict` (`strictNullChecks`) | `strict.ts` | TS2322 |
| `strict` (`noImplicitAny`) | `strict.ts` | TS7006 |
| `noUncheckedIndexedAccess` | `no-unchecked-indexed-access.ts` | TS2322 |
| `exactOptionalPropertyTypes` | `exact-optional-property-types.ts` | TS2375 |
| `noImplicitOverride` | `no-implicit-override.ts` | TS4114 |
| `noImplicitReturns` | `no-implicit-returns.ts` | TS7030 |
| `noFallthroughCasesInSwitch` | `no-fallthrough-cases-in-switch.ts` | TS7029 |
| `noPropertyAccessFromIndexSignature` | `no-property-access-from-index-signature.ts` | TS4111 |
| `useUnknownInCatchVariables` | `use-unknown-in-catch-variables.ts` | TS18046 |
| `verbatimModuleSyntax` (import) | `verbatim-module-syntax.ts` | TS1484 |
| `verbatimModuleSyntax` (re-export) | `verbatim-module-syntax-reexport.ts` | TS1205 |
| `module` / `moduleResolution` = `nodenext` | `module-nodenext.ts` | TS2835 |

## Two fixtures that must stay SILENT

`relaxations-must-stay-silent.ts` and `broken.d.ts` produce nothing today, and
that is the assertion. The manifest is a **set**, so a new finding fails CI
exactly as a missing one does — which is the only way to test a flag whose
effect is to *permit* something:

- drop `lib` below `es2023` and `findLast` becomes TS2550;
- drop `skipLibCheck` and the deliberately broken declaration file becomes
  TS2304.

## What is still NOT proven here, and why

Honest list, because a coverage claim that quietly rounds up is worse than the
gap it hides. All four are covered by
[`configs/typescript/tsconfig.snapshot.json`](../../configs/typescript/tsconfig.snapshot.json)
instead — the resolved-options snapshot exists precisely for the flags no
fixture can reach.

- **`isolatedModules`** — measured with tsc 6.0.3, `--isolatedModules false`
  changes not one error in this directory. `verbatimModuleSyntax` subsumes it:
  TS1205's own message names `verbatimModuleSyntax`, not `isolatedModules`. The
  file that tests it is therefore named `verbatim-module-syntax-reexport.ts` and
  not `isolated-modules.ts`, which is what it was called until the ablation said
  otherwise.
- **`esModuleInterop`** — cannot be switched off to test: tsc 6.0.3 rejects
  `esModuleInterop: false` with TS5107, deprecated ahead of removal in
  TypeScript 7.
- **`forceConsistentCasingInFileNames`** — needs a case-insensitive filesystem
  to change anything. On the Linux runner a wrong-case import fails to resolve
  whether the flag is on or off, so a fixture would pass for the wrong reason.
- **`declaration` / `declarationMap` / `sourceMap`** — they change emit, and
  this project runs `--noEmit`. CI asserts them separately by emitting
  `samples/typescript-clean` to a temp directory and requiring `.d.ts`,
  `.d.ts.map` and `.js.map` to appear.

## Adding a flag to the baseline

Add the fixture in the same change, and **ablate it** — turn the new flag off on
its own and confirm your new error is the one that goes away. If it is not, the
fixture is testing a different flag and the new one is still untested.
