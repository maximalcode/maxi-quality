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

# THE RUST PAIR (#58). The toolchain and cargo-deny are pinned in TWO places:
# adopt.sh stamps them into every consumer's scaffolded workflow, and ci.yml's
# layer1-rust job installs its own. If they drift, CI validates the finding
# manifests against a clippy consumers never run — the exact Semgrep failure
# this script was written for, wearing a different toolchain.
ADOPT="$BASELINE/scripts/adopt.sh"
[ -f "$ADOPT" ] || die "not found: $ADOPT"

RUST_PIN="$(sed -n 's/^RUST_TOOLCHAIN_PIN="\([0-9.]*\)".*/\1/p' "$ADOPT" | head -1)"
DENY_PIN="$(sed -n 's/^CARGO_DENY_PIN="\([0-9.]*\)".*/\1/p' "$ADOPT" | head -1)"
[ -n "$RUST_PIN" ] || die "could not read RUST_TOOLCHAIN_PIN from $ADOPT"
[ -n "$DENY_PIN" ] || die "could not read CARGO_DENY_PIN from $ADOPT"
# Assigned is not used — the same decorative-pin trap as scan.sh's (#43).
grep -q 'rustup toolchain install [$]RUST_TOOLCHAIN_PIN' "$ADOPT" \
  || die "$ADOPT sets RUST_TOOLCHAIN_PIN but the scaffold no longer installs it — the pin is decorative"
grep -q 'download/[$]CARGO_DENY_PIN/' "$ADOPT" \
  || die "$ADOPT sets CARGO_DENY_PIN but the scaffold no longer downloads it — the pin is decorative"

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

bold "── pinned ──"
info "semgrep       $SEMGREP_PIN   (action.yml)"
info "semgrep       $CI_SEMGREP   (ci.yml, $(grep -cE 'semgrep==[0-9.]+' "$CI") job(s))"
info "semgrep       $SCAN_SEMGREP   (scan.sh, uvx + docker fallbacks)"
info "gitleaks      $GITLEAKS_PIN"
info "osv-scanner   $OSV_PIN"
info "uv            $UV_PIN   (quality.yml)"
info "rust          $RUST_PIN   (adopt.sh scaffold)"
info "rust          $CI_RUST   (ci.yml)"
info "cargo-deny    $DENY_PIN   (adopt.sh scaffold)"
info "cargo-deny    $CI_DENY   (ci.yml)"
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
if [ "$RUST_PIN" != "$CI_RUST" ] || [ "$DENY_PIN" != "$CI_DENY" ]; then
  printf '\033[31mFAIL\033[0m — Rust pins disagree:\n'
  printf '  scripts/adopt.sh (scaffold)  : rust %s · cargo-deny %s\n' "$RUST_PIN" "$DENY_PIN"
  printf '  .github/workflows/ci.yml     : rust %s · cargo-deny %s\n' "$CI_RUST" "$CI_DENY"
  printf '\nThe clippy manifest and the RUSTSEC fixture would be asserted against a\n'
  printf 'toolchain consumers are never handed. Set both files to the same versions.\n'
  exit 2
fi
info "rust pins agree between adopt.sh and ci.yml"

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
