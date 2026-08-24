# Public and adoptable, with no support obligation

This repo is public and anyone may wire the baseline into their own repository,
but the only thing owed to them is the **version contract** — what may and may
not change under a tag they have pinned. Issues and pull requests from outside
carry no promise of a response, and no language, package manager or CI host
gets added because someone outside asks for it.

## Why this was decided at all

Nothing in `CONCEPT.md` said who the baseline was for. Its goals describe what
it does; its success criteria name one specific consumer. Meanwhile G2 ("new
project onboarding ≤ 10 minutes") and §10 ("using only this repo's README") are
written for a stranger, and publishing cost two fresh-repo rebuilds — which is
not what transparency alone is worth.

That gap was load-bearing. Nine tracker issues could not be ranked without it,
because each one is only a defect if reach is a goal.

## Considered options

- **A personal baseline that happens to be public.** Rejected: the README, the
  quick start and the ten-minute onboarding claim are all already aimed at
  someone who does not work here. Calling it personal would make the docs a lie
  rather than making the repo simpler.
- **A baseline meant for outside adoption.** Rejected: it carries a permanent
  maintenance tax — triage of strangers' issues, a semver contract, and
  pressure to add languages nobody here writes. The evidence bar that makes
  this repo worth anything (measure, publish numbers, decline nine of ten) does
  not survive that pressure.
- **Public and genuinely adoptable, no support obligation.** Chosen.

## Consequences

- The **supported stack** is stated in `README.md` so an Adopter learns the
  boundary before wiring anything up. An unstated boundary is the specific
  dishonesty this decision exists to remove; a narrow one is not.
- **In-house demand** stays the test that admits a language. A fixture corpus
  can prove detection, never demand — so no language is added because an
  outsider needs it. Go (#72) and yarn/bun (#73) close under this.
- The **version contract** becomes real work: a CHANGELOG, an upgrade contract,
  and a revocation runbook for a bad `v1`, which reaches every Adopter at once.
- A **Mechanism change** gets a new major tag rather than riding the moving
  `v1`. No `v2` machinery is built until a breaking change actually needs one —
  the same discipline as not writing configs for languages nobody uses.
- SHA-pinning is **not** recommended to Adopters. The pinned workflow text still
  resolves `actions/layer2@v1` one level down, so the pin would look real and
  protect nothing. `v1.x.y` exists for anyone who needs an immutable ref.
- Judging whether correct, tested code should exist stays **out of scope**. It
  is review, not a gate, and no mechanism here will ever cover it.
