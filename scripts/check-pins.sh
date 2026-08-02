#!/usr/bin/env bash
#
# maxi-quality — check the hand-pinned tool versions (issue #13).
#
# Dependabot covers npm, NuGet and GitHub Actions. It has no ecosystem for "a
# version number written into an action input default", which is exactly how
# Semgrep, Gitleaks and OSV-Scanner are pinned in actions/layer2/action.yml.
# This script is the mechanism for those three.
#
# It also asserts the thing that actually bites: Semgrep is pinned in TWO
# places — the action default AND the layer2-counts job in ci.yml. If those
# drift, CI validates the finding counts against a different Semgrep than
# consumers are handed, and the samples stop meaning what they claim.
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
#             2 the two Semgrep pins disagree — always fatal
#             3 usage error

set -Eeuo pipefail

BASELINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="$BASELINE/actions/layer2/action.yml"
CI="$BASELINE/.github/workflows/ci.yml"
QUALITY="$BASELINE/.github/workflows/quality.yml"

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

CI_SEMGREP="$(grep -oE 'semgrep==[0-9.]+' "$CI" | head -1 | cut -d= -f3)"
[ -n "$CI_SEMGREP" ] || die "could not read semgrep== pin from $CI"

bold "── pinned ──"
info "semgrep       $SEMGREP_PIN   (action.yml)"
info "semgrep       $CI_SEMGREP   (ci.yml layer2-counts)"
info "gitleaks      $GITLEAKS_PIN"
info "osv-scanner   $OSV_PIN"
info "uv            $UV_PIN   (quality.yml)"
printf '\n'

# --- consistency: the two Semgrep pins must agree ----------------------------
# This is the one that is always fatal. A mismatch means the counts asserted in
# CI were produced by a different Semgrep than the one consumers run, so a
# green build would be telling you nothing about what the action actually does.
if [ "$SEMGREP_PIN" != "$CI_SEMGREP" ]; then
  printf '\033[31mFAIL\033[0m — semgrep pins disagree:\n'
  printf '  actions/layer2/action.yml : %s\n' "$SEMGREP_PIN"
  printf '  .github/workflows/ci.yml  : %s\n' "$CI_SEMGREP"
  printf '\nCI would assert 59 findings against a Semgrep that consumers never run.\n'
  printf 'Set both to the same version.\n'
  exit 2
fi
info "semgrep pins agree in both files"

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
