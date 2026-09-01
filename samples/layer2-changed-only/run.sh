#!/usr/bin/env bash
# Drive the production Layer 2 scan step with real Git and pinned Semgrep.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
cleanup() {
  local rc=$?
  if (( rc == 0 )); then
    rm -rf "$WORK"
  else
    echo "Fixture evidence retained in $WORK" >&2
  fi
}
trap cleanup EXIT

# Do not resolve a substitute scanner or download one on a cache miss.
command -v semgrep >/dev/null || { echo 'Pinned native Semgrep is required' >&2; exit 1; }
# Version checks should not make this local Git fixture depend on a service.
export SEMGREP_ENABLE_VERSION_CHECK=0
PIN=$(sed -n '/^  semgrep-version:/,/^  [a-z].*:/s/^    default: '\''\([^'\'']*\)'\''/\1/p' \
  "$ROOT/actions/layer2/action.yml")
VERSION=$(semgrep --version 2>/dev/null | tr -d '[:space:]')
[[ "$VERSION" == "$PIN" ]] || { echo "Need Semgrep $PIN, found $VERSION" >&2; exit 1; }
echo "Semgrep $VERSION; $(git --version); $(python3 --version)"

# Extract the action's actual scan step, without reimplementing its fetch or
# scan invocation. The other action steps install tools and are not run here.
python3 - "$ROOT/actions/layer2/action.yml" "$WORK/action.sh" <<'PY'
import pathlib
import sys
import textwrap

lines = pathlib.Path(sys.argv[1]).read_text().splitlines(keepends=True)
step = next(i for i, line in enumerate(lines) if line == "      id: scan\n")
start = next(i for i in range(step, len(lines)) if lines[i] == "      run: |\n") + 1
end = next((i for i in range(start, len(lines))
            if lines[i].strip() and not lines[i].startswith("        ")), len(lines))
pathlib.Path(sys.argv[2]).write_text(textwrap.dedent("".join(lines[start:end])))
PY

# Only the unrelated external scanners are isolated. Git, Semgrep, scan.sh and
# the action body are real; these shims prevent OSV network/tool downloads.
mkdir "$WORK/bin"
printf '#!/usr/bin/env bash\necho "fixture: gitleaks isolated"\nexit 0\n' > "$WORK/bin/gitleaks"
printf '#!/usr/bin/env bash\necho "fixture: osv isolated"\nexit 128\n' > "$WORK/bin/osv-scanner"
chmod +x "$WORK/bin/"*
export PATH="$WORK/bin:$PATH"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

run_action() {
  local target="$1" label="$2"
  mkdir "$WORK/$label"
  ACTION_RC=0
  env TARGET="$target" JSON_OUT="$WORK/$label/results.json" SBOM_OUT='' LICENSES='' \
    NO_FAIL=false CHANGED_ONLY=origin/main ANNOTATE=false MAX_ANNOTATIONS=50 \
    WORKSPACE="$target" GITHUB_ACTION_PATH="$ROOT/actions/layer2" \
    RUNNER_TEMP="$WORK/$label" GITHUB_OUTPUT="$WORK/$label/outputs" \
    bash "$WORK/action.sh" > "$WORK/$label/action.log" 2>&1 || ACTION_RC=$?
  echo "$label: action exit $ACTION_RC; $(sed -n '/^semgrep=/p' "$WORK/$label/outputs")"
}

SOURCE="$WORK/source"
git init -q --initial-branch=main "$SOURCE"
git -C "$SOURCE" config user.name fixture
git -C "$SOURCE" config user.email fixture@example.invalid
printf 'export function existing() { return new Date(); }\n' > "$SOURCE/old.ts"
git -C "$SOURCE" add old.ts
git -C "$SOURCE" commit -qm baseline
# 205 reachable commits: --depth=200 must not discard any of them.
TREE=$(git -C "$SOURCE" rev-parse 'HEAD^{tree}')
TIP=$(git -C "$SOURCE" rev-parse HEAD)
for ((i=1; i<205; i++)); do
  TIP=$(git -C "$SOURCE" commit-tree "$TREE" -p "$TIP" -m "history $i")
done
git -C "$SOURCE" update-ref refs/heads/main "$TIP"
git clone -q "file://$SOURCE" "$WORK/complete"
git -C "$WORK/complete" rev-list --all | sort > "$WORK/before"
run_action "$WORK/complete" complete-history
git -C "$WORK/complete" rev-list --all | sort > "$WORK/after"
SHALLOW=$(git -C "$WORK/complete" rev-parse --is-shallow-repository)
echo "complete-history: shallow=$SHALLOW; commits $(wc -l < "$WORK/before" | tr -d ' ') -> $(wc -l < "$WORK/after" | tr -d ' ')"
[[ "$SHALLOW" == false ]] || { echo 'FAIL: complete checkout became shallow' >&2; exit 1; }
cmp "$WORK/before" "$WORK/after"
[[ "$ACTION_RC" == 0 ]] || { cat "$WORK/complete-history/action.log"; exit 1; }
echo 'OK: complete checkout preserves all 205 commits'

check_findings() {
  local label="$1" expected="$2"
  python3 - "$WORK/$label/results.json" "$expected" <<'PY'
import json
import pathlib
import sys

doc = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert not doc["errors"], doc["errors"]
findings = sorted((row["check_id"].split(".")[-1], row["path"], row["start"]["line"])
                  for row in doc["results"])
expected = [] if sys.argv[2] == "none" else [("no-ambient-clock", sys.argv[2], 1)]
print(f"{pathlib.Path(sys.argv[1]).parent.name}: findings={findings}")
assert findings == expected, (findings, expected)
PY
}

# A PR edits the file containing the existing violation. This forces baseline
# filtering to exclude it; merely skipping an unchanged file proves less.
git -C "$SOURCE" checkout -qb feature
printf '// A harmless PR edit keeps the existing finding on line 1.\n' >> "$SOURCE/old.ts"
git -C "$SOURCE" commit -qam 'touch existing file'
git -C "$SOURCE" checkout -qb pr-clean main
git -C "$SOURCE" merge -q --no-ff feature -m 'synthesized clean PR merge'

# Sanity: the base violation is active under the real rules and scanner.
mkdir "$WORK/full-scan"
SANITY_RC=0
"$ROOT/scripts/scan.sh" "$SOURCE" --skip gitleaks --skip osv --require-tools \
  --json-out "$WORK/full-scan/results.json" > "$WORK/full-scan/scan.log" 2>&1 || SANITY_RC=$?
[[ "$SANITY_RC" == 1 ]] || { cat "$WORK/full-scan/scan.log"; exit 1; }
echo "full-scan: scan.sh exit $SANITY_RC"
check_findings full-scan old.ts

git clone -q --branch pr-clean "file://$SOURCE" "$WORK/full-clean"
run_action "$WORK/full-clean" full-clean-result
[[ "$ACTION_RC" == 0 ]] || { cat "$WORK/full-clean-result/action.log"; exit 1; }
check_findings full-clean-result none

# Match actions/checkout's depth-one detached merge HEAD: no parents and no
# base branch initially, while the remote can supply the missing history.
git init -q "$WORK/shallow-clean"
git -C "$WORK/shallow-clean" remote add origin "file://$SOURCE"
git -C "$WORK/shallow-clean" fetch -q --depth=1 origin pr-clean
git -C "$WORK/shallow-clean" checkout -q --detach FETCH_HEAD
[[ "$(git -C "$WORK/shallow-clean" rev-list --count HEAD)" == 1 ]]
run_action "$WORK/shallow-clean" shallow-clean-result
[[ "$ACTION_RC" == 0 ]] || { cat "$WORK/shallow-clean-result/action.log"; exit 1; }
check_findings shallow-clean-result none
echo 'OK: complete and shallow PR checkouts both exclude the existing finding'

# Add one new violation to the same PR, retaining the harmless old.ts edit.
git -C "$SOURCE" checkout -q feature
printf 'export function introduced() { return new Date(); }\n' > "$SOURCE/new.ts"
git -C "$SOURCE" add new.ts
git -C "$SOURCE" commit -qm 'new violation'
git -C "$SOURCE" checkout -qb pr-new main
git -C "$SOURCE" merge -q --no-ff feature -m 'synthesized PR merge with new violation'

git clone -q --branch pr-new "file://$SOURCE" "$WORK/full-new"
run_action "$WORK/full-new" full-new-result
[[ "$ACTION_RC" == 1 ]] || { cat "$WORK/full-new-result/action.log"; exit 1; }
grep -qx 'semgrep=FINDINGS' "$WORK/full-new-result/outputs"
check_findings full-new-result new.ts

git init -q "$WORK/shallow-new"
git -C "$WORK/shallow-new" remote add origin "file://$SOURCE"
git -C "$WORK/shallow-new" fetch -q --depth=1 origin pr-new
git -C "$WORK/shallow-new" checkout -q --detach FETCH_HEAD
[[ "$(git -C "$WORK/shallow-new" rev-list --count HEAD)" == 1 ]]
run_action "$WORK/shallow-new" shallow-new-result
[[ "$ACTION_RC" == 1 ]] || { cat "$WORK/shallow-new-result/action.log"; exit 1; }
grep -qx 'semgrep=FINDINGS' "$WORK/shallow-new-result/outputs"
check_findings shallow-new-result new.ts
echo 'OK: complete and shallow PR checkouts both report only new.ts:1'
