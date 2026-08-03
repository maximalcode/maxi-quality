#!/usr/bin/env bash
# Snapshot the MSBuild properties configs/dotnet/Directory.Build.props actually
# RESOLVES TO, and fail when one silently disappears.
#
# WHY THIS EXISTS, AND WHY THE FIXTURE IS NOT ENOUGH
#
# The .NET twin of scripts/snapshot-tsconfig.mjs and
# scripts/snapshot-eslint-rules.mjs, and it exists for the same measured reason
# (#8). samples/dotnet pins the diagnostics the config produces, which catches a
# setting that stops firing on something we bait. Several settings bake no
# diagnostic out at all:
#
#   - TreatWarningsAsErrors and WarningLevel change the SEVERITY of other
#     diagnostics, not the set of them. Drop either and the sample still fails,
#     just differently, and the finding manifest cannot tell.
#   - RestoreLockedMode is conditional on ContinuousIntegrationBuild AND a
#     packages.lock.json existing. Neither holds in samples/dotnet, so nothing
#     the sample does can observe it — and it is the property that decides
#     whether a consumer's dependency scan sees transitive packages at all
#     (README, the .NET trade-off).
#   - Deterministic and GenerateDocumentationFile are silent by construction.
#
# IT IS `dotnet msbuild -getProperty:`, NOT A READ OF THE XML. Reading the file
# would assert what we wrote; -getProperty asserts what MSBuild resolved, after
# conditions and after any SDK default that would override us.
#
# TWO PASSES, because RestoreLockedMode is conditional and a single pass would
# snapshot the empty string and call it covered. The second pass sets
# ContinuousIntegrationBuild and plants a lock file, which is the CI shape a
# consumer who opted in actually has.
#
# A .NET SDK upgrade CAN change this snapshot — a changed default, a new implied
# property. That is intended, and matches the policy for the other two
# snapshots: the bump PR is where a human reads the diff and decides.
# Regenerate with --write and say in the commit message what moved and why.
#
# Usage:
#   scripts/snapshot-msbuild-props.sh --check    # CI: diff against the snapshot
#   scripts/snapshot-msbuild-props.sh --write    # regenerate it deliberately
#
# Exit codes: 0 snapshot matches · 1 the resolved properties drifted · 3 usage error
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAPSHOT="$REPO/configs/dotnet/msbuild.snapshot.json"
PROJECT="$REPO/samples/dotnet"

MODE="${1:-}"
if [[ "$MODE" != "--check" && "$MODE" != "--write" ]]; then
  echo "usage: snapshot-msbuild-props.sh --check | --write" >&2
  exit 3
fi

# Every property the baseline sets, plus the two the SDK would otherwise pick
# for us. Adding a property to Directory.Build.props means adding it here — the
# snapshot cannot notice a setting it was never asked about, and that limit is
# stated rather than hidden.
PROPS=(
  AnalysisLevel
  AnalysisMode
  Deterministic
  EnforceCodeStyleInBuild
  GenerateDocumentationFile
  ImplicitUsings
  LangVersion
  Nullable
  RestoreLockedMode
  TreatWarningsAsErrors
  WarningLevel
)

args=()
for p in "${PROPS[@]}"; do args+=("-getProperty:$p"); done

# Pass 1: the shape a consumer has by default — no lock file, not a CI build.
plain="$(cd "$PROJECT" && dotnet msbuild "${args[@]}")"

# Pass 2: the opted-in CI shape, so the conditional property is observable.
# The lock file is a throwaway; `dotnet msbuild` only needs it to EXIST for the
# Exists() condition, and it is removed however this script leaves.
LOCK="$PROJECT/packages.lock.json"
cleanup() { [[ -f "$LOCK" ]] && rm -f "$LOCK"; return 0; }
trap cleanup EXIT
echo '{"version": 1, "dependencies": {}}' > "$LOCK"
locked="$(cd "$PROJECT" && dotnet msbuild -p:ContinuousIntegrationBuild=true "${args[@]}")"
cleanup
trap - EXIT

serialised="$(python3 - "$plain" "$locked" <<'PY'
import json, sys
plain = json.loads(sys.argv[1])["Properties"]
locked = json.loads(sys.argv[2])["Properties"]
out = {
    "default": dict(sorted(plain.items())),
    "ci_with_lock_file": dict(sorted(locked.items())),
}
print(json.dumps(out, indent=2))
PY
)"

if [[ "$MODE" == "--write" ]]; then
  printf '%s\n' "$serialised" > "$SNAPSHOT"
  echo "wrote ${SNAPSHOT#"$REPO"/} — ${#PROPS[@]} properties in 2 configurations"
  exit 0
fi

if [[ ! -f "$SNAPSHOT" ]]; then
  echo "::error::${SNAPSHOT#"$REPO"/} is missing. Run: scripts/snapshot-msbuild-props.sh --write" >&2
  exit 1
fi

if diff -q <(printf '%s\n' "$serialised") "$SNAPSHOT" >/dev/null; then
  echo "msbuild snapshot matches — ${#PROPS[@]} properties in 2 configurations"
  exit 0
fi

# Name what moved. A bare "files differ" leaves two JSON blobs to diff by eye,
# and the whole point of this check is that a DELETED property is easy to miss.
echo '::error::the resolved MSBuild properties drifted:' >&2
diff -u "$SNAPSHOT" <(printf '%s\n' "$serialised") >&2 || true
echo 'If this was deliberate, regenerate with: scripts/snapshot-msbuild-props.sh --write' >&2
exit 1
