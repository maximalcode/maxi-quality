#!/usr/bin/env bash
#
# maxi-quality — adopt the baseline into a consuming repo (issue #11).
#
# Detects which languages a repo actually contains, copies the small set of
# files that .NET and ESLint cannot consume remotely, and scaffolds the CI call.
# Everything else is pulled from this repo at run time by the reusable workflow.
#
# Usage:
#   scripts/adopt.sh [TARGET_REPO] [options]
#
#   TARGET_REPO       Repo to adopt into. Default: current directory.
#
#   --dry-run         Print every action, write nothing. Do this first.
#   --force           Overwrite files that already exist. Off by default —
#                     a repo with its own Directory.Build.props must be merged
#                     by hand, not clobbered (docs/ADOPTION.md §3).
#   --ref REF         Tag/branch consumers pin in the workflow. Default: v1.
#   --no-workflow     Skip scaffolding .github/workflows/quality.yml.
#   --hooks           ALSO install the opt-in pre-commit hook (gitleaks on the
#                     staged diff, Semgrep on the staged content). Never
#                     installed without this flag: a hook that appears in
#                     someone's repo unasked gets ripped out along with
#                     everything near it. Bypass with `git commit --no-verify`.
#   -h, --help        This text.
#
# What gets written, per detected language:
#
#   always   .editorconfig                 <- configs/editorconfig
#   c#       Directory.Build.props         <- configs/dotnet/Directory.Build.props
#   c#       .editorconfig                 += configs/dotnet/dotnet.editorconfig
#   ts       eslint.base.mjs               <- configs/typescript/eslint.config.mjs
#   ts       tsconfig.base.json            <- configs/typescript/tsconfig.strict.json
#   ts       eslint.config.mjs             (3-line stub, only if absent)
#   python   ruff.base.toml                <- configs/python/ruff.toml
#   python   mypy.ini                      <- configs/python/mypy.ini
#   python   ruff.toml                     (1-line extend stub, only if absent)
#   always   .maxi-quality.yml             (commented starter, only if absent)
#   any      .github/workflows/quality.yml (unless --no-workflow)
#   --hooks  .git/hooks/pre-commit         <- hooks/pre-commit (only with --hooks)
#
# The TS pair is a copy for the same reason Directory.Build.props is: a private
# git devDep cannot npm-install in a consumer's CI.
#
# Exit codes: 0 adopted (or dry-run) · 1 nothing detected · 3 usage error

set -Eeuo pipefail

BASELINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- argument parsing --------------------------------------------------------
TARGET=""
DRY_RUN=0
FORCE=0
REF="v1"
NO_WORKFLOW=0
HOOKS=0

die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 3; }
bold() { printf '\033[1m%s\033[0m\n' "$1"; }
warn() { printf '\033[33mwarn:\033[0m %s\n' "$1" >&2; }
info() { printf '\033[36m›\033[0m %s\n' "$1"; }
skip() { printf '\033[33mskip\033[0m %s\n' "$1"; }
wrote() { printf '\033[32mwrite\033[0m %s\n' "$1"; }

usage() { sed -n '3,44p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --force) FORCE=1; shift ;;
    --no-workflow) NO_WORKFLOW=1; shift ;;
    --hooks) HOOKS=1; shift ;;
    --ref)
      [ $# -ge 2 ] || die "--ref needs a value"
      REF="$2"; shift 2 ;;
    -h|--help) usage ;;
    -*) die "unknown option: $1" ;;
    *)
      [ -z "$TARGET" ] || die "more than one target given: $TARGET and $1"
      TARGET="$1"; shift ;;
  esac
done

[ -n "$TARGET" ] || TARGET="$(pwd)"
[ -d "$TARGET" ] || die "not a directory: $TARGET"
TARGET="$(cd "$TARGET" && pwd)"

if [ "$TARGET" = "$BASELINE" ]; then
  die "refusing to adopt maxi-quality into itself"
fi

# --- detection ---------------------------------------------------------------
# Glob for real project files, ignoring the usual build-output graveyards.
# `find -print -quit` stops at the first hit; on a large repo that matters.
detect() {
  find "$TARGET" \
    \( -name node_modules -o -name obj -o -name bin -o -name dist -o -name .git \) -prune -o \
    -name "$1" -print -quit 2>/dev/null | head -1
}

HAS_DOTNET=0
HAS_TS=0
HAS_PYTHON=0
[ -n "$(detect '*.csproj')" ] && HAS_DOTNET=1
[ -n "$(detect '*.sln')" ] && HAS_DOTNET=1
[ -n "$(detect '*.slnx')" ] && HAS_DOTNET=1
[ -n "$(detect 'tsconfig.json')" ] && HAS_TS=1
[ -n "$(detect 'package.json')" ] && HAS_TS=1
[ -n "$(detect 'pyproject.toml')" ] && HAS_PYTHON=1
[ -n "$(detect 'requirements.txt')" ] && HAS_PYTHON=1
[ -n "$(detect 'uv.lock')" ] && HAS_PYTHON=1

bold "── maxi-quality adopt ──"
info "baseline: $BASELINE"
info "target:   $TARGET"
info "ref:      $REF"
[ "$DRY_RUN" -eq 1 ] && warn "dry run — nothing will be written"

if [ "$HAS_DOTNET" -eq 0 ] && [ "$HAS_TS" -eq 0 ] && [ "$HAS_PYTHON" -eq 0 ]; then
  warn "no TypeScript, C# or Python project found under $TARGET"
  warn "scope is TypeScript, C# and Python (CLAUDE.md §4). Nothing to do."
  exit 1
fi

[ "$HAS_TS" -eq 1 ] && info "detected: TypeScript"
[ "$HAS_DOTNET" -eq 1 ] && info "detected: C#/.NET"
[ "$HAS_PYTHON" -eq 1 ] && info "detected: Python"
printf '\n'

# --- file helpers ------------------------------------------------------------
# Refuses to clobber by default. A repo that already has a Directory.Build.props
# needs its properties MERGED, and silently overwriting one is exactly the kind
# of "helpful" adoption script that loses someone's build config.
NEEDS_MERGE=0

copy_file() {
  src="$1"; dst="$2"
  if [ -e "$dst" ] && [ "$FORCE" -eq 0 ]; then
    skip "$dst — already exists (use --force to overwrite, or merge by hand)"
    NEEDS_MERGE=1
    return 0
  fi
  wrote "$dst"
  [ "$DRY_RUN" -eq 1 ] && return 0
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
}

append_once() {
  src="$1"; dst="$2"; marker="$3"
  if [ -e "$dst" ] && grep -qF "$marker" "$dst" 2>/dev/null; then
    skip "$dst — already contains the C# section"
    return 0
  fi
  wrote "$dst (append)"
  [ "$DRY_RUN" -eq 1 ] && return 0
  cat "$src" >> "$dst"
}

write_new() {
  dst="$1"; body="$2"
  if [ -e "$dst" ] && [ "$FORCE" -eq 0 ]; then
    skip "$dst — already exists, leaving yours alone"
    return 0
  fi
  wrote "$dst"
  [ "$DRY_RUN" -eq 1 ] && return 0
  mkdir -p "$(dirname "$dst")"
  printf '%s' "$body" > "$dst"
}

# --- shared ------------------------------------------------------------------
copy_file "$BASELINE/configs/editorconfig" "$TARGET/.editorconfig"

# --- C# ----------------------------------------------------------------------
if [ "$HAS_DOTNET" -eq 1 ]; then
  # MSBuild walks UP from each project and stops at the FIRST
  # Directory.Build.props it finds — it does not merge the ones above it.
  # (Verified, not assumed: with a props file at both the root and one level
  # down, only the nearer one's properties are defined.)
  #
  # So writing to $TARGET/Directory.Build.props when a deeper one already
  # exists produces a file MSBuild never reads: the gate looks adopted and
  # analyses nothing. That is the worst possible outcome for a quality tool,
  # so it is a loud warning rather than a silent success.
  SHADOWERS="$(find "$TARGET" \
    \( -name node_modules -o -name obj -o -name bin -o -name .git \) -prune -o \
    -name Directory.Build.props -print 2>/dev/null | grep -v "^$TARGET/Directory.Build.props$" || true)"

  if [ -n "$SHADOWERS" ]; then
    printf '\n'
    warn "a deeper Directory.Build.props already exists:"
    printf '%s\n' "$SHADOWERS" | sed 's|^|        |' >&2
    warn "MSBuild stops at the FIRST props file walking up from each project, so"
    warn "one written at $TARGET would be SILENTLY IGNORED."
    warn ""
    warn "Do one of these instead:"
    warn "  a) re-run adopt.sh against that directory, or"
    warn "  b) merge configs/dotnet/Directory.Build.props into the existing file,"
    warn "     or add <Import Project=\"...\"/> at its top (docs/ADOPTION.md §3)."
    printf '\n'
    SKIP_DOTNET_PROPS=1
  else
    SKIP_DOTNET_PROPS=0
  fi

  if [ "${SKIP_DOTNET_PROPS:-0}" -eq 0 ] || [ "$FORCE" -eq 1 ]; then
    copy_file "$BASELINE/configs/dotnet/Directory.Build.props" "$TARGET/Directory.Build.props"
  else
    skip "$TARGET/Directory.Build.props — would be shadowed, see the warning above"
    NEEDS_MERGE=1
  fi
  append_once "$BASELINE/configs/dotnet/dotnet.editorconfig" "$TARGET/.editorconfig" \
    'maxi-quality — C# analyzer severities and style.'
fi

# --- TypeScript --------------------------------------------------------------
if [ "$HAS_TS" -eq 1 ]; then
  copy_file "$BASELINE/configs/typescript/eslint.config.mjs" "$TARGET/eslint.base.mjs"
  copy_file "$BASELINE/configs/typescript/tsconfig.strict.json" "$TARGET/tsconfig.base.json"
  write_new "$TARGET/eslint.config.mjs" \
"// Consumes the maxi-quality baseline. Add project-specific overrides below the
// spread — see docs/ADOPTION.md §2. Regenerate eslint.base.mjs with scripts/adopt.sh.
import base from './eslint.base.mjs';

export default [
  ...base,
  { languageOptions: { parserOptions: { tsconfigRootDir: import.meta.dirname } } },
];
"
  # knip (#51) — dead files, unused exports and unused/unlisted dependencies.
  # The stub is a real file rather than documentation because both of its keys
  # were measured conditions in #39, not defaults anyone would guess:
  #   - entry: a zero-config knip run on a non-default layout reports the
  #     layout, not defects. The entry points are the consumer's to declare.
  #   - ignoreDependencies: the baseline arrives by relative import (the copy
  #     above), so knip never sees eslint.base.mjs's three plugins resolved as
  #     a package's dependencies and reports them unused. Baked in here;
  #     revisit if the baseline ever publishes to npm.
  # knip parses knip.json as JSONC, so the stub documents itself.
  write_new "$TARGET/knip.json" \
"// maxi-quality knip stub (#51). DECLARE YOUR REAL ENTRY POINTS — knip's
// verdicts are only as good as this list, and a wrong one reports your layout
// rather than your defects.
{
  \"entry\": [\"src/index.ts\"],
  \"project\": [\"src/**/*.ts\"],
  // eslint.base.mjs imports these three; without a package boundary knip
  // cannot see that, and reports all three as unused. Measured, not assumed.
  \"ignoreDependencies\": [\"@eslint/js\", \"typescript-eslint\", \"eslint-plugin-sonarjs\"]
}
"
fi

# --- Python ------------------------------------------------------------------
# ruff CAN inherit (`extend`), mypy CANNOT — it has no include mechanism at all.
# So ruff gets a one-line stub pointing at a copied base, and mypy.ini is copied
# whole. The copy is the drift risk that bit samples/dotnet/.editorconfig; the
# fix is the same, never hand-edit it, re-run this script.
if [ "$HAS_PYTHON" -eq 1 ]; then
  copy_file "$BASELINE/configs/python/ruff.toml" "$TARGET/ruff.base.toml"
  copy_file "$BASELINE/configs/python/mypy.ini" "$TARGET/mypy.ini"
  write_new "$TARGET/ruff.toml" \
"# Consumes the maxi-quality baseline. Project-specific exemptions go below.
# Regenerate ruff.base.toml with scripts/adopt.sh — do not hand-edit it.
#
# THE EXTEND- PREFIXES ARE LOAD-BEARING. Ruff's plain \`select\` and
# \`per-file-ignores\` REPLACE what the base defines rather than merging with
# it, and neither warns when they do. Writing \`[lint.per-file-ignores]\` here
# silently drops the baseline's own exemptions — the \`assert\`-in-tests waiver
# among them, so every test file in the repo starts failing S101. Verified, not
# assumed. Use the extend- forms and that cannot happen.
extend = \"./ruff.base.toml\"

[lint.extend-per-file-ignores]
# e.g. \"scripts/**\" = [\"T20\"]

# [lint]
# extend-select = [\"PL\"]   # add a family — NOT \`select\`, which replaces
"
fi

# --- policy ------------------------------------------------------------------
# Written entirely commented out, so adopting changes nothing about what the
# gate does. The file exists to be DISCOVERABLE: the alternative to a legitimate
# way of saying "that rule does not apply to us" is a deleted workflow file, and
# a consumer who does not know the knob exists reaches for the second one.
write_new "$TARGET/.maxi-quality.yml" \
"# maxi-quality policy for this repo. Everything below is commented out, so as
# written this file changes nothing — uncomment what you need.
#
# Unknown keys, unknown rule ids and unknown group names are HARD ERRORS, not
# warnings. That is deliberate: a typo that silently does nothing is the failure
# mode this file exists to prevent.
#
# rules:
#   groups: [general, security, conventions]   # omit one to stop running it
#   disable:                                   # the rule does not apply here
#     - no-float-for-money
#   warn:                                      # reported, never fails the build
#     - todo-without-issue
#
# paths:
#   exclude:
#     - legacy                                 # NOT 'legacy/**' — semgrep's
#                                              # --exclude matches path
#                                              # components and would silently
#                                              # ignore the glob form.
#
# extends: .maxi-quality/rules                 # your own semgrep rules, run
#                                              # alongside the baseline's
#
# Gitleaks and OSV-Scanner are deliberately not configurable here: a leaked
# credential and a known CVE are not matters of local policy.
"

# --- CI ----------------------------------------------------------------------
if [ "$NO_WORKFLOW" -eq 0 ]; then
  write_new "$TARGET/.github/workflows/quality.yml" \
"name: quality

on: [push, pull_request]

jobs:
  quality:
    uses: maximalcode/maxi-quality/.github/workflows/quality.yml@$REF
"
fi

# --- the pre-commit hook, only on --hooks ------------------------------------
#
# ONLY on --hooks, and that is the whole design (#40). A hook installed by
# default is a hook somebody deletes in a hurry, taking the rest of the adoption
# with it. Everything below fails soft for the same reason: this is a
# convenience, and CI is the gate.
if [ "$HOOKS" -eq 1 ]; then
  GITDIR="$(git -C "$TARGET" rev-parse --git-dir 2>/dev/null || true)"
  if [ -z "$GITDIR" ]; then
    warn "--hooks: $TARGET is not a git repository; no hook installed"
  else
    case "$GITDIR" in /*) ;; *) GITDIR="$TARGET/$GITDIR" ;; esac
    # A repo with core.hooksPath set does not read .git/hooks at all. Writing
    # there anyway would install a hook that never runs — which is worse than
    # not installing one, because it looks done.
    HOOKSPATH="$(git -C "$TARGET" config --get core.hooksPath 2>/dev/null || true)"
    if [ -n "$HOOKSPATH" ]; then
      case "$HOOKSPATH" in /*) HOOKDIR="$HOOKSPATH" ;; *) HOOKDIR="$TARGET/$HOOKSPATH" ;; esac
      info "core.hooksPath is set to '$HOOKSPATH'; installing there instead of .git/hooks"
    else
      HOOKDIR="$GITDIR/hooks"
    fi

    HOOK="$HOOKDIR/pre-commit"
    if [ -e "$HOOK" ] && [ "$FORCE" -eq 0 ]; then
      skip "$HOOK (already exists — merge by hand or re-run with --force)"
      NEEDS_MERGE=1
    elif [ "$DRY_RUN" -eq 1 ]; then
      wrote "$HOOK (dry run)"
    else
      mkdir -p "$HOOKDIR"
      # The baseline path is baked in at install time so the hook works for
      # someone who has never heard of it, and MAXI_QUALITY_BASELINE still wins
      # at run time so a team can relocate the checkout without reinstalling.
      # `|` as the sed delimiter: the path contains slashes.
      sed "s|@BASELINE@|$BASELINE|" "$BASELINE/hooks/pre-commit" > "$HOOK"
      chmod +x "$HOOK"
      wrote "$HOOK"
    fi
  fi
fi

# --- what the human still has to do ------------------------------------------
printf '\n'
bold "── next steps ──"

if [ "$HOOKS" -eq 1 ]; then
  printf '  Pre-commit hook\n'
  printf '    Installed. It runs gitleaks on the staged diff (~50ms) and Semgrep\n'
  printf '    on the staged CONTENT — not the working tree, because "git commit"\n'
  printf '    commits the index and those differ.\n'
  printf '    Bypass one commit:  git commit --no-verify\n'
  printf '    Drop the slow half: export MAXI_QUALITY_HOOK_SKIP_SEMGREP=1\n'
  printf '    It never blocks on its OWN problems — a missing tool warns and\n'
  printf '    lets the commit through. CI is the gate.\n'
fi

if [ "$HAS_TS" -eq 1 ]; then
  printf '  TypeScript\n'
  printf '    1. npm i -D eslint @eslint/js typescript-eslint typescript @types/node \\\n'
  printf '            eslint-plugin-sonarjs\n'
  printf '       sonarjs is LGPL-3.0-only and pins typescript >=5 <6.1.0 as a hard\n'
  printf '       dependency, not a peer. Both are fine today; both are yours to check.\n'
  printf '    2. tsconfig.json: { "extends": "./tsconfig.base.json", ... }\n'
  printf '    3. package.json scripts.lint: "eslint src --max-warnings 0"\n'
  printf '       --max-warnings 0 is load-bearing; without it no-console is toothless.\n'
  printf '    4. typescript-eslint 8.x needs typescript >=4.8.4 <6.1.0 — TS 7 is refused\n'
  printf '       outright, not warned about (STATUS §4).\n'
  printf '    5. OPTIONAL — the formatter. Not copied in, because adopting it on an\n'
  printf '       existing repo reformats every file and that is your commit to make,\n'
  printf '       not this script'"'"'s:\n'
  printf '         npm i -D prettier\n'
  printf '         cp %s/configs/typescript/prettier.config.mjs ./prettier.config.mjs\n' "$BASELINE"
  printf '       Then run prettier --write ONCE, alone, and put that commit in\n'
  printf '       .git-blame-ignore-revs. No eslint-config-prettier needed —\n'
  printf '       typescript-eslint has shipped no formatting rules since v6.\n'
  printf '    6. OPTIONAL — knip (npm i -D knip, pin >=6.31.0; 6.31.0 fixed a\n'
  printf '       signature-only-type false positive that 5.64.3 shipped). A\n'
  printf '       knip.json stub was written; declare your real entry points in\n'
  printf '       it. In PUBLISHED LIBRARY packages gate dependencies, unlisted\n'
  printf '       imports and unused files only — an export no in-repo code\n'
  printf '       references is indistinguishable from public API there (19 of\n'
  printf '       26 real-code findings in the #39 eval sat in that class).\n'
  printf '    7. Fixing what knip finds: DELETION IS THE FIX, and knip can do\n'
  printf '       it — npx knip --fix removes unused exports and dependencies;\n'
  printf '       add --allow-remove-files to also delete dead files. Same rule\n'
  printf '       as the formatter: run it ONCE, alone, at adoption, and READ\n'
  printf '       the diff before committing. The false-positive class is code\n'
  printf '       reached outside the module graph — codegen plugins invoked by\n'
  printf '       non-npm tools, reflection — and a wrong deletion merges an\n'
  printf '       outage. Put real ones in knip.json ignoreDependencies, where\n'
  printf '       they are scoped and greppable. Never wire --fix into CI: the\n'
  printf '       gate detects, a human deletes. The measured backlog is small\n'
  printf '       (6 true positives across two real monorepos in #39), so one\n'
  printf '       cleanup commit clears it and CI holds it at zero after that.\n'
fi

if [ "$HAS_DOTNET" -eq 1 ]; then
  printf '  C#/.NET\n'
  printf '    1. No .csproj changes — MSBuild picks up Directory.Build.props for\n'
  printf '       every project beneath it.\n'
  printf '    2. First build will be noisy on an existing codebase. scripts/scan.sh\n'
  printf '       --changed-only is the new-code-only ratchet if you need it.\n'
  printf '    3. DECIDE on packages.lock.json. Without one the dependency scan sees\n'
  printf '       your DIRECT dependencies only — measured 4 findings vs 7 on the\n'
  printf '       same project (README, .NET trade-off). dotnet restore\n'
  printf '       --use-lock-file opts in; RestoreLockedMode then fails CI on a\n'
  printf '       stale one, which is the commitment. This script will not make\n'
  printf '       that call for you.\n'
  printf '    4. OPTIONAL — the formatter needs no extra config; the .editorconfig\n'
  printf '       copied above IS the policy. Gate it with:\n'
  printf '         dotnet format whitespace --verify-no-changes\n'
  printf '       The WHITESPACE subcommand, not bare "dotnet format" — the bare form\n'
  printf '       also runs every analyzer and re-reports the build gate'"'"'s own\n'
  printf '       diagnostics under the formatter'"'"'s exit code.\n'
fi

if [ "$HAS_PYTHON" -eq 1 ]; then
  printf '  Python\n'
  printf '    1. Add ruff and mypy as dev dependencies (uv add --dev ruff mypy,\n'
  printf '       or put them in requirements-dev.txt). CI runs the versions YOU\n'
  printf '       pin — it does not smuggle in its own.\n'
  printf '    2. mypy.ini was copied whole; mypy has no extend. Add [mypy-*]\n'
  printf '       sections for untyped third-party imports there.\n'
  printf '    3. An existing codebase will be noisy on first run. Move real\n'
  printf '       exemptions into ruff.toml per-file-ignores rather than widening\n'
  printf '       the global ignore list — scoped and greppable beats invisible.\n'
  printf '    4. OPTIONAL — the formatter is already configured by the ruff.base.toml\n'
  printf '       copied above; it just needs running:\n'
  printf '         ruff format .           # fix\n'
  printf '         ruff format --check .   # gate\n'
  printf '       Note line-length = 100 drives the FORMATTER as well as E501, so\n'
  printf '       overriding it moves both. One reformat commit, alone, in\n'
  printf '       .git-blame-ignore-revs.\n'
  printf '    5. OPTIONAL — deptry (unused/undeclared dependencies): add it as\n'
  printf '       a dev dependency and run it PER PACKAGE, never at a workspace\n'
  printf '       root — measured there: 125 findings, 118 of them one\n'
  printf '       first-party artifact; 3 on the member package. Run it inside\n'
  printf '       the project env (uv run deptry src) so import-name mapping\n'
  printf '       works — isolated, it false-positives on every package whose\n'
  printf '       import name differs (beautifulsoup4/bs4). Fixes are one-line\n'
  printf '       pyproject.toml edits — make them BY HAND in one cleanup\n'
  printf '       commit; there is no auto-fix and none is needed.\n'
fi

if [ "$NEEDS_MERGE" -eq 1 ]; then
  printf '\n'
  warn "some files already existed and were left untouched."
  warn "merge those by hand — overwriting a repo's own build config is not a"
  warn "decision this script gets to make. Re-run with --force only if you are sure."
fi

printf '\n'
if [ "$DRY_RUN" -eq 1 ]; then
  printf '\033[33mDRY RUN\033[0m — nothing written. Re-run without --dry-run to apply.\n'
else
  printf '\033[32mADOPTED\033[0m — commit these files, push, and CI gates the next PR.\n'
fi
