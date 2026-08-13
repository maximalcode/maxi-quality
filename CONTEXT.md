# maxi-quality

A shared lint and static-analysis baseline that repositories **consume** rather
than copy. This file is the glossary — it fixes the words the docs, the issues
and the rules in `CLAUDE.md` use. It holds no implementation detail and no plan;
`docs/CONCEPT.md` remains the source of truth for the design, and the issue
tracker for the work.

## Language

### Who uses this

**Consumer**:
One of the specific repositories whose real code this baseline was measured
against, referred to only by pseudonym (Consumer A, B, C, D). A finite, known
set.
_Avoid_: using "consumer" for any repo that merely uses the baseline — that is
an Adopter.

**Adopter**:
Anyone who wires the baseline into a repository. Every Consumer is an Adopter;
most Adopters are strangers and are owed no support.
_Avoid_: user, client, customer.

**Supported stack**:
The combination of language, package manager and CI host the baseline claims to
work on. Anything outside it is out of scope rather than broken, and the
boundary is stated in `README.md` so an Adopter learns it before wiring
anything up.
_Avoid_: supported language (the boundary is wider than language alone).

### What admits a language

Three separate tests. The phrase "a real consuming project" used to fuse all
three into one, which is how Java shipped satisfying two of them while the rule
as written said it should not have (`docs/STATUS.md` §5).

**Detection proof**:
Evidence that a config actually fires on the bugs it claims to catch — planted
findings in `samples/` with a committed expectation manifest, or findings on a
Consumer's real code.
_Avoid_: "tested", "validated".

**Adoption-cost proof**:
Evidence that switching the config on is survivable — measured by a Consumer
turning it on and living with the result, never by a fixture built here.
_Avoid_: "first-run cost" when a fixture produced the number.

**In-house demand**:
Whether a language is written in a repository the owner maintains. It is a
taste judgment, it is the one test no fixture corpus can substitute for, and it
is what keeps the baseline from growing configs nobody exercises.
_Avoid_: "a real consuming project" — the fused phrase this replaces.

### What is promised

**Version contract**:
The only obligation owed to an Adopter: what may and may not change under a
tag they have pinned. Issues and pull requests from outside carry no promise;
the tag does.
_Avoid_: "support", "SLA".

**Mechanism change**:
A change to how the baseline is wired — an input removed or renamed, a job
renamed, detection behaviour altered, or anything new an Adopter must have in
their own repository. Breaking under the Version contract, and it gets a new
major tag rather than riding the moving one.
_Avoid_: "breaking change" unqualified — a Finding change breaks builds too and
is not breaking here.

**Finding change**:
A change to what the baseline reports — a new rule, an analyzer version bump, a
tightened config. It can turn a green build red and is deliberately **not**
breaking: ratcheting up is the product, and `--changed-only` is how an Adopter
grandfathers a backlog.
_Avoid_: treating new findings as a regression in the baseline.
