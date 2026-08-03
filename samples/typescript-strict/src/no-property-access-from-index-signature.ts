// PROVES: "noPropertyAccessFromIndexSignature": true.
//
// `env.HOME` reads like a checked property and is not one — the index signature
// makes every name legal, so a typo types fine and is undefined at runtime.
// The flag forces `env['HOME']`, which at least looks like the lookup it is.
//
// MUST PRODUCE: TS4111 — samples/expected/tsc.json holds the line.
interface Env {
  [key: string]: string | undefined;
}

export function readHome(env: Env): string | undefined {
  return env.HOME;
}
