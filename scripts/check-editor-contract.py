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

     Stated precisely, because a guard that overstates itself is worse than
     none: this checks a comment is PRESENT, never that it names a real CI
     behaviour. The second half is a review job and is not mechanisable.
  2. A verified divergence silently dropped, or a value edited away from what
     README.md §1 records. §1's "contract values" block is the SOURCE — this
     script parses it rather than carrying its own copy, so the doc and the
     templates cannot drift apart in either direction. An earlier version kept
     the values as a constant here, which pinned script-to-template and left
     the doc free to say anything.
  3. C# Dev Kit recommended. It is a licensing trap for exactly the audience a
     free baseline serves (README.md §2), and VS Code offers it unprompted, so
     merely omitting it is not a decision the adopter ever sees.
  4. An expectation manifest the contract does not know about. README.md §3 is
     the source step 3's parity run diffs the Problems panel against; a
     manifest missing from that table is parity measured against nothing.

Plus the shape-guard the rest of this repo uses: a language that ships a config
must have a fragment, so the next language cannot arrive with the editor
contract silently not covering it.

And since #126 the fragments are no longer only copied by hand —
`scripts/editor-settings.py` composes them into a consumer's `.vscode/` files.
That adds a second way for this contract to rot quietly: a template row the
composer has no rule for, or a composer rule for a row that no longer exists.
Neither is visible in a diff of either file alone, so both are asserted here.

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

def mask_strings(text):
    """Blank every string's CONTENTS, keeping the quotes and the length.

    The structural pass below counts braces to track nesting depth, and a brace
    inside a VALUE would miscount it — "${workspaceFolder}" only survives
    because its pair happens to balance. Masking first means the depth counter
    reads structure and never data.
    """
    out, i, n = [], 0, len(text)
    in_str = esc = False
    while i < n:
        c = text[i]
        if in_str:
            if esc:
                esc = False; out.append("x")
            elif c == "\\":
                esc = True; out.append("x")
            elif c == '"':
                in_str = False; out.append(c)
            else:
                out.append("\n" if c == "\n" else "x")
        else:
            out.append(c)
            if c == '"':
                in_str = True
        i += 1
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
    stripped = mask_strings(split_comments(raw)).split("\n")
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
            bad(f"{path}:{i+1}: {lines[i].strip()[:48]} has no "
                "justification comment above it")

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

readme = (D / "README.md").read_text()

# --- G4: the doc is the SOURCE, and the fragments must agree with it --------
# The values used to be a constant in this file, which pinned script<->template
# and could not see the doc drift at all — README §1 could be edited to say
# anything and this exited 0. Now §1's "The contract values, in one place" block
# IS the constant: one statement of the fact, checked against the templates in
# both directions.
section = readme.split("### The contract values, in one place", 1)
if len(section) != 2:
    bad("configs/editor/README.md no longer has the 'contract values' block — "
        "this guard has nothing to check the fragments against")
    divergences = []
else:
    block = section[1].split("```")[1]
    divergences = []
    for line in block.strip().splitlines():
        m = re.match(r"^(\S+\.settings\.json)\s+(\S+)\s*=\s*(.+?)\s*$", line)
        if not m:
            bad(f"unparseable line in the contract-values block: {line!r}")
            continue
        try:
            want = json.loads(m.group(3))
        except json.JSONDecodeError:
            bad(f"contract-values block: {m.group(3)!r} is not a JSON value")
            continue
        divergences.append((m.group(1), m.group(2), want))

if len(divergences) < 6:
    bad(f"the contract-values block lists only {len(divergences)} settings — "
        "README §1 documents six verified divergences, so this guard stopped "
        "guarding")

for fname, key, want in divergences:
    target = D / fname
    if not target.exists():
        bad(f"the contract-values block names {fname}, which does not exist")
        continue
    _, doc = load(target)
    if doc is None: continue
    if key not in doc:
        bad(f"{fname} no longer sets {key} — README §1 says it must")
    elif doc[key] != want:
        bad(f"{fname} sets {key} to {doc[key]!r}, README §1 says {want!r}")

# --- every section this directory cites must exist --------------------------
# A dangling "§N" is how a doc rots without anyone noticing: the sentence still
# reads fine and points at nothing. Caught a real one (§0) the first time it ran.
headings = {int(m) for m in re.findall(r"^## (\d+)\.", readme, re.M)}
cited = set()
for q in sorted(D.iterdir()):
    if q.suffix not in (".md", ".json"): continue
    for m in re.findall(r"\u00a7(\d+)", q.read_text()):
        if int(m) not in headings:
            bad(f"{q} cites README \u00a7{m}, which is not a section")
        cited.add(int(m))
if not headings:
    bad("configs/editor/README.md has no numbered sections — this guard "
        "stopped guarding")

# --- G3: every expectation manifest is named in §3's table ------------------
# Scoped to §3, not to the whole file: a filename mentioned in passing anywhere
# else is not the same as a row in the table step 3 diffs against.
try:
    s3 = readme.split("## 3. The authoritative expectation source", 1)[1].split("\n## ", 1)[0]
except IndexError:
    s3 = ""
    bad("configs/editor/README.md has no §3 — the expectation-source table is gone")
manifests = sorted(q.name for q in pathlib.Path("samples/expected").glob("*.json"))
for m in manifests:
    if m not in s3:
        bad(f"samples/expected/{m} is not named in README §3 — step 3 would "
            "measure parity against a manifest the contract does not know exists")
for m in re.findall(r"samples/expected/([A-Za-z0-9._-]+\.json)", s3):
    if m not in manifests:
        bad(f"README §3 names samples/expected/{m}, which does not exist")
# No numeric floor here on purpose: the check above is BIDIRECTIONAL, so a
# deleted manifest fails as "README §3 names X, which does not exist". An
# arbitrary minimum would only add slack.
if not manifests:
    bad("samples/expected/ is empty — this guard stopped guarding")

# --- G7: the composer and the templates must agree -------------------------
# scripts/editor-settings.py turns these templates into a consumer's .vscode/
# files, which means it carries a table saying which detected language earns
# each extension row. A table beside the data it describes drifts from it — so
# it is checked in both directions rather than trusted, and the composer is run
# once here on every language, because a splitter that mangles a fragment
# produces a plausible file nobody would look twice at.
import importlib.util

# The docstring above promises this script WRITES NOTHING, and importing a
# module by path is enough to make CPython drop a __pycache__ directory into
# scripts/. Turned off rather than gitignored: a guard that dirties the tree it
# is checking is a guard people learn to run with `git checkout .` afterwards.
sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location(
    "editor_settings", pathlib.Path("scripts/editor-settings.py"))
compose = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(compose)
except Exception as e:            # noqa: BLE001 - reported, not swallowed
    bad(f"scripts/editor-settings.py does not import: {e}")
    compose = None

if compose is not None and ext is not None:
    if set(compose.FRAGMENTS) != langs:
        bad("scripts/editor-settings.py's FRAGMENTS map covers "
            f"{sorted(compose.FRAGMENTS)}, configs/ ships {sorted(langs)} — "
            "adopt.sh --editor would write nothing for the difference")
    for lang, fname in compose.FRAGMENTS.items():
        if not (D / fname).exists():
            bad(f"editor-settings.py maps {lang} to {fname}, which does not exist")

    for key, table, name in ((("recommendations"), compose.RECOMMENDATIONS,
                              "RECOMMENDATIONS"),
                             ("unwantedRecommendations", compose.UNWANTED,
                              "UNWANTED")):
        listed = set(ext.get(key, []))
        for ident in sorted(listed - set(table)):
            bad(f"extensions.json lists {ident} under {key}, and "
                f"editor-settings.py's {name} has no rule for it — "
                "adopt.sh --editor would refuse to compose")
        for ident in sorted(set(table) - listed):
            bad(f"editor-settings.py's {name} has a rule for {ident}, which "
                "extensions.json no longer lists")
        for ident, rule in sorted(table.items()):
            if rule not in (compose.ALWAYS, compose.PRETTIER,
                            compose.NOT_PORTABLE) and rule not in langs:
                bad(f"{name}[{ident}] is gated on {rule!r}, which is not a "
                    "language configs/ ships")

    # The prettier gate names two keys in typescript.settings.json. If either is
    # renamed, the gate silently stops gating and a repo with no prettier config
    # gets format-on-save against Prettier's defaults — the exact failure
    # extensions.json's own comment says step 2 must prevent.
    try:
        ts_keys = {k for _, k, _ in
                   compose.object_entries((D / "typescript.settings.json").read_text())}
    except Exception as e:        # noqa: BLE001
        ts_keys = set()
        bad(f"editor-settings.py cannot split typescript.settings.json: {e}")
    for k in compose.PRETTIER_KEYS:
        if k not in ts_keys:
            bad(f"editor-settings.py gates {k!r} on the prettier config, but "
                "typescript.settings.json no longer has that key")

    # Compose every language once. Cheap, and it is the only place the splitter
    # itself is exercised against all six fragments at their current shape.
    try:
        composed = compose.compose_settings(list(compose.FRAGMENTS), prettier=True)
        doc = compose.parse(composed)
    except Exception as e:        # noqa: BLE001
        doc = {}
        bad(f"editor-settings.py cannot compose all languages: {e}")
    for fname in sorted(compose.FRAGMENTS.values()):
        for _, key, _ in compose.object_entries((D / fname).read_text()):
            if key not in doc:
                bad(f"{key} is in {fname} but not in the composed settings — "
                    "adopt.sh --editor would drop it silently")
    # Never the semgrep fragment: its rule paths resolve only inside a checkout
    # of this repo (README §5, issue #153), so composing it into a consumer's
    # tree would point the extension at nothing.
    if "semgrep.scan.onlyGitDirty" in doc:
        bad("the composed settings include the semgrep fragment — its rule "
            "paths do not exist in a consumer's tree (README §5)")

if fail:
    for f in fail: print(f"::error::{f}")
    sys.exit(1)
print(f"OK: {len(frags)} fragments annotated, {len(divergences)} contract "
      f"values agree with README §1, C# Dev Kit excluded, all {len(manifests)} "
      "expectation manifests named in README §3")
