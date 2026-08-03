/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * Bait for `eslint-plugin-sonarjs`, adopted in #11. The plugin was measured
 * before it was adopted (docs/EVAL-vs-oss-tools.md §2b) and scored **1 of 8**
 * on bad.ts — it implements no counterpart for `no-floating-promises` or the
 * `no-unsafe-*` family, and on our own fixtures it looks nearly worthless.
 *
 * That scoreboard under-counts by construction, because our fixtures bait our
 * rules. The reverse probe is what earned the plugin its place: five defect
 * classes typescript-eslint has no rule for at all. This file is those five,
 * so the claim is a gate rather than a paragraph in a document.
 *
 * If a typescript-eslint upgrade ever grows a counterpart, this file is where
 * the duplicate shows up — as two rule ids on one line in the manifest.
 *
 * Planted findings and the rule that must fire:
 *   1. both if/else branches identical   sonarjs/no-all-duplicated-branches
 *   2. identical function bodies         sonarjs/no-identical-functions
 *   3. collection read, never filled     sonarjs/no-empty-collection
 *   4. catastrophic-backtracking regex   sonarjs/slow-regex
 *   5. eval on a non-literal             sonarjs/code-eval
 */

// --- 1. Both branches identical --------------------------------------------
// The condition is decoration: whatever it evaluates to, the result is the
// same. Either the condition is dead or one branch was never written.
export function priceFor(tier: string): number {
  let price: number;
  if (tier === 'gold') {
    price = 100;
  } else {
    price = 100;
  }
  return price;
}

// --- 2. Two functions with identical bodies ---------------------------------
// A fix applied to one silently does not reach the other. This is the class
// that a diff review cannot see, because the two are never adjacent.
export function totalNet(prices: number[]): number {
  let total = 0;
  for (const price of prices) {
    total += price;
  }
  return total;
}

export function totalGross(prices: number[]): number {
  let total = 0;
  for (const price of prices) {
    total += price;
  }
  return total;
}

// --- 3. A collection that is read but never filled ---------------------------
// Every read returns nothing, forever. The code looks like it works and the
// type system agrees with it.
export function firstWarning(): string | undefined {
  const warnings: string[] = [];
  return warnings.find((w) => w.length > 0);
}

// --- 4. Catastrophic backtracking (ReDoS) -----------------------------------
// Nested quantifiers over an overlapping character class. On a non-matching
// input this is exponential, and the input is usually user-supplied.
export function looksLikeCsv(input: string): boolean {
  return /^(\w+\s?)+$/.test(input);
}

// --- 5. eval on a value that is not a literal --------------------------------
// The Layer 2 command-injection rules cover `exec`; nothing in the baseline
// covered `eval` itself.
export function compute(expr: string): unknown {
  return eval(expr);
}
