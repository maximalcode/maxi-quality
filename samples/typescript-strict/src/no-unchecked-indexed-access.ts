// PROVES: "noUncheckedIndexedAccess": true.
//
// Without it, `names[0]` types as `string` and this file compiles — which is
// the lie the flag exists to remove. It is also the compiler half of the bug
// samples/typescript/src/bad.ts plants for ESLint's non-null assertion.
//
// MUST PRODUCE: TS2322 — samples/expected/tsc.json holds the line.
export function firstUpper(names: string[]): string {
  const first: string = names[0];
  return first.toUpperCase();
}
