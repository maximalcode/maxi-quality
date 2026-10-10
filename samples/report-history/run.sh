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
printf '{"results":[],"errors":[],"paths":{"scanned":["src/a.ts"]}}\n' >"$WORK/clean-findings.json"
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id run-one --run-attempt 1 \
  --started-at 2026-01-01T10:00:00Z --scope "$S1" >"$WORK/one.md"

# Persistence is present in the source but absent from visible HTML text. A
# pair of separately closed marker comments must not expose the JSON between.
python3 - "$WORK/one.md" "$WORK/bare-one.md" "$ROOT" <<'PY'
from html.parser import HTMLParser
from pathlib import Path
import json, subprocess, sys

class PersistenceHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.visible = []
        self.comments = []
    def handle_data(self, data):
        self.visible.append(data)
    def handle_comment(self, data):
        self.comments.append(data)

body = open(sys.argv[1], encoding="utf-8").read()
start = body.index("<!-- maxi-quality:history-v2 -->") + len("<!-- maxi-quality:history-v2 -->")
end = body.index("<!-- /maxi-quality:history-v2 -->", start)
parser = PersistenceHTML()
parser.feed(body[start:end])
assert not "".join(parser.visible).strip(), "persistence JSON renders as visible text"
assert any(isinstance(json.loads(comment), dict) for comment in parser.comments)
# Simulate the previous bare-JSON format, retaining all comparison metadata.
Path(sys.argv[2]).write_text(body[:start] + parser.comments[0] + body[end:], encoding="utf-8")

# A tool-emitted value containing comment delimiters must remain exact after
# serialization, without closing or nesting the HTML comment around it.
work = Path(sys.argv[1]).parent
finding = "comment--><!--nested"
source = work / "comment-findings.json"
source.write_text(json.dumps({"results": [{"check_id": "fixture." + finding}],
    "errors": [], "paths": {"scanned": ["fixture.ts"]}}), encoding="utf-8")
previous = None
for attempt in (1, 2):
    args = [sys.executable, str(Path(sys.argv[3]) / "scripts/quality-report.py"),
        "--json", str(source), "--date", "2026-01-01", "--run-id", "comment-run",
        "--run-attempt", str(attempt), "--started-at", f"2026-01-01T0{attempt}:00:00Z"]
    if previous:
        args += ["--previous-body", str(previous)]
    rendered = subprocess.run(args, text=True, capture_output=True, check=True).stdout
    content = rendered.split("<!-- maxi-quality:history-v2 -->", 1)[1].split("<!-- /maxi-quality:history-v2 -->", 1)[0]
    encoded = PersistenceHTML()
    encoded.feed(content)
    assert not "".join(encoded.visible).strip(), "tool text escaped the hidden comment"
    assert len(encoded.comments) == 1 and "--" not in encoded.comments[0]
    assert finding in json.dumps(json.loads(encoded.comments[0])), "tool text changed during serialization"
    assert "| comment-run | 1 |" in rendered
    previous = work / f"comment-{attempt}.md"
    previous.write_text(rendered, encoding="utf-8")
PY

# A finding is an analysis failure for the scanner, but it is still valid
# finding data for the report. Exercise the actual producer shape rather than
# synthesizing a successful scope around finding JSON.
SFIND="$WORK/producer-findings-scope.json"
cp "$S1" "$SFIND"
python3 - "$SFIND" <<'PY'
import json, sys
path = sys.argv[1]
doc = json.load(open(path, encoding="utf-8"))
doc["analysis"].update(outcome="failure", exit_code=1)
doc["tools"]["semgrep"].update(outcome="failure", exit_code=1, reason="Semgrep completed with findings")
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
set +e
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id run-one --run-attempt 1 \
  --started-at 2026-01-01T10:00:00Z --scope "$SFIND" >"$WORK/producer-findings.md"
producer_rc=$?
set -e
[[ $producer_rc == 0 ]]
grep -q '| Semgrep | \*\*2\*\* findings |' "$WORK/producer-findings.md"
if grep -q 'ERRORED' "$WORK/producer-findings.md"; then
  echo "normal producer findings were rendered as an operational error" >&2
  exit 1
fi

# Malformed optional analysis fields are unknown metadata, not a renderer
# crash or a fabricated zero/error finding result.
MALFORMED_ANALYSIS="$WORK/malformed-analysis-scope.json"
cp "$SFIND" "$MALFORMED_ANALYSIS"
python3 - "$MALFORMED_ANALYSIS" <<'PY'
import json, sys
path = sys.argv[1]
doc = json.load(open(path, encoding="utf-8"))
doc["analysis"]["outcome"] = []
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
set +e
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id malformed-analysis --run-attempt 1 \
  --started-at 2026-01-01T10:15:00Z --scope "$MALFORMED_ANALYSIS" >"$WORK/malformed-analysis.md"
malformed_analysis_rc=$?
set -e
[[ $malformed_analysis_rc == 0 ]]
grep -q '| Semgrep | \*\*2\*\* findings |' "$WORK/malformed-analysis.md"
if grep -q 'ERRORED' "$WORK/malformed-analysis.md"; then
  echo "malformed optional analysis metadata fabricated an operational error" >&2
  exit 1
fi

# A mixed run retains valid Semgrep findings while native report-tool failures
# remain visible diagnostics without changing the report verdict. Reason text
# alone is not finding classification evidence.
MIXED_SCOPE="$WORK/mixed-scope.json"
cp "$SFIND" "$MIXED_SCOPE"
python3 - "$MIXED_SCOPE" <<'PY'
import json, sys
path = sys.argv[1]
doc = json.load(open(path, encoding="utf-8"))
doc["tools"]["licenses"].update(
    state="run", outcome="failure", exit_code=7,
    reason="License allowlist reported violations or an error",
)
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
set +e
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id run-one --run-attempt 1 \
  --started-at 2026-01-01T10:00:00Z --scope "$MIXED_SCOPE" >"$WORK/mixed.md"
mixed_rc=$?
set -e
[[ $mixed_rc == 0 ]]
grep -q '| Semgrep | \*\*2\*\* findings |' "$WORK/mixed.md"
if grep -q 'ERRORED' "$WORK/mixed.md"; then
  echo "native license failure changed the report verdict" >&2
  exit 1
fi

for native_tool in gitleaks osv; do
  NATIVE_SCOPE="$WORK/native-$native_tool.json"
  cp "$SFIND" "$NATIVE_SCOPE"
  python3 - "$NATIVE_SCOPE" "$native_tool" <<'PY'
import json, sys
path, tool = sys.argv[1:]
doc = json.load(open(path, encoding="utf-8"))
doc["identity"].update(run_id="native-" + tool, invocation_id="native-" + tool)
doc["tools"][tool].update(state="run", outcome="failure", exit_code=7, reason=tool + " unavailable")
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
  python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
    --date 2026-01-01 --run-id "native-$native_tool" --run-attempt 1 \
    --started-at 2026-01-01T10:00:00Z --scope "$NATIVE_SCOPE" >"$WORK/native-$native_tool.md"
  grep -q '| Semgrep | \*\*2\*\* findings |' "$WORK/native-$native_tool.md"
  if grep -q 'ERRORED' "$WORK/native-$native_tool.md"; then
    echo "$native_tool failure changed the report verdict" >&2
    exit 1
  fi
  CLEAN_SCOPE="$WORK/native-clean-$native_tool.json"
  cp "$NATIVE_SCOPE" "$CLEAN_SCOPE"
  python3 - "$CLEAN_SCOPE" "native-clean-$native_tool" <<'PY'
import json, sys
path, run = sys.argv[1:]
doc = json.load(open(path, encoding="utf-8"))
doc["identity"].update(run_id=run, invocation_id=run)
doc["tools"]["semgrep"].update(state="run", outcome="success", exit_code=0, reason="fixture scan")
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
  python3 "$ROOT/scripts/quality-report.py" --json "$WORK/clean-findings.json" \
    --date 2026-01-01 --run-id "native-clean-$native_tool" --run-attempt 1 \
    --started-at 2026-01-01T10:00:00Z --scope "$CLEAN_SCOPE" >"$WORK/native-clean-$native_tool.md"
  grep -q '| Semgrep | \*\*0\*\* findings |' "$WORK/native-clean-$native_tool.md"
  grep -q "| $native_tool | run | failure |" "$WORK/native-clean-$native_tool.md"
done

MIXED_FINDING_SCOPE="$WORK/mixed-finding-scope.json"
cp "$SFIND" "$MIXED_FINDING_SCOPE"
python3 - "$MIXED_FINDING_SCOPE" <<'PY'
import json, sys
path = sys.argv[1]
doc = json.load(open(path, encoding="utf-8"))
doc["tools"]["licenses"].update(
    state="run", outcome="failure", exit_code=1,
    reason="License allowlist reported violations or an error",
)
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
set +e
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id run-one --run-attempt 1 \
  --started-at 2026-01-01T10:00:00Z --scope "$MIXED_FINDING_SCOPE" >"$WORK/mixed-finding.md"
mixed_finding_rc=$?
set -e
[[ $mixed_finding_rc == 0 ]]
grep -q '| Semgrep | \*\*2\*\* findings |' "$WORK/mixed-finding.md"
if grep -q 'ERRORED' "$WORK/mixed-finding.md"; then
  echo "native license findings were rendered as an operational error" >&2
  exit 1
fi

# Two actual producer-shaped findings runs remain comparable even though both
# analysis outcomes are failure: the failure is the findings verdict, not an
# incomplete scanner attempt.
FINDING_NEXT="$WORK/producer-findings-next-scope.json"
cp "$SFIND" "$FINDING_NEXT"
python3 - "$FINDING_NEXT" <<'PY'
import json, sys
path = sys.argv[1]
doc = json.load(open(path, encoding="utf-8"))
doc["identity"].update(run_id="run-next", invocation_id="run-next", started_at="2026-01-01T10:30:00Z")
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id run-next --run-attempt 1 \
  --started-at 2026-01-01T10:30:00Z --scope "$FINDING_NEXT" \
  --previous-body "$WORK/producer-findings.md" >"$WORK/producer-findings-next.md"
if grep -q 'incomplete attempt is not a stable baseline' "$WORK/producer-findings-next.md"; then
  echo "valid findings history was qualified as an incomplete attempt" >&2
  exit 1
fi

# A real scanner boundary failure still controls the report exit and visible
# ERRORED state when a stale or partial JSON happens to be readable.
SOP=$(scope operational 1 2026-01-01T10:30:00Z)
python3 - "$SOP" <<'PY'
import json, sys
path = sys.argv[1]
doc = json.load(open(path, encoding="utf-8"))
doc["analysis"].update(outcome="failure", exit_code=9)
doc["tools"]["semgrep"].update(outcome="failure", exit_code=9, reason="Semgrep result classification failed")
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
set +e
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id operational --run-attempt 1 \
  --started-at 2026-01-01T10:30:00Z --scope "$SOP" >"$WORK/operational.md"
operational_rc=$?
set -e
[[ $operational_rc == 2 ]]
grep -q 'ERRORED' "$WORK/operational.md"

# Excerpts are Markdown table cells. Keep hostile diagnostic syntax visible
# and bounded while the complete raw value remains in the scope artifact.
python3 - "$SFIND" <<'PY'
import json, sys
path = sys.argv[1]
doc = json.load(open(path, encoding="utf-8"))
doc["tools"]["semgrep"]["diagnostics"] = [{"stream": "combined", "source": "fixture", "text": "<!-- hidden error --> **not literal** [details](https://example.invalid)|\nsecond line " + "x" * 260}]
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id run-one --run-attempt 1 \
  --started-at 2026-01-01T10:00:00Z --scope "$SFIND" >"$WORK/escaped-diagnostic.md"
grep -q '&lt;!-- hidden error --&gt;' "$WORK/escaped-diagnostic.md"
grep -Fq '\*\*not literal\*\*' "$WORK/escaped-diagnostic.md"
grep -Fq '\[details\]\(https://example.invalid\)' "$WORK/escaped-diagnostic.md"
grep -Fq '\|' "$WORK/escaped-diagnostic.md"
grep -q '\.\.\.' "$WORK/escaped-diagnostic.md"

# A legacy finding row remains visible, but its unavailable scope cannot be a
# numeric comparison baseline for a new measured execution.
cat >"$WORK/legacy.md" <<'MD'
## History

| Date | Findings | Top rules |
|---|---:|---|
| 2025-12-31 | 10 | fixture.rule (10) |
MD
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id run-one --run-attempt 1 \
  --started-at 2026-01-01T10:00:00Z --scope "$S1" \
  --previous-body "$WORK/legacy.md" >"$WORK/from-legacy.md"
grep -q 'Comparison unavailable:' "$WORK/from-legacy.md"
if grep -q 'Findings: -8 findings' "$WORK/from-legacy.md"; then
  echo "legacy scope was used as a numeric comparison baseline" >&2
  exit 1
fi
grep -Fq '| legacy | unknown | 2025-12-31T00:00:00Z | success | 10 |' "$WORK/from-legacy.md"

# SBOM inventory is diagnostic evidence and must remain non-gating. A failure
# from that optional tool cannot turn a valid findings report into ERRORED,
# either by itself or alongside a Semgrep findings verdict.
for sbom_mode in alone_with_failure semgrep_finding; do
  SBOM_SCOPE="$WORK/sbom-$sbom_mode.json"
  cp "$S1" "$SBOM_SCOPE"
  python3 - "$SBOM_SCOPE" "$sbom_mode" <<'PY'
import json, sys
path, mode = sys.argv[1:]
doc = json.load(open(path, encoding="utf-8"))
doc["identity"].update(run_id="sbom-" + mode, invocation_id="sbom-" + mode)
doc["analysis"].update(outcome="failure", exit_code=7)
doc["tools"]["sbom"].update(state="run", outcome="failure", exit_code=7, reason="SBOM inventory unavailable")
if mode == "semgrep_finding":
    doc["tools"]["semgrep"].update(outcome="failure", exit_code=1, reason="Semgrep completed with findings")
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
  set +e
  python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
    --date 2026-01-01 --run-id "sbom-$sbom_mode" --run-attempt 1 \
    --started-at 2026-01-01T10:00:00Z --scope "$SBOM_SCOPE" >"$WORK/sbom-$sbom_mode.md"
  sbom_rc=$?
  set -e
  if [[ $sbom_rc != 0 ]]; then echo "SBOM failure changed report exit: $sbom_rc" >&2; exit 1; fi
  grep -q '| Semgrep | \*\*2\*\* findings |' "$WORK/sbom-$sbom_mode.md"
  if grep -q 'ERRORED' "$WORK/sbom-$sbom_mode.md"; then
    echo "SBOM-only failure became an operational report error" >&2
    exit 1
  fi
  CLEAN_SCOPE="$WORK/sbom-clean-$sbom_mode.json"
  cp "$SBOM_SCOPE" "$CLEAN_SCOPE"
  python3 - "$CLEAN_SCOPE" "sbom-clean-$sbom_mode" <<'PY'
import json, sys
path, run = sys.argv[1:]
doc = json.load(open(path, encoding="utf-8"))
doc["identity"].update(run_id=run, invocation_id=run)
doc["tools"]["semgrep"].update(state="run", outcome="success", exit_code=0, reason="fixture scan")
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
  python3 "$ROOT/scripts/quality-report.py" --json "$WORK/clean-findings.json" \
    --date 2026-01-01 --run-id "sbom-clean-$sbom_mode" --run-attempt 1 \
    --started-at 2026-01-01T10:00:00Z --scope "$CLEAN_SCOPE" >"$WORK/sbom-clean-$sbom_mode.md"
  grep -q '| Semgrep | \*\*0\*\* findings |' "$WORK/sbom-clean-$sbom_mode.md"
  grep -q '| sbom | run | failure |' "$WORK/sbom-clean-$sbom_mode.md"
done

# Legacy rows have dates but no run identity. Re-reading the rendered body
# must preserve each date exactly once while two new executions are added, and
# repeating the newest execution must remain idempotent.
cat >"$WORK/legacy-two.md" <<'MD'
## History

| Date | Findings | Top rules |
|---|---:|---|
| 2025-12-30 | 8 | old.rule (8) |
| 2025-12-31 | 10 | fixture.rule (10) |
MD
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id legacy-new-a --run-attempt 1 \
  --started-at 2026-01-01T10:00:00Z --previous-body "$WORK/legacy-two.md" >"$WORK/legacy-new-a.md"
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id legacy-new-b --run-attempt 1 \
  --started-at 2026-01-01T11:00:00Z --previous-body "$WORK/legacy-new-a.md" >"$WORK/legacy-new-b.md"
legacy_rows=$(grep -Ec '^\| (legacy|legacy-new-[ab]) \|' "$WORK/legacy-new-b.md")
if [[ $legacy_rows != 4 ]]; then echo "legacy history rows duplicated: $legacy_rows" >&2; exit 1; fi
grep -Fq '| legacy | unknown | 2025-12-30T00:00:00Z | success | 8 |' "$WORK/legacy-new-b.md"
grep -Fq '| legacy | unknown | 2025-12-31T00:00:00Z | success | 10 |' "$WORK/legacy-new-b.md"
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id legacy-new-b --run-attempt 1 \
  --started-at 2026-01-01T11:00:00Z --previous-body "$WORK/legacy-new-b.md" >"$WORK/legacy-new-b-repeat.md"
repeat_legacy_rows=$(grep -Ec '^\| (legacy|legacy-new-[ab]) \|' "$WORK/legacy-new-b-repeat.md")
if [[ $repeat_legacy_rows != 4 ]]; then echo "legacy history repeat changed row count: $repeat_legacy_rows" >&2; exit 1; fi

for metadata_mode in absent malformed; do
  python3 - "$WORK/legacy-new-a.md" "$WORK/legacy-new-a-$metadata_mode.md" "$metadata_mode" <<'PY'
import sys
source, target, mode = sys.argv[1:]
body = open(source, encoding="utf-8").read()
start_marker = "<!-- maxi-quality:history-v2 -->"
end_marker = "<!-- /maxi-quality:history-v2 -->"
start = body.index(start_marker)
end = body.index(end_marker, start) + len(end_marker)
replacement = "{not-json" if mode == "malformed" else ""
open(target, "w", encoding="utf-8").write(body[:start] + start_marker + replacement + end_marker + body[end:])
PY
  python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
    --date 2026-01-01 --run-id "legacy-fallback-$metadata_mode" --run-attempt 1 \
    --started-at 2026-01-01T12:00:00Z --previous-body "$WORK/legacy-new-a-$metadata_mode.md" >"$WORK/legacy-fallback-$metadata_mode.md"
  if [[ $(grep -Ec '^\| (legacy|legacy-new-[ab]|legacy-fallback-[a-z]+) \|' "$WORK/legacy-fallback-$metadata_mode.md") != 4 ]]; then
    echo "legacy $metadata_mode fallback changed row count" >&2
    exit 1
  fi
  grep -Fq '| legacy | unknown | 2025-12-30T00:00:00Z | success | 8 |' "$WORK/legacy-fallback-$metadata_mode.md"
  grep -Fq '| legacy | unknown | 2025-12-31T00:00:00Z | success | 10 |' "$WORK/legacy-fallback-$metadata_mode.md"
done

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
raw = body[start:end].strip()
if raw.startswith("<!--") and raw.endswith("-->"):
    raw = raw[4:-3].strip()
rows = json.loads(raw)
if isinstance(rows, dict):
    rows = dict(rows)
    rows["entries"] = list(rows["entries"])
    rows["entries"][0] = dict(rows["entries"][0])
    rows["entries"][0]["scope"] = {"status": "available", "tools": {"semgrep": {
        "effective": [], "measurements": {"examined": [], "unparsed": None},
        "not_applicable": [{}, [], None, "examined"], "native": {"component_count": {"status": "known", "count": None}},
    }}
    }
else:
    rows = list(rows)
    rows[0]["scope"] = {"status": "available", "tools": {"semgrep": {
        "effective": [], "measurements": {"examined": [], "unparsed": None},
        "not_applicable": [{}, [], None, "examined"], "native": {"component_count": {"status": "known", "count": None}},
    }}
    }
open(target, "w", encoding="utf-8").write(
    body[:start] + "\n" + json.dumps(rows) + "\n" + body[end:]
)
PY
SMALNEXT=$(scope run-two 1 2026-01-01T11:30:00Z)
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-01 --run-id run-two --run-attempt 1 \
  --started-at 2026-01-01T11:30:00Z --scope "$SMALNEXT" --previous-body "$WORK/malformed-history.md" \
  >"$WORK/malformed-history-rendered.md"
grep -q '| run-two | 1 |' "$WORK/malformed-history-rendered.md"
grep -q 'Comparison unavailable:' "$WORK/malformed-history-rendered.md"

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
render "$WORK/two.md" "$WORK/bare-one.md" run-one 2 2026-01-01T11:00:00Z "$S2"
grep -q 'Findings: +0 findings' "$WORK/two.md"
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

# Equal finding counts still reveal changed effective scanner conditions.
SALT=$(scope run-altered 1 2026-01-02T11:00:00Z)
qualify_scope "$SALT" 8 2 1 5
python3 - "$SALT" <<'PY'
import json, sys
path = sys.argv[1]
doc = json.load(open(path, encoding="utf-8"))
doc["tools"]["semgrep"]["effective"]["version"] = "1.173.0"
doc["tools"]["semgrep"]["effective"]["config_fingerprint"] = "altered-config"
json.dump(doc, open(path, "w", encoding="utf-8"))
PY
python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
  --date 2026-01-02 --run-id run-altered --run-attempt 1 \
  --started-at 2026-01-02T11:00:00Z --scope "$SALT" \
  --previous-body "$WORK/qualified.md" >"$WORK/altered.md"
grep -q 'Findings: +0 findings' "$WORK/altered.md"
grep -q 'semgrep effective changed' "$WORK/altered.md"

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

# Malformed optional scope containers must leave the findings report usable and
# make scope evidence explicitly unavailable. The report CLI receives a valid
# scope envelope with analysis replaced by both wrong JSON container types.
for malformed in list null; do
  bad_scope="$WORK/malformed-analysis-$malformed.json"
  python3 - "$S1" "$bad_scope" "$malformed" <<'PY'
import json, sys
source, target, shape = sys.argv[1:]
scope = json.load(open(source))
scope["identity"]["run_id"] = "malformed-analysis-" + shape
scope["identity"]["run_attempt"] = "1"
scope["analysis"] = [] if shape == "list" else None
json.dump(scope, open(target, "w"))
PY
  python3 "$ROOT/scripts/quality-report.py" --json "$WORK/findings.json" \
    --date 2026-01-04 --run-id "malformed-analysis-$malformed" --run-attempt 1 \
    --started-at 2026-01-04T10:00:00Z --scope "$bad_scope" --previous-body "$WORK/one.md" >"$WORK/malformed-analysis-$malformed.md"
  grep -q 'scope artifact analysis metadata is malformed' "$WORK/malformed-analysis-$malformed.md"
  grep -q "| malformed-analysis-$malformed | 1 |" "$WORK/malformed-analysis-$malformed.md"
  grep -q '| run-one | 1 |' "$WORK/malformed-analysis-$malformed.md"
  grep -Fq '| Semgrep | **2** findings |' "$WORK/malformed-analysis-$malformed.md"
done

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
