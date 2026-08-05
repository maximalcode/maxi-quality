#!/usr/bin/env node
/*
 * Snapshot the ESLint rules the baseline actually ENABLES, and fail when one
 * silently disappears.
 *
 * WHY THIS EXISTS, AND WHY THE FINDINGS MANIFEST IS NOT ENOUGH
 *
 * samples/expected/eslint.json pins the findings the bad fixture produces. That
 * catches a rule that stops firing on something we bait. It cannot catch a rule
 * that bait nothing — and that is nearly all of them: configs/typescript enables
 * 140 rules and the fixture triggers 8. Measured, not estimated: replacing the
 * whole shared config with an 18-line file that drops eslint.configs.recommended,
 * strictTypeChecked and stylisticTypeChecked and hand-lists those 8 rules leaves
 * both CI steps green with 94% of the baseline deleted.
 *
 * So this asserts the CONFIGURATION rather than the output. It is the only
 * mechanism that notices `no-misused-promises` being switched off, a preset
 * downgraded from strictTypeChecked to recommendedTypeChecked, or the hand-tuned
 * options on eqeqeq / no-unused-vars / ban-ts-comment being reverted to defaults
 * — none of which any fixture can see.
 *
 * OPTIONS ARE PART OF THE SNAPSHOT. `eqeqeq: ['error', 'always', {null: 'ignore'}]`
 * degrading to `eqeqeq: 'error'` changes real behaviour and leaves every finding
 * count untouched, so the serialised value is [severity, ...options], not just
 * the severity.
 *
 * SEVERAL PATHS ARE SAMPLED, because the config is path-dependent by design:
 * the scripts-directory and config-file blocks turn no-console off, and plain
 * JS gets disableTypeChecked. One path would leave those blocks unasserted, and
 * they are exactly the kind of thing that gets deleted as dead weight.
 * (Globs are spelled out in the PROBES comments below rather than here — a
 * doubled star followed by a slash would close this comment.)
 *
 * A typescript-eslint upgrade WILL change this snapshot and turn CI red. That is
 * the intended behaviour and it matches the policy already stated in
 * docs/STATUS.md §4 — an analyzer upgrade that adds or drops rules is a breaking
 * change for a repo with an exact-count gate, and the bump PR is where a human
 * reads the diff and decides. Regenerate with --write, and say in the commit
 * message what moved and why.
 *
 * Usage:
 *   node scripts/snapshot-eslint-rules.mjs --check    # CI: diff against the snapshot
 *   node scripts/snapshot-eslint-rules.mjs --write    # regenerate it deliberately
 *
 * Exit codes: 0 snapshot matches · 1 the enabled rule set drifted · 3 usage error
 */

import { ESLint } from 'eslint';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';

// Relative to samples/typescript, which is where the baseline is consumed the
// way a real project consumes it. Each path exists to pin a different config
// block; see the header.
const PROBES = [
  'src/bad.ts', // type-aware TypeScript — the main surface
  'scripts/tool.ts', // the **/scripts/** waiver (no-console off)
  'eslint.config.mjs', // *.config.mjs — same waiver, different glob
  'legacy.js', // plain JS — tseslint disableTypeChecked
];

const SNAPSHOT = 'configs/typescript/expected-rules.json';
// ESLint requires an absolute cwd. Resolve against process.cwd() so the script
// is run from the repo root, like every other check in ci.yml.
const CWD = path.resolve(process.cwd(), 'samples/typescript');

const mode = process.argv[2];
if (mode !== '--check' && mode !== '--write') {
  process.stderr.write('usage: snapshot-eslint-rules.mjs --check|--write\n');
  process.exit(3);
}

// `severity` is normalised to a number by ESLint; map it back so the snapshot
// reads the way the config is written.
const NAMES = ['off', 'error', 'warn'];
const severityName = (s) => (s === 2 ? 'error' : s === 1 ? 'warn' : 'off');

const eslint = new ESLint({ cwd: CWD });
const snapshot = {};

for (const probe of PROBES) {
  // calculateConfigForFile resolves the config a path WOULD get; the file does
  // not have to exist, which is what lets one probe stand in for a whole glob
  // without planting a fixture for it.
  const config = await eslint.calculateConfigForFile(path.join(CWD, probe));
  const rules = {};
  for (const [id, entry] of Object.entries(config.rules ?? {})) {
    const value = Array.isArray(entry) ? entry : [entry];
    const [severity, ...options] = value;
    if (severityName(severity) === 'off') continue;
    rules[id] = [severityName(severity), ...options];
  }
  snapshot[probe] = Object.fromEntries(
    Object.entries(rules).sort(([a], [b]) => a.localeCompare(b)),
  );
}

const serialised = `${JSON.stringify(snapshot, null, 2)}\n`;

if (mode === '--write') {
  writeFileSync(SNAPSHOT, serialised);
  const counts = PROBES.map((p) => `${p}=${Object.keys(snapshot[p]).length}`).join(' ');
  process.stderr.write(`wrote ${SNAPSHOT} (${counts})\n`);
  process.exit(0);
}

let expected;
try {
  expected = JSON.parse(readFileSync(SNAPSHOT, 'utf8'));
} catch (err) {
  // A missing or unparseable snapshot is NOT "nothing expected" — that would
  // make deleting the file a passing gate.
  process.stderr.write(`error: ${SNAPSHOT} is unusable: ${err.message}\n`);
  process.exit(3);
}

let drifted = false;
for (const probe of PROBES) {
  const exp = expected[probe] ?? {};
  const act = snapshot[probe] ?? {};
  const ids = [...new Set([...Object.keys(exp), ...Object.keys(act)])].sort();
  for (const id of ids) {
    const e = exp[id] ? JSON.stringify(exp[id]) : null;
    const a = act[id] ? JSON.stringify(act[id]) : null;
    if (e === a) continue;
    drifted = true;
    if (e && !a) {
      process.stderr.write(
        `::error::${probe}: rule '${id}' is no longer enabled — a check was REMOVED (was ${e})\n`,
      );
    } else if (!e && a) {
      process.stderr.write(`  ADDED    ${probe}: ${id} = ${a}\n`);
    } else {
      process.stderr.write(`::error::${probe}: rule '${id}' changed: ${e} -> ${a}\n`);
    }
  }
}

const total = PROBES.reduce((n, p) => n + Object.keys(snapshot[p]).length, 0);
process.stdout.write(`eslint_enabled_rules=${total}\n`);

if (!drifted) {
  process.stderr.write(
    `OK: enabled rule set matches ${SNAPSHOT} (${total} rule bindings across ${PROBES.length} probes)\n`,
  );
  process.exit(0);
}

process.stderr.write(
  `\nThe enabled ESLint rule set drifted from ${SNAPSHOT}.\n` +
    'If deliberate — a typescript-eslint bump, or a rule you meant to change —\n' +
    'regenerate with `node scripts/snapshot-eslint-rules.mjs --write` and say in\n' +
    'the commit message what moved and why (CONTRIBUTING.md rule 2).\n' +
    'Never regenerate to make a red build green.\n',
);
process.exit(1);
