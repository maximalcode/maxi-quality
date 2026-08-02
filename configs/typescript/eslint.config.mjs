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
