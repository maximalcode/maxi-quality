#!/usr/bin/env bash
#
# maxi-quality — the patch-coverage demo (issue #123).
#
# One command over samples/coverage/patch that prints, for the same committed
# change:
#
#   * the aggregate ratchet reporting `ok` — the defect,
#   * coverage of the CHANGED lines, computed two ways, agreeing.
#
# The two ways are the build-vs-reuse question #112 left open: scripts/coverage.py
# --diff-file (extend what we already parse) against diff-cover (one pinned pip
# dependency). Both run on the identical reports and the identical diff, and the
# numbers are checked against the hand-count in samples/coverage/patch/README.md
# rather than against each other — two implementations agreeing on a wrong number
# is the failure this is built to catch.
#
# The comparison is on LINE COUNTS, not on the printed percentage: diff-cover
# truncates its percentage to a whole number (2 of 6 covered prints 33, not
# 33.33), so comparing the strings would report a disagreement that is only
# formatting. What has to match is which lines each tool measured and which it
# found covered.
#
# Usage:
#   scripts/patch-coverage-demo.sh [options]
#
#   --skip-diff-cover   Run only scripts/coverage.py. Works offline; proves
#                       nothing about agreement, so it is not what CI runs.
#   -h, --help          This text.
#
# Exit codes: 0 everything agreed with the hand-count
#             1 a number disagreed — read the output, do not adjust the fixture
#             3 usage error, or diff-cover could not be installed

set -Eeuo pipefail

# The one place this version is written. CI runs this script rather than
# installing diff-cover itself, so there is no second pin to drift from.
DIFF_COVER_VERSION=10.0.0

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE="$REPO/samples/coverage/patch"
SKIP_DIFF_COVER=0
FAILED=0

die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 3; }
bold() { printf '\n\033[1m%s\033[0m\n' "$1"; }
fail() { printf '\033[31mFAIL:\033[0m %s\n' "$1" >&2; FAILED=1; }
ok() { printf '\033[32mok:\033[0m %s\n' "$1"; }

usage() { sed -n '3,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-diff-cover) SKIP_DIFF_COVER=1; shift ;;
    -h|--help) usage ;;
    *) die "unknown option: $1" ;;
  esac
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- the two implementations, each reduced to "<measured> <covered>" ----------

# scripts/coverage.py. `n/a` is a first-class answer and stays a word: turning it
# into a number here is the exact lie the flag exists to avoid.
coverage_py() { # <report> <diff>  ->  "<measured> <covered>"
  local out
  out="$(python3 "$REPO/scripts/coverage.py" --report "$1" \
          --floor-file "$FIXTURE/floor.json" --diff-file "$2" 2>/dev/null)"
  printf '%s %s\n' \
    "$(printf '%s\n' "$out" | sed -n 's/^patch_lines_found=//p')" \
    "$(printf '%s\n' "$out" | sed -n 's/^patch_lines_hit=//p')"
}

# diff-cover reports the lines it could NOT cover, so covered is the difference.
# It must run from the repo root: even with --diff-file it shells out to git to
# resolve report paths against the working tree.
#
# A FRESH report path per run, and no `|| true`. Both matter: diff-cover dies on
# inputs this script deliberately feeds it — a mixed-format pair, a diff with no
# `diff --git` header — and a swallowed exit code over a reused file re-reports
# the PREVIOUS case as this one's answer. Two of the four cases here expect the
# same "0 0", so that failure would have read as agreement.
DC_RUN=0
diffcover() { # <report> <diff>  ->  "<measured> <covered>"
  local json="$TMP/dc-$DC_RUN.json"
  DC_RUN=$((DC_RUN + 1))
  ( cd "$REPO" && "$DC" "$1" --diff-file "$2" --json-report "$json" -q >/dev/null 2>&1 ) || {
    printf 'diff-cover exited %s on %s + %s\n' "$?" "$1" "$2" >&2
    return 1
  }
  [ -f "$json" ] || { printf 'diff-cover wrote no report for %s + %s\n' "$1" "$2" >&2; return 1; }
  python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d["total_num_lines"], d["total_num_lines"] - d["total_num_violations"])
' "$json"
}

# "<measured> <covered>" -> a percentage, or the word n/a. Zero measured lines
# has no percentage to print, and inventing one here would undo the whole point.
render() {
  local measured covered
  read -r measured covered <<<"$1"
  case "$measured" in
    '' | *[!0-9]*) printf '%s' "$1"; return ;;  # already a word: (skipped), (failed)
  esac
  if [ "$measured" -eq 0 ]; then
    printf 'n/a (0 lines)'
  else
    python3 -c "print('%.2f%% (%s/%s)' % (100.0 * $covered / $measured, $covered, $measured))"
  fi
}

if [ "$SKIP_DIFF_COVER" -eq 0 ]; then
  if command -v diff-cover >/dev/null 2>&1; then
    DC="$(command -v diff-cover)"
  else
    printf 'installing diff-cover==%s into a throwaway venv…\n' "$DIFF_COVER_VERSION"
    python3 -m venv "$TMP/venv" >/dev/null 2>&1 || die "python3 -m venv failed"
    "$TMP/venv/bin/pip" install --quiet --disable-pip-version-check \
      "diff_cover==$DIFF_COVER_VERSION" >/dev/null 2>&1 \
      || die "could not install diff-cover==$DIFF_COVER_VERSION (offline? try --skip-diff-cover)"
    DC="$TMP/venv/bin/diff-cover"
  fi
fi

# --- 1. the defect: the aggregate ratchet sees nothing ------------------------

bold "1. The aggregate ratchet, on the change that adds an untested function"
set +e
RATCHET="$(python3 "$REPO/scripts/coverage.py" --report "$FIXTURE/lcov.info" \
            --floor-file "$FIXTURE/floor.json" 2>&1)"
RATCHET_RC=$?
set -e
printf '%s\n' "$RATCHET" | sed 's/^/    /'
[ "$RATCHET_RC" -eq 0 ] || fail "the ratchet exited $RATCHET_RC on the fixture; the defect is that it PASSES"
printf '%s\n' "$RATCHET" | grep -q '^status=ok$' \
  || fail "the ratchet did not report status=ok — the fixture no longer demonstrates the defect"
printf '%s\n' "$RATCHET" | grep -q '^coverage=94.95$' \
  || fail "the fixture aggregate moved off 94.95 — recompute the numbers in the fixture README"
[ "$FAILED" -eq 0 ] && ok "94.95% against a 95.00% floor is inside the ratchet's own 0.1pp tolerance"

# --- 2. the number it cannot see ---------------------------------------------

# case | diff | report | expected measured/covered, hand-counted
CASES="
uncovered function added|$FIXTURE/changed.diff|4 0
one covered edit + the same function|$FIXTURE/partial.diff|6 2
documentation only|$FIXTURE/docs-only.diff|0 0
nothing changed at all|/dev/null|0 0
"

bold "2. Coverage of the CHANGED lines — two implementations, both report formats"
printf '    %-38s %-13s %-14s %-14s\n' 'case' 'report' 'coverage.py' 'diff-cover'
while IFS='|' read -r name diff expected; do
  [ -n "$name" ] || continue
  for report in lcov.info cobertura.xml; do
    got_proto="$(coverage_py "$FIXTURE/$report" "$diff")"
    if [ "$SKIP_DIFF_COVER" -eq 1 ]; then
      got_dc="(skipped)"
    elif ! got_dc="$(diffcover "$FIXTURE/$report" "$diff")"; then
      fail "diff-cover produced no answer for $name/$report — see above"
      got_dc="(failed)"
    fi
    shown_dc='(skipped)'
    [ "$SKIP_DIFF_COVER" -eq 1 ] || shown_dc="$(render "$got_dc")"
    printf '    %-38s %-13s %-14s %-14s\n' "$name" "$report" \
      "$(render "$got_proto")" "$shown_dc"

    [ "$got_proto" = "$expected" ] \
      || fail "coverage.py measured [$got_proto] on $name/$report, hand-count says [$expected]"
    if [ "$SKIP_DIFF_COVER" -eq 0 ] && [ "$got_dc" != "$expected" ]; then
      fail "diff-cover measured [$got_dc] on $name/$report, hand-count says [$expected]"
    fi
  done
done <<EOF
$CASES
EOF

printf '\n    Percentages above are rendered from each tool\x27s own line counts.\n'
printf "    diff-cover's own printed percentage truncates to a whole number:\n"
printf '    it prints 33%% where 2 of 6 lines are covered. Same measurement,\n'
printf '    coarser presentation — docs/EVAL-vs-diff-cover.md §3.\n'

bold "3. Verdict"
if [ "$FAILED" -eq 0 ]; then
  ok "aggregate ratchet ok · changed lines 0.00% · both implementations, both formats, the hand-count"
  printf '\n    The ratchet is green and four added lines are untested. That gap is\n'
  printf '    what a patch gate closes; docs/EVAL-vs-diff-cover.md records which\n'
  printf '    implementation gets to close it.\n'
else
  printf '\n\033[31mSomething disagreed.\033[0m The fixture is the evidence — fix the code,\n' >&2
  printf 'not the fixture. samples/coverage/patch/README.md holds the hand-count.\n' >&2
fi
exit "$FAILED"
