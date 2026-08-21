#!/usr/bin/env python3
"""Assert that configs/editor/ still says what the editor contract claims.

WHY THIS EXISTS

configs/editor/ is the one thing in this repo that NOTHING RUNS. Every other
config is proven by a sample that fails without it: delete a ruff family and
samples/python stops matching its manifest. A .vscode/settings.json cannot be
exercised in CI at all — there is no headless VS Code here — so the failure
mode is the one CONTRIBUTING.md warns about in every other form: a file that is
present, plausible, and pins nothing.

Four things this refuses to let happen quietly:

  1. A key with no justification. "Every key names the CI behaviour it pins" is
     issue #120's first acceptance criterion, and the thing it exists to catch
     is a settings file cargo-culted from a blog post. So the NEAREST PRECEDING
     NON-BLANK line of every setting id must be a comment — which also means
     one comment block cannot cover two adjacent keys.
  2. A verified divergence silently dropped, or a value edited away from what
     README.md §1 records. The doc and the templates are two statements of the
     same fact and they must not drift.
  3. C# Dev Kit recommended. It is a licensing trap for exactly the audience a
     free baseline serves (README.md §2), and VS Code offers it unprompted, so
     merely omitting it is not a decision the adopter ever sees.
  4. An expectation manifest the contract does not know about. README.md §3 is
     the source step 3's parity run diffs the Problems panel against; a
     manifest missing from that table is parity measured against nothing.

Plus the shape-guard the rest of this repo uses: a language that ships a config
must have a fragment, so the next language cannot arrive with the editor
contract silently not covering it.

Reads only committed files. Does no network I/O and writes nothing.

Exit codes: 0 the contract holds - 1 it drifted
"""
import json, pathlib, re, sys

D = pathlib.Path("configs/editor")
fail = []
def bad(msg): fail.append(msg)

# --- JSONC -> JSON, comment-aware and string-aware -------------------------
def split_comments(text):
    """Return (stripped_text, is_comment_line[]) preserving line count."""
    out, i, n = [], 0, len(text)
    in_str = esc = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if c == "/" and i + 1 < n and text[i+1] == "/":
            while i < n and text[i] != "\n": i += 1
            continue
        if c == "/" and i + 1 < n and text[i+1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i+1] == "/"):
                if text[i] == "\n": out.append("\n")
                i += 1
            i += 2; continue
        out.append(c); i += 1
    return "".join(out)

def load(path):
    raw = path.read_text()
    try:
        return raw, json.loads(split_comments(raw))
    except json.JSONDecodeError as e:
        bad(f"{path}: does not parse as JSONC ({e})")
        return raw, None

# --- G1: every documented unit carries a justification ---------------------
# depth-1 keys need a comment above them; deeper lines inherit from the depth-1
# key that encloses them. extensions.json's array ELEMENTS are the unit there,
# so they are checked at depth 2 as well.
def check_annotations(path, raw, extra_depth=()):
    stripped = split_comments(raw).split("\n")
    lines = raw.split("\n")
    depth = 0
    for i, sl in enumerate(stripped):
        start_depth = depth
        depth += sl.count("{") + sl.count("[") - sl.count("}") - sl.count("]")
        body = sl.strip()
        if not body:
            continue
        is_key = start_depth == 1 and body.startswith('"')
        is_elem = start_depth in extra_depth and body.startswith('"')
        if not (is_key or is_elem):
            continue
        # The NEAREST PRECEDING NON-BLANK line must be a comment. Blank lines
        # are skipped so a justification may sit above a blank; anything else
        # above it (another key, a brace) is not a justification. One comment
        # block therefore cannot cover two adjacent keys.
        j = i - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j < 0 or not lines[j].strip().startswith("//"):
            bad(f"{path}:{i+1}: {body[:48]} has no justification comment above it")

# --- run -------------------------------------------------------------------
frags = sorted(D.glob("*.settings.json"))

# G6: a language that ships a config must have a fragment.
langs = {p.name for p in pathlib.Path("configs").iterdir()
         if p.is_dir() and p.name != "editor"}
for lang in sorted(langs):
    if not (D / f"{lang}.settings.json").exists():
        bad(f"configs/{lang}/ ships a config but configs/editor/{lang}.settings.json "
            "does not exist — the editor contract does not cover it")
if len(frags) < len(langs) + 1:   # +1 for semgrep, which is a layer not a language
    bad(f"found only {len(frags)} settings fragments — this guard stopped guarding")

for p in frags:
    raw, doc = load(p)
    if doc is None: continue
    check_annotations(p, raw)

raw_ext, ext = load(D / "extensions.json")
if ext is not None:
    check_annotations(D / "extensions.json", raw_ext, extra_depth=(2,))
    rec = ext.get("recommendations", [])
    unw = ext.get("unwantedRecommendations", [])
    # G2: the licensing trap
    if "ms-dotnettools.csharp" not in rec:
        bad("extensions.json does not recommend ms-dotnettools.csharp")
    if "ms-dotnettools.csdevkit" not in unw:
        bad("extensions.json does not list ms-dotnettools.csdevkit as UNWANTED — "
            "omitting it is not enough, VS Code steers users to it on its own (#120)")
    if "ms-dotnettools.csdevkit" in rec:
        bad("extensions.json RECOMMENDS C# Dev Kit — that is the licensing trap")

# G4: each verified divergence must survive in the fragment that closes it
DIVERGENCES = [
    ("semgrep.settings.json", "semgrep.scan.onlyGitDirty", False),
    ("python.settings.json",  "mypy-type-checker.importStrategy", "fromEnvironment"),
    ("python.settings.json",  "mypy-type-checker.reportingScope", "workspace"),
    ("rust.settings.json",    "rust-analyzer.check.command", "clippy"),
    ("dotnet.settings.json",  "dotnet.backgroundAnalysis.analyzerDiagnosticsScope", "fullSolution"),
    ("typescript.settings.json", "typescript.tsdk", "node_modules/typescript/lib"),
]
for fname, key, want in DIVERGENCES:
    _, doc = load(D / fname)
    if doc is None: continue
    if key not in doc:
        bad(f"{fname} no longer sets {key} — a verified divergence (README §1) "
            "was dropped without the doc changing")
    elif doc[key] != want:
        bad(f"{fname} sets {key} to {doc[key]!r}, README §1 says {want!r}")

# G3: every committed expectation manifest is named in the contract doc
readme = (D / "README.md").read_text()
manifests = sorted(p.name for p in pathlib.Path("samples/expected").glob("*.json"))
for m in manifests:
    if m not in readme:
        bad(f"samples/expected/{m} is not named in configs/editor/README.md — "
            "step 3 would measure parity against a manifest the contract "
            "does not know exists")
for m in re.findall(r"samples/expected/([A-Za-z0-9._-]+\.json)", readme):
    if m not in manifests:
        bad(f"configs/editor/README.md names samples/expected/{m}, which does not exist")
if len(manifests) < 15:
    bad(f"found only {len(manifests)} manifests — this guard stopped guarding")

if fail:
    for f in fail: print(f"::error::{f}")
    sys.exit(1)
print(f"OK: {len(frags)} fragments annotated, {len(DIVERGENCES)} verified "
      f"divergences still pinned, C# Dev Kit excluded, all {len(manifests)} "
      "expectation manifests named in the contract")
