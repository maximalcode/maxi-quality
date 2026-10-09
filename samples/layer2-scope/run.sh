#!/usr/bin/env bash
# Exercise Layer 2 scope collection at the scanner-command seam.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
cleanup() {
  local rc=$?
  if [[ -f "$WORK/policy-disabled.yml" ]]; then
    mv "$WORK/policy-disabled.yml" samples/policy/exclude/.maxi-quality.yml
  fi
  rm -rf "$WORK"
  return "$rc"
}
trap cleanup EXIT

scope_check() {
  local path="$1" expected="$2"
  python3 - "$path" "$expected" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1]))
assert data["schema_version"] == 1
assert data["kind"] == "layer2-scope"
assert set(data["tools"]) == {"semgrep", "gitleaks", "osv", "licenses", "sbom"}
assert data["analysis"]["outcome"] == sys.argv[2]
assert data["collection"]["status"] in {"complete", "partial"}
assert all(set(tool["measurements"]) == {"examined", "unparsed", "policy_excluded"}
           for tool in data["tools"].values())
print(f"OK: {sys.argv[1]} outcome={data['analysis']['outcome']}")
PY
}

# Clean and explicit skip: disabled optional invocations remain visible.
mkdir "$WORK/clean"
./scripts/scan.sh samples/policy/exclude --skip semgrep --skip gitleaks --skip osv \
  --scope-out "$WORK/clean/scope.json" >"$WORK/clean/log" 2>&1
scope_check "$WORK/clean/scope.json" success
python3 - "$WORK/clean/scope.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert all(d["tools"][name]["state"] == "skipped" for name in ("semgrep", "gitleaks", "osv"))
assert all(m["count"] is None for t in d["tools"].values() for m in t["measurements"].values())
PY

# Findings: the scanner's nonzero verdict survives collection.
mkdir "$WORK/findings"
rc=0
./scripts/scan.sh samples/semgrep --skip gitleaks --skip osv \
  --scope-out "$WORK/findings/scope.json" >"$WORK/findings/log" 2>&1 || rc=$?
[[ "$rc" == 1 ]] || { echo "expected findings exit 1, got $rc" >&2; exit 1; }
scope_check "$WORK/findings/scope.json" failure
python3 - "$WORK/findings/scope.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["tools"]["semgrep"]["state"] == "run"
assert d["tools"]["semgrep"]["outcome"] == "failure"
assert d["tools"]["semgrep"]["diagnostics"]
measurements = d["tools"]["semgrep"]["measurements"]
assert measurements["examined"]["status"] == "known"
assert measurements["examined"]["count"] == 12
assert measurements["unparsed"]["status"] == "known"
assert measurements["unparsed"]["count"] == 0
assert measurements["policy_excluded"]["status"] == "known"
assert measurements["policy_excluded"]["count"] == 0
assert any("attempted=12 target_path" in line and
           "unparsed (overlapping)=0 target_path" in line
           for line in d["summary"]["lines"])
PY

# --no-fail changes the process exit for report mode, but it does not relabel a
# finding run as successful evidence.
mkdir "$WORK/no-fail"
./scripts/scan.sh samples/semgrep --skip gitleaks --skip osv --no-fail \
  --scope-out "$WORK/no-fail/scope.json" >"$WORK/no-fail/log" 2>&1
scope_check "$WORK/no-fail/scope.json" failure

# A real policy fixture proves both sides of the directory exclusion. The
# policy-on scan exposes one selected target and one whole directory path from
# Semgrep's verbose skip list; removing the policy makes both files attempted.
mkdir "$WORK/policy-measure"
rc=0
./scripts/scan.sh samples/policy/exclude --skip gitleaks --skip osv \
  --scope-out "$WORK/policy-measure/on.json" >"$WORK/policy-measure/on.log" 2>&1 || rc=$?
[[ "$rc" == 1 ]] || { echo "expected policy-on findings exit 1, got $rc" >&2; exit 1; }
python3 - "$WORK/policy-measure/on.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
m = d["tools"]["semgrep"]["measurements"]
assert m["examined"]["count"] == 1
assert m["policy_excluded"]["count"] == 1
assert m["policy_excluded"]["unit"] == "target_path"
PY
mv samples/policy/exclude/.maxi-quality.yml "$WORK/policy-disabled.yml"
rc=0
./scripts/scan.sh samples/policy/exclude --skip gitleaks --skip osv \
  --scope-out "$WORK/policy-measure/off.json" >"$WORK/policy-measure/off.log" 2>&1 || rc=$?
[[ "$rc" == 1 ]] || { echo "expected policy-off findings exit 1, got $rc" >&2; exit 1; }
python3 - "$WORK/policy-measure/off.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
m = d["tools"]["semgrep"]["measurements"]
assert m["examined"]["count"] == 2
assert m["policy_excluded"]["count"] == 0
PY

# Semgrep's own ignore mechanism is a separate observed skip reason. It must
# not be reclassified as a project policy exclusion just because a directory
# disappeared from the selected target list.
mkdir "$WORK/default-ignore"
rc=0
./scripts/scan.sh samples/layer2-scope/default-ignore --skip gitleaks --skip osv \
  --scope-out "$WORK/default-ignore/scope.json" >"$WORK/default-ignore/log" 2>&1 || rc=$?
[[ "$rc" == 1 ]] || { echo "expected default-ignore findings exit 1, got $rc" >&2; exit 1; }
python3 - "$WORK/default-ignore/scope.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
m = d["tools"]["semgrep"]["measurements"]
assert m["examined"]["count"] == 1
assert m["policy_excluded"]["count"] == 0
raw = "\n".join(item["text"] for item in d["tools"]["semgrep"]["diagnostics"])
assert "semgrepignore_patterns_match" in raw
PY

# Missing tool/setup evidence: a restricted PATH makes all three resolvers
# unavailable while the scope writer remains available from /usr/bin/python3.
mkdir "$WORK/missing"
mkdir "$WORK/missing/bin"
printf '#!/usr/bin/env bash\nexit 1\n' > "$WORK/missing/bin/docker"
chmod +x "$WORK/missing/bin/docker"
rc=0
PATH="$WORK/missing/bin:/usr/bin:/bin" bash "$ROOT/scripts/scan.sh" samples/policy/exclude --require-tools \
  --scope-out "$WORK/missing/scope.json" >"$WORK/missing/log" 2>&1 || rc=$?
[[ "$rc" == 2 ]] || { echo "expected unavailable-tools exit 2, got $rc" >&2; exit 1; }
scope_check "$WORK/missing/scope.json" failure
python3 - "$WORK/missing/scope.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert all(d["tools"][name]["state"] == "skipped" for name in ("semgrep", "gitleaks", "osv"))
assert all(d["tools"][name]["reason_code"] == "unavailable" for name in ("semgrep", "gitleaks", "osv"))
PY

# An invalid policy fails before Semgrep is invoked and before later scanners
# are reached. The original policy diagnostic remains attached to the blocked
# Semgrep record, while the untouched later records prove they never started.
mkdir "$WORK/policy"
rc=0
./scripts/scan.sh samples/policy/invalid/unknown-key \
  --scope-out "$WORK/policy/scope.json" >"$WORK/policy/log" 2>&1 || rc=$?
[[ "$rc" == 3 ]] || { echo "expected invalid-policy exit 3, got $rc" >&2; exit 1; }
scope_check "$WORK/policy/scope.json" failure
python3 - "$WORK/policy/scope.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
semgrep = d["tools"]["semgrep"]
assert semgrep["state"] == "skipped"
assert semgrep["outcome"] == "failure"
assert semgrep["reason_code"] == "blocked"
diagnostics = "\n".join(item["text"] for item in semgrep["diagnostics"])
assert "unknown" in diagnostics and "rules" in diagnostics
assert all(d["tools"][name]["state"] == "unknown" for name in ("gitleaks", "osv"))
assert all(not d["tools"][name]["diagnostics"] for name in ("gitleaks", "osv"))
PY

# Setup failure path: execute the production finalizer body extracted from the
# composite action. No scanner command is reached; every requested tool is
# explicitly blocked and the setup log is retained as analysis evidence.
mkdir "$WORK/setup"
python3 "$ROOT/scripts/layer2_scope.py" init \
  --out "$WORK/setup/scope.json" --producer gate --workflow fixture \
  --invocation-id setup --run-id setup --run-attempt 1 --job layer2 \
  --commit fixture --ref fixture --mode full
printf 'pinned tool download failed\n' > "$WORK/setup/setup.log"
python3 - "$ROOT/actions/layer2/action.yml" "$WORK/setup/finalize.sh" <<'PY'
import pathlib, sys, textwrap
lines = pathlib.Path(sys.argv[1]).read_text().splitlines(keepends=True)
start = next(i for i, line in enumerate(lines)
             if line == "    - name: Finalize scope after tool setup failure\n")
run = next(i for i in range(start, len(lines)) if lines[i] == "      run: |\n")
end = next((i for i in range(run + 1, len(lines))
            if lines[i].strip() and not lines[i].startswith("        ")), len(lines))
pathlib.Path(sys.argv[2]).write_text(textwrap.dedent("".join(lines[run + 1:end])))
PY
SCOPE_OUT="$WORK/setup/scope.json" \
GITHUB_ACTION_PATH="$ROOT/actions/layer2" \
RUNNER_TEMP="$WORK/setup" \
bash "$WORK/setup/finalize.sh"
python3 - "$ROOT/actions/layer2/action.yml" "$WORK/setup/diagnostic.sh" <<'PY'
import pathlib, sys, textwrap
lines = pathlib.Path(sys.argv[1]).read_text().splitlines(keepends=True)
start = next(i for i, line in enumerate(lines)
             if line == "    - name: Retain setup diagnostics in scope evidence\n")
run = next(i for i in range(start, len(lines)) if lines[i] == "      run: |\n")
end = next((i for i in range(run + 1, len(lines))
            if lines[i].strip() and not lines[i].startswith("        ")), len(lines))
pathlib.Path(sys.argv[2]).write_text(textwrap.dedent("".join(lines[run + 1:end])))
PY
SCOPE_OUT="$WORK/setup/scope.json" \
SETUP_LOG="$WORK/setup/setup.log" \
GITHUB_ACTION_PATH="$ROOT/actions/layer2" \
bash "$WORK/setup/diagnostic.sh"
python3 - "$WORK/setup/scope.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["analysis"]["outcome"] == "failure"
assert any("pinned tool download failed" in item["text"] for item in d["analysis"]["diagnostics"])
assert all(d["tools"][name]["state"] == "skipped" for name in ("semgrep", "gitleaks", "osv", "licenses", "sbom"))
assert all(d["tools"][name]["reason_code"] == "setup_failure" for name in ("semgrep", "gitleaks", "osv"))
assert all(d["tools"][name]["reason_code"] == "blocked" for name in ("licenses", "sbom"))
print("OK: extracted action setup-failure finalization and diagnostics")
PY

# Boundary scanner failure plus multiline diagnostics.
mkdir -p "$WORK/stub/bin"
cat > "$WORK/stub/bin/semgrep" <<'SH'
#!/usr/bin/env bash
printf 'first scanner error\nsecond scanner line\n' >&2
exit 9
SH
chmod +x "$WORK/stub/bin/semgrep"
mkdir "$WORK/stub/result"
rc=0
PATH="$WORK/stub/bin:/usr/bin:/bin" bash "$ROOT/scripts/scan.sh" samples/policy/exclude \
  --skip gitleaks --skip osv --scope-out "$WORK/stub/result/scope.json" >"$WORK/stub/result/log" 2>&1 || rc=$?
[[ "$rc" == 1 ]] || { echo "expected scanner failure exit 1, got $rc" >&2; exit 1; }
scope_check "$WORK/stub/result/scope.json" failure
grep -q 'first scanner error' "$WORK/stub/result/log"
python3 - "$WORK/stub/result/scope.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
text = d["tools"]["semgrep"]["diagnostics"][0]["text"]
assert "first scanner error" in text and "second scanner line" in text
PY

# Result-file boundaries: fatal JSON, malformed JSON, and missing JSON retain
# their raw evidence or expose the collection gap without changing the exit.
cat > "$WORK/stub/bin/semgrep" <<'SH'
#!/usr/bin/env bash
if [[ "${1:-}" == --version ]]; then
  echo 1.172.0
  exit 0
fi
for arg in "$@"; do
  if [[ "$arg" == --json-output=* ]]; then
    path="${arg#--json-output=}"
    case "${STUB_MODE:-missing}" in
      fatal) printf '{"errors":[{"type":"ScanError","message":"first error\nsecond error"}],"results":[]}' > "$path" ;;
      malformed) printf 'not json\nsecond malformed line\n' > "$path" ;;
    esac
  fi
done
exit 0
SH
chmod +x "$WORK/stub/bin/semgrep"
for mode in fatal malformed missing; do
  mkdir "$WORK/stub/$mode"
  rc=0
  STUB_MODE="$mode" PATH="$WORK/stub/bin:/usr/bin:/bin" bash "$ROOT/scripts/scan.sh" \
    samples/policy/exclude --skip gitleaks --skip osv \
    --scope-out "$WORK/stub/$mode/scope.json" >"$WORK/stub/$mode/log" 2>&1 || rc=$?
  [[ "$rc" == 1 ]] || { echo "expected $mode exit 1, got $rc" >&2; exit 1; }
  python3 - "$WORK/stub/$mode/scope.json" "$mode" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
mode = sys.argv[2]
diagnostics = d["tools"]["semgrep"]["diagnostics"]
text = "\n".join(item["text"] for item in diagnostics)
if mode == "fatal":
    assert '"errors"' in text and "first error" in text and "second error" in text
elif mode == "malformed":
    assert "not json" in text and "second malformed line" in text
    assert d["collection"]["status"] == "partial"
else:
    assert d["collection"]["status"] == "partial"
    assert any("diagnostic unavailable" in issue for issue in d["collection"]["issues"])
print(f"OK: {mode} Semgrep result evidence")
PY
done

# A malformed or missing artifact is a collection error, not a clean summary.
rc=0
python3 "$ROOT/scripts/layer2_scope.py" summary --out "$WORK/no-such.json" >/dev/null 2>&1 || rc=$?
[[ "$rc" == 2 ]] || { echo "missing artifact was accepted" >&2; exit 1; }
printf 'not json\n' > "$WORK/malformed.json"
rc=0
python3 "$ROOT/scripts/layer2_scope.py" summary --out "$WORK/malformed.json" >/dev/null 2>&1 || rc=$?
[[ "$rc" == 2 ]] || { echo "malformed artifact was accepted" >&2; exit 1; }

# A scope writer failure cannot change the scanner verdict.
mkdir "$WORK/fault"
rc=0
./scripts/scan.sh samples/semgrep --skip gitleaks --skip osv --scope-out "$WORK/fault" \
  >/dev/null 2>&1 || rc=$?
[[ "$rc" == 1 ]] || { echo "scope writer fault changed findings exit to $rc" >&2; exit 1; }

echo 'OK: Layer 2 scope scanner-command failure and collection seams'
