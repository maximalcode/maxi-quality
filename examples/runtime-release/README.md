# Runtime installation diagnosis example

This copyable, invented Adopter checkout has a declared gate (`python3 gate.py`)
and a real expectation manifest under `samples/expected/`. Its gate checks that
Python's JSON parser rejects the intentionally incomplete text fixture at the
expected line. Fixing or deleting that fixture makes the gate fail.

Run this complete block in Bash from the maxi-quality repository root, with
Python 3 and Git available. It copies this directory into a temporary Git
checkout, prepares an isolated cache from the current committed baseline, and
uses the checkout's public launcher directly. The development version below is
only a local demonstration label; it does not publish or install a release.
For a released installation, follow [the runtime guide](../../docs/QUALITY-RUNTIME.md).

```bash
set -eu
baseline_root=$(git rev-parse --show-toplevel)
demo_root=$(mktemp -d "${TMPDIR:-/tmp}/runtime-example.XXXXXX")
adopter_root="$demo_root/adopter"
runtime="$baseline_root/scripts/quality-runtime.py"
runtime_commit=$(git -C "$baseline_root" rev-parse HEAD)
runtime_version=v0.0.0-diagnosis-example
cp -R "$baseline_root/examples/runtime-release" "$adopter_root"
git -C "$adopter_root" init --quiet
python3 "$runtime" prepare --source "$baseline_root" \
  --version "$runtime_version" --commit "$runtime_commit" \
  --cache-root "$demo_root/cache" --allow-untagged-development
python3 "$baseline_root/scripts/quality-runtime-migrate.py" \
  --target "$adopter_root" --version "$runtime_version" \
  --commit "$runtime_commit" --launcher "$runtime"

# Prove the example's declared gate works, explicitly through the recorder.
python3 "$runtime" record-gate --root "$adopter_root" \
  --cache-root "$demo_root/cache" --gate

# Both readable and JSON diagnosis exit 0 for the healthy installation.
python3 "$runtime" diagnose --root "$adopter_root" --cache-root "$demo_root/cache"
python3 "$runtime" diagnose --root "$adopter_root" \
  --cache-root "$demo_root/cache" --json > "$demo_root/healthy.json"
cat "$demo_root/healthy.json"

# Keep an exact backup, then deliberately narrow the owned sample matcher.
cp "$adopter_root/.claude/settings.json" "$demo_root/settings.backup.json"
python3 - "$adopter_root/.claude/settings.json" <<'PY'
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
settings = json.loads(path.read_text())
groups = [group for group in settings["hooks"]["PreToolUse"]
          if group.get("matcher") == "Edit|Write|MultiEdit"]
assert len(groups) == 1
groups[0]["matcher"] = "Edit|Write"
path.write_text(json.dumps(settings, indent=2) + "\n")
PY

# The same public entry point now exits nonzero.
if python3 "$runtime" diagnose --root "$adopter_root" \
  --cache-root "$demo_root/cache" --json > "$demo_root/broken.json"; then
  echo "Unexpected success for the broken matcher" >&2
  exit 1
fi
cat "$demo_root/broken.json"

# Restore the exact settings and verify that diagnosis returns to exit 0.
cp "$demo_root/settings.backup.json" "$adopter_root/.claude/settings.json"
python3 "$runtime" diagnose --root "$adopter_root" \
  --cache-root "$demo_root/cache" --json > "$demo_root/restored.json"
echo "Example checkout and reports: $demo_root"
```

The healthy report names the pinned version and commit, the
`versioned-with-samples` installation profile, the gate, and the cache and
wiring checks. The broken report identifies `hook-sample-guard` as failed.
Both reports say `live_enforcement: unverified`; a static read cannot establish
that an agent host executed a hook. Host settings and overrides also remain
`unverified`. Diagnosis itself does not edit the checkout or run its gate.

The directory printed at the end is disposable; remove it when finished.
`python3 samples/runtime-release/test_runtime.py` runs this exact README block
and checks all three reports, alongside the profiles without sample protection,
with guards disabled, and with legacy copied or shared installation.
