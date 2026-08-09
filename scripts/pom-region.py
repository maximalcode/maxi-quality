#!/usr/bin/env python3
"""Insert, refresh or verify the maxi-quality managed region in a pom.xml.

WHY THIS EXISTS

Maven has no remote lint consumption, so the Java baseline is a COPY into the
consumer's own pom.xml — the same constraint Cargo imposes on `[lints]`. Rust
gets away with `cat >> Cargo.toml` because TOML is append-only-friendly. XML is
not: the block has to land INSIDE `<project><build><plugins>`, so there is no
append, only an edit.

An edit that a human has to redo on every baseline bump is not an upgrade path,
it is copy-paste-drift with a changelog. So the block is delimited:

    <!-- maxi-quality:begin ... -->   ...   <!-- maxi-quality:end -->

and re-running scripts/adopt.sh replaces everything between the markers and
NOTHING outside them. The consumer's own plugins, properties, comments and
formatting are untouched, and `check` turns a stale region into a failed gate
rather than a silent divergence.

WHY IT IS NOT AN XML REWRITE

ElementTree round-trips a POM into something a human did not write: comments
move, self-closing tags change shape, namespaces get prefixed, the whole file
reindents. A consumer whose build config comes back as a 400-line diff will not
adopt this twice. So the file is edited as TEXT, and ElementTree is used only to
ANSWER QUESTIONS about it (is there a project-level <build>? does it already
declare the compiler plugin?) where being wrong would be worse than being ugly.

REFUSING IS A FEATURE

A pom that already configures maven-compiler-plugin outside the region is not
merged into. Two declarations of one plugin in one POM is not a merge — it is
last-one-wins, so writing ours would SILENTLY DELETE a `-Werror` the consumer
already had. That exit code is what makes adopt.sh print the merge instructions
instead of quietly downgrading somebody's build (docs/ADOPTION.md §5).

Exit codes:
  0  applied / already current / check passed
  1  check failed — region missing or drifted
  3  usage or parse error
  4  refused — the pom configures maven-compiler-plugin outside the region
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET

BEGIN = "<!-- maxi-quality:begin"
END = "<!-- maxi-quality:end -->"

# Deliberately tolerant of what comes after "begin": the marker line carries
# prose that will change when the fragment does, and keying on the exact text
# would make every reworded comment look like a missing region.
REGION_RE = re.compile(
    r"(?P<indent>[ \t]*)" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"[ \t]*\n?",
    re.S,
)

MAVEN_NS = "http://maven.apache.org/POM/4.0.0"


class PomError(Exception):
    pass


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse(text: str) -> ET.Element:
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise PomError(f"not parseable as XML: {exc}") from exc


def declares_compiler_plugin(text: str) -> bool:
    """True when a maven-compiler-plugin sits OUTSIDE the managed region.

    Checked on the text with our region removed, so re-running the script does
    not read its own previous output as the consumer's config — that would make
    the second run refuse what the first one wrote, which is the exact
    non-idempotence this whole file exists to avoid.
    """
    root = _parse(REGION_RE.sub("", text))
    for plugin in root.iter():
        if _strip_ns(plugin.tag) != "plugin":
            continue
        for child in plugin:
            if _strip_ns(child.tag) == "artifactId" and (child.text or "").strip() == "maven-compiler-plugin":
                return True
    return False


def _indent_fragment(fragment: str, indent: str) -> str:
    lines = fragment.rstrip("\n").split("\n")
    return "\n".join(indent + line if line.strip() else line for line in lines)


def _find_project_build_plugins(text: str) -> tuple[int, str] | None:
    """Locate the insertion point: just before the project-level </plugins>.

    Returns (offset, indent_of_that_close_tag) or None.

    Depth is tracked over real tags only. `<profiles>` and `<reporting>` carry
    their own <build>/<plugins>, and `<pluginManagement>` carries a third — a
    naive search for the first `</plugins>` lands in whichever appears first in
    the file, which on a real Spring Boot pom is frequently the wrong one.
    """
    # Comments first: a commented-out <build> is not a build section, and every
    # pom this baseline writes is full of prose about why.
    scrubbed = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), text, flags=re.S)

    path: list[str] = []
    want = ["project", "build", "plugins"]
    for m in re.finditer(r"<(/?)([A-Za-z_][\w.-]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*?)(/?)>", scrubbed):
        closing, name, _attrs, self_closing = m.group(1), m.group(2), m.group(3), m.group(4)
        if closing:
            if path[-3:] == want and name == "plugins":
                line_start = text.rfind("\n", 0, m.start()) + 1
                return m.start(), text[line_start : m.start()]
            if path and path[-1] == name:
                path.pop()
        elif not self_closing:
            path.append(name)
    return None


def apply_region(text: str, fragment: str) -> str:
    match = REGION_RE.search(text)
    if match:
        # Refresh in place at the indentation the region already sits at. Taken
        # from the regex's own leading-whitespace group rather than from
        # match.start(), which is BEFORE that whitespace — reading it there
        # yields "" and silently re-indents the whole block to column zero, so
        # apply-then-check disagreed with itself.
        indent = match.group("indent")
        body = _indent_fragment(fragment, indent)
        return text[: match.start()] + body + "\n" + text[match.end() :]

    spot = _find_project_build_plugins(text)
    if spot is None:
        raise PomError(
            "no project-level <build><plugins> to insert into. Add\n"
            "  <build>\n    <plugins>\n    </plugins>\n  </build>\n"
            "to the pom and re-run — this script will not invent a build section, "
            "because guessing where one belongs in someone's pom is how a config "
            "lands somewhere Maven never reads it."
        )
    offset, indent = spot
    # Cut at the START OF THE LINE holding </plugins>, not at the tag itself.
    # Cutting at the tag leaves that line's indentation in the prefix, so the
    # fragment's FIRST line comes out indented twice and every other line once.
    # The file looks fine — one comment sits a few columns too far right — and
    # then the refresh path reads that first line's whitespace as the region's
    # indent and re-indents the whole block by it, every single run. Caught by
    # adopting a fresh repo twice, not by reading this function.
    line_start = text.rfind("\n", 0, offset) + 1
    body = _indent_fragment(fragment, indent + "  ")
    return text[:line_start] + body + "\n" + indent + text[offset:]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=("apply", "check"))
    ap.add_argument("--pom", required=True)
    ap.add_argument("--fragment", required=True)
    args = ap.parse_args()

    try:
        text = open(args.pom, encoding="utf-8").read()
        fragment = open(args.fragment, encoding="utf-8").read()
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    try:
        if declares_compiler_plugin(text):
            print(
                f"error: {args.pom} already configures maven-compiler-plugin outside the "
                "maxi-quality region. Two declarations of one plugin in one POM is not a "
                "merge — it is last-one-wins, so writing the baseline's would silently drop "
                "whatever compiler args you already had. Merge configs/java/pom-lints.xml "
                "into your existing declaration by hand (docs/ADOPTION.md §5).",
                file=sys.stderr,
            )
            return 4
        updated = apply_region(text, fragment)
    except PomError as exc:
        print(f"error: {args.pom}: {exc}", file=sys.stderr)
        return 3

    if args.mode == "check":
        if not REGION_RE.search(text):
            print(f"error: {args.pom} carries no maxi-quality region", file=sys.stderr)
            return 1
        if updated != text:
            print(
                f"error: the maxi-quality region in {args.pom} has drifted from "
                f"{args.fragment}. Regenerate it:\n"
                f"  python3 scripts/pom-region.py apply --pom {args.pom} --fragment {args.fragment}",
                file=sys.stderr,
            )
            return 1
        return 0

    if updated != text:
        with open(args.pom, "w", encoding="utf-8") as fh:
            fh.write(updated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
