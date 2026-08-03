# An existing repo — start here

The shape for a codebase nobody has linted before, and the one most people
should adopt first.

Two lines do the work:

- **`changed-only: origin/main`** — everything already on the main branch is
  grandfathered on day one, and the gate still fails on anything this branch
  introduces. Semgrep supports this natively via `--baseline-commit`.
- **`languages: 'none'`** — Layer 2 only, at first. Layer 1 has *no* per-finding
  grandfathering in ESLint, Roslyn or mypy: a rule is either on and failing your
  build, or off. Measured on a real codebase, turning it on cold produced 4,902
  findings. Add it one language at a time, when someone has the week.

The `.maxi-quality.yml` downgrades the noisiest advisory rule to a warning for
the first pass. Reported, visible, does not block a merge.

Then tighten: drop `--no-fail` locally in week two, drop `changed-only` once the
tree is clean, and add Layer 1 per language after that.
