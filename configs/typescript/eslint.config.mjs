// maxi-quality — TypeScript ESLint baseline (flat config, type-aware)
//
// USAGE — a consuming project's own eslint.config.mjs is ~3 lines:
//
//   import base from '@maximalcode/maxi-quality/configs/typescript/eslint.config.mjs';
//   export default [...base, { /* project-specific overrides here */ }];
//
// Until this repo is published to npm, point at it directly — a file: devDep,
// a git devDep, or a relative import from a sibling checkout:
//
//   import base from '../../configs/typescript/eslint.config.mjs';
//   export default [...base];
//
// The consuming project needs these devDependencies:
//   eslint  @eslint/js  typescript-eslint  typescript
//
// Type-aware linting is ON (projectService). That means every linted file must
// be covered by a tsconfig.json in the project root. If your tsconfig lives
// elsewhere, override tsconfigRootDir in your own config:
//
//   export default [...base, {
//     languageOptions: { parserOptions: { tsconfigRootDir: import.meta.dirname } },
//   }];

import eslint from '@eslint/js';
import sonarjs from 'eslint-plugin-sonarjs';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  // Never lint build output or dependencies.
  {
    ignores: ['**/dist/**', '**/build/**', '**/out/**', '**/coverage/**', '**/node_modules/**'],
  },

  eslint.configs.recommended,

  // Layer 1, the deep part: type-aware bug finding.
  tseslint.configs.strictTypeChecked,
  // Consistency layer. Cheap to satisfy, keeps diffs boring.
  tseslint.configs.stylisticTypeChecked,

  // Sonar's engine as a plain ESLint plugin — the symmetry the C# side already
  // has through SonarAnalyzer.CSharp, with no server, database or dashboard.
  // Adopted on measurement, not reputation (docs/EVAL-vs-oss-tools.md §2b, #11):
  // it contributes FIVE bug classes typescript-eslint has no counterpart for —
  // both if/else branches identical, two functions with identical bodies, a
  // collection read but never filled, a catastrophic-backtracking regex, and
  // `eval` on a non-literal. Each is baited in samples/typescript/src/sonarjs.ts.
  //
  // `recommended` (217 of 279 rules), NOT all 279. Measured: all-279 puts two
  // findings on samples/typescript-clean — `file-header` and
  // `arrow-function-convention`, both rules that need options nobody supplied —
  // and this repo's own rule is that a config which flags the clean fixture has
  // regressed. All-279 would have raised Layer 2 TS coverage from 4/30 to 10/30,
  // so it is a real trade and it is refused on the clean-fixture rule.
  sonarjs.configs.recommended,

  {
    languageOptions: {
      parserOptions: {
        // Pulls type information from the nearest tsconfig automatically.
        projectService: true,
      },
    },
    rules: {
      // --- Things the presets leave looser than I want -------------------
      // `==` is a bug waiting to happen; `== null` stays legal because the
      // null-or-undefined check is genuinely the clearest way to write it.
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      // Unused code is either a mistake or dead weight. `_`-prefixed args are
      // the documented escape hatch for required-but-unused parameters.
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          args: 'all',
          argsIgnorePattern: '^_',
          caughtErrors: 'all',
          caughtErrorsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          ignoreRestSiblings: true,
        },
      ],
      // Suppressions must say why. A bare ts-expect-error tells the next
      // reader nothing.
      '@typescript-eslint/ban-ts-comment': [
        'error',
        { 'ts-expect-error': 'allow-with-description', minimumDescriptionLength: 10 },
      ],
      // console.* is for CLIs, not for libraries; warn so local debugging
      // isn't blocked but CI (--max-warnings 0) still catches leftovers.
      'no-console': 'warn',

      // --- The two SonarJS rules that are switched off, both on measurement --
      // `todo-tag` fires on `TODO(#412)`, which Layer 2's todo-without-issue
      // DELIBERATELY exempts — a tracked TODO is a decision somebody can find
      // again. Two layers disagreeing about one line is worse than either
      // verdict alone; the same reasoning is already written into
      // debug-print-left-behind-ts.
      'sonarjs/todo-tag': 'off',
      // An exact duplicate of @typescript-eslint/no-unused-vars, which is
      // configured above with options this one does not have. Measured: on
      // bad.ts:48 the combined config reported ONE unused variable THREE times
      // (that rule, this one, and sonarjs/no-dead-store).
      //
      // `no-dead-store` STAYS ON — a value assigned and then overwritten before
      // it is read is a different defect from a variable nobody uses, and it is
      // one the baseline had no rule for.
      'sonarjs/no-unused-vars': 'off',

      // --- Two more off, from the real-code noise run -----------------------
      // 44,089 lines of zod, got and zustand: 520 findings, 11.8 per KLOC.
      // Six rules were 86% of it. These two are 52% of it between them, and
      // neither finds a bug (docs/EVAL-vs-oss-tools.md §2e).
      //
      // `no-redundant-optional` IS NOT NOISE — IT IS WRONG HERE, and it was the
      // single highest-volume rule at 144 findings. It asks you to delete the
      // `| undefined` from `retries?: number | undefined`. Our own
      // tsconfig.strict.json sets `exactOptionalPropertyTypes: true`, under
      // which those two spellings mean different things, and following the
      // advice makes tsc reject the code with TS2375. Verified both ways round.
      // Two halves of this baseline cannot contradict each other; the compiler
      // wins, and samples/typescript-clean now carries the shape so a future
      // re-enable fails CI instead of shipping.
      'sonarjs/no-redundant-optional': 'off',
      // 125 findings, all of the form "use '\d' instead of '[0-9]'". A syntax
      // preference with no defect behind it, and 24% of everything the plugin
      // said about real code. This is the same argument that declined
      // eslint-plugin-unicorn — a preset whose dominant output is restyling
      // working code is how a gate gets switched off. `slow-regex` and
      // `regex-complexity`, which find actual ReDoS, stay on.
      'sonarjs/concise-regex': 'off',
      //
      // `cognitive-complexity` STAYS ON despite being third at 100 findings.
      // Sampled, it is real signal — "reduce Cognitive Complexity from 33 to
      // the 15 allowed" on functions that genuinely are that tangled. It is
      // also the rule SonarJS is best known for, and switching it off would
      // leave the plugin doing very little. Adoption on an existing codebase
      // is what `scan.sh --changed-only` is for (README §8).
    },
  },

  // Config files and scripts are allowed to be pragmatic.
  {
    files: ['**/*.config.{js,mjs,cjs,ts}', '**/scripts/**'],
    rules: {
      'no-console': 'off',
    },
  },

  // Plain JS gets the non-type-aware treatment — no tsconfig coverage needed.
  {
    files: ['**/*.{js,mjs,cjs}'],
    extends: [tseslint.configs.disableTypeChecked],
  },
);
