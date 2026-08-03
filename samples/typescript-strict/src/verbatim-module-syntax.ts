// PROVES: "verbatimModuleSyntax": true — the import half.
//
// `Widget` is a type. Imported without `type`, the import statement survives
// into the emitted JavaScript and resolves a module at runtime that only ever
// existed at compile time.
//
// MUST PRODUCE: TS1484 — samples/expected/tsc.json holds the line.
import { Widget } from './types.js';

export function idOf(w: Widget): string {
  return w.id;
}
