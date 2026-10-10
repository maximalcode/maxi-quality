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
#   --scope-out FILE       Write the versioned Layer 2 scope artifact for this
#                          run. It is finalized on ordinary early exits too.
#   --licenses LIST        Fail on any dependency whose license is not in this
#                          comma-separated SPDX allowlist. Off by default: a
#                          license policy is a per-repo decision, and a default
#                          allowlist would either gate nothing or gate wrongly.
#   --annotate             Emit GitHub workflow commands so Semgrep findings
#                          render on the pull-request diff instead of only in
#                          the job log. Additive: it cannot change the exit
#                          code. No effect outside GitHub Actions.
#   --max-annotations N    Cap the annotations (default 50). The omitted count
#                          is always reported — GitHub drops them past a limit
#                          it does not document, and a silent truncation reads
#                          as "that was all of them".
#   --annotate-prefix P    Prepended to annotated paths. Needed when the target
#                          is a subdirectory of the workspace.
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

# THE THIRD PLACE SEMGREP IS PINNED, and until #43 it was not pinned at all.
#
# actions/layer2/action.yml pins it for consumers and ci.yml pins it for this
# repo's own manifest job; check-pins.sh has asserted those two agree since #13,
# because a drift there means CI validates the finding counts against a
# different semgrep than consumers are handed. The local path had neither: the
# uvx fallback ran a bare `uvx semgrep` and the docker fallback ran `:latest`.
#
# That is not theoretical. It is why the C# 12 parse failure in #43 was
# irreproducible — "the same file scanned clean earlier in the same session",
# because two runs minutes apart could resolve two different semgreps. A local
# scan that disagrees with CI is worse than no local scan; people trust it.
#
# check-pins.sh now asserts all THREE agree. Bump them together or it fails.
SEMGREP_PIN="1.172.0"

# AND THE INTERPRETER IS PINNED WITH IT. A bare `uvx semgrep==<pin>` resolves an
# interpreter from the host, which is the same undeclared ambient dependency
# that made CI unable to install this pin at all on a stock macOS runner (#131,
# scripts/install-semgrep.sh). uv fetches this version rather than hoping the
# machine has it, so a local scan and CI agree on the interpreter as well as on
# the tool. Same 3.12 install-semgrep.sh uses — bump them together.
UVX_PYTHON="3.12"

# --- argument parsing --------------------------------------------------------
TARGET=""
CHANGED_ONLY=0
BASE_REF="origin/main"
NO_FAIL=0
ANNOTATE=0
MAX_ANNOTATIONS=50
ANNOTATE_PREFIX=""
JSON_OUT=""
SBOM_OUT=""
SCOPE_OUT=""
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
    --scope-out)
      [[ $# -gt 1 ]] || die "--scope-out needs a file path"
      SCOPE_OUT="$2"; shift ;;
    --licenses)
      [[ $# -gt 1 ]] || die "--licenses needs an SPDX allowlist, e.g. MIT,Apache-2.0"
      LICENSES="$2"; shift ;;
    --annotate)      ANNOTATE=1 ;;
    --max-annotations)
      [[ $# -gt 1 ]] || die "--max-annotations needs a number"
      [[ "$2" =~ ^[0-9]+$ ]] || die "--max-annotations expects a non-negative integer, got '$2'"
      MAX_ANNOTATIONS="$2"; shift ;;
    --annotate-prefix)
      [[ $# -gt 1 ]] || die "--annotate-prefix needs a path prefix"
      ANNOTATE_PREFIX="$2"; shift ;;
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
    # The header above IS the help text, not a hand-maintained copy of it. The
    # range runs to the exit-code block; keep it in step when the header grows.
    -h|--help) sed -n '2,54p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

# Scope collection is deliberately additive. The scan's exit code is captured
# before finalization and returned unchanged even when the evidence writer has
# a filesystem or JSON problem.
SCOPE_LOG="$WORKDIR/scan.log"
scope_record() {
  [[ -n "$SCOPE_OUT" ]] || return 0
  python3 "$BASELINE/scripts/layer2_scope.py" record \
    --out "$SCOPE_OUT" "$@" || warn "scope record failed for ${1:-tool}"
}
scope_capture_issue() {
  [[ -n "$SCOPE_OUT" ]] || return 0
  python3 "$BASELINE/scripts/layer2_scope.py" diagnostic \
    --out "$SCOPE_OUT" --section collection --stream combined \
    --source "$1" --log "$2" || warn "scope capture diagnostic failed"
}
scope_finish() {
  local rc=$?
  if [[ -n "$SCOPE_OUT" && -f "$SCOPE_OUT" ]]; then
    local outcome=success
    if (( rc != 0 )); then
      outcome=failure
    elif (( FINDINGS )); then
      outcome=failure
    elif (( UNAVAILABLE )); then
      outcome=unknown
    fi
    local -a finish_args=(--out "$SCOPE_OUT" --analysis-outcome "$outcome" \
      --analysis-exit-code "$rc" --collection-status complete)
    [[ -f "$SCOPE_LOG" ]] && finish_args+=(--log "$SCOPE_LOG")
    python3 "$BASELINE/scripts/layer2_scope.py" finalize \
      "${finish_args[@]}" || warn "scope finalization failed"
  fi
  rm -rf "$WORKDIR"
  return "$rc"
}
trap scope_finish EXIT

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

if [[ -n "$SCOPE_OUT" ]]; then
  scope_mode=full
  [[ "$CHANGED_ONLY" == 1 ]] && scope_mode=changed-only
  scope_commit="$(git -C "$TARGET" rev-parse HEAD 2>/dev/null || echo unknown)"
  scope_ref="$(git -C "$TARGET" symbolic-ref --quiet --short HEAD 2>/dev/null || git -C "$TARGET" describe --tags --exact-match 2>/dev/null || echo unknown)"
  scope_baseline=()
  (( CHANGED_ONLY )) && scope_baseline=(--baseline-ref "$BASE_REF")
  python3 "$BASELINE/scripts/layer2_scope.py" init \
    --out "$SCOPE_OUT" \
    --producer "${LAYER2_PRODUCER:-gate}" \
    --workflow "${GITHUB_WORKFLOW:-local}" \
    --invocation-id "${LAYER2_INVOCATION_ID:-${GITHUB_RUN_ID:-local}}" \
    --run-id "${GITHUB_RUN_ID:-local}" \
    --run-attempt "${GITHUB_RUN_ATTEMPT:-1}" \
    --job "${GITHUB_JOB:-layer2}" \
    --fragment-id "${LAYER2_FRAGMENT_ID:-${LAYER2_PRODUCER:-gate}:${GITHUB_ACTION:-layer2}:${TARGET}}" \
    --commit "$scope_commit" --ref "$scope_ref" --mode "$scope_mode" \
    ${scope_baseline[@]+"${scope_baseline[@]}"} \
    --licenses-requested "$([[ -n "$LICENSES" ]] && echo true || echo false)" \
    --sbom-requested "$([[ -n "$SBOM_OUT" ]] && echo true || echo false)" \
    || warn "scope initialization failed"
fi

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
    info "$bin not installed; running via uvx on Python $UVX_PYTHON"
    RESOLVED_CMD=(uvx --python "$UVX_PYTHON" "$uvx_pkg")
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
  resolve_tool semgrep semgrep "semgrep==$SEMGREP_PIN" \
    "returntocorp/semgrep:$SEMGREP_PIN" semgrep \
    "install it (\`brew install semgrep\`), or provide uvx or docker" \
    -v "$BASELINE:/baseline:ro" || {
      scope_record --tool semgrep --state skipped --outcome unknown --reason-code unavailable \
        --reason "Semgrep binary unavailable" --exit-code 127
      return 0
    }

  # The uvx and docker paths are pinned above. A NATIVE binary on PATH is
  # whatever the machine has, and that cannot be fixed from here — but it can
  # stop being silent. Warn rather than fail: refusing to run because someone's
  # brew is one patch ahead would just get the script abandoned.
  if [[ "${RESOLVED_CMD[0]}" == "semgrep" ]]; then
    local have_ver
    have_ver="$(semgrep --version 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ -n "$have_ver" && "$have_ver" != "$SEMGREP_PIN" ]]; then
      warn "semgrep $have_ver is on PATH but this baseline is pinned to $SEMGREP_PIN."
      warn "findings and PARSE ERRORS can both differ between versions — if a result"
      warn "here disagrees with CI, this is the first thing to check."
    fi
  fi

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
  local policy_log="$WORKDIR/policy.log"
  if ! python3 "$BASELINE/scripts/policy.py" resolve \
    --target "$TARGET" --baseline "$BASELINE" \
    --baseline-path "$baseline_path" --out "$POLICY_JSON" \
    2>"$policy_log"; then
    scope_record --tool semgrep --state skipped --outcome failure --reason-code blocked \
      --reason "policy setup failed" --exit-code 3 --log "$policy_log"
    # The resolver's complete diagnostic was captured before the scope record
    # so the temporary file can be removed safely on EXIT. Replay it here to
    # preserve the existing CLI error contract for callers without --scope-out.
    if [[ -s "$policy_log" ]]; then
      cat "$policy_log" >&2
    fi
    die "the policy in $TARGET/.maxi-quality.yml is not usable (see above)"
  fi

  local -a cfg=()
  local line
  while IFS= read -r line; do
    cfg+=("$line")
  done < <(python3 "$BASELINE/scripts/policy.py" args \
             --resolved "$POLICY_JSON" \
             --baseline-path "$baseline_path" --target-path "$path")

  _semgrep_exec "${RESOLVED_CMD[@]}" ${cfg[@]+"${cfg[@]}"} "$path"
}

scope_measure_semgrep() {
  [[ -n "$SCOPE_OUT" ]] || return 0
  local mode=full baseline=()
  if (( CHANGED_ONLY )); then
    mode=changed-only
    baseline=(--baseline-ref "$BASE_REF")
  fi
  python3 "$BASELINE/scripts/layer2_scope.py" measure-semgrep \
    --out "$SCOPE_OUT" --results "$WORKDIR/semgrep.json" \
    --scan-root "$TARGET" --scanner-root "${RESOLVED_ROOT:-$TARGET}" \
    --baseline-root "$BASELINE" \
    --policy "$POLICY_JSON" --mode "$mode" \
    ${baseline[@]+"${baseline[@]}"} || warn "Semgrep measurement failed"
}

_semgrep_exec() {
  local -a extra=()
  if (( CHANGED_ONLY )); then
    extra+=(--baseline-commit "$BASE_REF")
    info "semgrep: new-code-only against $BASE_REF"
  fi

  # Semgrep only serializes whole-target skip evidence in verbose mode. This
  # does not alter findings or target selection; it makes the scanner's own
  # policy attribution available to the scope artifact.
  extra+=(--verbose)

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

  local rc=0 semgrep_log="$WORKDIR/semgrep.log"
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
  set +e
  ( cd "$TARGET" && "$@" --metrics=off --disable-version-check ${extra[@]+"${extra[@]}"} ) 2>&1 | \
    (tee "$semgrep_log" || { capture_rc=$?; cat; exit "$capture_rc"; })
  local -a semgrep_status=("${PIPESTATUS[@]}")
  set -e
  rc=${semgrep_status[0]:-1}
  if (( ${semgrep_status[1]:-0} != 0 )); then
    scope_capture_issue "semgrep diagnostic capture incomplete (tee exit ${semgrep_status[1]})" "$semgrep_log"
  fi

  if [[ -n "$staged" && -f "$staged" ]]; then
    mv "$staged" "$json_host"
  fi

  local -a result_issue=()
  if [[ ! -s "$json_host" ]]; then
    result_issue=(--collection-issue "Semgrep result JSON missing")
  elif ! python3 - "$json_host" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as fh:
    json.load(fh)
PY
  then
    result_issue=(--collection-issue "Semgrep result JSON malformed")
  fi

  if (( rc != 0 )); then
    # semgrep itself failed. Not a finding, and emphatically not a pass.
    record_status semgrep "ERROR (semgrep exit $rc)"
    FINDINGS=1
    scope_record --tool semgrep --state run --outcome failure \
      --reason "Semgrep exited before producing a usable result" --exit-code "$rc" \
      --mode "$([[ "$CHANGED_ONLY" == 1 ]] && echo changed-only || echo full)" \
      --baseline-ref "$([[ "$CHANGED_ONLY" == 1 ]] && echo "$BASE_REF" || true)" \
      --log "$semgrep_log" --log "$json_host" --effective-json "$POLICY_JSON" \
      ${result_issue[@]+"${result_issue[@]}"}
    scope_measure_semgrep
    return 0
  fi

  # The caller's copy, if they asked for one. Written from the file the verdict
  # was actually computed from, so a report can never disagree with the gate.
  if [[ -n "$JSON_OUT" ]]; then
    mkdir -p "$(dirname "$JSON_OUT")"
    cp "$json_host" "$JSON_OUT"
  fi

  # classify's stdout is teed rather than left to flow, because the summary
  # needs one number out of it. Deriving that number a second time from the
  # JSON is how the docker and native paths came to disagree about
  # --changed-only: two computations of the same thing, one of them wrong.
  # Under `set -o pipefail` the pipeline reports python's exit code, not tee's.
  local -a cls_extra=()
  if (( ANNOTATE )); then
    cls_extra+=(--annotate --max-annotations "$MAX_ANNOTATIONS")
    if [[ -n "$ANNOTATE_PREFIX" ]]; then
      cls_extra+=(--annotate-prefix "$ANNOTATE_PREFIX")
    fi
  fi

  local crc=0 classify_out="$WORKDIR/classify.out"
  python3 "$BASELINE/scripts/policy.py" classify \
    --resolved "$POLICY_JSON" --results "$json_host" \
    ${cls_extra[@]+"${cls_extra[@]}"} | tee "$classify_out" || crc=$?

  # Files semgrep could not parse. NOT a finding and NOT a failure (#43) — but
  # it belongs on the summary line, because a scan that skipped nine files is
  # not the same clean as a scan that read all of them.
  local unparsed suffix=""
  unparsed=$(sed -n 's/^semgrep_unparsed=//p' "$classify_out" | tail -1)
  [[ -n "$unparsed" ]] || unparsed=0
  if (( unparsed > 0 )); then
    suffix=" ($unparsed file(s) UNPARSED)"
  fi

  case "$crc" in
    0)
      record_status semgrep "clean$suffix"
      scope_record --tool semgrep --state run --outcome success \
        --reason "Semgrep completed" --exit-code 0 \
        --mode "$([[ "$CHANGED_ONLY" == 1 ]] && echo changed-only || echo full)" \
        --baseline-ref "$([[ "$CHANGED_ONLY" == 1 ]] && echo "$BASE_REF" || true)" \
        --log "$semgrep_log" --log "$json_host" --effective-json "$POLICY_JSON" \
        ${result_issue[@]+"${result_issue[@]}"}
      scope_measure_semgrep
      ;;
    1)
      record_status semgrep "FINDINGS$suffix"; FINDINGS=1
      scope_record --tool semgrep --state run --outcome failure \
        --reason "Semgrep completed with findings" --exit-code 1 \
        --mode "$([[ "$CHANGED_ONLY" == 1 ]] && echo changed-only || echo full)" \
        --baseline-ref "$([[ "$CHANGED_ONLY" == 1 ]] && echo "$BASE_REF" || true)" \
        --log "$semgrep_log" --log "$json_host" --effective-json "$POLICY_JSON" \
        ${result_issue[@]+"${result_issue[@]}"}
      scope_measure_semgrep
      ;;
    # Exit 2 is a broken mechanism: unreadable results, a semgrep error that is
    # not a per-file parse failure, every file unparseable, or a disabled rule
    # that was not actually disabled. Each one means the verdict is unknown,
    # and an unknown verdict is a failure here rather than a pass.
    *)
      record_status semgrep "ERROR (policy exit $crc)"; FINDINGS=1
      scope_record --tool semgrep --state run --outcome failure \
        --reason "Semgrep result classification failed" --exit-code "$crc" \
        --mode "$([[ "$CHANGED_ONLY" == 1 ]] && echo changed-only || echo full)" \
        --baseline-ref "$([[ "$CHANGED_ONLY" == 1 ]] && echo "$BASE_REF" || true)" \
        --log "$semgrep_log" --log "$json_host" --effective-json "$POLICY_JSON" \
        ${result_issue[@]+"${result_issue[@]}"}
      scope_measure_semgrep
      ;;
  esac
  return 0
}

# --- 2. Gitleaks -------------------------------------------------------------
run_gitleaks() {
  resolve_tool gitleaks gitleaks - ghcr.io/gitleaks/gitleaks:latest - \
    "install it (\`brew install gitleaks\`) or start docker" || {
      scope_record --tool gitleaks --state skipped --outcome unknown --reason-code unavailable \
        --reason "Gitleaks binary unavailable" --exit-code 127
      return 0
    }
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
  local history_mode="history" fallback=""
  if ! git -C "$TARGET" rev-parse HEAD >/dev/null 2>&1; then
    warn "gitleaks: no commits found; scanning the working tree instead of history"
    subcmd="dir"
    history_mode="worktree"
    fallback="no commits; history unavailable"
  elif (( CHANGED_ONLY )); then
    if git -C "$TARGET" rev-parse --verify --quiet "$BASE_REF" >/dev/null; then
      extra+=(--log-opts "$BASE_REF..HEAD")
      info "gitleaks: commits since $BASE_REF only"
    else
      warn "gitleaks: ref '$BASE_REF' not found; scanning full history instead"
      fallback="baseline '$BASE_REF' unavailable; full history fallback"
    fi
  fi

  local gitleaks_version=""
  gitleaks_version="$("${RESOLVED_CMD[@]}" --version 2>/dev/null || true)"
  gitleaks_version="${gitleaks_version%%$'\n'*}"
  [[ -n "$gitleaks_version" ]] || gitleaks_version="unknown"
  local gitleaks_effective="$WORKDIR/gitleaks-effective.json"
  local -a gitleaks_metadata_issue=()
  if ! python3 - "$gitleaks_effective" "$gitleaks_version" "$history_mode" "$fallback" "${TARGET}/.gitleaks.toml" "${TARGET}/gitleaks.toml" <<'PY'
import hashlib
import json
import pathlib
import sys

out, version, mode, fallback, *config_paths = sys.argv[1:]
config = None
unknown_sources = ["gitleaks environment/global/ignore configuration"]
for raw in config_paths:
    path = pathlib.Path(raw)
    try:
        if path.is_file():
            config = hashlib.sha256(path.read_bytes()).hexdigest()
            break
    except OSError:
        unknown_sources.append(f"unreadable configuration: {path}")
if version == "unknown":
    unknown_sources.append("gitleaks version")
payload = {"tool": "gitleaks", "version": version, "mode": mode,
           "fallback": fallback or "none", "config_fingerprint": config or "none",
           "unknown_sources": unknown_sources}
payload["comparison"] = {"status": "incomplete", "reason": "gitleaks global and environment configuration is not observable"}
payload["content_fingerprint"] = hashlib.sha256(
    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
json.dump(payload, open(out, "w", encoding="utf-8"), sort_keys=True)
PY
  then
    warn "gitleaks effective metadata unavailable; scope comparison is incomplete"
    rm -f "$gitleaks_effective"
    gitleaks_effective=""
    gitleaks_metadata_issue=(--collection-issue "effective metadata unavailable for gitleaks")
  fi
  local -a gitleaks_effective_arg=()
  [[ -n "$gitleaks_effective" ]] && gitleaks_effective_arg=(--effective-json "$gitleaks_effective")

  local rc=0 gitleaks_log="$WORKDIR/gitleaks.log"
  set +e
  "${RESOLVED_CMD[@]}" "$subcmd" "$root" --no-banner --redact ${extra[@]+"${extra[@]}"} \
    2>&1 | (tee "$gitleaks_log" || { capture_rc=$?; cat; exit "$capture_rc"; })
  local -a gitleaks_status=("${PIPESTATUS[@]}")
  set -e
  rc=${gitleaks_status[0]:-1}
  if (( ${gitleaks_status[1]:-0} != 0 )); then
    scope_capture_issue "gitleaks diagnostic capture incomplete (tee exit ${gitleaks_status[1]})" "$gitleaks_log"
  fi
  record_result gitleaks "$rc"
  if (( rc == 0 )); then
    scope_record --tool gitleaks --state run --outcome success \
      --reason "Gitleaks completed" --exit-code 0 --mode "$history_mode" \
      --baseline-ref "$([[ "$CHANGED_ONLY" == 1 ]] && echo "$BASE_REF" || true)" \
      --fallback "$fallback" --log "$gitleaks_log" \
      ${gitleaks_effective_arg[@]+"${gitleaks_effective_arg[@]}"} \
      ${gitleaks_metadata_issue[@]+"${gitleaks_metadata_issue[@]}"}
  else
    scope_record --tool gitleaks --state run --outcome failure \
      --reason "Gitleaks exited with an error or findings" --exit-code "$rc" \
      --mode "$history_mode" \
      --baseline-ref "$([[ "$CHANGED_ONLY" == 1 ]] && echo "$BASE_REF" || true)" \
      --fallback "$fallback" --log "$gitleaks_log" \
      ${gitleaks_effective_arg[@]+"${gitleaks_effective_arg[@]}"} \
      ${gitleaks_metadata_issue[@]+"${gitleaks_metadata_issue[@]}"}
  fi
  return 0
}

# --- 3. OSV-Scanner ----------------------------------------------------------
run_osv() {
  resolve_tool osv osv-scanner - ghcr.io/google/osv-scanner:latest - \
    "install it (\`brew install osv-scanner\`) or start docker" || {
      scope_record --tool osv --state skipped --outcome unknown --reason-code unavailable \
        --reason "OSV-Scanner binary unavailable" --exit-code 127
      [[ -n "$LICENSES" ]] && scope_record --tool licenses --state skipped --outcome unknown --reason-code blocked \
        --reason "OSV-Scanner unavailable before license invocation" --exit-code 127
      [[ -n "$SBOM_OUT" ]] && scope_record --tool sbom --state skipped --outcome unknown --reason-code blocked \
        --reason "OSV-Scanner unavailable before SBOM invocation" --exit-code 127
      return 0
    }
  local root="$RESOLVED_ROOT"

  local osv_version=""
  osv_version="$("${RESOLVED_CMD[@]}" --version 2>/dev/null || true)"
  osv_version="${osv_version%%$'\n'*}"
  [[ -n "$osv_version" ]] || osv_version="unknown"
  local osv_effective="$WORKDIR/osv-effective.json"
  local licenses_effective="$WORKDIR/licenses-effective.json"
  local sbom_effective="$WORKDIR/sbom-effective.json"
  local -a osv_metadata_issue=()
  if ! python3 - "$osv_effective" "$licenses_effective" "$sbom_effective" "$osv_version" "$LICENSES" <<'PY'
import hashlib
import json
import sys

osv_path, license_path, sbom_path, version, allowlist = sys.argv[1:]
base = {"tool": "osv-scanner", "version": version, "mode": "source-recursive",
        "resolution": "no-resolve"}
if version == "unknown":
    base["unknown_sources"] = ["osv-scanner version"]
    base["comparison"] = {"status": "incomplete", "reason": "scanner version unavailable"}
else:
    base["comparison"] = {"status": "complete"}
def write(path, payload):
    payload = dict(payload)
    payload["content_fingerprint"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    json.dump(payload, open(path, "w", encoding="utf-8"), sort_keys=True)
write(osv_path, base)
write(license_path, {**base, "resolution": "resolver-enabled",
                      "license_allowlist": [item.strip() for item in allowlist.split(",") if item.strip()]})
write(sbom_path, {**base, "resolution": "resolver-enabled", "format": "cyclonedx-1-6",
                  "all_packages": True, "license_metadata": True})
PY
  then
    warn "OSV effective metadata unavailable; scope comparison is incomplete"
    rm -f "$osv_effective" "$licenses_effective" "$sbom_effective"
    osv_effective=""
    licenses_effective=""
    sbom_effective=""
    osv_metadata_issue=(--collection-issue "effective metadata unavailable for osv-scanner")
  fi
  local -a osv_effective_arg=() licenses_effective_arg=() sbom_effective_arg=()
  [[ -n "$osv_effective" ]] && osv_effective_arg=(--effective-json "$osv_effective")
  [[ -n "$licenses_effective" ]] && licenses_effective_arg=(--effective-json "$licenses_effective")
  [[ -n "$sbom_effective" ]] && sbom_effective_arg=(--effective-json "$sbom_effective")

  # OSV has no changed-only mode: a vulnerable dependency is vulnerable
  # regardless of which commit introduced it.
  #
  # --no-resolve, and it is a MEASURED decision rather than a default anyone
  # would guess (2026-08-09, osv-scanner v2.4.0, adding the Java layer).
  #
  # Lockfiles are unaffected by this flag — package-lock.json, Cargo.lock,
  # requirements.txt and uv.lock are read exactly as before. What it disables is
  # transitive resolution of MANIFESTS, which in practice means Maven: a
  # pom.xml's dependency graph is not in the file, so osv-scanner walks it by
  # fetching every POM and BOM in the tree from Maven Central at scan time.
  #
  # On a Spring Boot pom that is over a hundred requests per run, and Maven
  # Central rate-limits them. Measured on this repo's own tree: WITH resolution
  # the scan died with 9 × HTTP 429 and exit 127; WITHOUT it, exit 0 — and the
  # per-file package counts were IDENTICAL for every manifest and lockfile,
  # because resolution never completed before being throttled.
  #
  # A gate that goes red when a third-party registry is busy is not a gate; it
  # is a check people learn to re-run until it passes, and then to ignore. So
  # the flag is on.
  #
  # WHAT IT COSTS, stated plainly rather than buried: for a Maven project this
  # means DIRECT dependencies only. Transitive vulnerabilities — which is most
  # of them in the JVM ecosystem — are not seen here. That is the same
  # trade-off .NET already has without a packages.lock.json (README: 4 findings
  # vs 7 on the same project), and it has the same answer: it is the consumer's
  # call, made with `mvn dependency:tree` or a lockfile-equivalent of their own,
  # not something this script decides silently by being slow and flaky instead.
  local rc=0 osv_log="$WORKDIR/osv.log"
  set +e
  "${RESOLVED_CMD[@]}" scan source --recursive --no-resolve "$root" \
    2>&1 | (tee "$osv_log" || { capture_rc=$?; cat; exit "$capture_rc"; })
  local -a osv_status=("${PIPESTATUS[@]}")
  set -e
  rc=${osv_status[0]:-1}
  if (( ${osv_status[1]:-0} != 0 )); then
    scope_capture_issue "osv diagnostic capture incomplete (tee exit ${osv_status[1]})" "$osv_log"
  fi
  # osv keeps its own three-way result: 128 means "no lockfiles found", which
  # is neither clean nor a finding, so record_result would mislabel it.
  case "$rc" in
    0)
      record_status osv "clean"
      scope_record --tool osv --state run --outcome success \
        --reason "OSV-Scanner completed" --exit-code 0 --mode "source-recursive" \
        --resolution "no-resolve" --log "$osv_log" \
        ${osv_effective_arg[@]+"${osv_effective_arg[@]}"} \
        ${osv_metadata_issue[@]+"${osv_metadata_issue[@]}"}
      ;;
    128)
      record_status osv "no lockfiles found"; warn "osv-scanner found nothing to scan"
      scope_record --tool osv --state run --outcome success \
        --reason "OSV-Scanner found no dependency inputs" --exit-code 128 \
        --mode "source-recursive" --resolution "no-resolve" --log "$osv_log" \
        ${osv_effective_arg[@]+"${osv_effective_arg[@]}"} \
        ${osv_metadata_issue[@]+"${osv_metadata_issue[@]}"}
      ;;
    *)
      record_status osv "FINDINGS (exit $rc)"; FINDINGS=1
      osv_reason="OSV-Scanner reported findings or an unclassified scanner error"
      if (( rc == 127 || rc >= 129 )); then
        osv_reason="OSV-Scanner reported an operational error"
      elif (( rc == 1 )); then
        osv_reason="OSV-Scanner reported findings"
      fi
      scope_record --tool osv --state run --outcome failure \
        --reason "$osv_reason" --exit-code "$rc" \
        --mode "source-recursive" --resolution "no-resolve" --log "$osv_log" \
        ${osv_effective_arg[@]+"${osv_effective_arg[@]}"} \
        ${osv_metadata_issue[@]+"${osv_metadata_issue[@]}"}
      ;;
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
    local lrc=0 license_log="$WORKDIR/licenses.log"
    set +e
    "${RESOLVED_CMD[@]}" scan source --recursive --licenses="$LICENSES" "$root" \
      2>&1 | (tee "$license_log" || { capture_rc=$?; cat; exit "$capture_rc"; })
    local -a license_status=("${PIPESTATUS[@]}")
    set -e
    lrc=${license_status[0]:-1}
    if (( ${license_status[1]:-0} != 0 )); then
      scope_capture_issue "license diagnostic capture incomplete (tee exit ${license_status[1]})" "$license_log"
    fi
    case "$lrc" in
      0)
        record_status licenses "clean (allowlist: $LICENSES)"
        scope_record --tool licenses --state run --outcome success \
          --reason "License invocation completed" --exit-code 0 --mode "source-recursive" \
          --resolution "resolver-enabled" --log "$license_log" \
          ${licenses_effective_arg[@]+"${licenses_effective_arg[@]}"} \
          ${osv_metadata_issue[@]+"${osv_metadata_issue[@]}"}
        ;;
      128)
        record_status licenses "no lockfiles found"
        scope_record --tool licenses --state run --outcome success \
          --reason "License invocation found no dependency inputs" --exit-code 128 \
          --mode "source-recursive" --resolution "resolver-enabled" --log "$license_log" \
          ${licenses_effective_arg[@]+"${licenses_effective_arg[@]}"} \
          ${osv_metadata_issue[@]+"${osv_metadata_issue[@]}"}
        ;;
      *)
        record_status licenses "VIOLATIONS (exit $lrc)"; FINDINGS=1
        scope_record --tool licenses --state run --outcome failure \
          --reason "License allowlist reported violations or an error" --exit-code "$lrc" \
          --mode "source-recursive" --resolution "resolver-enabled" --log "$license_log" \
          ${licenses_effective_arg[@]+"${licenses_effective_arg[@]}"} \
          ${osv_metadata_issue[@]+"${osv_metadata_issue[@]}"}
        ;;
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
    local src=0 sbom_log="$WORKDIR/sbom.log"
    # Drain through a foreground tee before scope_record reads the log. If the
    # diagnostic sink fails, the fallback cat consumes the remainder so the
    # scanner is not killed by SIGPIPE. PIPESTATUS keeps the scanner's verdict
    # separate from the non-gating collection failure.
    local tee_rc=0
    set +e
    "${RESOLVED_CMD[@]}" scan source --recursive --all-packages --licenses \
      --format=cyclonedx-1-6 --output-file="$out" "$root" 2>&1 | \
      (tee "$sbom_log" || { tee_rc=$?; cat; exit "$tee_rc"; })
    local -a sbom_status=("${PIPESTATUS[@]}")
    set -e
    src=${sbom_status[0]:-1}
    tee_rc=${sbom_status[1]:-1}
    if (( tee_rc != 0 )); then
      scope_capture_issue "sbom diagnostic capture incomplete (tee exit $tee_rc)" "$sbom_log"
    fi
    if [[ -n "$staged" && -f "$staged" ]]; then
      mkdir -p "$(dirname "$SBOM_OUT")"
      mv "$staged" "$SBOM_OUT"
    fi
    if [[ -f "$SBOM_OUT" ]]; then
      local n
      n=$(python3 - "$SBOM_OUT" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    document = json.load(fh)
components = document.get("components") if isinstance(document, dict) else None
if not isinstance(components, list):
    raise ValueError("CycloneDX components is not a list")
print(len(components))
PY
      ) || n='?'
      record_status sbom "$n components -> $SBOM_OUT"
      sbom_outcome=success
      (( src == 0 )) || sbom_outcome=failure
      native_count=()
      [[ "$n" =~ ^[0-9]+$ ]] && native_count=(--native-component-count "$n")
      scope_record --tool sbom --state run --outcome "$sbom_outcome" \
        --reason "SBOM invocation completed" --exit-code "$src" --mode "source-recursive" \
        --resolution "resolver-enabled" ${native_count[@]+"${native_count[@]}"} --log "$sbom_log" \
        ${sbom_effective_arg[@]+"${sbom_effective_arg[@]}"} \
        ${osv_metadata_issue[@]+"${osv_metadata_issue[@]}"}
      info "SBOM written to $SBOM_OUT ($n components)"
    else
      # Never a gate failure: an SBOM is an artifact, not a finding. But it must
      # not be silently absent either — the report reads this file.
      record_status sbom "NOT WRITTEN (osv exit $src)"
      warn "SBOM was requested but osv-scanner produced no file (exit $src)"
      scope_record --tool sbom --state run --outcome failure \
        --reason "SBOM invocation produced no artifact" --exit-code "$src" \
        --mode "source-recursive" --resolution "resolver-enabled" --log "$sbom_log" \
        ${sbom_effective_arg[@]+"${sbom_effective_arg[@]}"} \
        ${osv_metadata_issue[@]+"${osv_metadata_issue[@]}"}
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
else
  record_status semgrep "skipped (--skip)"
  scope_record --tool semgrep --state skipped --outcome unknown \
    --reason-code not_applicable \
    --reason "explicit --skip semgrep" --exit-code 0
fi

if (( ! SKIP_GITLEAKS )); then bold "── Gitleaks ──"; run_gitleaks; echo
else
  record_status gitleaks "skipped (--skip)"
  scope_record --tool gitleaks --state skipped --outcome unknown \
    --reason-code not_applicable \
    --reason "explicit --skip gitleaks" --exit-code 0
fi

if (( ! SKIP_OSV )); then bold "── OSV-Scanner ──"; run_osv; echo
else
  record_status osv "skipped (--skip)"
  scope_record --tool osv --state skipped --outcome unknown \
    --reason-code not_applicable \
    --reason "explicit --skip osv" --exit-code 0
  [[ -n "$LICENSES" ]] && scope_record --tool licenses --state skipped --outcome unknown --reason-code blocked \
    --reason "OSV-Scanner explicitly skipped before license invocation" --exit-code 0
  [[ -n "$SBOM_OUT" ]] && scope_record --tool sbom --state skipped --outcome unknown --reason-code blocked \
    --reason "OSV-Scanner explicitly skipped before SBOM invocation" --exit-code 0
fi

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
