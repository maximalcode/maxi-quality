# samples/knip — the dead-code and dependency bait

The #39 slop corpus, promoted to a fixture by #51. Every planted finding is
asserted in `samples/expected/knip.json` (fixture-relative paths — knip runs
from inside this directory); the negative controls are asserted by the same
manifest, because anything extra fires as UNEXPECTED.

Planted (6 cases, 7 manifest entries — `storeThing` surfaces at both its
source and the barrel re-export):

| Case | Where | knip reports |
|---|---|---|
| unused file | `src/orphan.ts` | `files` |
| unused export | `util.unusedExport` | `exports` |
| unused exported type | `util.UnusedShape` | `types` |
| unused export through a barrel | `storeThing` via `src/barrel/` | `exports` ×2 |
| unused dependency | `left-pad` in package.json | `dependencies` |
| unlisted dependency | `lodash` imported, never declared | `unlisted` |

Negative controls — flagged by NONE of the above, and the reason this fixture
earns its place (a detector that cannot pass these reports style, not slop):

- `src/lazy.ts` — reachable only through a literal dynamic `import()`
- `ms` — a dependency that is actually imported
- `typescript` — a devDependency used by tsconfig.json, not by any import
- `usedHelper`, `UsedShape`, `fetchThing` — exports with real consumers

There is deliberately no `knip.json` here: the fixture follows knip's default
layout (`main` + `src/`), so it also proves the zero-config path. The
config-is-load-bearing proof lives in `samples/knip-clean`, whose entry point
knip cannot find on its own — CI moves that config aside and asserts the
verdict flips.

The packages in `dependencies` are bait, not software: nothing installs them,
knip's analysis is static. Do not "fix" the unused ones — fixing a fixture
deletes the test (CONTRIBUTING.md rule 2).
