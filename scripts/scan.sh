#!/usr/bin/env bash
#
# maxi-quality — Layer 2 (cross-language umbrella) scan.
#
# Runs the same three tools locally that CI runs:
#   1. Semgrep      — this repo's rules in semgrep/
#   2. Gitleaks     — secrets in the working tree and history
#   3. OSV-Scanner  — known-vulnerable dependencies via lockfiles
#
# Usage:
#   scripts/scan.sh [TARGET_REPO] [options]
#
#   TARGET_REPO            Repo to scan. Default: the current git repo root.
#
#   --changed-only [REF]   New-code-only mode (concept §8): Semgrep reports only
#                          findings absent from REF, Gitleaks only scans commits
#                          since REF. Default REF: origin/main.
#   --json-out FILE        Also write Semgrep's JSON results to FILE. The pretty
#                          output is unchanged; this is the machine-readable
#                          copy the reporting workflow parses.
#   --sbom FILE            Write a CycloneDX 1.6 SBOM of every resolved
#                          dependency to FILE. Never gates — an inventory is not
#                          a finding.
#   --licenses LIST        Fail on any dependency whose license is not in this
#                          comma-separated SPDX allowlist. Off by default: a
#                          license policy is a per-repo decision, and a default
#                          allowlist would either gate nothing or gate wrongly.
#   --no-fail              Report everything, always exit 0. Use for the
#                          adoption week on an existing repo, then drop it.
#   --require-tools        Exit non-zero if any tool is unavailable, instead of
#                          warning and continuing. Use this in CI.
#   --skip TOOL            Skip semgrep|gitleaks|osv. Repeatable.
#   -h, --help             This text.
#
# Each tool is resolved as: native binary → uvx/docker fallback → skipped with a
# loud warning. Nothing is silently not-run.
#
# If TARGET_REPO holds a `.maxi-quality.yml`, it is read first and decides which
# Semgrep rules run, which are downgraded to warnings, and which paths are out of
# scope (see README). An unusable policy is fatal — exit 3, never a clean scan.
# Without one, nothing changes and no YAML parser is needed.
#
# Exit codes: 0 clean · 1 findings · 2 a tool was unavailable (--require-tools)
#             3 usage error

set -Eeuo pipefail

BASELINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- argument parsing --------------------------------------------------------
TARGET=""
CHANGED_ONLY=0
BASE_REF="origin/main"
NO_FAIL=0
JSON_OUT=""
SBOM_OUT=""
LICENSES=""
REQUIRE_TOOLS=0
SKIP_SEMGREP=0
SKIP_GITLEAKS=0
SKIP_OSV=0

die() { printf '\033[31merror:\033[0m %s\n' "$1" >&2; exit 3; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --changed-only)
      CHANGED_ONLY=1
      # An optional REF may follow, but not another flag.
      if [[ $# -gt 1 && "$2" != --* ]]; then BASE_REF="$2"; shift; fi
      ;;
    --json-out)
      [[ $# -gt 1 ]] || die "--json-out needs a file path"
      JSON_OUT="$2"; shift ;;
    --sbom)
      [[ $# -gt 1 ]] || die "--sbom needs a file path"
      SBOM_OUT="$2"; shift ;;
    --licenses)
      [[ $# -gt 1 ]] || die "--licenses needs an SPDX allowlist, e.g. MIT,Apache-2.0"
      LICENSES="$2"; shift ;;
    --no-fail)       NO_FAIL=1 ;;
    --require-tools) REQUIRE_TOOLS=1 ;;
    --skip)
      [[ $# -gt 1 ]] || die "--skip needs a tool name"
      case "$2" in
        semgrep)  SKIP_SEMGREP=1 ;;
        gitleaks) SKIP_GITLEAKS=1 ;;
        osv)      SKIP_OSV=1 ;;
        *) die "--skip expects semgrep|gitleaks|osv, got '$2'" ;;
      esac
      shift
      ;;
    -h|--help) sed -n '2,39p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) die "unknown option '$1'" ;;
    *)
      [[ -z "$TARGET" ]] || die "TARGET_REPO given twice ('$TARGET' and '$1')"
      TARGET="$1"
      ;;
  esac
  shift
done

if [[ -z "$TARGET" ]]; then
  TARGET="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
[[ -d "$TARGET" ]] || die "not a directory: $TARGET"
TARGET="$(cd "$TARGET" && pwd)"

# Scratch space for the resolved policy and semgrep's JSON. Both are internal —
# --json-out still writes wherever the caller asked, this is just where the run
# assembles them.
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

# --- output helpers ----------------------------------------------------------
bold() { printf '\033[1m%s\033[0m\n' "$1"; }
warn() { printf '\033[33mwarn:\033[0m %s\n' "$1" >&2; }
info() { printf '\033[36m›\033[0m %s\n' "$1"; }

FINDINGS=0        # a tool reported something
UNAVAILABLE=0     # a tool could not be run
declare -a SUMMARY=()

record() { SUMMARY+=("$1"); }

have() { command -v "$1" >/dev/null 2>&1; }

docker_ok() { have docker && docker info >/dev/null 2>&1; }

# Every summary line is `<label><pad><text>` with the label padded to 11. It was
# hand-aligned in eight places, which is a typo away from breaking the parser in
# actions/layer2 — that reads these lines with `s/^  NAME \{1,\}//p` and needs at
# least one space after the label.
record_status() { record "$(printf '%-11s%s' "$1" "$2")"; }

# --- tool resolution ---------------------------------------------------------
#
# ONE ladder, used by all three tools: native binary → uvx (where it applies) →
# docker → skipped with a loud warning. It was written out three times, and the
# three copies DID diverge: the docker branches set semgrep's working directory
# via `-w /repo` while the native branch did not `cd` at all, so
# `--baseline-commit` resolved against the wrong repository and `--changed-only`
# silently reported zero findings. A consumer adopting with the ratchet got a
# permanently green gate. Nothing compared the paths, because there was nothing
# that held them side by side.
#
#   resolve_tool <label> <binary> <uvx-pkg|-> <docker-image> <docker-entry|-> \
#                <install-hint> [extra docker run args...]
#
# On success sets RESOLVED_CMD (array), RESOLVED_ROOT (the path the tool should
# be pointed at) and RESOLVED_IS_DOCKER. Returns 1 when nothing is available,
# having already warned, recorded the SKIP and set UNAVAILABLE.
resolve_tool() {
  local label="$1" bin="$2" uvx_pkg="$3" image="$4" entry="$5" hint="$6"
  shift 6
  local -a docker_extra=("$@")

  RESOLVED_CMD=(); RESOLVED_ROOT=""; RESOLVED_IS_DOCKER=0

  if have "$bin"; then
    RESOLVED_CMD=("$bin")
    RESOLVED_ROOT="$TARGET"
    return 0
  fi

  if [[ "$uvx_pkg" != "-" ]] && have uvx; then
    info "$bin not installed; running via uvx"
    RESOLVED_CMD=(uvx "$uvx_pkg")
    RESOLVED_ROOT="$TARGET"
    return 0
  fi

  if docker_ok; then
    info "$bin not installed; running via docker"
    RESOLVED_CMD=(docker run --rm ${docker_extra[@]+"${docker_extra[@]}"}
                  -v "$TARGET:/repo" -w /repo "$image")
    # An `if`, not `[[ ... ]] && RESOLVED_CMD+=(...)`.
    #
    # The real rule, measured rather than assumed: under `set -e` a false
    # `[[ ]] && cmd` does NOT abort mid-script — execution continues. It bites
    # in exactly two places: as the last statement of a script (the script exits
    # 1, which fails a CI step) and as the last statement of a FUNCTION (the
    # function returns 1). The second is what would bite here — a tool with no
    # docker entrypoint would make resolve_tool return 1 and be reported as
    # unavailable — if a later edit ever moved this line to the end.
    if [[ "$entry" != "-" ]]; then
      RESOLVED_CMD+=("$entry")
    fi
    RESOLVED_ROOT="/repo"
    RESOLVED_IS_DOCKER=1
    return 0
  fi

  warn "SKIPPED $bin — $hint"
  record_status "$label" "SKIPPED"
  UNAVAILABLE=1
  return 1
}

# The clean/FINDINGS half was also written out per tool. osv keeps its own
# three-way version because 128 ("no lockfiles") is neither.
record_result() {
  local label="$1" rc="$2"
  if (( rc == 0 )); then
    record_status "$label" "clean"
  else
    record_status "$label" "FINDINGS (exit $rc)"
    FINDINGS=1
  fi
}

# --- 1. Semgrep --------------------------------------------------------------
POLICY_JSON=""   # set by run_semgrep, read by _semgrep_exec

run_semgrep() {
  # semgrep is the one tool with a uvx fallback, and the one that needs a second
  # mount: the RULES live in $BASELINE, which is not inside the scanned repo.
  resolve_tool semgrep semgrep semgrep returntocorp/semgrep:latest semgrep \
    "install it (\`brew install semgrep\`), or provide uvx or docker" \
    -v "$BASELINE:/baseline:ro" || return 0

  # Native/uvx read the rules from the host path and scan "." — NOT "$TARGET" —
  # because _semgrep_exec runs from inside $TARGET. Docker sees them at the
  # mount point and scans /repo. This is the one place the two genuinely differ.
  #
  # It is also why the policy resolver is told BOTH paths. Semgrep derives a
  # rule's check_id prefix from the --config path exactly as written, so
  # `--exclude-rule` needs a different string on each of these two paths for the
  # very same rule. scripts/policy.py computes it and then proves it worked.
  local baseline_path="$BASELINE" path="."
  if (( RESOLVED_IS_DOCKER )); then
    baseline_path=/baseline
    path=/repo
  fi

  # The consumer's policy is resolved BEFORE anything is scanned, and a bad one
  # is fatal. A policy error is a usage error, not a finding: it must never be
  # reported as a clean scan, and it must not be recoverable into "carry on with
  # the defaults" — that would apply a policy the consumer did not write.
  POLICY_JSON="$WORKDIR/policy.json"
  python3 "$BASELINE/scripts/policy.py" resolve \
    --target "$TARGET" --baseline "$BASELINE" \
    --baseline-path "$baseline_path" --out "$POLICY_JSON" \
    || die "the policy in $TARGET/.maxi-quality.yml is not usable (see above)"

  local -a cfg=()
  local line
  while IFS= read -r line; do
    cfg+=("$line")
  done < <(python3 "$BASELINE/scripts/policy.py" args \
             --resolved "$POLICY_JSON" \
             --baseline-path "$baseline_path" --target-path "$path")

  _semgrep_exec "${RESOLVED_CMD[@]}" ${cfg[@]+"${cfg[@]}"} "$path"
}

_semgrep_exec() {
  local -a extra=()
  if (( CHANGED_ONLY )); then
    extra+=(--baseline-commit "$BASE_REF")
    info "semgrep: new-code-only against $BASE_REF"
  fi

  # THE RESULTS ARE ALWAYS WRITTEN AS JSON, and the verdict always comes from
  # them — not from semgrep's exit code.
  #
  # `--error` can only say "something matched". It cannot express "something
  # matched a rule this repo downgraded to a warning", so a policy with a `warn`
  # list is unrepresentable in an exit code. Reading the JSON is also the rule
  # this repo already arrived at the hard way: semgrep prints a rule id once per
  # file and lists further matches beneath it, so counting the human-readable
  # output undercounts (docs/STATUS.md §5). One path, for every repo, policy or
  # not — the alternative was a second code path that only consumers with a
  # policy file ever exercised.
  #
  # --json-output writes a COPY; stdout stays the human-readable log someone
  # reads when a gate fails, which is what the ratchet fixtures grep.
  local json_host="$WORKDIR/semgrep.json" json_arg staged=""
  json_arg="$json_host"
  if (( RESOLVED_IS_DOCKER )); then
    # The container can only write inside the mount, so stage it there and move
    # it back — the same trick the SBOM needs, for the same reason. Before this,
    # --json-out under docker wrote to a path inside the container and the file
    # simply never appeared on the host.
    staged="$TARGET/.maxi-quality-semgrep.json"
    json_arg="/repo/.maxi-quality-semgrep.json"
  fi
  extra+=(--json-output="$json_arg")

  local rc=0
  # THE `cd` IS LOAD-BEARING, and its absence was a silent no-op gate.
  #
  # `--baseline-commit` resolves the ref against the git repo of semgrep's
  # WORKING DIRECTORY, not against the paths being scanned. Running from
  # anywhere else diffed the WRONG repository's history and then reported zero
  # findings — while still printing "Scan was limited to files changed since
  # baseline commit", so it looked like a working ratchet.
  #
  # Consequence, before the fix: `--changed-only` silently found nothing. A
  # consumer adopting with the ratchet got a permanently green gate. Caught by
  # planting a new violation and watching it NOT fire, while a full scan counted
  # it (68 -> 69).
  #
  # The docker branches already got this right via `-w /repo`, which is why only
  # the native/uvx path was affected — and why the bug survived: the two paths
  # disagreed and nothing compared them.
  #
  # No `--error`: findings are classified from the JSON below, so semgrep's own
  # exit code is reserved for semgrep FAILING — a config that would not load, a
  # target that does not exist. Those must not be reported as findings.
  # ${a[@]+"${a[@]}"} is the bash 3.2 (macOS system bash) safe way to expand a
  # possibly-empty array under `set -u`.
  ( cd "$TARGET" && "$@" --metrics=off --disable-version-check ${extra[@]+"${extra[@]}"} ) || rc=$?

  if [[ -n "$staged" && -f "$staged" ]]; then
    mv "$staged" "$json_host"
  fi

  if (( rc != 0 )); then
    # semgrep itself failed. Not a finding, and emphatically not a pass.
    record_status semgrep "ERROR (semgrep exit $rc)"
    FINDINGS=1
    return 0
  fi

  # The caller's copy, if they asked for one. Written from the file the verdict
  # was actually computed from, so a report can never disagree with the gate.
  if [[ -n "$JSON_OUT" ]]; then
    mkdir -p "$(dirname "$JSON_OUT")"
    cp "$json_host" "$JSON_OUT"
  fi

  local crc=0
  python3 "$BASELINE/scripts/policy.py" classify \
    --resolved "$POLICY_JSON" --results "$json_host" || crc=$?
  case "$crc" in
    0) record_status semgrep "clean" ;;
    1) record_status semgrep "FINDINGS"; FINDINGS=1 ;;
    # Exit 2 is a broken mechanism: unreadable results, a semgrep whose
    # `.errors` is non-empty, or a disabled rule that was not actually
    # disabled. Each one means the verdict is unknown, and an unknown verdict
    # is a failure here rather than a pass.
    *) record_status semgrep "ERROR (policy exit $crc)"; FINDINGS=1 ;;
  esac
  return 0
}

# --- 2. Gitleaks -------------------------------------------------------------
run_gitleaks() {
  resolve_tool gitleaks gitleaks - ghcr.io/gitleaks/gitleaks:latest - \
    "install it (\`brew install gitleaks\`) or start docker" || return 0
  local root="$RESOLVED_ROOT"

  local -a extra=()
  # Honour a repo-local gitleaks config if the target has one.
  if [[ -f "$TARGET/.gitleaks.toml" ]]; then
    extra+=(--config "$root/.gitleaks.toml")
  elif [[ -f "$TARGET/gitleaks.toml" ]]; then
    extra+=(--config "$root/gitleaks.toml")
  fi

  # Decide history-vs-worktree scan FIRST, so --log-opts is only ever added on
  # the path where it is meaningful.
  local subcmd="git"
  if ! git -C "$TARGET" rev-parse HEAD >/dev/null 2>&1; then
    warn "gitleaks: no commits found; scanning the working tree instead of history"
    subcmd="dir"
  elif (( CHANGED_ONLY )); then
    if git -C "$TARGET" rev-parse --verify --quiet "$BASE_REF" >/dev/null; then
      extra+=(--log-opts "$BASE_REF..HEAD")
      info "gitleaks: commits since $BASE_REF only"
    else
      warn "gitleaks: ref '$BASE_REF' not found; scanning full history instead"
    fi
  fi

  local rc=0
  "${RESOLVED_CMD[@]}" "$subcmd" "$root" --no-banner --redact ${extra[@]+"${extra[@]}"} || rc=$?
  record_result gitleaks "$rc"
  return 0
}

# --- 3. OSV-Scanner ----------------------------------------------------------
run_osv() {
  resolve_tool osv osv-scanner - ghcr.io/google/osv-scanner:latest - \
    "install it (\`brew install osv-scanner\`) or start docker" || return 0
  local root="$RESOLVED_ROOT"

  # OSV has no changed-only mode: a vulnerable dependency is vulnerable
  # regardless of which commit introduced it.
  local rc=0
  "${RESOLVED_CMD[@]}" scan source --recursive "$root" || rc=$?
  # osv keeps its own three-way result: 128 means "no lockfiles found", which
  # is neither clean nor a finding, so record_result would mislabel it.
  case "$rc" in
    0)   record_status osv "clean" ;;
    128) record_status osv "no lockfiles found"; warn "osv-scanner found nothing to scan" ;;
    *)   record_status osv "FINDINGS (exit $rc)"; FINDINGS=1 ;;
  esac

  # --- licenses and SBOM, both optional, both separate osv invocations -------
  #
  # Separate on purpose. Folding --licenses into the vulnerability run above
  # would work and would save a round trip, but the two would then share one
  # exit code — and "the gate went red" would no longer distinguish "you shipped
  # a CVE" from "a transitive dep is BSD-2 and your allowlist says MIT". Those
  # need different people and different fixes.
  if [[ -n "$LICENSES" ]]; then
    bold "── Licenses ──"
    local lrc=0
    "${RESOLVED_CMD[@]}" scan source --recursive --licenses="$LICENSES" "$root" || lrc=$?
    case "$lrc" in
      0)   record_status licenses "clean (allowlist: $LICENSES)" ;;
      128) record_status licenses "no lockfiles found" ;;
      *)   record_status licenses "VIOLATIONS (exit $lrc)"; FINDINGS=1 ;;
    esac
    echo
  fi

  if [[ -n "$SBOM_OUT" ]]; then
    bold "── SBOM ──"
    # --all-packages is load-bearing: without it the CycloneDX output contains
    # only the packages that appear in the RESULTS, so a clean repo produces an
    # empty SBOM. An inventory that shrinks when things get better is not an
    # inventory. (Measured: 28 components vs the real 94.)
    # osv-scanner will not create the output directory and exits 127 when it is
    # missing — a failure mode that reads as "the tool is broken" rather than
    # "make the folder". Measured; do not remove this line.
    mkdir -p "$(dirname "$SBOM_OUT")"
    local out="$SBOM_OUT"
    local staged=""
    if (( RESOLVED_IS_DOCKER )); then
      # The container only sees $TARGET as /repo, so write inside it and move.
      staged="$TARGET/.maxi-quality-sbom.json"
      out="/repo/.maxi-quality-sbom.json"
    fi
    # Bare `--licenses` (no `=allowlist`) is REPORT-ONLY: it resolves each
    # package's license and exits 0 regardless. Without it every component comes
    # back with `"licenses": []` — the key is present and empty, which is how
    # this was nearly shipped as "104 components, all UNKNOWN". An SBOM without
    # licence data is the half of the artifact nobody needs.
    local src=0
    "${RESOLVED_CMD[@]}" scan source --recursive --all-packages --licenses \
      --format=cyclonedx-1-6 --output-file="$out" "$root" >/dev/null 2>&1 || src=$?
    if [[ -n "$staged" && -f "$staged" ]]; then
      mkdir -p "$(dirname "$SBOM_OUT")"
      mv "$staged" "$SBOM_OUT"
    fi
    if [[ -f "$SBOM_OUT" ]]; then
      local n
      n=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("components",[])))' \
            "$SBOM_OUT" 2>/dev/null || echo '?')
      record_status sbom "$n components -> $SBOM_OUT"
      info "SBOM written to $SBOM_OUT ($n components)"
    else
      # Never a gate failure: an SBOM is an artifact, not a finding. But it must
      # not be silently absent either — the report reads this file.
      record_status sbom "NOT WRITTEN (osv exit $src)"
      warn "SBOM was requested but osv-scanner produced no file (exit $src)"
    fi
    echo
  fi
  return 0
}

# --- run ---------------------------------------------------------------------
bold "maxi-quality Layer 2 scan"
info "baseline: $BASELINE"
info "target:   $TARGET"
echo

if (( ! SKIP_SEMGREP )); then bold "── Semgrep ──"; run_semgrep; echo
else record_status semgrep "skipped (--skip)"; fi

if (( ! SKIP_GITLEAKS )); then bold "── Gitleaks ──"; run_gitleaks; echo
else record_status gitleaks "skipped (--skip)"; fi

if (( ! SKIP_OSV )); then bold "── OSV-Scanner ──"; run_osv; echo
else record_status osv "skipped (--skip)"; fi

# --- summary -----------------------------------------------------------------
bold "── Summary ──"
for line in ${SUMMARY[@]+"${SUMMARY[@]}"}; do printf '  %s\n' "$line"; done
echo

if (( UNAVAILABLE && REQUIRE_TOOLS )); then
  printf '\033[31mFAIL\033[0m — a tool was unavailable and --require-tools was set\n'
  exit 2
fi
if (( FINDINGS )); then
  if (( NO_FAIL )); then
    printf '\033[33mFINDINGS\033[0m — exiting 0 because --no-fail was set\n'
    exit 0
  fi
  printf '\033[31mFAIL\033[0m — Layer 2 findings above\n'
  exit 1
fi
if (( UNAVAILABLE )); then
  printf '\033[33mPASS (partial)\033[0m — some tools were skipped; see warnings above\n'
  exit 0
fi
printf '\033[32mPASS\033[0m — Semgrep, Gitleaks and OSV-Scanner all clean\n'
