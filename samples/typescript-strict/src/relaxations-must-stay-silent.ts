// PROVES: "lib": ["es2023"] and "esModuleInterop": true — BY STAYING SILENT.
//
// These two are permissive rather than strict, so no code fails while they are
// on. They are asserted in the opposite direction: this file compiles cleanly
// today, and the expected-findings manifest is a SET, so a NEW error here fails
// CI exactly as a missing one does.
//
//   - `findLast` arrived in ES2023. Drop lib to es2020 and this is TS2550.
//   - the default import of a CommonJS module needs esModuleInterop.
//
// Caveat, measured on typescript 6.0.3: `esModuleInterop: false` is refused
// outright (TS5107, deprecated and removed in TypeScript 7), so that half
// cannot be ablated and is really the snapshot's job.
//
// MUST PRODUCE: nothing.
import assert from 'node:assert';

export function lastEven(ns: number[]): number | undefined {
  return ns.findLast((n) => n % 2 === 0);
}

export function check(ok: boolean): void {
  assert.ok(ok);
}
