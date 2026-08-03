// The whole of it. `eslint.base.mjs` is written by adopt.sh.
import base from './eslint.base.mjs';

export default [
  ...base,
  { languageOptions: { parserOptions: { tsconfigRootDir: import.meta.dirname } } },
];
