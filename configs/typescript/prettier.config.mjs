// maxi-quality — Prettier baseline (TypeScript / JavaScript)
//
// USAGE — a consuming project's own prettier.config.mjs is one line:
//
//   export { default } from '@maximalcode/maxi-quality/configs/typescript/prettier.config.mjs';
//
// Until this repo is published to npm, point at it directly:
//
//   export { default } from '../../configs/typescript/prettier.config.mjs';
//
// The consuming project needs one devDependency: prettier.
//
// WHY A FORMATTER IS IN THE BASELINE AT ALL
//
// docs/CONCEPT.md §4 has always said formatting is "autofixed, never argued
// about". Until now that was a claim with nothing behind it for TypeScript —
// issue #42. A formatter is not a detector and it will never find a bug; what it
// removes is a whole category of review comment, and the layout drift that makes
// a real diff hard to read.
//
// WHY THESE VALUES, MEASURED (2026-08-05, prettier 3.7.2)
//
// Every TypeScript file in this repo ALREADY conforms to this config. Running
// `--check` over samples/ and examples/ with these settings reformats nothing.
// That is the whole reason it could be adopted in one commit rather than as a
// tree-wide reformat: the gate starts green and only ever fires on future drift.
//
// Run the same files against Prettier's DEFAULTS and 13 of them fail. The two
// settings below are what closes that gap, and neither is a taste call:
//
//   printWidth   Prettier defaults to 80. configs/editorconfig ships
//                `max_line_length = 100` and configs/python/ruff.toml ships
//                `line-length = 100`. Leaving the default would have meant the
//                baseline shipping two different line lengths and a formatter
//                that fights the .editorconfig in the same repo.
//   singleQuote  Prettier defaults to double. Every .ts file here uses single,
//                so the default would have rewritten all of them for nothing.
//                Note this DOES differ from Python, where ruff.toml keeps
//                double — each language gets its own community default rather
//                than a cross-language consistency nobody asked for.
//
// The rest are Prettier's own defaults, written out on purpose. A default that
// is not stated is a default that changes under you in a major bump and lands
// as unexplained churn in a consumer's diff. Stated, the same bump shows up
// here as a one-line diff somebody has to justify.
//
// NOT gated over samples/semgrep/ or samples/format/ — see .prettierignore.

/** @type {import('prettier').Config} */
export default {
  // --- the two that are not defaults, both measured -------------------------
  printWidth: 100,
  singleQuote: true,

  // --- Prettier 3 defaults, stated so a major bump is a visible diff --------
  tabWidth: 2,
  useTabs: false,
  semi: true,
  trailingComma: 'all',
  bracketSpacing: true,
  arrowParens: 'always',
  endOfLine: 'lf',
};
