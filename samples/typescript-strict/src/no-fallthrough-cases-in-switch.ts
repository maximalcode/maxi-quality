// PROVES: "noFallthroughCasesInSwitch": true.
//
// The `case 'a'` body does not break or return, so it falls into `case 'b'` and
// returns 'b' for both inputs.
//
// NO `console.log` HERE, deliberately. The obvious way to write a fallthrough
// body trips `debug-print-left-behind-ts` and would push a Layer 1 fixture into
// the Layer 2 manifest — the same separation samples/semgrep/README.md keeps in
// the other direction.
//
// MUST PRODUCE: TS7029 — samples/expected/tsc.json holds the line.
export function route(kind: 'a' | 'b', log: string[]): string {
  switch (kind) {
    case 'a':
      log.push('a');
    case 'b':
      return 'b';
  }
}
