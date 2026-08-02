// This is the whole thing a consuming project writes — it consumes the shared
// baseline from ../../configs/typescript and adds nothing of its own.
//
// A real project outside this repo would import from the published package or a
// git devDep instead of a relative path; see the header of the base config.

import base from '../../configs/typescript/eslint.config.mjs';

export default [
  ...base,
  { languageOptions: { parserOptions: { tsconfigRootDir: import.meta.dirname } } },
];
