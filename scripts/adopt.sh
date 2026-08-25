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
#   --editor          ALSO write .vscode/settings.json and .vscode/extensions.json
#                     from configs/editor/, for the DETECTED languages only.
#                     Opt-in for the same reason --hooks is, and one more: this
#                     is the first thing the baseline writes that gates nothing.
#                     It NEVER merges — if either file exists it writes nothing
#                     to it, prints the delta it would have applied, and exits 5.
#   --agent           ALSO install the agent contract from configs/agent/: the
#                     hooks and deny rules that constrain a Claude Code session
#                     writing in your repo. Opt-in like the two above, and for
#                     the strongest reason of the three — this is executable
#                     policy arriving in someone's tree.
#                     Unlike --editor it DOES merge, because unlike .vscode/ a
#                     .claude/settings.json usually already exists. Your hook
#                     entries and deny rules are appended to, never replaced,
#                     never reordered, and re-running adds nothing twice. A
#                     settings.json that does not parse, or whose `hooks` key is
#                     not the documented shape, is REFUSED — nothing --agent
#                     would have written gets written at all, and the run exits 6.
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
#   rust     rustfmt.toml                  <- configs/rust/rustfmt.toml
#   rust     deny.toml                     <- configs/rust/deny.toml
#   rust     Cargo.toml                    += configs/rust/lints.toml ([lints])
#   java     pom.xml                       += configs/java/pom-lints.xml, as a
#                                             MARKER-DELIMITED REGION inside
#                                             <build><plugins>. Re-running
#                                             replaces the region and nothing
#                                             else, which is the upgrade path —
#                                             XML has no append, so without a
#                                             managed region every baseline bump
#                                             would be a hand edit.
#   always   .maxi-quality.yml             (commented starter, only if absent)
#   any      .github/workflows/quality.yml (unless --no-workflow — the same six
#                                           lines for every language, Rust
#                                           included since #70)
#   --hooks  .git/hooks/pre-commit         <- hooks/pre-commit (only with --hooks)
#   --editor .vscode/settings.json         <- configs/editor/<lang>.settings.json
#                                             for the detected languages, composed
#                                             by scripts/editor-settings.py
#   --editor .vscode/extensions.json       <- configs/editor/extensions.json, the
#                                             same rows and nothing else
#   --agent  .claude/agent-guard/*.py      <- scripts/agent-guard/ (baseline code,
#                                             REFRESHED on every --agent run)
#   --agent  .claude/settings.json         += configs/agent/settings.json, merged
#                                             by scripts/agent-settings.py
#   --agent  CLAUDE.md                     += configs/agent/CLAUDE.fragment.md,
#                                             marker-guarded
#   --agent  .gitignore                    += .claude/agent-guard-receipt.json
#
# The TS pair is a copy for the same reason Directory.Build.props is: a private
# git devDep cannot npm-install in a consumer's CI. The Rust trio is a copy for
# a harder reason: Cargo has no remote lint consumption at all — [lints] must
# live in the consumer's own manifest. Java is the Rust case again: Maven's one
# real inheritance mechanism is a parent POM, which needs a registry to publish
# and a free <parent> slot to consume, and a Spring Boot project has neither.
#
# Exit codes: 0 adopted (or dry-run) · 1 nothing detected · 3 usage error
#             5 --editor refused: a .vscode file already existed and was left
#               alone. Everything else still adopted; only the editor files
#               were held back, and the delta was printed.
#             6 --agent refused: .claude/settings.json could not be merged into.
#               Nothing --agent writes was written — not the scripts, not the
#               fragment — because half an agent contract is a CLAUDE.md that
#               promises refusals nothing performs. 6 wins over 5 when both
#               happen: 5 held back files that gate nothing, 6 held back the gate.

set -Eeuo pipefail

BASELINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The cargo-deny version, for the "install it locally to match CI" line in the
# summary only — this script no longer stamps a Rust job into anyone's workflow
# (#70), so nothing here installs it. The pins that RUN live in
# .github/workflows/quality.yml, and scripts/check-pins.sh asserts they agree
# with ci.yml's layer1-rust job: CI must validate the same toolchain consumers
# are handed.
CARGO_DENY_PIN="0.20.2"

# --- argument parsing --------------------------------------------------------
TARGET=""
DRY_RUN=0
FORCE=0
REF="v1"
NO_WORKFLOW=0
HOOKS=0
# Not named EDITOR: that is a standard environment variable, and a script that
# shadows someone's $EDITOR is a script that surprises them elsewhere.
WANT_EDITOR=0
EDITOR_CONFLICT=0
# Not named AGENT either: --hooks already taught this script that a short,
# obvious name can mean two unrelated things (configs/agent/README.md §8).
WANT_AGENT=0
AGENT_CONFLICT=0

die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 3; }
bold() { printf '\033[1m%s\033[0m\n' "$1"; }
warn() { printf '\033[33mwarn:\033[0m %s\n' "$1" >&2; }
info() { printf '\033[36m›\033[0m %s\n' "$1"; }
skip() { printf '\033[33mskip\033[0m %s\n' "$1"; }
wrote() { printf '\033[32mwrite\033[0m %s\n' "$1"; }

usage() { sed -n '3,83p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

# --- the agent contract, only on --agent -------------------------------------
#
# ONLY on --agent, and for the strongest reason any of the three opt-ins has.
# --hooks installs something a developer can bypass; --editor writes something
# that gates nothing. This writes EXECUTABLE POLICY into someone's repository:
# hooks Claude Code runs on every tool call and every stop, and deny rules it
# enforces before any of them. Nothing about that should arrive by default.
#
# It is also the one thing here that MERGES rather than refusing, which is the
# opposite of --editor two blocks up. The reason is the file, not a change of
# heart: .vscode/settings.json is a file a consumer may not have, and
# .claude/settings.json is a file a consumer who runs Claude Code almost
# certainly does. Refuse-if-exists there would mean this never adopts anywhere
# it matters. scripts/agent-settings.py holds the merge and its ownership rule.
#
# EVERYTHING OR NOTHING. The merge is dry-run first, and a refusal skips the
# whole block — not just the settings file. Copying the scripts and appending
# the fragment without the hooks would leave a CLAUDE.md that says "they are
# not advice — they refuse" in a repo where nothing refuses. A contract that
# describes enforcement it does not have is worse than no contract, because
# the next session reads it and believes it.
install_agent_contract() {
  AGENT_SETTINGS="$TARGET/.claude/settings.json"
  AGENT_DIR="$TARGET/.claude/agent-guard"

  # Preflight. Runs before the first byte is written, so a refusal costs the
  # consumer a message and not a half-adopted tree.
  if ! python3 "$BASELINE/scripts/agent-settings.py" merge \
         --baseline "$BASELINE/configs/agent/settings.json" \
         --target "$AGENT_SETTINGS" --dry-run >/dev/null; then
    AGENT_CONFLICT=1
    NEEDS_MERGE=1
  else
    # A guard that is not in a git working tree allows every stop and reports
    # nothing — stop-gate.py fails open on plumbing, by design. Installing it
    # there anyway produces the one outcome this script cares most about
    # avoiding: a tree that looks adopted and enforces nothing.
    if ! git -C "$TARGET" rev-parse --show-toplevel >/dev/null 2>&1; then
      warn "--agent: $TARGET is not a git working tree. The Stop gate"
      warn "fingerprints \`git status\`, so outside one it allows every stop and"
      warn "says nothing. Installing anyway; run \`git init\` before you rely on it."
      NEEDS_MERGE=1
    fi

    # The scripts are BASELINE CODE, not your configuration, so unlike every
    # other copy in this script they are refreshed rather than skipped. There
    # is no remote consumption for a hook command — it is a path on disk — so
    # re-running this script IS the upgrade path, the same trade the C# and
    # Rust configs already make. --force is not needed and would not mean
    # anything here.
    for src in "$BASELINE"/scripts/agent-guard/*.py; do
      wrote "$AGENT_DIR/$(basename "$src") (refreshed)"
      [ "$DRY_RUN" -eq 1 ] && continue
      mkdir -p "$AGENT_DIR"
      cp "$src" "$AGENT_DIR/$(basename "$src")"
    done

    # The fragment, marker-guarded. Same discipline as the C# .editorconfig
    # section and the Rust [lints] block: re-running never appends twice, and
    # the markers are how a later baseline replaces the region without a merge.
    AGENT_MARKER='<!-- BEGIN maxi-quality agent-guard -->'
    if [ -e "$TARGET/CLAUDE.md" ] && grep -qF "$AGENT_MARKER" "$TARGET/CLAUDE.md" 2>/dev/null; then
      skip "$TARGET/CLAUDE.md — already contains the agent-guard region"
    else
      wrote "$TARGET/CLAUDE.md (append)"
      if [ "$DRY_RUN" -eq 0 ]; then
        # Terminate the consumer's last line if they left it unterminated, then
        # separate with a blank one. Appending straight onto someone's final
        # paragraph would put an HTML comment inside it, and a heading that
        # continues the previous line is not a heading at all.
        if [ -s "$TARGET/CLAUDE.md" ]; then
          [ -z "$(tail -c 1 "$TARGET/CLAUDE.md")" ] || printf '\n' >> "$TARGET/CLAUDE.md"
          printf '\n' >> "$TARGET/CLAUDE.md"
        fi
        cat "$BASELINE/configs/agent/CLAUDE.fragment.md" >> "$TARGET/CLAUDE.md"
      fi
    fi

    # Per-checkout state: a receipt describes THIS working tree's diff, so a
    # committed one is a claim about somebody else's. Nothing breaks if this
    # line is missing — the receipt is excluded from the fingerprint either
    # way — which is exactly why it is worth writing for people rather than
    # leaving as a step nobody notices they skipped.
    AGENT_IGNORE='.claude/agent-guard-receipt.json'
    if [ -e "$TARGET/.gitignore" ] && grep -qxF "$AGENT_IGNORE" "$TARGET/.gitignore" 2>/dev/null; then
      skip "$TARGET/.gitignore — already ignores the receipt"
    else
      wrote "$TARGET/.gitignore (append)"
      if [ "$DRY_RUN" -eq 0 ]; then
        if [ -s "$TARGET/.gitignore" ]; then
          [ -z "$(tail -c 1 "$TARGET/.gitignore")" ] || printf '\n' >> "$TARGET/.gitignore"
          printf '\n' >> "$TARGET/.gitignore"
        fi
        printf '# maxi-quality agent guard — per-checkout state, never committed\n%s\n' \
          "$AGENT_IGNORE" >> "$TARGET/.gitignore"
      fi
    fi

    # And the merge for real. The preflight above already proved it parses, so
    # a failure HERE is ours: report it as such rather than as a conflict.
    if [ "$DRY_RUN" -eq 1 ]; then
      info "$AGENT_SETTINGS (dry run) — the merge would apply:"
      python3 "$BASELINE/scripts/agent-settings.py" merge \
        --baseline "$BASELINE/configs/agent/settings.json" \
        --target "$AGENT_SETTINGS" --dry-run | sed 's/^/    /'
    else
      wrote "$AGENT_SETTINGS (merge)"
      python3 "$BASELINE/scripts/agent-settings.py" merge \
        --baseline "$BASELINE/configs/agent/settings.json" \
        --target "$AGENT_SETTINGS" | sed 's/^/    /' \
        || die "the merge failed after its own dry run passed — this is a bug in maxi-quality, not in your repo"
    fi
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --force) FORCE=1; shift ;;
    --no-workflow) NO_WORKFLOW=1; shift ;;
    --hooks) HOOKS=1; shift ;;
    --editor) WANT_EDITOR=1; shift ;;
    --agent) WANT_AGENT=1; shift ;;
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

# Adopting the baseline into itself is refused, with EXACTLY ONE exception.
#
# The refusal is about the language configs: configs/typescript/ is the source
# and the consumer's tree is the destination, so pointing them at each other
# means copying files onto the originals and calling the result an adoption.
#
# `--agent` is not that shape. Its source is configs/agent/ and its destination
# is .claude/ — two different paths in this tree, no collision, and the result
# is a repo that runs the contract it ships instead of one that only describes
# it. That is the in-house-demand test the whole baseline is governed by
# (CLAUDE.md §4), applied to the one thing here that can meet it before a
# consumer does. Refusing it would mean the agent contract is the only surface
# this repo asks other people to adopt and does not adopt itself (#166).
#
# Only the agent contract runs on this path — not the detection, not the
# configs, not the workflow scaffold — and the run stops after it, so nothing
# can reach the copy steps by accident.
if [ "$TARGET" = "$BASELINE" ]; then
  if [ "$WANT_AGENT" -eq 0 ]; then
    die "refusing to adopt maxi-quality into itself"
  fi
  bold "── maxi-quality adopt: the agent contract, into the baseline itself ──"
  info "baseline: $BASELINE"
  info "target:   the same tree"
  [ "$DRY_RUN" -eq 1 ] && warn "dry run — nothing will be written"
  printf '\n'
  # Named rather than silently ignored: someone who typed --editor here has a
  # reasonable expectation this script owes them an answer about.
  if [ "$WANT_EDITOR" -eq 1 ] || [ "$HOOKS" -eq 1 ] || [ "$FORCE" -eq 1 ]; then
    warn "on this path --agent is the ONLY thing that runs; every other flag you"
    warn "passed is ignored, because adopting the rest of the baseline into"
    warn "itself would copy its own configs over their originals."
    printf '\n'
  fi
  install_agent_contract
  if [ "$AGENT_CONFLICT" -eq 1 ]; then
    printf '\n'
    printf '\033[31mAGENT CONTRACT NOT INSTALLED\033[0m — .claude/settings.json could not\n'
    printf 'be merged into, and the reason is above. Nothing was written.\n'
    exit 6
  fi
  printf '\n'
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '\033[33mDRY RUN\033[0m — nothing written. Re-run without --dry-run to apply.\n'
  else
    printf '\033[32mADOPTED\033[0m — this repo now runs the contract it ships.\n'
  fi
  exit 0
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
HAS_RUST=0
HAS_JAVA=0
[ -n "$(detect '*.csproj')" ] && HAS_DOTNET=1
[ -n "$(detect '*.sln')" ] && HAS_DOTNET=1
[ -n "$(detect '*.slnx')" ] && HAS_DOTNET=1
[ -n "$(detect 'tsconfig.json')" ] && HAS_TS=1
[ -n "$(detect 'package.json')" ] && HAS_TS=1
[ -n "$(detect 'pyproject.toml')" ] && HAS_PYTHON=1
[ -n "$(detect 'requirements.txt')" ] && HAS_PYTHON=1
[ -n "$(detect 'uv.lock')" ] && HAS_PYTHON=1
# One manifest for workspace and single-crate alike — a workspace root and a
# lone crate both mean "this is a Rust repo".
[ -n "$(detect 'Cargo.toml')" ] && HAS_RUST=1
# Java is v1-Maven-only, and Gradle FAILS LOUD rather than adopting half of
# itself — see the block after detection. Both markers are collected here so
# the message can name what was actually found.
[ -n "$(detect 'pom.xml')" ] && HAS_JAVA=1
GRADLE_FOUND="$(detect 'build.gradle')"
[ -n "$GRADLE_FOUND" ] || GRADLE_FOUND="$(detect 'build.gradle.kts')"

NEEDS_MERGE=0

bold "── maxi-quality adopt ──"
info "baseline: $BASELINE"
info "target:   $TARGET"
info "ref:      $REF"
[ "$DRY_RUN" -eq 1 ] && warn "dry run — nothing will be written"

# Gradle before the nothing-detected check, so a Gradle-only repo gets the
# reason rather than "nothing to do". v1 supports Maven; saying so out loud is
# the whole difference between a scope decision and a silent hole (#10).
if [ -n "$GRADLE_FOUND" ] && [ "$HAS_JAVA" -eq 0 ]; then
  printf '\n'
  warn "found a Gradle build ($GRADLE_FOUND) and no pom.xml."
  warn "The Java layer is MAVEN-ONLY in v1 — Gradle gets built when a Gradle"
  warn "consumer exists, the same just-in-time rule that produced the Java"
  warn "layer itself. Nothing Java was written, deliberately and not silently."
  printf '\n'
  NEEDS_MERGE=1
fi

if [ "$HAS_DOTNET" -eq 0 ] && [ "$HAS_TS" -eq 0 ] && [ "$HAS_PYTHON" -eq 0 ] \
   && [ "$HAS_RUST" -eq 0 ] && [ "$HAS_JAVA" -eq 0 ]; then
  warn "no TypeScript, C#, Python, Rust or Java project found under $TARGET"
  warn "scope is TypeScript, C#, Python, Rust and Java/Maven (CLAUDE.md §4)."
  # Said separately, because "nothing to do" does not answer "so where are my
  # .vscode files". The editor settings are per-language all the way down —
  # there is no language-independent half — so a tree with no detected language
  # gets an EMPTY settings file or none, and an empty .vscode/settings.json is
  # worse than none: it shadows nothing, explains nothing, and looks configured.
  [ "$WANT_EDITOR" -eq 1 ] && warn "--editor wrote no .vscode/settings.json or .vscode/extensions.json: every key in configs/editor/ belongs to a language, and none was found."
  # Said separately again, and for the OPPOSITE reason: the agent contract has
  # no language in it — it guards git state and samples/expected/ — so unlike
  # the editor files it would have been perfectly writable here. It is held
  # back only because this run stops before reaching it, and that is a limit of
  # this script rather than of the contract. Adopt it by hand
  # (configs/agent/README.md §7) if this really is the repo you meant.
  [ "$WANT_AGENT" -eq 1 ] && warn "--agent wrote nothing either — not because the agent contract needs a detected language (it does not), but because this run stops here."
  warn "Nothing to do."
  exit 1
fi

[ "$HAS_TS" -eq 1 ] && info "detected: TypeScript"
[ "$HAS_DOTNET" -eq 1 ] && info "detected: C#/.NET"
[ "$HAS_PYTHON" -eq 1 ] && info "detected: Python"
[ "$HAS_RUST" -eq 1 ] && info "detected: Rust"
[ "$HAS_JAVA" -eq 1 ] && info "detected: Java (Maven)"
printf '\n'

# --- file helpers ------------------------------------------------------------
# Refuses to clobber by default. A repo that already has a Directory.Build.props
# needs its properties MERGED, and silently overwriting one is exactly the kind
# of "helpful" adoption script that loses someone's build config.
# (NEEDS_MERGE is declared above detection — the Gradle branch sets it.)

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

# --- Rust --------------------------------------------------------------------
# The C# pattern, not the TS one, and by necessity rather than preference:
# Cargo cannot consume [lints] from a remote package, rustfmt and cargo-deny
# have no extend mechanism. Three copies, refreshed by re-running this script.
#
# The [lints] block is APPENDED to the consumer's own Cargo.toml — workspace
# form when the root manifest declares [workspace], single-crate form
# otherwise. Same discipline as the C# .editorconfig append: marker-guarded so
# re-running never appends twice, and a manifest that already carries its own
# [lints] section gets a skip and a warning, never a merge attempt.
if [ "$HAS_RUST" -eq 1 ]; then
  MANIFEST="$TARGET/Cargo.toml"
  if [ ! -f "$MANIFEST" ]; then
    # Cargo walks UP from a crate to find its workspace; a lints block written
    # to a directory that has no manifest configures nothing. Same failure
    # shape as the shadowed Directory.Build.props, so same loudness.
    printf '\n'
    warn "Cargo.toml was found below $TARGET but not AT it, so there is no"
    warn "manifest here to hold the [lints] block. Re-run adopt.sh against the"
    warn "directory that owns the workspace/crate root."
    printf '\n'
    NEEDS_MERGE=1
  else
    copy_file "$BASELINE/configs/rust/rustfmt.toml" "$TARGET/rustfmt.toml"
    copy_file "$BASELINE/configs/rust/deny.toml" "$TARGET/deny.toml"

    RUST_MARKER='maxi-quality — Rust lint baseline'
    if grep -qF "$RUST_MARKER" "$MANIFEST" 2>/dev/null; then
      skip "$MANIFEST — already contains the maxi-quality [lints] block"
    elif grep -qE '^\[(workspace\.)?lints' "$MANIFEST" 2>/dev/null; then
      skip "$MANIFEST — has its own [lints] section; merge configs/rust/lints.toml by hand"
      warn "Cargo.toml already defines [lints]. Appending a second table would be"
      warn "rejected by cargo, so nothing was written — merge configs/rust/lints.toml"
      warn "into the existing section instead (docs/ADOPTION.md §4b)."
      NEEDS_MERGE=1
    else
      wrote "$MANIFEST (append [lints])"
      # Decided BEFORE the append: reading the manifest inside a block that
      # redirects into it is the read-and-write-same-file trap (SC2094).
      IS_WORKSPACE=0
      grep -qE '^\[workspace\]' "$MANIFEST" && IS_WORKSPACE=1
      if [ "$DRY_RUN" -eq 0 ]; then
        {
          printf '\n'
          if [ "$IS_WORKSPACE" -eq 1 ]; then
            cat "$BASELINE/configs/rust/lints.toml"
          else
            sed 's/^\[workspace\.lints/[lints/' "$BASELINE/configs/rust/lints.toml"
          fi
        } >> "$MANIFEST"
      fi
      if [ "$IS_WORKSPACE" -eq 1 ]; then
        info "workspace detected: members opt in with '[lints]' + 'workspace = true'"
      fi
    fi
  fi
fi

# --- Java (Maven) ------------------------------------------------------------
# The Rust pattern, one notch harder. Cargo forces a copy because it cannot
# consume [lints] remotely; Maven forces one for the same reason, and then
# refuses the easy delivery on top: TOML appends, XML does not. The block has to
# land INSIDE <build><plugins>, so there is no `cat >>` — only an edit.
#
# An edit a human redoes on every baseline bump is not an upgrade path, so the
# block is written as a MARKER-DELIMITED REGION and scripts/pom-region.py
# replaces the region and nothing else. Re-running is idempotent; the consumer's
# own plugins, properties, comments and formatting are untouched.
if [ "$HAS_JAVA" -eq 1 ]; then
  POM="$TARGET/pom.xml"
  if [ ! -f "$POM" ]; then
    # Same failure shape as a Cargo.toml below the target and a shadowed
    # Directory.Build.props: a config written where the build never reads it
    # looks adopted and analyses nothing.
    #
    # This is also the one place #68 (polyglot repos, configs at the wrong
    # depth) could get WORSE for Java, so it is a refusal rather than a guess:
    # a Java server under a repo whose root is something else gets told which
    # directory to re-run against, and nothing is written.
    printf '\n'
    warn "pom.xml was found below $TARGET but not AT it, so there is no manifest"
    warn "here to hold the lint region. Re-run adopt.sh against the directory"
    warn "that owns the root pom.xml — writing one here would configure nothing."
    printf '\n'
    NEEDS_MERGE=1
  else
    JAVA_RC=0
    if [ "$DRY_RUN" -eq 1 ]; then
      # --dry-run must write NOTHING, so the check mode is used to predict the
      # outcome: exit 4 is the refusal, 0/1 are "would be current"/"would change".
      python3 "$BASELINE/scripts/pom-region.py" check --pom "$POM" \
        --fragment "$BASELINE/configs/java/pom-lints.xml" >/dev/null 2>&1 || JAVA_RC=$?
      if [ "$JAVA_RC" -eq 4 ]; then
        JAVA_REFUSED=1
      else
        wrote "$POM (maxi-quality lint region)"
      fi
    else
      python3 "$BASELINE/scripts/pom-region.py" apply --pom "$POM" \
        --fragment "$BASELINE/configs/java/pom-lints.xml" > /tmp/maxi-pom.$$ 2>&1 || JAVA_RC=$?
      if [ "$JAVA_RC" -eq 0 ]; then
        wrote "$POM (maxi-quality lint region)"
      else
        cat /tmp/maxi-pom.$$ >&2
      fi
      rm -f /tmp/maxi-pom.$$
      [ "$JAVA_RC" -eq 4 ] && JAVA_REFUSED=1
    fi

    if [ "${JAVA_REFUSED:-0}" -eq 1 ]; then
      printf '\n'
      warn "$POM already configures maven-compiler-plugin, so NOTHING was written."
      warn "Two declarations of one plugin in one POM is not a merge — it is"
      warn "last-one-wins, so writing the baseline's would SILENTLY DROP the"
      warn "compilerArgs you already have. If those include -Xlint/-Werror, the"
      warn "gate would come out weaker than before adoption."
      warn ""
      warn "Merge by hand instead: copy the <compilerArgs> and"
      warn "<annotationProcessorPaths> from"
      warn "  $BASELINE/configs/java/pom-lints.xml"
      warn "into your existing declaration, keeping your own args, and add the"
      warn "spotless plugin beside it (docs/ADOPTION.md §5)."
      printf '\n'
      NEEDS_MERGE=1
    elif [ "$JAVA_RC" -ne 0 ] && [ "$JAVA_RC" -ne 1 ]; then
      NEEDS_MERGE=1
    fi
  fi
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
  WORKFLOW_BODY="name: quality

on: [push, pull_request]

jobs:
  quality:
    uses: maximalcode/maxi-quality/.github/workflows/quality.yml@$REF
"
  # THE UPGRADE PATH (#70). Until #70 Rust could not ride the reusable
  # workflow, so this script stamped a whole pinned-toolchain `rust:` job into
  # the consumer's own file. Those jobs are still out there, and the reusable
  # call now runs Rust itself — so a repo adopted before #70 would run clippy
  # TWICE, the second time against pins that only move when someone re-runs
  # this script. write_new leaves an existing workflow alone, correctly: it is
  # the consumer's file. Which means this cannot be fixed silently, only said
  # out loud.
  WORKFLOW_PATH="$TARGET/.github/workflows/quality.yml"
  # Keyed on the JOB, not on the comment a pre-#70 adopt.sh wrote above it. A
  # consumer who reworded or deleted that comment still runs clippy twice, and
  # a marker only the tidy repos kept is a check that stays quiet on exactly
  # the repos most likely to have edited the job as well.
  if [ -f "$WORKFLOW_PATH" ] && grep -qE '^[[:space:]]+rust:[[:space:]]*$' "$WORKFLOW_PATH" 2>/dev/null; then
    warn "$WORKFLOW_PATH already declares a 'rust:' job of its own."
    warn "Since #70 the reusable workflow runs Rust itself, so that job is a"
    warn "second clippy run — and if adopt.sh scaffolded it, one pinned to a"
    warn "toolchain that no longer moves. Delete it: the 'quality:' call covers"
    warn "Rust now. To keep your own instead, pass a 'languages:' input without"
    warn "rust so this baseline stops running it. Do not leave both."
    warn "Note the baseline job does NOT run 'cargo test': it is a quality gate,"
    warn "like the TypeScript and Python jobs. Keep your tests in their own job."
    NEEDS_MERGE=1
  fi
  write_new "$WORKFLOW_PATH" "$WORKFLOW_BODY"
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

# --- the editor, only on --editor --------------------------------------------
#
# ONLY on --editor, and for one reason more than --hooks has: this is the first
# thing the baseline writes that GATES NOTHING. Everything else here fails a
# build when it is wrong; a settings file only changes what someone sees while
# typing, and .vscode/settings.json is a file developers have opinions about.
#
# So it never merges. If either target exists, nothing is written to it, the
# delta is printed, and the run exits 5 — the consumer applies it by hand or
# deletes the file and re-runs. Silently clobbering someone's editor config is
# the one unrecoverable thing this feature could do, and "helpfully merged your
# settings" is not a sentence this script gets to say.
if [ "$WANT_EDITOR" -eq 1 ]; then
  # Language tokens are the configs/ directory names, which is what
  # scripts/editor-settings.py keys its fragment map on.
  EDITOR_LANGS=""
  [ "$HAS_TS" -eq 1 ] && EDITOR_LANGS="$EDITOR_LANGS,typescript"
  [ "$HAS_DOTNET" -eq 1 ] && EDITOR_LANGS="$EDITOR_LANGS,dotnet"
  [ "$HAS_PYTHON" -eq 1 ] && EDITOR_LANGS="$EDITOR_LANGS,python"
  [ "$HAS_RUST" -eq 1 ] && EDITOR_LANGS="$EDITOR_LANGS,rust"
  [ "$HAS_JAVA" -eq 1 ] && EDITOR_LANGS="$EDITOR_LANGS,java"
  EDITOR_LANGS="${EDITOR_LANGS#,}"

  # The prettier rows — the extension recommendation and the [typescript] /
  # [typescriptreact] formatter blocks — are gated on the repo ACTUALLY having
  # taken adopt.sh's OPTIONAL prettier step. With the extension installed and
  # no config present, VS Code formats at Prettier's default width and every
  # save fights `prettier --check` at the width configs/typescript pins. That
  # is strictly worse than no formatter routing at all, so it is conditional
  # rather than recommended-and-caveated.
  #
  # Declared empty, and every expansion below uses the ${arr[@]+"${arr[@]}"}
  # form: under `set -u`, bash 3.2 treats an EMPTY array as an unbound variable,
  # so plain "${PRETTIER_ARGS[@]}" aborts on every repo that has no prettier
  # config — which is most of them. CI runs this on ubuntu and would never see
  # it; this script is run by a person on their own machine, and /bin/bash on
  # macOS is still 3.2. Same reason hooks/pre-commit is written for 3.2.
  # Found by running it there, not by reading the manual.
  PRETTIER_ARGS=()
  if [ "$HAS_TS" -eq 1 ]; then
    for f in prettier.config.mjs prettier.config.js prettier.config.cjs \
             .prettierrc .prettierrc.json .prettierrc.json5 .prettierrc.yaml \
             .prettierrc.yml .prettierrc.mjs .prettierrc.js .prettierrc.cjs \
             .prettierrc.toml; do
      if [ -e "$TARGET/$f" ]; then PRETTIER_ARGS=(--prettier); break; fi
    done
    # package.json's own "prettier" key is a config too — parsed rather than
    # grepped, because `"prettier"` also appears in devDependencies and a
    # dependency is not a configuration.
    if [ ${#PRETTIER_ARGS[@]} -eq 0 ] && [ -f "$TARGET/package.json" ]; then
      python3 -c 'import json,sys; sys.exit(0 if "prettier" in json.load(open(sys.argv[1])) else 1)' \
        "$TARGET/package.json" 2>/dev/null && PRETTIER_ARGS=(--prettier)
    fi
  fi

  for spec in "settings:.vscode/settings.json" "extensions:.vscode/extensions.json"; do
    kind="${spec%%:*}"; dst="$TARGET/${spec#*:}"
    if [ -e "$dst" ] && [ "$FORCE" -eq 0 ]; then
      skip "$dst — already exists; --editor never merges"
      printf '\n'
      python3 "$BASELINE/scripts/editor-settings.py" delta --kind "$kind" \
        --existing "$dst" --languages "$EDITOR_LANGS" \
        ${PRETTIER_ARGS[@]+"${PRETTIER_ARGS[@]}"} >&2
      printf '\n'
      EDITOR_CONFLICT=1
      NEEDS_MERGE=1
      continue
    fi
    wrote "$dst"
    [ "$DRY_RUN" -eq 1 ] && continue
    mkdir -p "$(dirname "$dst")"
    # Composed to a temp file first: a python failure mid-write against "$dst"
    # would leave a truncated settings.json, which VS Code reports as a parse
    # error in a panel nobody has open and otherwise treats as no settings.
    tmp="$dst.maxi-quality.$$"
    if python3 "$BASELINE/scripts/editor-settings.py" "$kind" \
         --languages "$EDITOR_LANGS" \
         ${PRETTIER_ARGS[@]+"${PRETTIER_ARGS[@]}"} > "$tmp"; then
      mv "$tmp" "$dst"
    else
      rm -f "$tmp"
      die "could not compose $dst from configs/editor/ — this is a bug in the baseline, not in your repo"
    fi
  done
fi

if [ "$WANT_AGENT" -eq 1 ]; then
  install_agent_contract
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
  printf '            eslint-plugin-sonarjs knip\n'
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
  printf '    6. knip — the gate RUNS it now (#97), not you. Two things it\n'
  printf '       needs from you, and it FAILS rather than guessing at either:\n'
  printf '         a) knip in devDependencies, >=6.31.0. Below that is refused\n'
  printf '            outright: 5.64.3 reported signature-only types as unused\n'
  printf '            exports, and a gate that fails on a finding which is not\n'
  printf '            real is one people learn to ignore.\n'
  printf '         b) real entry points in the knip.json written above. A\n'
  printf '            zero-config run on a non-default layout reports your\n'
  printf '            LAYOUT rather than your defects, so a missing config is\n'
  printf '            an error and never a default-layout run.\n'
  printf '       Until knip is installed the gate WARNS and passes — v1 is a\n'
  printf '       moving tag and it will not red your build overnight for a tool\n'
  printf '       you have not added yet. Set  dead-code: require  in your\n'
  printf '       workflow once it is in, so it cannot go quiet again.\n'
  printf '       Files, dependencies and unlisted imports gate by default.\n'
  printf '       Unused EXPORTS do not: add  dead-code-exports: true  if this\n'
  printf '       is an application. In a PUBLISHED LIBRARY leave it off — an\n'
  printf '       export no in-repo code references is indistinguishable from\n'
  printf '       public API there, and 19 of the 26 real-code findings in the\n'
  printf '       #39 eval sat in exactly that class.\n'
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
  printf '    1. Add ruff, mypy and deptry as dev dependencies (uv add --dev\n'
  printf '       ruff mypy deptry, or put them in requirements-dev.txt). CI runs\n'
  printf '       the versions YOU pin — it does not smuggle in its own.\n'
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
  printf '    5. deptry (unused/undeclared dependencies) — the gate RUNS it now\n'
  printf '       (#97). All you owe it is the dev dependency from step 1; the\n'
  printf '       two things that used to be your job are encoded:\n'
  printf '         - it runs PER PACKAGE, never at a workspace root. Measured\n'
  printf '           at a root: 125 findings, 118 of them one first-party\n'
  printf '           artifact; 3 at the granularity deptry is designed for.\n'
  printf '         - it runs INSIDE your project env, so the import-name\n'
  printf '           mapping works. Isolated it false-positives on every\n'
  printf '           package whose import name differs (beautifulsoup4/bs4).\n'
  printf '       Until deptry is installed the gate WARNS and passes; set\n'
  printf '       dead-code: require  in your workflow once it is in.\n'
  printf '       Fixes are one-line pyproject.toml edits — make them BY HAND in\n'
  printf '       one cleanup commit; there is no auto-fix and none is needed.\n'
  printf '       Unused Python CODE is not covered and that is deliberate:\n'
  printf '       vulture was measured and declined with numbers (0 confirmed\n'
  printf '       true positives over 3.18 KLOC). See docs/STATUS.md.\n'
fi

if [ "$HAS_RUST" -eq 1 ]; then
  printf '  Rust\n'
  printf '    1. No new dev dependencies — clippy and rustfmt ship with the\n'
  printf '       toolchain; cargo-deny is installed by the baseline rust job.\n'
  printf '       Locally: rustup component add clippy rustfmt, and install\n'
  printf '       cargo-deny %s to match CI.\n' "$CARGO_DENY_PIN"
  printf '    2. COMMIT Cargo.lock. The gate runs everything with --locked, and\n'
  printf '       detection REFUSES a crate that has none — a lockless crate is\n'
  printf '       one clippy cannot open, and this baseline does not do silently\n'
  printf '       unexamined. For a binary the lockfile is not optional hygiene\n'
  printf '       either: it is what cargo-deny and OSV-Scanner actually read.\n'
  printf '    3. The gate runs fmt, clippy and cargo-deny — NOT your tests, the\n'
  printf '       same split as every other language here. Keep cargo test in a\n'
  printf '       job of your own.\n'
  printf '    4. Workspace roots got [workspace.lints]; each member crate opts in\n'
  printf '       with two lines in its own Cargo.toml:  [lints]  workspace = true\n'
  printf '    5. An existing codebase will be noisy on first run — pedantic is\n'
  printf '       the strict tier and there is no ratchet for a compiler lint\n'
  printf '       (README, the ratchet asymmetry). Waive a single site with\n'
  printf '       #[allow(clippy::...)] and a reason; scoped and greppable beats\n'
  printf '       a global allow in the manifest.\n'
  printf '    6. unsafe_code is FORBIDDEN by default. A crate that genuinely\n'
  printf '       needs FFI lowers it to "deny" in its own manifest and documents\n'
  printf '       why — that is a policy call this script does not make for you.\n'
  printf '    7. OPTIONAL — the formatter: cargo fmt once, alone, and put that\n'
  printf '       commit in .git-blame-ignore-revs. Same rule as Prettier/ruff.\n'
  printf '    8. OPTIONAL — licences: deny.toml ships an EMPTY allowlist, so the\n'
  printf '       licenses check is not in the CI gate. Fill the allowlist and add\n'
  printf '       licenses to the cargo deny check line when you have a policy.\n'
  printf '    9. UNMAINTAINED crates gate only when YOU declared them. A\n'
  printf '       transitive one is unfixable at the leaf, so deny.toml scopes it\n'
  printf '       out — silently, not as a warning. List them on demand with:\n'
  printf '       cargo deny check advisories --warn unmaintained\n'
fi

if [ "$HAS_JAVA" -eq 1 ]; then
  printf '  Java (Maven)\n'
  printf '    1. No new dependencies to add by hand — Error Prone and NullAway\n'
  printf '       arrive as annotationProcessorPaths inside the region written\n'
  printf '       above, pinned. DO NOT hand-edit that region: re-run this script\n'
  printf '       to refresh it, which is the whole reason it has markers.\n'
  printf '    2. IF YOU USE LOMBOK OR MAPSTRUCT, add them to\n'
  printf '       <annotationProcessorPaths> too. Declaring that element at all\n'
  printf '       turns OFF classpath processor discovery — that is Maven behaviour,\n'
  printf '       not something this baseline chose, and it is the one way\n'
  printf '       adopting this can break a build that was previously fine.\n'
  # Written with %s rather than inline. The literal is a MAVEN property, and a
  # dollar-brace inside single quotes is flagged (correctly) as a shell
  # expansion someone forgot to make work — SC2016. Note also that a comment
  # line STARTING with the linter's own name is read as a directive to it, so
  # this paragraph deliberately does not.
  printf '    3. NullAway is told your code is yours via %sproject.groupId}. If\n' '$''{'
  printf '       your sources do not live under your groupId, change that one\n'
  printf '       value — a wrong prefix means NullAway analyses NOTHING and says\n'
  printf '       so nowhere.\n'
  printf '    4. -Werror AND ERROR PRONE INTERACT, measured and unavoidable: when\n'
  printf '       javac -Xlint produces a warning, the compile ends before Error\n'
  printf '       Prone runs, so its findings vanish from the output. The build\n'
  printf '       stays RED — a green build is one where Error Prone did run — but\n'
  printf '       the first run on an existing codebase may show only lint\n'
  printf '       warnings. Fix those, re-run, and the analyzer findings appear.\n'
  printf '    5. An existing codebase will be noisy on first run and there is no\n'
  printf '       ratchet for a compiler diagnostic. Waive a single site with\n'
  printf '       @SuppressWarnings("CheckName") and a comment saying why; scoped\n'
  printf '       and greppable beats -Xep:CheckName:OFF in the region.\n'
  printf '    6. OPTIONAL — the formatter. Not run for you, because it reformats\n'
  printf '       every file and that is your commit to make:\n'
  printf '         mvn spotless:apply     # once, alone\n'
  printf '         mvn spotless:check     # the gate\n'
  printf '       Put that one commit in .git-blame-ignore-revs. The style is\n'
  printf '       palantir-java-format AOSP: 4-space indent at 100 columns, which\n'
  printf '       is what the .editorconfig copied above already declares.\n'
fi

if [ "$WANT_EDITOR" -eq 1 ]; then
  printf '  Editor (VS Code)\n'
  printf '    1. Open the folder and take the extension recommendations. The\n'
  printf '       settings only matter with the extensions they configure.\n'
  printf '    2. TypeScript needs one HUMAN action no settings file can perform:\n'
  printf '       run "TypeScript: Select TypeScript Version" and pick the\n'
  printf '       WORKSPACE version. Until then the editor type-checks with the\n'
  printf "       one VS Code ships and CI uses yours — two compilers, two answers.\n"
  printf '    3. Every key carries the CI behaviour it pins in a comment above\n'
  printf '       it. Delete what you disagree with; the comment is there so that\n'
  printf '       is a decision rather than a guess.\n'
  printf '    4. Semgrep is NOT configured here, deliberately: its rules live in\n'
  printf '       the baseline, not in your tree, so the extension would scan with\n'
  printf '       rules this repo does not have. Semgrep still runs in CI.\n'
  printf '    5. Java gets build wiring only. Error Prone and NullAway are javac\n'
  printf '       plugins and the extension compiles with ECJ, so the Java gate\n'
  printf "       findings cannot reach the Problems panel — that is architecture,\n"
  printf '       not a missing setting.\n'
fi

if [ "$WANT_AGENT" -eq 1 ] && [ "$AGENT_CONFLICT" -eq 0 ]; then
  printf '  Agent contract (Claude Code)\n'
  printf '    1. Claude Code will ask you ONCE to trust the hooks in this repo,\n'
  printf '       the next time it starts here. That prompt is the point:\n'
  printf '       executable policy arriving in your tree should be something you\n'
  printf '       see. Until you accept it, none of this runs.\n'
  printf '    2. Declare your gate command, so a refusal can name it:\n'
  printf '         .claude/agent-guard.json  ->  { "gate_command": "<your gate>" }\n'
  printf '       Without it the Stop hook still blocks, it just cannot tell the\n'
  printf '       session WHAT to run — and a refusal with no remedy attached is a\n'
  printf '       refusal that gets worked around.\n'
  printf '    3. Run your gate through the recorder from now on:\n'
  printf '         python3 .claude/agent-guard/record-gate.py -- <your gate>\n'
  printf '       Same command, same exit code, plus a receipt of what it saw.\n'
  printf '    4. Read the startup output once. A deny rule Claude Code will not\n'
  printf '       consult warns there and then never mentions itself again.\n'
  printf '    5. selftest.py came along with the rest of scripts/agent-guard/ and\n'
  printf '       is the BASELINE\047s own corpus runner — it needs fixtures that do\n'
  printf '       not exist in your repo. Nothing in your tree invokes it.\n'
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

# LAST, so a refused editor file does not cost the run everything else it did.
# The rest of adoption has already happened and been reported; these exit codes
# say one specific thing each, and a caller that scripts adopt.sh can tell them
# apart from "nothing detected" (1) and "you typed it wrong" (3).
#
# BOTH messages print when both happened; only one code can be returned, and it
# is 6. A refused editor file held back settings that gate nothing; a refused
# merge held back the gate itself.
if [ "$EDITOR_CONFLICT" -eq 1 ]; then
  printf '\n'
  printf '\033[31mEDITOR FILES NOT WRITTEN\033[0m — a .vscode file already existed.\n'
  printf 'The delta above is what --editor would have applied. Merge it by hand,\n'
  printf 'or delete the file and re-run. --force overwrites, if that is what you want.\n'
fi

if [ "$AGENT_CONFLICT" -eq 1 ]; then
  printf '\n'
  printf '\033[31mAGENT CONTRACT NOT INSTALLED\033[0m — .claude/settings.json could not\n'
  printf 'be merged into, and the reason is above. NOTHING --agent writes was\n'
  printf 'written: not the scripts, not the CLAUDE.md region, not the .gitignore\n'
  printf 'line. Half a contract is a CLAUDE.md promising refusals that nothing\n'
  printf 'performs, which is worse than none. Fix the file and re-run, or adopt\n'
  printf 'it by hand — configs/agent/README.md section 7.\n'
  exit 6
fi

if [ "$EDITOR_CONFLICT" -eq 1 ]; then
  exit 5
fi
