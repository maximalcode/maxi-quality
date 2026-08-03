# Mixed monorepo — TypeScript and C#

One workflow covers both. `adopt.sh` writes each language's files where that
language actually lives.

Two things worth copying:

**`languages: 'ts,dotnet'` is pinned rather than left on `auto`.** Detection
would find both today. Naming them means a third language appearing in the tree
later does not silently widen the gate without anyone deciding to.

**The `.maxi-quality.yml` shows the two knobs people reach for first** — a rule
that genuinely does not apply (`disable`), and one worth seeing but not worth
blocking a merge over (`warn`). Note `third_party`, not `third_party/**`:
semgrep's `--exclude` matches path components and would silently ignore the glob
form. The policy file rejects that spelling rather than letting it no-op.
