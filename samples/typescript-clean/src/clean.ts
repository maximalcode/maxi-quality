/*
 * DELIBERATELY CLEAN CODE — `npm run lint` MUST PASS with zero findings.
 *
 * This file is the negative control for configs/typescript. Every block is the
 * correct counterpart of a planted bug in ../../typescript/src/bad.ts, written
 * the way the baseline wants it. A config that flags everything is as useless
 * as one that flags nothing, and until this file existed that second half of
 * the claim was asserted in the docs but never tested.
 *
 * If this file starts FAILING, the baseline has become over-strict — fix the
 * config. Do not silence it here with disable comments; a suppression would
 * defeat the entire point of the fixture.
 *
 * Counterpart map (bad.ts finding -> the fix below):
 *   1. floating promise         -> awaited
 *   2. any-leak                 -> `unknown` + a type guard at the boundary
 *   3. `==`                     -> `===` on operands of the same type
 *   4. unused variable          -> the value is actually used
 *   5. unsafe member access     -> access on a narrowed, typed value
 *   6. non-null assertion       -> the undefined case is handled
 */

// --- 1. Awaited promise. Rejections propagate to the caller ------------------
async function delay(ms: number): Promise<void> {
  await new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function saveUser(name: string): Promise<string> {
  await delay(1);
  return `saved ${name}`;
}

export async function onSubmit(): Promise<string> {
  return await saveUser('ada');
}

// --- 2 & 5. `unknown` at the boundary, narrowed by a guard ------------------
interface ServerConfig {
  server: {
    port: number;
  };
}

function isServerConfig(value: unknown): value is ServerConfig {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const candidate = value as { server?: unknown };
  if (typeof candidate.server !== 'object' || candidate.server === null) {
    return false;
  }
  const server = candidate.server as { port?: unknown };
  return typeof server.port === 'number';
}

export function parseConfig(raw: string): ServerConfig {
  // JSON.parse returns `any`; widening it to `unknown` is the one assignment
  // the baseline allows, because it forces the guard below.
  const parsed: unknown = JSON.parse(raw);
  if (!isServerConfig(parsed)) {
    throw new TypeError('config must contain a numeric server.port');
  }
  return parsed;
}

export function getPort(raw: string): number {
  // `.server.port` is now a checked, typed access — the compiler knows it
  // exists and knows it is a number.
  return parseConfig(raw).server.port;
}

// --- 3. Strict equality between operands of the same type -------------------
export function isAdmin(roleId: number, adminRoleId: number): boolean {
  return roleId === adminRoleId;
}

// --- 4. Every declared value is used -----------------------------------------
export function computeTotal(prices: number[], taxRate: number): number {
  const subtotal = prices.reduce((sum, price) => sum + price, 0);
  return subtotal * (1 + taxRate);
}

// --- 6. The empty-array case is handled instead of asserted away ------------
export function firstUpper(names: string[]): string | undefined {
  const first = names[0];
  return first?.toUpperCase();
}
