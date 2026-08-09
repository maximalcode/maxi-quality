#!/usr/bin/env python3
"""Snapshot what the Java toolchain RESOLVES to, not what the fragment says.

THE GAP THIS CLOSES — the same one #8 closed for the other four languages.

samples/expected/java.json pins what the fixtures BAIT. It cannot see anything
that changes no diagnostic on those fixtures, and for Java that is most of the
config's load-bearing surface:

  - `-Werror` looks identical to its own absence on a fixture whose findings
    are all ERROR-severity;
  - `-Xep:NullAway:ERROR` looks identical to its absence unless a NullAway
    finding is present AND nothing else has already failed the build;
  - the four PINNED VERSIONS bake out no diagnostic at all until the day an
    upgrade adds a check, which is the exact day the pin was supposed to help;
  - `<style>AOSP</style>` is invisible to every compile — it only shows up in
    the formatter's verdict, and only on a line between 101 and 120 columns;
  - `<fork>true</fork>` and the ten `-J` flags do not change WHAT is reported,
    they decide whether Error Prone runs at all. Delete them and the build
    fails with an IllegalAccessError that reads like a broken plugin.

So this asserts the EFFECTIVE POM — Maven's own resolver, after Spring Boot's
parent has had its say — rather than the fragment this repo ships. Those two
being the same thing is a claim, and it is the claim that stops being true the
first time a consumer's parent POM sets its own compiler configuration.

Exit codes: 0 matches (or written) · 1 drifted · 3 mvn/parse failure
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_POM = os.path.join(HERE, "samples", "java-clean")
DEFAULT_SNAPSHOT = os.path.join(HERE, "configs", "java", "settings.snapshot.json")

# The plugins whose resolved configuration IS the Java baseline. Anything else
# in the effective POM is Spring Boot's, and pinning it would make this snapshot
# fail on every Boot upgrade for no benefit.
PLUGINS = ("maven-compiler-plugin", "spotless-maven-plugin")


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def to_plain(el: ET.Element):
    """Element -> nested dict/str, namespaces dropped, whitespace normalised.

    Repeated child names collapse into a list so <arg> ordering survives —
    javac reads its arguments in order, and `-Xlint` after `-Xplugin` is not
    the same command line as before it."""
    children = list(el)
    if not children:
        return (el.text or "").strip()
    out: dict = {}
    for child in children:
        name = strip_ns(child.tag)
        value = to_plain(child)
        if name in out:
            if not isinstance(out[name], list):
                out[name] = [out[name]]
            out[name].append(value)
        else:
            out[name] = value
    return out


def effective_pom(project_dir: str) -> str:
    out_file = os.path.join(project_dir, "target", "effective-pom.xml")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    proc = subprocess.run(
        ["mvn", "-B", "-q", "help:effective-pom", f"-Doutput={out_file}"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not os.path.exists(out_file):
        raise RuntimeError(
            "mvn help:effective-pom failed — the snapshot cannot be taken:\n"
            + (proc.stderr or proc.stdout)[-2000:]
        )
    with open(out_file, encoding="utf-8") as fh:
        return fh.read()


def collect(pom_text: str) -> dict:
    root = ET.fromstring(pom_text)
    found: dict = {}
    for plugin in root.iter():
        if strip_ns(plugin.tag) != "plugin":
            continue
        fields = {strip_ns(c.tag): c for c in plugin}
        artifact = (fields.get("artifactId").text or "").strip() if "artifactId" in fields else ""
        if artifact not in PLUGINS:
            continue
        entry = {"version": (fields["version"].text or "").strip() if "version" in fields else None}
        if "configuration" in fields:
            entry["configuration"] = to_plain(fields["configuration"])
        # pluginManagement and build/plugins can both carry an entry. The one
        # with a configuration is the one that runs; keeping the richer of the
        # two makes the snapshot independent of which section Maven emits first.
        if artifact not in found or len(json.dumps(entry)) > len(json.dumps(found[artifact])):
            found[artifact] = entry

    missing = [p for p in PLUGINS if p not in found]
    if missing:
        raise RuntimeError(
            f"the effective POM declares no {', '.join(missing)} — the Java baseline "
            "is not wired into this project at all, which is exactly the "
            "looks-adopted-gates-nothing state configs/java exists to prevent."
        )
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", default=DEFAULT_POM, help="Maven project to resolve")
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    ap.add_argument("--check", action="store_true", help="compare instead of writing")
    args = ap.parse_args()

    try:
        resolved = collect(effective_pom(args.project))
    except (RuntimeError, ET.ParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    rendered = json.dumps(resolved, indent=2, sort_keys=True) + "\n"

    if not args.check:
        with open(args.snapshot, "w", encoding="utf-8") as fh:
            fh.write(rendered)
        print(f"wrote {args.snapshot}")
        return 0

    try:
        with open(args.snapshot, encoding="utf-8") as fh:
            committed = fh.read()
    except OSError as exc:
        print(f"error: cannot read {args.snapshot}: {exc}", file=sys.stderr)
        return 3

    if committed == rendered:
        print(f"OK: resolved Java settings match {os.path.relpath(args.snapshot, HERE)}")
        return 0

    print("error: the resolved Java settings no longer match the snapshot.", file=sys.stderr)
    print("Regenerate with scripts/snapshot-java-settings.py and say in the", file=sys.stderr)
    print("commit message what changed and why the new value is correct.", file=sys.stderr)
    import difflib

    sys.stderr.writelines(
        difflib.unified_diff(
            committed.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile="committed",
            tofile="resolved",
        )
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
