#!/usr/bin/env bash
#
# maxi-quality — check the hand-pinned tool versions (issue #13).
#
# Dependabot covers npm, NuGet and GitHub Actions. It has no ecosystem for "a
# version number written into an action input default", which is exactly how
# Semgrep, Gitleaks and OSV-Scanner are pinned in actions/layer2/action.yml.
# This script is the mechanism for those three.
#
# It also asserts the thing that actually bites: Semgrep is pinned in THREE
# places — the action default, the layer2-counts job in ci.yml, and scan.sh's
# uvx/docker fallbacks. If those drift, CI validates the finding counts against
# a different Semgrep than consumers are handed, and the samples stop meaning
# what they claim.
#
# scan.sh was the third and it was not pinned at all until #43: `uvx semgrep`
# and `returntocorp/semgrep:latest`. That is why a C# parse failure could not be
# reproduced between two runs minutes apart — they were not the same tool.
#
# Usage:
#   scripts/check-pins.sh [options]
#
#   --offline           Only run the internal consistency checks; contact no
#                       network. This is what PR CI runs.
#   --fail-on-drift     Exit 1 when a newer upstream version exists. The weekly
#                       workflow uses this; a red scheduled run is the signal.
#   -h, --help          This text.
#
# Exit codes: 0 consistent (and current, unless --fail-on-drift was not set)
#             1 drift found and --fail-on-drift was set
#             2 the three Semgrep pins disagree — always fatal
#             3 usage error

set -Eeuo pipefail

BASELINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="$BASELINE/actions/layer2/action.yml"
CI="$BASELINE/.github/workflows/ci.yml"
QUALITY="$BASELINE/.github/workflows/quality.yml"
SCAN="$BASELINE/scripts/scan.sh"

OFFLINE=0
FAIL_ON_DRIFT=0

die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 3; }
bold() { printf '\033[1m%s\033[0m\n' "$1"; }
warn() { printf '\033[33mwarn:\033[0m %s\n' "$1" >&2; }
info() { printf '\033[36m›\033[0m %s\n' "$1"; }

usage() { sed -n '3,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --offline) OFFLINE=1; shift ;;
    --fail-on-drift) FAIL_ON_DRIFT=1; shift ;;
    -h|--help) usage ;;
    *) die "unknown option: $1" ;;
  esac
done

[ -f "$ACTION" ] || die "not found: $ACTION"
[ -f "$CI" ] || die "not found: $CI"
[ -f "$QUALITY" ] || die "not found: $QUALITY"
[ -f "$SCAN" ] || die "not found: $SCAN"

# --- read the pins -----------------------------------------------------------
# `default: '1.172.0'` on the line after the input's `default:` key. Read the
# value that follows each version input by name so reordering the file is safe.
pin_of() {
  awk -v key="$1" -v indent="${2:-  }" '
    $0 ~ "^" indent key ":" { found = 1; next }
    found && /default:/ {
      gsub(/.*default: *'\''/, ""); gsub(/'\''.*/, "");
      print; exit
    }
  ' "${3:-$ACTION}"
}

SEMGREP_PIN="$(pin_of semgrep-version)"
GITLEAKS_PIN="$(pin_of gitleaks-version)"
OSV_PIN="$(pin_of osv-scanner-version)"

# uv lives in quality.yml, not the layer2 action, and is indented deeper
# (workflow_call inputs). It is tracked here for the same reason as the other
# three: it is a version string Dependabot has no ecosystem for, and it replaced
# an UNPINNED `curl | sh` — a pin nobody watches rots back into the same risk.
UV_PIN="$(pin_of uv-version '      ' "$QUALITY")"

[ -n "$SEMGREP_PIN" ] || die "could not read semgrep-version from $ACTION"
[ -n "$GITLEAKS_PIN" ] || die "could not read gitleaks-version from $ACTION"
[ -n "$OSV_PIN" ] || die "could not read osv-scanner-version from $ACTION"
[ -n "$UV_PIN" ] || die "could not read uv-version from $QUALITY"

# EVERY semgrep== pin in ci.yml, not just the first one.
#
# `head -1` was enough while layer2-counts was the only job installing semgrep
# directly. It is not a property worth depending on: a second job pinning a
# different version would sit under a guard reporting "pins agree", which is
# the exact failure this script exists to prevent — a guard that passes while
# its own violation is in the file it just read.
CI_SEMGREP_ALL="$(grep -oE 'semgrep==[0-9.]+' "$CI" | cut -d= -f3 | sort -u)"
[ -n "$CI_SEMGREP_ALL" ] || die "could not read any semgrep== pin from $CI"
CI_SEMGREP="$(printf '%s\n' "$CI_SEMGREP_ALL" | head -1)"
CI_SEMGREP_COUNT="$(printf '%s\n' "$CI_SEMGREP_ALL" | grep -c .)"
if [ "$CI_SEMGREP_COUNT" -ne 1 ]; then
  printf '\033[31mFAIL\033[0m — ci.yml pins more than one semgrep version:\n'
  printf '%s\n' "$CI_SEMGREP_ALL" | sed 's/^/  /'
  printf '\nEvery job that installs semgrep must install the same one, or the\n'
  printf 'jobs are asserting against different tools.\n'
  exit 2
fi

# PYYAML, in ci.yml AND the consumer-facing layer2 action. It is checked from
# both ends for the same reason the rust pin below is: agreeing on a version is
# worth nothing if some other line installs it unpinned.
#
# The unpinned form is the one that matters. `pip install pyyaml` resolved to
# whatever PyPI served that morning, in every consumer's CI, twelve lines above
# a sha256 check — and nothing here noticed, because there was no pin to compare
# against. A guard that only validates pins it can find will always pass on the
# install that has none.
PYYAML_ALL="$(grep -hoE "pyyaml==[0-9.]+" "$CI" "$ACTION" | cut -d= -f3 | sort -u)"
[ -n "$PYYAML_ALL" ] || die "could not read any pyyaml== pin from $CI or $ACTION"
if [ "$(printf '%s\n' "$PYYAML_ALL" | grep -c .)" -ne 1 ]; then
  printf '\033[31mFAIL\033[0m — more than one pyyaml version is pinned:\n'
  printf '%s\n' "$PYYAML_ALL" | sed 's/^/  /'
  exit 2
fi
PYYAML_PIN="$PYYAML_ALL"
# An install with no version at all, anywhere in either file.
UNPINNED_PYYAML="$(grep -nE "pip install[^|&]*pyyaml([^=]|$)" "$CI" "$ACTION" || true)"
if [ -n "$UNPINNED_PYYAML" ]; then
  printf '\033[31mFAIL\033[0m — pyyaml installed WITHOUT a version:\n'
  printf '%s\n' "$UNPINNED_PYYAML" | sed 's/^/  /'
  printf '\nA version is the pin for a PyPI package (actions/layer2/action.yml\n'
  printf 'says so about semgrep). An unversioned install is not one, and it\n'
  printf 'runs in every consumer CI.\n'
  exit 2
fi

# THE RUST PAIR (#58, and #70 moved one half of it). The toolchain and
# cargo-deny are pinned in TWO places: quality.yml's rust job is the one every
# consumer actually runs, and ci.yml's layer1-rust job installs its own to
# validate the fixtures. If they drift, CI validates the finding manifests
# against a clippy consumers never run — the exact Semgrep failure this script
# was written for, wearing a different toolchain.
#
# The consumer-facing half used to be scripts/adopt.sh, which stamped a pinned
# job into each consumer's own workflow file. Since #70 it is quality.yml, so
# this is now an assertion about the file that runs rather than about the file
# that once wrote the file that ran.
RUST_PIN="$(pin_of rust-version '      ' "$QUALITY")"
[ -n "$RUST_PIN" ] || die "could not read rust-version from $QUALITY"
# Declared is not used — the same decorative-pin trap as scan.sh's (#43). Both
# halves are checked: an input nothing reads, and a rustup line that hardcodes
# a version instead of reading the input, are the same failure from either end.
grep -q 'RUST_VERSION: [$]{{ inputs.rust-version }}' "$QUALITY" \
  || die "$QUALITY declares rust-version but no step passes it through — the pin is decorative"
grep -q 'rustup toolchain install "[$]RUST_VERSION"' "$QUALITY" \
  || die "$QUALITY declares rust-version but the rust job no longer installs it — the pin is decorative"

# cargo-deny is a literal URL rather than an input (the checksum is bound to the
# version — quality.yml says why), so it is read the same way as ci.yml's.
QUALITY_DENY_ALL="$(grep -oE 'cargo-deny/releases/download/[0-9.]+/' "$QUALITY" | grep -oE '[0-9]+\.[0-9.]+' | sort -u)"
[ -n "$QUALITY_DENY_ALL" ] || die "could not read any cargo-deny pin from $QUALITY"
[ "$(printf '%s\n' "$QUALITY_DENY_ALL" | grep -c .)" -eq 1 ] || {
  printf '\033[31mFAIL\033[0m — quality.yml pins more than one cargo-deny:\n'
  printf '%s\n' "$QUALITY_DENY_ALL" | sed 's/^/  /'
  exit 2
}
DENY_PIN="$(printf '%s\n' "$QUALITY_DENY_ALL" | head -1)"

# THE THIRD CARGO-DENY SITE. adopt.sh no longer installs cargo-deny, but it
# still PRINTS a version in its summary ("install cargo-deny X to match CI"),
# and a version a human is told to install is a pin like any other: let it
# drift and every adopter runs a different cargo-deny than the gate, which is
# this script's founding complaint (#43) with the tool swapped out. Cheaper to
# assert than to notice.
ADOPT="$BASELINE/scripts/adopt.sh"
[ -f "$ADOPT" ] || die "not found: $ADOPT"
ADOPT_DENY="$(sed -n 's/^CARGO_DENY_PIN="\([0-9.]*\)".*/\1/p' "$ADOPT" | head -1)"
[ -n "$ADOPT_DENY" ] || die "could not read CARGO_DENY_PIN from $ADOPT"
grep -q 'cargo-deny %s to match CI' "$ADOPT" \
  || die "$ADOPT sets CARGO_DENY_PIN but no longer tells anyone to install it — the pin is decorative"

# Every occurrence in ci.yml, not the first — same argument as the semgrep
# grep above: `rustup default` drifting from `rustup toolchain install` is two
# versions under a guard reporting one.
CI_RUST_ALL="$(grep -oE 'rustup (toolchain install|default) [0-9.]+' "$CI" | grep -oE '[0-9.]+$' | sort -u)"
[ -n "$CI_RUST_ALL" ] || die "could not read any rustup pin from $CI"
[ "$(printf '%s\n' "$CI_RUST_ALL" | grep -c .)" -eq 1 ] || {
  printf '\033[31mFAIL\033[0m — ci.yml pins more than one Rust toolchain:\n'
  printf '%s\n' "$CI_RUST_ALL" | sed 's/^/  /'
  exit 2
}
CI_RUST="$(printf '%s\n' "$CI_RUST_ALL" | head -1)"
CI_DENY_ALL="$(grep -oE 'cargo-deny/releases/download/[0-9.]+/' "$CI" | grep -oE '[0-9]+\.[0-9.]+' | sort -u)"
[ -n "$CI_DENY_ALL" ] || die "could not read any cargo-deny pin from $CI"
[ "$(printf '%s\n' "$CI_DENY_ALL" | grep -c .)" -eq 1 ] || {
  printf '\033[31mFAIL\033[0m — ci.yml pins more than one cargo-deny:\n'
  printf '%s\n' "$CI_DENY_ALL" | sed 's/^/  /'
  exit 2
}
CI_DENY="$(printf '%s\n' "$CI_DENY_ALL" | head -1)"

# The checksum is the other half of the cargo-deny pin, and it is copied into
# both files. Bumping the version in one of them while the other keeps its old
# checksum produces a job that dies on `sha256sum -c` — loud, but only after a
# push, and only in whichever half was half-bumped. Both are read as sets, so a
# file that disagrees with ITSELF is caught too.
deny_sha_of() { grep -oE "CARGO_DENY_SHA256: '[0-9a-f]{64}'" "$1" | grep -oE '[0-9a-f]{64}' | sort -u; }
QUALITY_DENY_SHA="$(deny_sha_of "$QUALITY")"
CI_DENY_SHA="$(deny_sha_of "$CI")"
[ -n "$QUALITY_DENY_SHA" ] || die "could not read CARGO_DENY_SHA256 from $QUALITY"
[ -n "$CI_DENY_SHA" ] || die "could not read CARGO_DENY_SHA256 from $CI"

# THE THIRD SITE (#43). scripts/scan.sh is what a human runs locally, and until
# #43 it pinned nothing at all — `uvx semgrep` and `returntocorp/semgrep:latest`.
# A local scan resolving a different semgrep than CI is how a parse failure came
# to be irreproducible between two runs minutes apart.
SCAN_SEMGREP="$(sed -n 's/^SEMGREP_PIN="\([0-9.]*\)".*/\1/p' "$SCAN" | head -1)"
[ -n "$SCAN_SEMGREP" ] || die "could not read SEMGREP_PIN from $SCAN"
# The literal has to be USED, not merely assigned. A pin nothing reads is a
# comment, and this script would happily report three agreeing versions while
# scan.sh ran `uvx semgrep` unpinned two lines below.
grep -q 'semgrep==[$]SEMGREP_PIN' "$SCAN" \
  || die "$SCAN sets SEMGREP_PIN but no longer passes it to uvx — the pin is decorative"
grep -q 'returntocorp/semgrep:[$]SEMGREP_PIN' "$SCAN" \
  || die "$SCAN sets SEMGREP_PIN but no longer passes it to docker — the pin is decorative"

# --- THE JAVA PINS (#10) -----------------------------------------------------
#
# Four analyzer versions live in configs/java/pom-lints.xml — the file consumers
# COPY — and the JDK lives in quality.yml. The consistency that matters here is
# not between two workflow files: it is that CI validates the SAME analyzer
# versions the consumers were handed, and that the JDK CI compiles the fixtures
# on is the one the reusable job pins. Otherwise samples/expected/java.json is a
# manifest for a toolchain nobody runs.
#
# Read out of the shipped fragment rather than out of the fixtures: the fixtures
# are generated FROM it (scripts/pom-region.py), so reading them would be this
# script checking a copy against itself.
frag_version() {
  # <artifactId>X</artifactId> on one line, <version>N</version> on the next —
  # which is exactly how the fragment is written and how pom-region.py keeps it.
  grep -A1 "<artifactId>$1</artifactId>" "$JAVA_FRAGMENT" \
    | grep -oE '<version>[^<]+</version>' | head -1 | sed -e 's|<version>||' -e 's|</version>||'
}
JAVA_FRAGMENT="$BASELINE/configs/java/pom-lints.xml"
[ -f "$JAVA_FRAGMENT" ] || die "missing $JAVA_FRAGMENT"

EP_PIN="$(frag_version error_prone_core)"
NULLAWAY_PIN="$(frag_version nullaway)"
COMPILER_PIN="$(frag_version maven-compiler-plugin)"
SPOTLESS_PIN="$(frag_version spotless-maven-plugin)"
for pair in "error_prone_core:$EP_PIN" "nullaway:$NULLAWAY_PIN" \
            "maven-compiler-plugin:$COMPILER_PIN" "spotless-maven-plugin:$SPOTLESS_PIN"; do
  [ -n "${pair#*:}" ] || die "could not read the ${pair%%:*} version from $JAVA_FRAGMENT"
done

# palantir-java-format sits one level deeper (inside <palantirJavaFormat>), so
# it is read by its own element rather than by the artifactId pair above.
PALANTIR_PIN="$(sed -n '/<palantirJavaFormat>/,/<\/palantirJavaFormat>/p' "$JAVA_FRAGMENT" \
  | grep -oE '<version>[^<]+</version>' | head -1 | sed -e 's|<version>||' -e 's|</version>||')"
[ -n "$PALANTIR_PIN" ] || die "could not read the palantir-java-format version from $JAVA_FRAGMENT"

JAVA_PIN="$(pin_of java-version '      ' "$QUALITY")"
[ -n "$JAVA_PIN" ] || die "could not read java-version from $QUALITY"
# Same decorative-pin guard as rust-version: an input nothing passes through is
# a comment with a default value.
grep -q 'java-version: [$]{{ inputs.java-version }}' "$QUALITY" \
  || die "$QUALITY declares java-version but no step passes it through — the pin is decorative"

CI_JAVA="$(grep -oE "java-version: '[0-9.]+'" "$CI" | grep -oE "[0-9.]+" | sort -u)"
[ -n "$CI_JAVA" ] || die "could not read a java-version pin from $CI"
[ "$(printf '%s\n' "$CI_JAVA" | grep -c .)" -eq 1 ] || {
  printf '\033[31merror:\033[0m %s pins more than one JDK:\n' "$CI" >&2
  printf '%s\n' "$CI_JAVA" | sed 's/^/  /'
  exit 1; }

# --- THE DEAD-CODE PINS (#97) ------------------------------------------------
#
# knip and deptry are the first tools in this baseline that the CONSUMER
# installs and the BASELINE holds to a floor. That makes the drift here a
# different shape from every pin above: the risk is not two files installing
# different versions, it is CI validating samples/expected/knip.json with a knip
# that a consumer would be REFUSED for running.
#
# The floor is a hard error in actions/deadcode because 5.64.3 shipped a false
# positive on signature-only types (#51), and a gate that fails on a finding
# that is not real teaches people to ignore it. So the floor and the version the
# fixtures are asserted against have to be the same number, and the two example
# repos — which are documentation people copy — have to name it too.
DEADCODE="$BASELINE/actions/deadcode/action.yml"
PKG="$BASELINE/package.json"
EXAMPLE_PKG="$BASELINE/examples/typescript-npm/package.json"
[ -f "$DEADCODE" ] || die "not found: $DEADCODE"
[ -f "$PKG" ] || die "not found: $PKG"
[ -f "$EXAMPLE_PKG" ] || die "not found: $EXAMPLE_PKG"

KNIP_FLOOR="$(pin_of knip-min-version '  ' "$DEADCODE")"
[ -n "$KNIP_FLOOR" ] || die "could not read knip-min-version from $DEADCODE"
# Declared is not used — the same decorative-pin guard the rust and java pins
# carry. An input the script never compares against is a comment.
grep -q 'KNIP_MIN: [$]{{ inputs.knip-min-version }}' "$DEADCODE" \
  || die "$DEADCODE declares knip-min-version but no step passes it through — the floor is decorative"

knip_version_in() { grep -oE '"knip": *"[^"]+"' "$1" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+'; }
KNIP_DEV="$(knip_version_in "$PKG")"
KNIP_EXAMPLE="$(knip_version_in "$EXAMPLE_PKG")"
[ -n "$KNIP_DEV" ] || die "could not read the knip devDependency from $PKG"
[ -n "$KNIP_EXAMPLE" ] || die "could not read the knip devDependency from $EXAMPLE_PKG"

# deptry, same argument one language over. The version CI installs to assert
# samples/expected/deptry.json, and the one the worked example tells a reader
# to add, must not drift apart — a finding manifest is only meaningful against a
# known resolution behaviour, which samples/deptry/requirements.txt already says
# about beautifulsoup4.
#
# NOTE the two are not the same KIND of constraint: `deptry==0.25.1` is an exact
# pin and `deptry>=0.25.1` is a floor. Only the NUMBERS are compared, and that
# is the whole intent — an example telling a reader to install a version older
# than the one CI measured against is the drift worth catching. Do not "fix"
# this into an operator comparison; a consumer pinning exactly is not an error.
PY_DEV="$BASELINE/samples/python/requirements-dev.txt"
EXAMPLE_PY="$BASELINE/examples/python-uv/pyproject.toml"
[ -f "$PY_DEV" ] || die "not found: $PY_DEV"
[ -f "$EXAMPLE_PY" ] || die "not found: $EXAMPLE_PY"
DEPTRY_CI="$(grep -oE '^deptry==[0-9.]+' "$PY_DEV" | cut -d= -f3)"
DEPTRY_EXAMPLE="$(grep -oE 'deptry>=[0-9.]+' "$EXAMPLE_PY" | grep -oE '[0-9]+\.[0-9.]+')"
[ -n "$DEPTRY_CI" ] || die "could not read the deptry pin from $PY_DEV"
[ -n "$DEPTRY_EXAMPLE" ] || die "could not read the deptry floor from $EXAMPLE_PY"

bold "── pinned ──"
info "semgrep       $SEMGREP_PIN   (action.yml)"
info "semgrep       $CI_SEMGREP   (ci.yml, $(grep -cE 'semgrep==[0-9.]+' "$CI") job(s))"
info "semgrep       $SCAN_SEMGREP   (scan.sh, uvx + docker fallbacks)"
info "gitleaks      $GITLEAKS_PIN"
info "osv-scanner   $OSV_PIN"
info "uv            $UV_PIN   (quality.yml)"
info "pyyaml        $PYYAML_PIN   (ci.yml + layer2 action, all sites)"
info "rust          $RUST_PIN   (quality.yml)"
info "rust          $CI_RUST   (ci.yml)"
info "cargo-deny    $DENY_PIN   (quality.yml)"
info "cargo-deny    $CI_DENY   (ci.yml)"
info "cargo-deny    $ADOPT_DENY   (adopt.sh, the 'install locally' line)"
info "jdk           $JAVA_PIN   (quality.yml)"
info "jdk           $CI_JAVA   (ci.yml)"
info "error-prone   $EP_PIN   (configs/java/pom-lints.xml)"
info "nullaway      $NULLAWAY_PIN   (configs/java/pom-lints.xml)"
info "mvn-compiler  $COMPILER_PIN   (configs/java/pom-lints.xml)"
info "spotless      $SPOTLESS_PIN   (configs/java/pom-lints.xml)"
info "palantir-fmt  $PALANTIR_PIN   (configs/java/pom-lints.xml)"
info "knip          $KNIP_FLOOR   (actions/deadcode, the floor consumers are held to)"
info "knip          $KNIP_DEV   (package.json, what CI asserts the fixtures with)"
info "knip          $KNIP_EXAMPLE   (examples/typescript-npm)"
info "deptry        $DEPTRY_CI   (samples/python/requirements-dev.txt)"
info "deptry        $DEPTRY_EXAMPLE   (examples/python-uv)"
printf '\n'

# --- consistency: the two Semgrep pins must agree ----------------------------
# This is the one that is always fatal. A mismatch means the counts asserted in
# CI were produced by a different Semgrep than the one consumers run, so a
# green build would be telling you nothing about what the action actually does.
if [ "$SEMGREP_PIN" != "$CI_SEMGREP" ] || [ "$SEMGREP_PIN" != "$SCAN_SEMGREP" ]; then
  printf '\033[31mFAIL\033[0m — semgrep pins disagree:\n'
  printf '  actions/layer2/action.yml : %s\n' "$SEMGREP_PIN"
  printf '  .github/workflows/ci.yml  : %s\n' "$CI_SEMGREP"
  printf '  scripts/scan.sh           : %s\n' "$SCAN_SEMGREP"
  printf '\nCI would assert its finding manifest against a Semgrep that consumers\n'
  printf 'never run, or a local scan would disagree with the gate it is meant to\n'
  printf 'predict. Set all three to the same version.\n'
  exit 2
fi
info "semgrep pins agree across all three files"

# --- consistency: the Rust pair, same rule, same severity --------------------
if [ "$RUST_PIN" != "$CI_RUST" ] || [ "$DENY_PIN" != "$CI_DENY" ] \
   || [ "$DENY_PIN" != "$ADOPT_DENY" ] || [ "$QUALITY_DENY_SHA" != "$CI_DENY_SHA" ]; then
  printf '\033[31mFAIL\033[0m — Rust pins disagree:\n'
  printf '  .github/workflows/quality.yml : rust %s · cargo-deny %s\n' "$RUST_PIN" "$DENY_PIN"
  printf '  .github/workflows/ci.yml      : rust %s · cargo-deny %s\n' "$CI_RUST" "$CI_DENY"
  printf '  scripts/adopt.sh (summary)    : cargo-deny %s\n' "$ADOPT_DENY"
  if [ "$QUALITY_DENY_SHA" != "$CI_DENY_SHA" ]; then
    printf '  cargo-deny checksums differ:\n'
    printf '    quality.yml : %s\n' "$QUALITY_DENY_SHA"
    printf '    ci.yml      : %s\n' "$CI_DENY_SHA"
  fi
  printf '\nThe clippy manifest and the RUSTSEC fixture would be asserted against a\n'
  printf 'toolchain consumers are never handed. Set both files to the same versions.\n'
  exit 2
fi
info "rust pins agree across quality.yml, ci.yml and adopt.sh"

if [ "$JAVA_PIN" != "$CI_JAVA" ]; then
  printf '\033[31merror:\033[0m the JDK pin disagrees between the two workflows:\n' >&2
  printf '  .github/workflows/quality.yml : jdk %s\n' "$JAVA_PIN" >&2
  printf '  .github/workflows/ci.yml      : jdk %s\n' "$CI_JAVA" >&2
  printf '\nsamples/expected/java.json would be asserted against a JDK consumers never\n' >&2
  printf 'run. Error Prone reaches into javac internals and -Xlint gains categories\n' >&2
  printf 'between releases, so the finding set is JDK-specific. Bump both together.\n' >&2
  exit 1
fi
info "jdk pin agrees across quality.yml and ci.yml"

# --- consistency: the dead-code floor (#97) ----------------------------------
# All four are compared as one set. The pair that MUST hold is floor vs the
# devDependency: if this repo asserts samples/expected/knip.json with a knip
# below the floor, CI is validating the fixtures with a version the action would
# refuse — a gate whose evidence comes from a tool it will not let consumers
# run. The examples are in the set because they are documentation people copy,
# and a worked example naming a version the gate rejects is a first run that
# fails for a reason the reader did nothing to cause.
if [ "$KNIP_FLOOR" != "$KNIP_DEV" ] || [ "$KNIP_FLOOR" != "$KNIP_EXAMPLE" ]; then
  printf '\033[31mFAIL\033[0m — knip versions disagree:\n'
  printf '  actions/deadcode/action.yml       : floor %s\n' "$KNIP_FLOOR"
  printf '  package.json                      : %s\n' "$KNIP_DEV"
  printf '  examples/typescript-npm           : %s\n' "$KNIP_EXAMPLE"
  printf '\nThe fixtures would be asserted against a knip the gate refuses, or the\n'
  printf 'worked example would name one. 5.64.3 shipped a false positive that\n'
  printf '6.31.0 fixed, which is why the floor is a hard error at all.\n'
  exit 2
fi
if [ "$DEPTRY_CI" != "$DEPTRY_EXAMPLE" ]; then
  printf '\033[31mFAIL\033[0m — deptry versions disagree:\n'
  printf '  samples/python/requirements-dev.txt : %s\n' "$DEPTRY_CI"
  printf '  examples/python-uv/pyproject.toml   : %s\n' "$DEPTRY_EXAMPLE"
  printf '\nsamples/expected/deptry.json is a manifest for one resolution behaviour.\n'
  exit 2
fi
info "dead-code pins agree (knip floor, devDependency and example; deptry both sites)"

if [ "$OFFLINE" -eq 1 ]; then
  printf '\n\033[32mPASS\033[0m — pins are internally consistent (--offline; upstream not checked)\n'
  exit 0
fi

# --- drift: is anything newer upstream? --------------------------------------
DRIFT=0

latest_pypi() {
  curl -fsSL --max-time 20 "https://pypi.org/pypi/$1/json" 2>/dev/null \
    | sed -n 's/.*"version":"\([^"]*\)".*/\1/p' | head -1
}

latest_gh() {
  curl -fsSL --max-time 20 "https://api.github.com/repos/$1/releases/latest" 2>/dev/null \
    | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1
}

compare() {
  name="$1"; pinned="$2"; latest="$3"
  if [ -z "$latest" ]; then
    warn "$name — could not reach upstream, skipping"
    return 0
  fi
  if [ "$pinned" = "$latest" ]; then
    info "$name is current ($pinned)"
  else
    printf '\033[33mdrift\033[0m %s: pinned %s, latest %s\n' "$name" "$pinned" "$latest"
    DRIFT=1
  fi
}

bold "── upstream ──"
compare "semgrep"     "$SEMGREP_PIN"  "$(latest_pypi semgrep)"
compare "gitleaks"    "$GITLEAKS_PIN" "$(latest_gh gitleaks/gitleaks | sed 's/^v//')"
compare "osv-scanner" "$OSV_PIN"      "$(latest_gh google/osv-scanner)"
compare "uv"          "$UV_PIN"      "$(latest_gh astral-sh/uv)"
# Not the GitHub releases API: rust-lang/rust publishes the channel manifest,
# and the [pkg.rust] version line is the stable version.
compare "rust"        "$RUST_PIN"    "$(curl -fsSL --max-time 20 https://static.rust-lang.org/dist/channel-rust-stable.toml 2>/dev/null | sed -n '/^\[pkg\.rust\]/,/^\[/{s/^version = "\([0-9.]*\).*/\1/p;}' | head -1)"
compare "cargo-deny"  "$DENY_PIN"    "$(latest_gh EmbarkStudios/cargo-deny)"
# Maven Central has no releases API; maven-metadata.xml is the equivalent, and
# its LAST <version> is the newest. Filtered for release versions — Error Prone
# and Spotless both publish nothing pre-release on these coordinates today, but
# a bump proposal built on an -RC is a bump nobody wanted.
latest_maven() {
  curl -fsSL --max-time 20 "https://repo1.maven.org/maven2/$1/maven-metadata.xml" 2>/dev/null \
    | grep -oE '<version>[^<]+</version>' | sed -e 's|<version>||' -e 's|</version>||' \
    | grep -viE 'alpha|beta|rc|-M[0-9]|snapshot' | tail -1
}
compare "error-prone"  "$EP_PIN"        "$(latest_maven com/google/errorprone/error_prone_core)"
compare "nullaway"     "$NULLAWAY_PIN"  "$(latest_maven com/uber/nullaway/nullaway)"
compare "mvn-compiler" "$COMPILER_PIN"  "$(latest_maven org/apache/maven/plugins/maven-compiler-plugin)"
compare "spotless"     "$SPOTLESS_PIN"  "$(latest_maven com/diffplug/spotless/spotless-maven-plugin)"
compare "palantir-fmt" "$PALANTIR_PIN"  "$(latest_maven com/palantir/javaformat/palantir-java-format)"

printf '\n'
if [ "$DRIFT" -eq 1 ]; then
  printf 'A newer version exists. Bumping is a DECISION, not a chore:\n'
  printf '  1. Bump action.yml and ci.yml together — this script fails if you do not.\n'
  printf '  2. Run ./scripts/scan.sh. If the counts moved, a rule changed behaviour;\n'
  printf '     update the expected count and say why. Never weaken a sample.\n'
  printf '  3. Move the v1 tag, or consumers keep the old tools (STATUS §4).\n\n'
  if [ "$FAIL_ON_DRIFT" -eq 1 ]; then
    printf '\033[33mDRIFT\033[0m — exiting 1 because --fail-on-drift was set\n'
    exit 1
  fi
  printf '\033[33mDRIFT\033[0m — reported, exiting 0\n'
  exit 0
fi

printf '\033[32mPASS\033[0m — pins consistent and current\n'
