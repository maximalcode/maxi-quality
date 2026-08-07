#!/usr/bin/env node
/*
 * Snapshot the compiler options configs/typescript/tsconfig.strict.json actually
 * RESOLVES TO, and fail when one silently disappears.
 *
 * WHY THIS EXISTS, AND WHY THE FIXTURE IS NOT ENOUGH
 *
 * This is the tsconfig twin of scripts/snapshot-eslint-rules.mjs, and it exists
 * for the same measured reason. samples/typescript-strict pins the errors the
 * strict flags produce, which catches a flag that stops firing on something we
 * bait. It cannot catch a flag that nothing bakes an error out of, and several
 * of them cannot be baited at all:
 *
 *   - skipLibCheck and esModuleInterop are RELAXATIONS. Nothing fails while
 *     they are on. (The fixture asserts them in the negative — see below — but
 *     only within the shapes it happens to contain.)
 *   - declaration / declarationMap / sourceMap change EMIT, and the fixture
 *     runs --noEmit.
 *   - forceConsistentCasingInFileNames needs a case-insensitive filesystem to
 *     differ at all; on a Linux runner the import fails either way.
 *   - isolatedModules is subsumed by verbatimModuleSyntax here: measured with
 *     tsc 6.0.3, `--isolatedModules false` changes not one error in the fixture.
 *
 * So this asserts the CONFIGURATION rather than the output, and it is the only
 * mechanism that notices any of those being deleted.
 *
 * IT IS `tsc --showConfig`, NOT A READ OF THE JSON FILE. Reading the file would
 * assert what we wrote; --showConfig asserts what the compiler resolved,
 * including the options tsc IMPLIES rather than us setting them — `nodenext`
 * implies moduleDetection: force, isolatedModules implies preserveConstEnums.
 * Those are real behaviour and they move when `module` moves, so they belong in
 * the snapshot.
 *
 * THE PROBE IS SYNTHETIC ON PURPOSE. It is a throwaway tsconfig that extends the
 * baseline by absolute path and adds nothing else, so the snapshot is the
 * baseline's own resolved options and nothing of any sample's — no rootDir, no
 * outDir, no file list to churn every time a fixture is added. `--showConfig`
 * needs at least one input file or it exits TS18003, hence the one-line probe.
 *
 * A typescript upgrade CAN change this snapshot — a new implied option, a
 * changed default. That is the intended behaviour and matches the policy for the
 * ESLint snapshot: the bump PR is where a human reads the diff and decides.
 * Regenerate with --write and say in the commit message what moved and why.
 *
 * Usage:
 *   node scripts/snapshot-tsconfig.mjs --check    # CI: diff against the snapshot
 *   node scripts/snapshot-tsconfig.mjs --write    # regenerate it deliberately
 *
 * Exit codes: 0 snapshot matches · 1 the resolved options drifted · 3 usage error
 */

import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const BASE = path.join(REPO, 'configs', 'typescript', 'tsconfig.strict.json');
const SNAPSHOT = path.join(REPO, 'configs', 'typescript', 'tsconfig.snapshot.json');
const TSC = path.join(REPO, 'node_modules', '.bin', 'tsc');

const mode = process.argv[2];
if (mode !== '--check' && mode !== '--write') {
  process.stderr.write('usage: snapshot-tsconfig.mjs --check | --write\n');
  process.exit(3);
}

function resolveOptions() {
  const dir = mkdtempSync(path.join(tmpdir(), 'maxi-tsconfig-'));
  try {
    writeFileSync(path.join(dir, 'probe.ts'), 'export const probe = 1;\n');
    writeFileSync(
      path.join(dir, 'tsconfig.json'),
      JSON.stringify({ extends: BASE, files: ['probe.ts'] }),
    );
    // --showConfig writes to stdout and exits 0; a resolution failure (a deleted
    // base, a syntax error in it) exits non-zero and execFileSync throws, which
    // is the behaviour we want — a snapshot check that cannot resolve the config
    // must fail, not compare an empty object.
    const out = execFileSync(TSC, ['--showConfig', '-p', path.join(dir, 'tsconfig.json')], {
      encoding: 'utf8',
    });
    // `files` is the probe path in a temp directory: machine-specific, and not
    // part of what the baseline promises.
    const { compilerOptions } = JSON.parse(out);
    return Object.fromEntries(
      Object.entries(compilerOptions).sort(([a], [b]) => a.localeCompare(b)),
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

const resolved = resolveOptions();
const serialised = `${JSON.stringify(resolved, null, 2)}\n`;

if (mode === '--write') {
  writeFileSync(SNAPSHOT, serialised);
  process.stdout.write(
    `wrote ${path.relative(REPO, SNAPSHOT)} — ${Object.keys(resolved).length} resolved options\n`,
  );
  process.exit(0);
}

let committed;
try {
  committed = readFileSync(SNAPSHOT, 'utf8');
} catch {
  process.stderr.write(
    `::error::${path.relative(REPO, SNAPSHOT)} is missing. Run: node scripts/snapshot-tsconfig.mjs --write\n`,
  );
  process.exit(1);
}

if (committed === serialised) {
  process.stdout.write(
    `tsconfig snapshot matches — ${Object.keys(resolved).length} resolved compiler options\n`,
  );
  process.exit(0);
}

// Name what moved. A bare "files differ" leaves the reader to diff two JSON
// blobs by eye, and the whole point of this check is that a DELETED option is
// easy to miss.
const before = JSON.parse(committed);
const keys = [...new Set([...Object.keys(before), ...Object.keys(resolved)])].sort();
process.stderr.write('::error::the resolved TypeScript compiler options drifted:\n');
for (const k of keys) {
  const b = JSON.stringify(before[k]);
  const a = JSON.stringify(resolved[k]);
  if (b === a) continue;
  if (a === undefined) process.stderr.write(`  REMOVED  ${k}: ${b}\n`);
  else if (b === undefined) process.stderr.write(`  ADDED    ${k}: ${a}\n`);
  else process.stderr.write(`  CHANGED  ${k}: ${b} -> ${a}\n`);
}
process.stderr.write(
  'If this was deliberate, regenerate with: node scripts/snapshot-tsconfig.mjs --write\n',
);
process.exit(1);
