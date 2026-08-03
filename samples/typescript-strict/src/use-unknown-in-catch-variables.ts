// PROVES: "useUnknownInCatchVariables": true.
//
// A thrown value is not necessarily an Error. Without the flag `err` is `any`
// and `err.message` type-checks all the way to a TypeError in production.
//
// MUST PRODUCE: TS18046 — samples/expected/tsc.json holds the line.
export function attempt(fn: () => void): string {
  try {
    fn();
    return 'ok';
  } catch (err) {
    return err.message;
  }
}
