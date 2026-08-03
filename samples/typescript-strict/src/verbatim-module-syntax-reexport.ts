// PROVES: "verbatimModuleSyntax": true — the re-export half.
//
// NAMED FOR WHAT IT ACTUALLY PROVES. This started life as `isolated-modules.ts`,
// on the assumption that a bare type re-export is an isolatedModules error.
// Ablation says otherwise: `--isolatedModules false` changes nothing here, and
// TS1205's own message names verbatimModuleSyntax. See the README — isolated-
// Modules has no independent fixture and is covered by the snapshot alone.
//
// MUST PRODUCE: TS1205 — samples/expected/tsc.json holds the line.
export { Widget } from './types.js';
