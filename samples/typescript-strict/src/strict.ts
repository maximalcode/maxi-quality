// PROVES: "strict": true — via two of its sub-flags.
//
// `strict` is an umbrella; tsc --showConfig does not expand it, so the snapshot
// can only see that it is on. These two errors are what say it is doing
// something. Ablation (see the README): --strictNullChecks false removes the
// first, --noImplicitAny false removes the second.
//
// MUST PRODUCE: TS2322 and TS7006 — samples/expected/tsc.json holds the lines.

// strictNullChecks — `null` is not silently assignable to a declared string.
export const label: string = null;

// noImplicitAny — an untyped parameter is an error, not an implicit `any`.
export function greet(name): string {
  return `hi ${String(name)}`;
}
