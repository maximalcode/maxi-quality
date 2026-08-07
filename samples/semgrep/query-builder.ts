// Bait for the "one step away from the sink" half of sql-string-concat and
// command-injection — see issue #20 and the rule comments in
// semgrep/security/. Every case here is silent under the sink-anchored rules
// and must fire under the builder/indirect ones.
//
// It is a separate file from bad.ts on purpose: appending to bad.ts would shift
// every line number below the insertion point in samples/expected/semgrep.json,
// and that churn is what hides a real regression in a large diff.
//
// Nothing here is compiled or linted. Semgrep only parses it.
import childProcess, { exec, execSync } from 'child_process';

interface Db {
  query: (sql: string, params?: unknown[]) => Promise<unknown>;
}

// --- sql-string-concat-builder-ts -------------------------------------------
// One fixture per statement branch, rotated across all three regex branches —
// backtick, double-quoted and single-quoted — because these are regexes over
// raw source text and one quote style says nothing about the others.

// branch: `return $SQL;` — single-quoted concatenation
export function byIdConcat(id: string): string {
  return 'SELECT * FROM users WHERE id = ' + id;
}

// branch: concise arrow body — double-quoted concatenation. Semgrep normalises
// this to a return, so it is the same rule branch reached by a different
// syntax; it is baited because the normalisation is an assumption, not a fact
// of the language.
export const byIdArrow = (id: string): string => "SELECT * FROM users WHERE id = " + id;

// branch: declaration — template literal. The shape that made the gap worth
// closing: the sink is on the next line and the sink-anchored rule sees an
// identifier.
export async function runConst(db: Db, id: string): Promise<unknown> {
  const sql = `DELETE FROM users WHERE id = ${id}`;
  return db.query(sql);
}

// branch: assignment to an existing binding — single-quoted concatenation
export async function runReassigned(db: Db, id: string): Promise<unknown> {
  let sql = 'SELECT * FROM users';
  sql = 'SELECT * FROM users WHERE id = ' + id;
  return db.query(sql);
}

// DUPLICATION CONTROL for the `^` anchors in the builder rule's regexes.
// `pattern-regex` inside a `metavariable-pattern` is a substring match, so
// unanchored it would match the concatenation nested inside this sink call and
// report the enclosing `return` on top of sql-string-concat-ts. Exactly ONE
// finding must land on this line.
export async function returnSink(db: Db, id: string): Promise<unknown> {
  return db.query('SELECT * FROM users WHERE id = ' + id);
}

// NEGATIVE CONTROLS. String building is the commonest thing in any codebase, so
// a builder rule not keyed on a SQL keyword is a rule against concatenation.
export const greet = (name: string): string => 'Hello ' + name;

export function paragraph(body: string): string {
  return `<p>${body}</p>`;
}

export async function parameterised(db: Db, id: string): Promise<unknown> {
  const sql = 'SELECT * FROM users WHERE id = ?';
  return db.query(sql, [id]);
}

// --- command-injection-indirect-ts ------------------------------------------
// One fixture per sink branch, rotated across the three source quote styles.
// Unlike SQL there is no keyword to key on, which is why this half is taint
// with the sink kept, rather than a sink-free pattern.

// branch: bare exec — template literal source
export function listDir(dir: string): void {
  const cmd = `ls -la ${dir}`;
  exec(cmd, () => {});
}

// branch: bare execSync — double-quoted concatenation source
export function listDirSync(dir: string): string {
  const cmd = "ls -la " + dir;
  return execSync(cmd).toString();
}

// branch: namespaced exec — single-quoted concatenation source
export function listDirNs(dir: string): void {
  const cmd = 'ls -la ' + dir;
  childProcess.exec(cmd, () => {});
}

// branch: namespaced execSync — template literal source
export function listDirNsSync(dir: string): string {
  const cmd = `ls -la ${dir}`;
  return childProcess.execSync(cmd).toString();
}

// DUPLICATION CONTROL. The inline form belongs to command-injection-ts, and the
// sink's metavariable-regex — a bare identifier only — keeps this rule off it.
// Exactly ONE finding on this line.
export function listDirInline(dir: string): void {
  exec(`ls -la ${dir}`, () => {});
}

// KNOWN GAP, kept visible on purpose. Semgrep OSS taint is intraprocedural, so
// the helper form is NOT reachable and this line is silent. If a future Semgrep
// makes it reachable, this comment is the thing to delete — but the finding then
// has to be added to samples/expected/semgrep.json in the same change, or the
// manifest fails.
function buildCommand(dir: string): string {
  return 'ls -la ' + dir;
}

export function listDirViaHelper(dir: string): void {
  exec(buildCommand(dir), () => {});
}

// NEGATIVE CONTROL. A command with no interpolated value at all is not tainted,
// so binding it to a variable must not be enough on its own.
export function listRoot(): void {
  const cmd = 'ls -la /';
  exec(cmd, () => {});
}
