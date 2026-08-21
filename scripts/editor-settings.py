#!/usr/bin/env python3
"""Compose a consumer's .vscode/ files from the frozen contract in configs/editor/.

WHY THIS IS A SCRIPT AND NOT A `cat`

`adopt.sh` copies most things verbatim. It cannot do that here for two reasons,
both of which decide the whole design:

  1. The fragments are per-language and a consumer's tree is not. Six files have
     to become ONE `.vscode/settings.json` holding only the rows for the
     languages detection actually found — a repo whose editor demands a
     toolchain the repo does not have is worse than no editor integration.
  2. THE COMMENTS ARE THE CONTRACT. configs/editor/README.md's opening claim is
     that "a settings line whose justification lives somewhere else becomes a
     settings line nobody dares delete", so every key ships with the CI
     behaviour it pins written directly above it. A parse-and-re-dump through
     `json` would drop every one of them and leave a plausible file that pins
     nothing — the exact failure `scripts/check-editor-contract.py` exists to
     prevent in the templates.

So this composes JSONC TEXTUALLY: it splits each fragment into top-level
entries, keeps each entry's leading comment block byte-for-byte, and re-emits
the selected ones. Nothing is reformatted, so the file a consumer reads is the
file this repo reviewed.

WHAT IS DELIBERATELY NOT WRITTEN

`configs/editor/semgrep.settings.json` names three rule directories that exist
only in a checkout of the baseline itself; a consumer's tree never contains
them (README §5). Writing it would point the extension at nothing, and its
`scan.configuration` default of `[]` means it would then scan with whatever the
Semgrep CLI is configured for — findings no gate here produces. Both halves are
divergence, so the fragment and the extension row are both held back and said
out loud. Making it portable is its own decision with its own costs; README §5
states them.

Subcommands:
  settings    print the composed .vscode/settings.json
  extensions  print the composed .vscode/extensions.json
  delta       print, key by key, what composing would add to an existing file

Exit codes: 0 fine - 1 the contract could not be composed (a bug here or a
drifted fragment, never a consumer's input)
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
EDITOR = HERE.parent / "configs" / "editor"

# The language token -> fragment map. Tokens are the configs/ directory names,
# which is what scripts/check-editor-contract.py already keys its G6 shape guard
# on, so a sixth language cannot arrive with a fragment nobody composes.
FRAGMENTS = {
    "typescript": "typescript.settings.json",
    "dotnet": "dotnet.settings.json",
    "python": "python.settings.json",
    "rust": "rust.settings.json",
    "java": "java.settings.json",
}

# Which detected language earns each recommendation. `None` means "always" —
# adopt.sh writes .editorconfig into every tree it touches. `PRETTIER` means the
# row is gated on the repo having actually taken adopt.sh's OPTIONAL prettier
# step: recommending the extension where no prettier config exists formats
# against Prettier's defaults rather than this baseline's, which is strictly
# worse than not recommending it. configs/editor/extensions.json says so at the
# row itself; this is where that sentence is executed.
#
# NOT_PORTABLE is the Semgrep row, for the reason in the module docstring.
ALWAYS = "always"
PRETTIER = "prettier"
NOT_PORTABLE = "not-portable"

RECOMMENDATIONS = {
    "EditorConfig.EditorConfig": ALWAYS,
    "dbaeumer.vscode-eslint": "typescript",
    "esbenp.prettier-vscode": PRETTIER,
    "ms-python.python": "python",
    "charliermarsh.ruff": "python",
    "ms-python.mypy-type-checker": "python",
    "rust-lang.rust-analyzer": "rust",
    "ms-dotnettools.csharp": "dotnet",
    "redhat.java": "java",
    "Semgrep.semgrep": NOT_PORTABLE,
}

# The unwanted half. Gated on C# rather than written always, for the same reason
# the recommendations are: a tree with no C# in it gets no C# rows at all. The
# licensing argument is unchanged — see configs/editor/README.md §2 — it simply
# has nothing to apply to until the repo has a .csproj.
UNWANTED = {"ms-dotnettools.csdevkit": "dotnet"}

# The two keys the OPTIONAL prettier step owns in the TypeScript fragment.
PRETTIER_KEYS = ("[typescript]", "[typescriptreact]")


class Drift(Exception):
    """A fragment is not shaped the way this composer requires."""


# --- JSONC lexing -----------------------------------------------------------
def classify(text):
    """Tag every character: 0 code, 1 string, 2 comment.

    Returns (tags, string_end) where string_end maps an opening quote's index to
    the index one past its closing quote. Structural scanning reads the tags, so
    a brace inside a value and a quote inside a comment are both inert.
    """
    tags = bytearray(len(text))
    ends = {}
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            start, j = i, i + 1
            tags[i] = 1
            while j < n:
                tags[j] = 1
                if text[j] == "\\":
                    if j + 1 < n:
                        tags[j + 1] = 1
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            ends[start] = j
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                tags[i] = 2
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = i + 2
            while j + 1 < n and not (text[j] == "*" and text[j + 1] == "/"):
                j += 1
            j = min(j + 2, n)
            for k in range(i, j):
                tags[k] = 2
            i = j
            continue
        i += 1
    return tags, ends


def outer_span(text, tags, opener="{", closer="}"):
    """Index of the outermost bracket pair's open and close characters."""
    start = None
    depth = 0
    for i, c in enumerate(text):
        if tags[i]:
            continue
        if c == opener:
            if start is None:
                start = i
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0 and start is not None:
                return start, i
    raise Drift(f"no balanced {opener}{closer} pair")


def _members(text, tags, lo, hi):
    """Split [lo, hi) into (leading, body) pairs, one per comma-separated member.

    `leading` is every byte before the member starts — its comments, its blank
    lines, its indentation — and is what makes this composer lossless.
    """
    out = []
    lead_start = lo
    i = lo
    depth = 0
    while i < hi:
        if tags[i]:
            i += 1
            continue
        c = text[i]
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        elif c == "," and depth == 0:
            out.append((lead_start, i))
            lead_start = i + 1
        i += 1
    tail = text[lead_start:hi]
    if tail.strip():
        out.append((lead_start, hi))
    members = []
    for a, b in out:
        chunk = text[a:b]
        # The member starts at its first code (non-comment, non-space) byte.
        rel = next(
            (k for k in range(a, b) if tags[k] != 2 and not text[k].isspace()),
            None,
        )
        if rel is None:
            raise Drift(f"empty member in {chunk!r}")
        members.append((text[a:rel], text[rel:b].rstrip()))
    return members


def object_entries(raw):
    """Split a whole JSONC object file into (leading, key, body) triples."""
    tags, ends = classify(raw)
    lo, hi = outer_span(raw, tags)
    entries = []
    for leading, body in _members(raw, tags, lo + 1, hi):
        if not body.startswith('"'):
            raise Drift(f"member does not start with a key: {body[:40]!r}")
        btags, bends = classify(body)
        key = json.loads(body[0 : bends[0]])
        entries.append((leading, key, body))
    return entries


def array_members(body):
    """Split a JSONC array VALUE (`[ ... ]`) into (leading, element) pairs."""
    tags, _ = classify(body)
    lo, hi = outer_span(body, tags, "[", "]")
    # The tail keeps the whitespace that sat in front of the closing bracket —
    # _members rstrips each element so they can be rejoined with commas, and
    # without this the last element and the `]` would end up on one line.
    ws = hi
    while ws > lo and body[ws - 1] in " \t\n":
        ws -= 1
    return _members(body, tags, lo + 1, hi), body[ws:]


def strip_comments(text):
    tags, _ = classify(text)
    return "".join(c if tags[i] != 2 else ("\n" if c == "\n" else " ")
                   for i, c in enumerate(text))


def parse(text):
    return json.loads(strip_comments(text))


# --- composition ------------------------------------------------------------
RULE = "  // " + "─" * 68


def banner(lines):
    return "\n".join("// " + ln if ln else "//" for ln in lines) + "\n"


def compose_settings(languages, prettier):
    blocks = []
    seen = {}
    for lang in languages:
        name = FRAGMENTS[lang]
        raw = (EDITOR / name).read_text()
        kept = []
        for leading, key, body in object_entries(raw):
            if key in PRETTIER_KEYS and not prettier:
                continue
            if key in seen:
                raise Drift(f"{name} and {seen[key]} both set {key!r} — two "
                            "fragments cannot own one setting")
            seen[key] = name
            kept.append(leading + body)
        if not kept:
            continue
        blocks.append(f"\n\n{RULE}\n  // configs/editor/{name}\n{RULE}"
                      + ",".join(kept))
    if not blocks:
        raise Drift("no fragments selected")
    head = banner([
        "maxi-quality — assembled by `scripts/adopt.sh --editor` from the frozen",
        "editor contract in the baseline's configs/editor/ directory.",
        "",
        "Every comment below arrived with the key it justifies. That is the point:",
        "a settings line whose reason lives somewhere else is one nobody dares",
        "delete. VS Code parses this file as JSONC, so they cost nothing.",
        "",
        "A `./README.md` or a `§N` in a comment below means the baseline's own",
        "configs/editor/README.md — the fragments were written there and are",
        "copied here byte for byte, references included.",
        "",
        f"Languages in this file: {', '.join(languages)}.",
        "",
        "Re-running `adopt.sh --editor` REFUSES to overwrite this file and prints",
        "what it would have changed instead — your editor settings are yours.",
        "Apply that by hand, or delete this file and re-run.",
        "",
        "NOT here, deliberately: the Semgrep fragment. It names rule directories",
        "that exist only inside a checkout of the baseline itself, so pointing the",
        "extension at them from here would configure it to scan with rules this",
        "tree does not have. See configs/editor/README.md §5.",
    ])
    return head + "{" + ",".join(blocks) + "\n}\n"


def _wants(rule, languages, prettier):
    if rule == ALWAYS:
        return True
    if rule == NOT_PORTABLE:
        return False
    if rule == PRETTIER:
        return "typescript" in languages and prettier
    return rule in languages


def compose_extensions(languages, prettier):
    raw = (EDITOR / "extensions.json").read_text()
    kept_entries = []
    for leading, key, body in object_entries(raw):
        table = {"recommendations": RECOMMENDATIONS,
                 "unwantedRecommendations": UNWANTED}.get(key)
        if table is None:
            raise Drift(f"extensions.json has an unknown top-level key {key!r}")
        members, tail = array_members(body)
        kept = []
        for lead, elem in members:
            ident = json.loads(strip_comments(elem).strip())
            if ident not in table:
                raise Drift(f"extensions.json recommends {ident!r}, which this "
                            "composer has no language rule for")
            if _wants(table[ident], languages, prettier):
                kept.append(lead + elem)
        if not kept:
            continue
        kept_entries.append(leading + '"' + key + '": [' + ",".join(kept) + tail)
    if not kept_entries:
        raise Drift("no recommendations selected")
    head = banner([
        "maxi-quality — assembled by `scripts/adopt.sh --editor` from the frozen",
        "editor contract in the baseline's configs/editor/ directory.",
        "",
        f"Rows for: {', '.join(languages)}. Extensions for languages this repo",
        "does not contain are left out — an editor that demands a toolchain the",
        "repo has not got is its own kind of noise.",
        "",
        "NOT here, deliberately: the Semgrep extension. Its rule paths do not",
        "resolve outside a checkout of the baseline, and with none configured it",
        "scans with whatever the Semgrep CLI is set to — findings no gate here",
        "produces. See configs/editor/README.md §5.",
    ])
    return head + "{" + ",".join(kept_entries) + "\n}\n"


# --- delta ------------------------------------------------------------------
def show_delta(kind, existing, composed):
    """Print, key by key, what composing would have added. Never writes."""
    want = parse(composed)
    try:
        have = parse(pathlib.Path(existing).read_text())
    except (json.JSONDecodeError, Drift):
        have = None
    print(f"  {existing} already exists — nothing was written to it.")
    print("  What --editor would have applied:")
    print()
    if have is None:
        print("    (your file does not parse as JSONC, so every key below is")
        print("     listed as new — compare by hand)")
        have = {}
    for key, value in want.items():
        rendered = json.dumps(value)
        if len(rendered) > 60:
            rendered = rendered[:57] + "..."
        if key not in have:
            print(f"    + {json.dumps(key)}: {rendered}")
        elif have[key] != value:
            cur = json.dumps(have[key])
            if len(cur) > 40:
                cur = cur[:37] + "..."
            print(f"    ~ {json.dumps(key)}: {cur}  ->  {rendered}")
        else:
            print(f"    = {json.dumps(key)}: already matches")
    print()
    print("  Merge those by hand, or delete the file and re-run. Every key's")
    print("  justification is in the baseline's configs/editor/ fragments and")
    print("  configs/editor/README.md.")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("settings", "extensions", "delta"))
    ap.add_argument("--languages", required=True,
                    help="comma-separated configs/ directory names")
    ap.add_argument("--prettier", action="store_true",
                    help="the target repo has a prettier config (adopt.sh's "
                         "OPTIONAL step); gates the prettier rows")
    ap.add_argument("--kind", choices=("settings", "extensions"),
                    help="delta only: which file is being compared")
    ap.add_argument("--existing", help="delta only: the file that already exists")
    args = ap.parse_args(argv)

    languages = [t for t in args.languages.split(",") if t]
    unknown = [t for t in languages if t not in FRAGMENTS]
    if unknown:
        print(f"error: unknown language(s): {', '.join(unknown)}", file=sys.stderr)
        return 1
    if not languages:
        print("error: no languages given", file=sys.stderr)
        return 1
    # Deterministic order, so re-running produces a byte-identical file and a
    # diff means a real change.
    languages = [t for t in FRAGMENTS if t in languages]

    try:
        if args.command == "delta":
            if not args.kind or not args.existing:
                print("error: delta needs --kind and --existing", file=sys.stderr)
                return 1
            composed = (compose_settings(languages, args.prettier)
                        if args.kind == "settings"
                        else compose_extensions(languages, args.prettier))
            show_delta(args.kind, args.existing, composed)
            return 0
        out = (compose_settings(languages, args.prettier)
               if args.command == "settings"
               else compose_extensions(languages, args.prettier))
    except (Drift, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    # Composed text must be valid JSONC. Asserted here rather than trusted:
    # a file that does not parse leaves VS Code with NO settings at all and
    # says so only in a panel nobody has open.
    try:
        parse(out)
    except json.JSONDecodeError as e:
        print(f"error: composed {args.command} is not valid JSONC ({e})",
              file=sys.stderr)
        return 1
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
