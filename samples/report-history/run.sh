#!/usr/bin/env bash
# Network-free standing-report history fixture. It exercises the public report
# CLI and extracts the production action/workflow handoff text for wiring checks.
set -Eeuo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/maxi-quality-report.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

cat >"$WORK/findings.json" <<'JSON'
{"results":[{"check_id":"a.no-clock"},{"check_id":"a.no-clock"}],"errors":[],"paths":{"scanned":["src/a.ts","src/b.ts"]},"version":"1.172.0"}
JSON

scope() {
  local run=$1 attempt=$2 started=$3
  local out="$WORK/$run-$attempt.json"
  python3 "$ROOT/scripts/layer2_scope.py" init --out "$out" --producer report \
    --workflow quality-report --invocation-id "$run" --run-id "$run" \
    --run-attempt "$attempt" --job report --fragment-id "fixture-$run-$attempt" \
    --commit abc123 --ref refs/heads/develop --mode full
  python3 - "$out" "$started" <<'PY'
import json, sys
path, started = sys.argv[1:]
doc = json.load(open(path))
doc["identity"]["started_at"] = started
json.dump(doc, open(path, "w"), indent=2)
PY
  python3 "$ROOT/scripts/layer2_scope.py" record --out "$out" --tool semgrep \
    --state run --outcome success --reason "fixture scan" --mode full
  python3 "$ROOT/scripts/layer2_scope.py" measure-semgrep --out "$out" \
    --results "$WORK/findings.json" --scan-root "$ROOT" --scanner-root "$ROOT" --mode full
  python3 "$ROOT/scripts/layer2_scope.py" finalize --out "$out" \
    --analysis-outcome success --analysis-exit-code 0 --collection-status complete
  printf '%s\n' "$out"
}

render() {
  local out=$1 body=$2 run=$3 attempt=$4 started=$5 scope_path=${6:-}
  local -a args=(--json "$WORK/findings.json" --date 2026-01-01 --run-id "$run"
    --run-attempt "$attempt" --started-at "$started" --previous-body "$body")
  [[ -n "$scope_path" ]] && args+=(--scope "$scope_path")
  python3 "$ROOT/scripts/quality-report.py" "${args[@]}" >"$out"
}

qualify_scope() {
  local path=$1 examined=$2 unparsed=$3 policy=$4 native=$5
  python3 - "$path" "$examined" "$unparsed" "$policy" "$native" <<'PY'
import json, sys
path, examined, unparsed, policy, native = sys.argv[1:]
d = json.load(open(path))
semgrep = d["tools"]["semgrep"]
semgrep["effective"] = {
    "tool": "semgrep", "version": "1.172.0", "diagnostic_mode": "verbose",
    "comparison": {"status": "complete"},
    "config_fingerprint": "fixture-config", "content_fingerprint": "fixture-rules",
}
for key, count in (("examined", examined), ("unparsed", unparsed), ("policy_excluded", policy)):
    semgrep["measurements"][key] = {
        "status": "known", "count": int(count), "unit": "target_path", "method": "fixture evidence",
    }
sbom = d["tools"]["sbom"]
sbom["native"] = {"component_count": {
    "status": "known", "count": int(native), "unit": "dependency_component", "method": "fixture inventory",
}}
json.dump(d, open(path, "w"))
PY
}

S1=$(scope run-one 1 2026-01-01T10:00:00Z)
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id run-one --run-attempt 1 \
  --started-at 2026-01-01T10:00:00Z --scope "$S1" >"$WORK/one.md"

# JSON-valid but semantically malformed retained scope metadata must degrade to
# unavailable comparison while preserving the visible finding row.
python3 - "$WORK/one.md" "$WORK/malformed-history.md" <<'PY'
import json, sys
source, target = sys.argv[1:]
body = open(source, encoding="utf-8").read()
start_marker = "<!-- maxi-quality:history-v2 -->"
end_marker = "<!-- /maxi-quality:history-v2 -->"
start = body.index(start_marker) + len(start_marker)
end = body.index(end_marker, start)
rows = json.loads(body[start:end].strip())
if isinstance(rows, dict):
    rows = dict(rows)
    rows["entries"] = list(rows["entries"])
    rows["entries"][0] = dict(rows["entries"][0])
    rows["entries"][0]["scope"] = {"status": "available", "tools": {"semgrep": {
        "effective": [], "measurements": {"examined": {"status": "known", "count": True}},
        "not_applicable": None, "native": {"component_count": {"status": "known", "count": None}},
    }}
    }
else:
    rows = list(rows)
    rows[0]["scope"] = {"status": "available", "tools": {"semgrep": {
        "effective": [], "measurements": {"examined": {"status": "known", "count": True}},
        "not_applicable": None, "native": {"component_count": {"status": "known", "count": None}},
    }}
    }
open(target, "w", encoding="utf-8").write(
    body[:start] + "\n" + json.dumps(rows) + "\n" + body[end:]
)
PY
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id run-two --run-attempt 1 \
  --started-at 2026-01-01T11:30:00Z --previous-body "$WORK/malformed-history.md" \
  >"$WORK/malformed-history-rendered.md"
grep -q '| run-two | 1 |' "$WORK/malformed-history-rendered.md"
grep -q 'Comparison unavailable\|Conditions:' "$WORK/malformed-history-rendered.md"

# Semantically malformed optional measurements from the current scope are
# non-gating and render as unknown rather than being treated as known counts.
SMAL=$(scope malformed-own 1 2026-01-01T11:45:00Z)
python3 - "$SMAL" <<'PY'
import json, sys
path = sys.argv[1]
doc = json.load(open(path))
doc["tools"]["semgrep"]["measurements"] = []
doc["tools"]["sbom"]["native"] = {"component_count": {
    "status": "known", "count": True, "unit": "dependency_component", "method": "malformed bool count",
}}
json.dump(doc, open(path, "w"))
PY
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id malformed-own --run-attempt 1 \
  --started-at 2026-01-01T11:45:00Z --scope "$SMAL" \
  >"$WORK/malformed-own-rendered.md"
grep -q '| malformed-own | 1 |' "$WORK/malformed-own-rendered.md"
grep -q 'unknown' "$WORK/malformed-own-rendered.md"

S2=$(scope run-one 2 2026-01-01T11:00:00Z)
render "$WORK/two.md" "$WORK/one.md" run-one 2 2026-01-01T11:00:00Z "$S2"
grep -q '| run-one | 2 |' "$WORK/two.md"
grep -q '| run-one | 1 |' "$WORK/two.md"
[[ $(grep -c '^| run-one |' "$WORK/two.md") == 2 ]]

# Reprocessing the same identity replaces one entry rather than appending it.
render "$WORK/repeat.md" "$WORK/two.md" run-one 2 2026-01-01T11:00:00Z "$S2"
[[ $(grep -c '^| run-one |' "$WORK/repeat.md") == 2 ]]

# Preserve the newest run's complete presentation when an older completion is
# inserted between it and its prior predecessor. Tool statuses, rule counts,
# parse-gap paths and dependency inventory must not be taken from the older run.
cat >"$WORK/findings-old.json" <<'JSON'
{"results":[{"check_id":"a.no-clock"}],"errors":[],"paths":{"scanned":["src/old.ts"]},"version":"1.172.0"}
JSON
SNEW=$(scope run-new 1 2026-01-01T11:00:00Z)
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id run-new --run-attempt 1 \
  --started-at 2026-01-01T11:00:00Z --scope "$SNEW" \
  --gitleaks newer --osv newer --licenses 'new licenses' \
  --previous-body "$WORK/one.md" >"$WORK/newest.md"
grep -q '## Current — 2026-01-01T11:00:00Z (run-new/1)' "$WORK/newest.md"
grep -q '| Gitleaks | newer |' "$WORK/newest.md"
grep -q "| \`no-clock\` | 2 |" "$WORK/newest.md"
grep -q 'Findings: +0 findings' "$WORK/newest.md"
SMID=$(scope run-between 1 2026-01-01T10:30:00Z)
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings-old.json" \
  --date 2026-01-01 --run-id run-between --run-attempt 1 \
  --started-at 2026-01-01T10:30:00Z --scope "$SMID" \
  --gitleaks older --osv older --licenses 'old licenses' \
  --previous-body "$WORK/newest.md" >"$WORK/inserted.md"
grep -q '## Current — 2026-01-01T11:00:00Z (run-new/1)' "$WORK/inserted.md"
grep -q '| Gitleaks | newer |' "$WORK/inserted.md"
grep -q "| \`no-clock\` | 2 |" "$WORK/inserted.md"
grep -q 'Findings: +1 findings' "$WORK/inserted.md"
if grep -q '| Gitleaks | older |' "$WORK/inserted.md"; then
  echo "older completion mixed its tool presentation into the current run" >&2
  exit 1
fi

# Complete comparison metadata qualifies directional scope changes even when
# finding deltas are shown: smaller examined scope, more gaps/exclusions, and a
# compatible native dependency inventory delta are all rendered explicitly.
SBASE=$(scope run-base 1 2026-01-02T09:00:00Z)
qualify_scope "$SBASE" 10 0 0 4
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings-old.json" \
  --date 2026-01-02 --run-id run-base --run-attempt 1 \
  --started-at 2026-01-02T09:00:00Z --scope "$SBASE" >"$WORK/base.md"
SQUAL=$(scope run-qualified 1 2026-01-02T10:00:00Z)
qualify_scope "$SQUAL" 8 2 1 5
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-02 --run-id run-qualified --run-attempt 1 \
  --started-at 2026-01-02T10:00:00Z --scope "$SQUAL" \
  --previous-body "$WORK/base.md" >"$WORK/qualified.md"
grep -q "semgrep examined: -2 \`target_path\`" "$WORK/qualified.md"
grep -q "semgrep unparsed: +2 \`target_path\`" "$WORK/qualified.md"
grep -q "semgrep policy_excluded: +1 \`target_path\`" "$WORK/qualified.md"
grep -q "sbom native component_count: +1 \`dependency_component\`" "$WORK/qualified.md"
grep -q 'smaller\|more analysis gaps\|more observed policy exclusions' "$WORK/qualified.md"

# An older completion is inserted chronologically but cannot replace the newest
# current findings/scope. Its insertion does change the current predecessor.
S0=$(scope run-zero 1 2026-01-01T09:00:00Z)
render "$WORK/old.md" "$WORK/two.md" run-zero 1 2026-01-01T09:00:00Z "$S0"
grep -q '## Current — 2026-01-01T11:00:00Z (run-one/2)' "$WORK/old.md"
grep -q '| run-zero | 1 |' "$WORK/old.md"

# Scope collection is optional and never erases parseable finding history.
render "$WORK/no-scope.md" "$WORK/old.md" run-three 1 2026-01-01T12:00:00Z
grep -q 'Scope evidence unavailable' "$WORK/no-scope.md"
[[ $(grep -c '^| run-' "$WORK/no-scope.md") == 4 ]]
printf '{"kind":"layer2-scope","schema_version":1,"identity":{},"tools":[],"summary":[]}\n' >"$WORK/malformed-scope.json"
render "$WORK/malformed-scope.md" "$WORK/old.md" run-malformed 1 2026-01-01T12:30:00Z "$WORK/malformed-scope.json"
grep -q 'Scope evidence unavailable' "$WORK/malformed-scope.md"
grep -q '| run-malformed | 1 |' "$WORK/malformed-scope.md"

# An explicit previous-body read failure refuses output instead of treating the
# standing issue as a new report with empty history.
set +e
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id unreadable --run-attempt 1 \
  --started-at 2026-01-01T12:45:00Z --previous-body "$WORK/does-not-exist.md" \
  >"$WORK/unreadable.md"
unreadable_rc=$?
set -e
[[ $unreadable_rc == 3 ]]
[[ ! -s "$WORK/unreadable.md" ]]

# A valid failed scope plus a missing success-only findings handoff is a failed
# attempt, not a clean zero. The renderer still emits a body for the action.
SF=$(scope failed-run 1 2026-01-01T13:00:00Z)
python3 - "$SF" <<'PY'
import json, sys
p=sys.argv[1]
d=json.load(open(p))
d["analysis"]["outcome"]="failure"
d["analysis"]["exit_code"]=17
json.dump(d, open(p,"w"))
PY
set +e
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/missing.json" \
  --date 2026-01-01 --run-id failed-run --run-attempt 1 \
  --started-at 2026-01-01T13:00:00Z --scope "$SF" >"$WORK/failure.md"
rc=$?
set -e
[[ $rc == 2 ]]
grep -q 'ERRORED' "$WORK/failure.md"
if grep -q '\*\*0\*\* findings' "$WORK/failure.md"; then
  echo "zero findings was rendered for a failed attempt" >&2
  exit 1
fi

# Execute the extracted production report-issue shell with a deterministic gh
# boundary. This proves the action carries failure and identity handoffs all
# the way to the issue writer, rather than only testing renderer arguments.
python3 - "$ROOT/actions/report-issue/action.yml" "$WORK/action-run.sh" <<'PY'
import pathlib, sys, yaml
source, output = sys.argv[1:]
doc = yaml.safe_load(pathlib.Path(source).read_text())
run = next(step["run"] for step in doc["runs"]["steps"] if step.get("id") == "upsert")
pathlib.Path(output).write_text(run)
PY
mkdir -p "$WORK/bin"
cat >"$WORK/bin/gh" <<'GH'
#!/usr/bin/env bash
set -Eeuo pipefail
state=${FAKE_GH_STATE:?}
if [[ "$1 $2" == "issue list" ]]; then
  [[ -s "$state" ]] && printf '7\n' || true
elif [[ "$1 $2" == "issue view" ]]; then
  [[ -z "${FAKE_GH_VIEW_FAIL:-}" ]] || exit 1
  cat "$state"
elif [[ "$1 $2" == "issue edit" ]]; then
  for ((i=1; i<=$#; i++)); do
    if [[ "${!i}" == "--body-file" ]]; then j=$((i+1)); cp "${!j}" "$state"; fi
  done
elif [[ "$1 $2" == "issue create" ]]; then
  for ((i=1; i<=$#; i++)); do
    if [[ "${!i}" == "--body-file" ]]; then j=$((i+1)); cp "${!j}" "$state"; fi
  done
  printf 'https://example.test/issues/7\n'
elif [[ "$1 $2" == "issue reopen" || "$1 $2" == "label create" ]]; then
  true
else
  echo "unexpected gh invocation: $*" >&2
  exit 1
fi
GH
chmod +x "$WORK/bin/gh"

run_action() {
  local json=$1 scope_path=$2 run_id=$3
  PATH="$WORK/bin:$PATH" FAKE_GH_STATE="$WORK/issue.md" \
    GH_TOKEN=test GITHUB_ACTION_PATH="$ROOT/actions/report-issue" \
    GITHUB_REPOSITORY=demo/repo RUNNER_TEMP="$WORK" GITHUB_OUTPUT="$WORK/action.out" \
    GITHUB_STEP_SUMMARY="$WORK/summary.md" JSON="$json" \
    SCOPE="$scope_path" RUN_ID="$run_id" RUN_ATTEMPT=1 INVOCATION_ID="$run_id" \
    STARTED_AT=2026-01-04T10:00:00Z COMMIT=abc123 REF=refs/heads/develop \
    LABEL=quality-report TITLE='Quality backlog' GITLEAKS=clean OSV=clean LICENSES='not run' SBOM='' \
    bash "$WORK/action-run.sh"
}
ACTION_SCOPE="$WORK/action-good-scope.json"
cp "$S1" "$ACTION_SCOPE"
python3 - "$ACTION_SCOPE" <<'PY'
import json, sys
p=sys.argv[1]
d=json.load(open(p))
d["identity"]["run_id"]="action-good"
d["identity"]["invocation_id"]="action-good"
json.dump(d, open(p,"w"))
PY
run_action "$WORK/findings.json" "$ACTION_SCOPE" action-good
grep -q '| action-good | 1 |' "$WORK/issue.md"
set +e
run_action "$WORK/missing-from-action.json" "$SF" failed-run
action_rc=$?
set -e
[[ $action_rc == 2 ]]
grep -q '| failed-run | 1 |' "$WORK/issue.md"
grep -q 'ERRORED' "$WORK/issue.md"

printf 'garbage, no history heading\n' >"$WORK/issue.md"
if run_action "$WORK/findings.json" "$S1" action-refused; then
  echo "unrecoverable prior history was overwritten" >&2
  exit 1
fi
grep -q 'garbage, no history heading' "$WORK/issue.md"
cp "$WORK/one.md" "$WORK/issue.md"

run_action "$WORK/findings.json" "$S1" action-foreign
grep -q '| action-foreign | 1 |' "$WORK/issue.md"
grep -q 'scope identity does not match' "$WORK/issue.md"

# A failure while reading the standing issue stops before rendering or writing;
# the existing body remains byte-for-byte intact.
cp "$WORK/issue.md" "$WORK/issue-before-view-failure.md"
set +e
PATH="$WORK/bin:$PATH" FAKE_GH_STATE="$WORK/issue.md" FAKE_GH_VIEW_FAIL=1 \
  GH_TOKEN=test GITHUB_ACTION_PATH="$ROOT/actions/report-issue" \
  GITHUB_REPOSITORY=demo/repo RUNNER_TEMP="$WORK" GITHUB_OUTPUT="$WORK/action.out" \
  GITHUB_STEP_SUMMARY="$WORK/summary.md" JSON="$WORK/findings.json" \
  SCOPE="$S1" RUN_ID=action-view-failure RUN_ATTEMPT=1 INVOCATION_ID=action-view-failure \
  STARTED_AT=2026-01-04T10:00:00Z COMMIT=abc123 REF=refs/heads/develop \
  LABEL=quality-report TITLE='Quality backlog' GITLEAKS=clean OSV=clean LICENSES='not run' SBOM='' \
  bash "$WORK/action-run.sh"
view_rc=$?
set -e
[[ $view_rc != 0 ]]
cmp -s "$WORK/issue-before-view-failure.md" "$WORK/issue.md"

# 52 entries means 52 attempts, including same-day runs, and old rows fall off.
body="$WORK/one.md"
for i in $(seq 2 54); do
  run="cap-$i"
  hour=$(printf '%02d' $((i % 24)))
  cap_scope="$WORK/$run-scope.json"
  cp "$S1" "$cap_scope"
  python3 - "$cap_scope" "$run" "2026-01-02T${hour}:00:00Z" "$i" <<'PY'
import json, sys
p, run, started, index = sys.argv[1:]
d = json.load(open(p))
d["identity"]["run_id"] = run
d["identity"]["invocation_id"] = run
d["identity"]["started_at"] = started
for name in ("semgrep", "gitleaks", "osv", "sbom"):
    tool = d["tools"][name]
    tool.update(requested=True, state="run", outcome="success", reason="completed", exit_code=0)
    tool["diagnostics"] = [{
        "stream": "stderr", "source": "fixture",
        "text": f"short diagnostic {index}: {name} completed",
    }]
semgrep = d["tools"]["semgrep"]
semgrep["effective"].update({
    "comparison": {"status": "complete"},
    "config_fingerprint": __import__("hashlib").sha256(f"configuration {index}".encode()).hexdigest(),
    "content_fingerprint": __import__("hashlib").sha256(f"rules {index}".encode()).hexdigest(),
})
d["tools"]["sbom"]["native"] = {"component_count": {
    "status": "known", "count": int(index) + 5,
    "unit": "dependency_component", "method": "CycloneDX components list",
}}
json.dump(d, open(p, "w"))
PY
  python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
    --date 2026-01-02 --run-id "$run" --run-attempt 1 \
    --started-at "2026-01-02T${hour}:00:00Z" --scope "$cap_scope" \
    --previous-body "$body" >"$WORK/cap-$i.md"
  body="$WORK/cap-$i.md"
done
[[ $(grep -c '^| cap-' "$body") == 52 ]]
body_size=$(wc -c < "$body")
[[ "$body_size" -lt 65536 ]]
echo "compact 52-entry report body: ${body_size} bytes (local conservative budget 65536 bytes)"
if grep -q '| run-one | 1 |' "$body"; then
  echo "retention did not evict the oldest entry" >&2
  exit 1
fi

# A scope from another run must remain an unavailable optional scope, never
# silently changing which own-run findings the report describes.
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-03 --run-id foreign-run --run-attempt 1 \
  --started-at 2026-01-03T10:00:00Z --scope "$S1" --previous-body "$body" >"$WORK/foreign.md"
grep -q 'scope identity does not match' "$WORK/foreign.md"
grep -q '| foreign-run | 1 |' "$WORK/foreign.md"

# The action/workflow handoff is checked from the production text itself.
python3 - "$ROOT/actions/report-issue/action.yml" "$ROOT/.github/workflows/quality-report.yml" <<'PY'
import pathlib, sys
action = pathlib.Path(sys.argv[1]).read_text()
workflow = pathlib.Path(sys.argv[2]).read_text()
run = action[action.index("run: |") :]
assert "ARGS+=(--scope \"$SCOPE\")" in run
assert "--run-attempt" in run and "--started-at" in run
assert "if: always()" in workflow
assert "cancel-in-progress: false" in workflow
assert "scope: ${{ steps.scan.outputs.scope }}" in workflow
PY

echo "OK: report history, scope, failure, retention, and production handoffs"
