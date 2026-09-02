# Dead-code action history regression

Run `python3 samples/deadcode/selftest.py` from the repository root. It needs
Git, Bash, Python and PyYAML (CI installs 6.0.3 if absent). All repositories
are disposable local fixtures; no network or account is needed.

The tests execute the shell body from `actions/deadcode/action.yml`, using
real depth-one Git fetches. Before the history fix, the PR merge case fails
with `fatal: origin/main...HEAD: no merge base` even though the base ref
resolves. Fetching only more base history does not repair the shallow HEAD.

The nine cases cover a PR merge, a diverged feature branch, a branch with more
than 200 commits, a full checkout, an absent base, an unrelated base, a remote
with incomplete history, a full scan with no base, and a merge where shallow
history exposes an older common ancestor while hiding the true merge base.
Changed-file assertions name the feature file exactly and exclude the file
added only on the base branch.

The fixture deliberately has no knip installation: the action must finish
its history work and reach the existing auto-mode warning. This suite proves
changed-file selection and failure handling, not analyzer detection. The
existing knip and deptry samples prove detection and gating separately.
