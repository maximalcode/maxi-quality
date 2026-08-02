/*
 * INTENTIONALLY BAD CODE — DO NOT FIX.
 *
 * Layer 2 sample: bait for the semgrep/ ruleset. Deliberately kept OUT of the
 * samples/typescript project so that adding Semgrep bait here never changes the
 * ESLint sample's expected finding count.
 *
 * This file is never compiled or linted — Semgrep only parses it.
 */

import * as childProcess from 'node:child_process';
import { exec, execSync } from 'node:child_process';
import crypto from 'node:crypto';

// --- todo-without-issue ----------------------------------------------------
// TODO: decide whether we keep this endpoint
// TODO(#412): this one is fine — it has an issue and must NOT be flagged

// --- hardcoded-secret-ts ---------------------------------------------------
const apiKey = 'sk_live_9f3b7c1d4e6a8b2c5d7e';
// A URL is exempt, but NOT when it carries userinfo — that is the shape that
// actually leaks, and the #17 value-guard must not blanket-exempt it.
const connectionString = 'postgres://admin:hunter2is@db.internal:5432/prod';

// Negative controls for #17 — these must stay SILENT. If either starts firing,
// the value-guard regressed back to name-only matching (0/5 precision).
const tokenEndpoint = 'https://github.com/login/oauth/access_token';
const UNASSIGNED_TOKEN = 'none';

// --- no-ambient-clock (cross-language proof rule, TS side) -----------------
export function isExpired(expiresAt: Date): boolean {
  return expiresAt < new Date();
}

// --- weak-crypto -----------------------------------------------------------
export function fingerprint(body: string): string {
  return crypto.createHash('md5').update(body).digest('hex');
}

// OpenSSL algorithm names are CASE-INSENSITIVE, so this is a working MD5 and
// was not matched by the literal-only rule. Pass 3.
export function signUpper(body: string): string {
  return crypto.createHash('MD5').update(body).digest('hex');
}

// The rule's message promises DES, but only the exact string "des" was listed.
// Triple-DES is des-ede3 / des-ede3-cbc, which is what real code writes.
export function encryptLegacy(key: Buffer, iv: Buffer) {
  return crypto.createCipheriv('des-ede3-cbc', key, iv);
}

// NEGATIVE CONTROLS for weak-crypto. Modern algorithms must NOT fire — a rule
// that flags every createHash call gets disabled, not fixed.
export function digestOk(body: string): string {
  return crypto.createHash('sha256').update(body).digest('hex');
}

export function encryptOk(key: Buffer, iv: Buffer) {
  return crypto.createCipheriv('aes-256-gcm', key, iv);
}

// --- sql-string-concat-ts --------------------------------------------------
export async function findUser(db: { query: (sql: string) => Promise<unknown> }, id: string) {
  return db.query(`SELECT * FROM users WHERE id = '${id}'`);
}

// The CONCATENATION branch, which had no fixture at all until security review
// pass 3 — so CI was green while `pattern-regex` matched only double quotes and
// the single-quoted form (the prevailing TypeScript style, and the commonest
// SQL-injection shape in JavaScript) went undetected. Both quote styles are
// baited now, because a regex over raw source text does not treat them alike.
export async function findUserDq(db: { query: (sql: string) => Promise<unknown> }, id: string) {
  return db.query("SELECT * FROM users WHERE id = " + id);
}

export async function findUserSq(db: { query: (sql: string) => Promise<unknown> }, id: string) {
  return db.query('SELECT * FROM users WHERE id = ' + id);
}

// The remaining two entry points from the accepted-method list. `.query` was
// the only one with a fixture, so `.execute` and `.raw` were advertised and
// untested — and the list itself is now a bound name plus a regex, which is
// the part that has to be exercised per name.
export async function findUserExecute(db: { execute: (sql: string) => Promise<unknown> }, id: string) {
  return db.execute("SELECT * FROM users WHERE id = " + id);
}

export async function findUserRaw(knex: { raw: (sql: string) => Promise<unknown> }, id: string) {
  return knex.raw(`SELECT * FROM users WHERE id = ${id}`);
}

// Prisma's raw escape hatches. The entry points used to be a fixed list of
// `.query` / `.execute` / `.raw`, so `$queryRawUnsafe` — the method whose NAME
// says it does not parameterise — matched nothing at all.
export async function findUserPrisma(
  prisma: { $queryRawUnsafe: (sql: string) => Promise<unknown> },
  id: string,
) {
  return prisma.$queryRawUnsafe('SELECT * FROM users WHERE id = ' + id);
}

export async function deleteUserPrisma(
  prisma: { $executeRawUnsafe: (sql: string) => Promise<unknown> },
  id: string,
) {
  return prisma.$executeRawUnsafe(`DELETE FROM users WHERE id = ${id}`);
}

// NEGATIVE CONTROL for sql-string-concat-ts. A parameterised query must NOT
// fire, or the rule is just "any query call" and will be switched off.
export async function findUserSafe(
  db: { query: (sql: string, params: unknown[]) => Promise<unknown> },
  id: string,
) {
  return db.query('SELECT * FROM users WHERE id = ?', [id]);
}

// NEGATIVE CONTROL for the widened entry point. `$queryRaw` is a TAGGED
// TEMPLATE and Prisma parameterises its interpolations, so it is the safe form
// of the same API and must stay out of the accepted-method regex.
export async function findUserPrismaSafe(
  prisma: { $queryRaw: (sql: TemplateStringsArray, ...values: unknown[]) => Promise<unknown> },
  id: string,
) {
  return prisma.$queryRaw`SELECT * FROM users WHERE id = ${id}`;
}

// --- command-injection-ts --------------------------------------------------
export function listDir(dir: string): void {
  exec(`ls -la ${dir}`, (err, stdout) => {
    // --- debug-print-left-behind-ts ---
    console.log(stdout);
  });
}

// The two CONCATENATION branches. Neither had a fixture, which is exactly why
// the single-quoted one was missing from the rule for as long as it was: a
// branch nothing bait tests cannot be observed to be absent.
export function listDirDq(dir: string): void {
  exec("ls -la " + dir, () => {});
}

export function listDirSq(dir: string): void {
  exec('ls -la ' + dir, () => {});
}

// ...and the other three entry points, none of which had one either.
export function listDirSync(dir: string): string {
  return execSync('ls -la ' + dir).toString();
}

export function listDirNs(dir: string): void {
  childProcess.exec(`ls -la ${dir}`, () => {});
}

export function listDirNsSync(dir: string): string {
  return childProcess.execSync("ls -la " + dir).toString();
}

// --- catch-and-swallow-ts --------------------------------------------------
export function loadSettings(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch (e) {
  }
}

// The OPTIONAL-BINDING branch. `catch { }` and `catch (e) { }` are separate
// patterns because they are separate AST shapes, and only the bound form had
// bait — the bare form was covered solely by the negative control below, which
// proves the escape hatch works and nothing about the branch still matching.
export function loadSettingsBare(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
  }
}

// NEGATIVE CONTROL for catch-and-swallow-ts. This one must NOT fire.
//
// The rule's message promises that a comment explaining the silence clears the
// finding. Until 2026-07-31 that promise was false — Semgrep matches the AST,
// comments are not AST nodes, so this block was still `{ }` to the pattern.
//
// It lives in the BAD sample deliberately: the suite asserts exactly what
// fires, so if the escape hatch ever breaks again this file gains a
// catch-and-swallow-ts finding it is not supposed to have and CI fails. No new
// assertion needed — the existing one IS the test.
export function tryClose(close: () => void): void {
  try {
    close();
  } catch {
    // Already closed — the caller cannot act on this and does not need to.
  }
}

// --- no-permission-denied-for-invisible-resource-ts -----------------------
class HttpError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function getDocument(doc: { id: string } | undefined): { id: string } {
  if (!doc) {
    // Leaks that the document exists to anyone probing ids.
    throw new HttpError(403, 'Forbidden');
  }
  return doc;
}

// The other four branches. `!x`, `=== null` and `=== undefined` are three
// different AST shapes and the rule spells out all three; only the first had
// bait. The two express idioms below are the shapes this actually takes in a
// real handler, and they had none at all.
export function getDocumentNull(doc: { id: string } | null): { id: string } {
  if (doc === null) {
    throw new HttpError(403, 'Forbidden');
  }
  return doc;
}

export function getDocumentUndefined(doc: { id: string } | undefined): { id: string } {
  if (doc === undefined) {
    throw new HttpError(403, 'Forbidden');
  }
  return doc;
}

interface Res {
  status: (code: number) => Res;
  send: (body: string) => void;
}

export function sendDocument(doc: { id: string } | undefined, res: Res): void {
  if (!doc) {
    res.status(403);
    return;
  }
  res.status(200).send(doc.id);
}

export function returnDocument(doc: { id: string } | undefined, res: Res): void {
  if (!doc) {
    return res.status(403).send('Forbidden');
  }
  res.status(200).send(doc.id);
}

export { apiKey };
