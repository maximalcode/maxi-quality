/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * This file is the test suite for configs/typescript. Every block below is a
 * planted bug that the baseline must catch. If `npm run lint` ever passes here,
 * the config regressed — fix the config, not this file.
 *
 * Planted findings and the rule that must fire:
 *   1. floating promise            @typescript-eslint/no-floating-promises
 *   2. any-leak / unsafe usage     @typescript-eslint/no-explicit-any,
 *                                  no-unsafe-assignment, no-unsafe-return
 *   3. == comparison               eqeqeq
 *   4. unused variable             @typescript-eslint/no-unused-vars
 *   5. unsafe member access        @typescript-eslint/no-unsafe-member-access
 */

// --- 1. Floating promise: nothing awaits or catches this ---------------------
async function saveUser(name: string): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 1));
  process.stdout.write(`saved ${name}\n`);
}

export function onSubmit(): void {
  // No await, no .catch() — a rejection here is an unhandled rejection.
  saveUser('ada');
}

// --- 2. any-leak: `any` crosses the boundary and infects every caller -------
export function parseConfig(raw: string): any {
  return JSON.parse(raw);
}

export function getPort(raw: string): number {
  const config = parseConfig(raw);
  // 5. Unsafe member access + unsafe return: `config` is `any`, so the compiler
  // has no idea `.server.port` exists or that it is a number.
  return config.server.port;
}

// --- 3. Loose equality across types ----------------------------------------
export function isAdmin(roleId: number, expected: string): boolean {
  // `==` coerces; `1 == '1'` is true. This is the bug eqeqeq exists to catch.
  return roleId == expected;
}

// --- 4. Unused variable ----------------------------------------------------
export function computeTotal(prices: number[]): number {
  const taxRate = 0.19; // never used — either a forgotten calculation or dead weight
  let total = 0;
  for (const price of prices) {
    total += price;
  }
  return total;
}

// --- Bonus: non-null assertion hiding a real undefined ---------------------
export function firstUpper(names: string[]): string {
  // noUncheckedIndexedAccess says this can be undefined; `!` silences the
  // compiler instead of handling the empty-array case.
  return names[0]!.toUpperCase();
}
