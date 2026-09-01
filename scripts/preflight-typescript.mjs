// Internal adapter. The public preflight command owns failure handling.
import { ESLint } from 'eslint';
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import ts from 'typescript';
import prettier from 'prettier';
import format from '../configs/typescript/prettier.config.mjs';

const root = path.resolve(process.argv[2] ?? '.');
const skip = new Set(['node_modules', '.git', 'dist', 'build', 'out', 'coverage']);
/** @param {string} directory @returns {string[]} */
function filesIn(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) return skip.has(entry.name) ? [] : filesIn(file);
    return entry.isFile() ? [file] : [];
  });
}

const files = filesIn(root);
// Match `prettier --check .`, including ignores and non-JavaScript parsers.
// Preserve the original bytes: the tsconfig overlay below is analysis setup,
// never formatting work the adopter needs to do.
const formatInputs = [];
for (const file of files) {
  const info = await prettier.getFileInfo(file, {
    ignorePath: [path.join(root, '.gitignore'), path.join(root, '.prettierignore')],
    resolveConfig: false,
  });
  if (!info.ignored && info.inferredParser) {
    formatInputs.push({ file, content: readFileSync(file, 'utf8') });
  }
}
const configs = files.filter((file) => /^tsconfig(?:\..+)?\.json$/.test(path.basename(file)));
const baseline = ts.readConfigFile(
  new URL('../configs/typescript/tsconfig.strict.json', import.meta.url).pathname,
  ts.sys.readFile,
).config.compilerOptions;
// Preserve project-specific module, target, lib and path settings. The strict
// checks themselves win over explicit false values in an unadopted project.
const strict = Object.fromEntries(
  Object.entries(baseline).filter(
    ([key]) =>
      ![
        'module',
        'moduleResolution',
        'target',
        'lib',
        'declaration',
        'declarationMap',
        'sourceMap',
      ].includes(key),
  ),
);
/** @param {string} tool */
function check(tool) {
  /** @type {[string, string, number, number][]} */
  const findings = [];
  return { tool, status: 'complete', detail: '', findings };
}
const compiler = check('tsc');
const extended = new Set();
const configHost = {
  ...ts.sys,
  /** @param {ts.Diagnostic} diagnostic */
  onUnRecoverableConfigFileDiagnostic(diagnostic) {
    throw new Error(ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n'));
  },
};
// Resolve every original config before writing any of them. Adding a default
// to a child before resolving `extends` shadows inherited browser/module settings.
const prepared = configs.map((file) => {
  const loaded = ts.readConfigFile(file, ts.sys.readFile);
  if (loaded.error)
    throw new Error(ts.flattenDiagnosticMessageText(loaded.error.messageText, '\n'));
  const resolved = ts.getParsedCommandLineOfConfigFile(file, {}, configHost);
  if (!resolved) throw new Error(`Cannot read ${file}`);
  for (const parent of [loaded.config.extends ?? []].flat()) {
    if (parent.startsWith('.')) {
      const resolved = path.resolve(path.dirname(file), parent);
      extended.add(resolved.endsWith('.json') ? resolved : `${resolved}.json`);
    }
  }
  const defaults = Object.fromEntries(
    Object.entries(baseline).filter(([key]) => resolved.options[key] === undefined),
  );
  loaded.config.compilerOptions = { ...defaults, ...loaded.config.compilerOptions, ...strict };
  return { file, config: loaded.config };
});
for (const { file, config } of prepared) {
  writeFileSync(file, JSON.stringify(config));
}
for (const file of configs) {
  if (extended.has(file)) continue;
  const parsed = ts.getParsedCommandLineOfConfigFile(file, { noEmit: true }, configHost);
  if (!parsed) throw new Error(`Cannot read ${file}`);
  const program = ts.createProgram(parsed.fileNames, parsed.options);
  for (const diagnostic of [...parsed.errors, ...ts.getPreEmitDiagnostics(program)]) {
    const position = diagnostic.file?.getLineAndCharacterOfPosition(diagnostic.start ?? 0);
    compiler.findings.push([
      `TS${diagnostic.code}`,
      diagnostic.file?.fileName ?? file,
      (position?.line ?? -1) + 1,
      (position?.character ?? -1) + 1,
    ]);
    if (
      !diagnostic.file ||
      [2307, 2591, 2688, 6053].includes(diagnostic.code) ||
      program.getSyntacticDiagnostics().length
    ) {
      compiler.status = 'incomplete';
      compiler.detail =
        'Compiler configuration or dependencies are incomplete; install dependencies and rerun.';
    }
  }
}
if (!configs.length) {
  compiler.status = 'unavailable';
  compiler.detail =
    'No tsconfig found; typed linting and compiler checks need a project configuration.';
}

const lint = check('eslint');
try {
  const eslint = new ESLint({
    cwd: root,
    overrideConfigFile: new URL('../configs/typescript/eslint.config.mjs', import.meta.url)
      .pathname,
    overrideConfig: [{ languageOptions: { parserOptions: { tsconfigRootDir: root } } }],
  });
  for (const result of await eslint.lintFiles(['**/*.{ts,tsx,mts,cts,js,mjs,cjs}'])) {
    for (const message of result.messages) {
      if (message.fatal || !message.ruleId) {
        lint.status = 'incomplete';
        lint.detail = message.message;
      }
      lint.findings.push([
        message.ruleId ?? 'unparsed',
        result.filePath,
        message.line ?? 0,
        message.column ?? 0,
      ]);
    }
  }
} catch (error) {
  lint.status = 'unavailable';
  lint.detail = String(error);
}

const formatting = check('prettier');
for (const { file, content } of formatInputs) {
  try {
    if (!(await prettier.check(content, { ...format, filepath: file }))) {
      formatting.findings.push(['format', file, 0, 0]);
    }
  } catch (error) {
    formatting.status = 'incomplete';
    formatting.detail = String(error);
  }
}
process.stdout.write(JSON.stringify([compiler, lint, formatting]));
