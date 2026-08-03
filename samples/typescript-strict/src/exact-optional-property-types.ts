// PROVES: "exactOptionalPropertyTypes": true.
//
// `retries?: number` means "absent or a number", not "or explicitly undefined".
// Without the flag the two are conflated and this compiles.
//
// MUST PRODUCE: TS2375 — samples/expected/tsc.json holds the line.
interface Options {
  retries?: number;
}

export const options: Options = { retries: undefined };
