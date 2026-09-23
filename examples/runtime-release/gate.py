"""Assert that the example's invalid JSON still fails Python's JSON parser."""

import json
from pathlib import Path

root = Path(__file__).resolve().parent
sample = "samples/invalid.txt"
findings = []
try:
    json.loads((root / sample).read_text(encoding="utf-8"))
except json.JSONDecodeError as error:
    findings.append({"rule": "invalid-json", "file": sample, "line": error.lineno})

expected = json.loads((root / "samples/expected/json.json").read_text(encoding="utf-8"))
if findings != expected["findings"]:
    raise SystemExit("JSON sample findings drifted from samples/expected/json.json")
print("JSON sample: expected parser failure verified")
