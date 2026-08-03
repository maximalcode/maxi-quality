// PROVES: "noImplicitReturns": true.
//
// THE RETURN TYPE INCLUDES `undefined` ON PURPOSE. Written as `: string` this
// file still fails, but with TS2366 from strictNullChecks — the same red CI on
// a different flag, so deleting noImplicitReturns would leave it green. Widening
// the return type satisfies strictNullChecks and leaves TS7030 as the only
// thing holding the error up. Verified by ablation, not by reading the docs.
//
// MUST PRODUCE: TS7030 — samples/expected/tsc.json holds the line.
export function classify(n: number): string | undefined {
  if (n > 0) {
    return 'positive';
  }
}
