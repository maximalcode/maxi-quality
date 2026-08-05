#!/usr/bin/env python3
"""Resolve a consumer's `.maxi-quality.yml` into Semgrep arguments and a gate verdict.

WHY THIS EXISTS

Before this, a consuming repo could configure which *jobs* ran and nothing about
which *rules* did. The only two ways to say "that rule does not apply to us" were
a per-finding `nosemgrep` comment and deleting the workflow file, and the second
one is what actually happens when a gate has no legitimate way to say no. A
deleted gate is worse than a configurable one.

THE THREE THINGS THIS FILE REFUSES TO DO QUIETLY

1. **Ignore a key it does not understand.** Every silent-knob bug this repo has
   shipped had the same shape: Ruff's bare `select` replacing what it inherits
   instead of merging, `pattern-not-regex` ignored when nested one level too
   high, `dotnet_diagnostic.IDE1006.severity` never set so three naming rules
   enforced nothing. Each looked identical to a working config from outside. An
   unknown key, an unknown rule id and an unknown group are all hard errors here.

2. **Trust `--exclude-rule` to have worked.** MEASURED, 2026-08-03, semgrep
   1.172.0: `--exclude-rule` matches the full path-prefixed `check_id`, and a
   bare rule id excludes NOTHING while exiting 0 with no warning. Worse, the
   prefix is derived from the config path as given, so the same rule is

       semgrep.security.weak-crypto                  (--config semgrep/security)
       baseline.semgrep.security.weak-crypto         (--config /baseline/...)
       Users.me.dev.maxi-quality.semgrep.security.weak-crypto   (absolute)

   The native and docker paths in scan.sh pass different config paths, so an
   exclusion computed for one silently does nothing in the other — which is
   exactly how the `--changed-only` no-op gate happened (docs/STATUS.md §4).
   So the prefix is computed here AND `classify` asserts afterwards that no
   disabled rule survived into the results. If the mangling ever changes, that
   assertion fails loudly instead of quietly un-disabling somebody's policy.

3. **Let a broken mechanism read as "clean".** An unreadable policy, an
   unparseable result set, or a semgrep run that FAILED are all failures. Never
   a pass. That is the shape of every gate bug this repo has actually hit.

   With one distinction, added in #43 and worth stating precisely, because
   getting it wrong in either direction is a real bug:

   **A file semgrep cannot parse is a coverage gap, not a scan failure.**
   Both used to be `.errors`, and both exited 2. Measured: a real C# codebase
   using C# 12 primary constructors turned a clean scan into a red gate —
   `Ran 22 rules on 29 files: 0 findings`, then `refusing to treat the result
   as a finding set`. There is nothing the consumer can do about semgrep's
   parser, so the gate was red on green code, which is how a gate gets ignored.

   The *worse* half is the one that had no output at all: a file that does not
   parse has no rules run against it. It was being reported as a failure, which
   at least made noise — but never as what it is, which is a hole in coverage
   with a name and a count. So parse failures are now split out, listed by file
   and counted (`semgrep_unparsed=N`), and they do not gate.

   Two guards keep that from becoming the silent-pass this file exists to
   prevent. Every error type NOT on the per-file list below is still fatal, so
   an unrecognised failure is never quietly downgraded. And if EVERY file
   semgrep looked at failed to parse, the run proved nothing and exits 2 —
   "0 findings because nothing was scanned" is precisely the shape that must
   not read as clean.

WHAT IS DELIBERATELY NOT CONFIGURABLE

Gitleaks and OSV-Scanner. A secret is not an opinion and neither is a known CVE.
There is likewise no key that turns the gate advisory — `--no-fail` already
exists for the standing report, and its own documentation says why it must never
be set on a gate.

Exit codes: 0 clean/valid · 1 gate findings · 2 a mechanism failed · 3 usage or
policy error
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# The group names are the directory names under semgrep/. They are listed
# explicitly rather than globbed so that adding a directory is a deliberate act
# with a docs change attached, not something a consumer discovers by accident.
GROUPS = ("general", "security", "conventions")

POLICY_FILENAME = ".maxi-quality.yml"

# Every key the schema accepts, at every level. Anything outside these sets is an
# error — see reason 1 in the module docstring.
TOP_LEVEL_KEYS = {"version", "rules", "paths", "extends"}
RULES_KEYS = {"groups", "disable", "warn"}
PATHS_KEYS = {"exclude"}

SUPPORTED_VERSION = 1

# --- semgrep error types that mean "this ONE FILE was not scanned" -------------
#
# As opposed to "the scan did not happen", which is everything else and stays
# fatal. The split is an ALLOWLIST on purpose: a type that is not named here —
# a rule that would not load, an unknown language, a missing plugin — keeps the
# old exit-2 behaviour, so a semgrep release that invents a new failure mode
# cannot quietly become a warning.
#
# `type` is a tagged union in semgrep's JSON and its shape varies: a bare string
# for some, a `[tag, payload]` list for others. PartialParsing is the list form
# and carries the offending spans. error_type() below normalises both.
#
# Measured 2026-08-05, semgrep 1.172.0 — which is the newest release on PyPI, so
# "upgrade semgrep" is not an available fix for the C# 12 case that prompted
# this (#43). 1.145.0 fails identically.
PER_FILE_ERROR_TYPES = frozenset(
    {
        "PartialParsing",
        "SyntaxError",
        "LexicalError",
        "Timeout",
        "OutOfMemory",
        "TimeoutDuringInterfile",
        "OutOfMemoryDuringInterfile",
    }
)


def error_type(err: dict) -> str:
    """The tag of a semgrep error, whichever of the two shapes it arrived in."""
    raw = err.get("type")
    if isinstance(raw, list):
        return str(raw[0]) if raw else "?"
    return str(raw)


class PolicyError(Exception):
    """A policy the consumer must fix. Always fatal, never downgraded."""


# --- semgrep's check_id prefix ------------------------------------------------
def semgrep_prefix(config_path: str) -> str:
    """Reproduce how semgrep derives a rule's `check_id` prefix from --config.

    Measured against semgrep 1.172.0 (see the module docstring): the config path
    has its leading slash stripped and its separators turned into dots, and that
    is prepended to the rule's own id.

        semgrep/security            -> semgrep.security.
        /baseline/semgrep/security  -> baseline.semgrep.security.

    This is an undocumented transform, which is why nothing here trusts it on its
    own — `classify` proves it worked on every run that has a disabled rule.
    """
    normalised = config_path.replace(os.sep, "/").strip("/")
    return normalised.replace("/", ".") + "." if normalised else ""


def bare_id(check_id: str) -> str:
    """The rule id as written in semgrep/, with the config-path prefix removed.

    Same convention scripts/check-expected.py uses, and for the same reason: the
    prefix is an artifact of how the scan was invoked, not part of the rule's
    identity. Matching on it would make a manifest depend on someone's home
    directory.
    """
    return check_id.split(".")[-1]


# --- reading the rule inventory ----------------------------------------------
def _require_yaml():
    try:
        import yaml  # noqa: PLC0415 — imported lazily on purpose, see below
    except ImportError:
        # A consumer with no policy file needs no YAML parser at all, so this
        # dependency is not imposed on anyone who has not opted in.
        raise PolicyError(
            f"a {POLICY_FILENAME} is present but PyYAML is not installed, so it "
            "cannot be read. Install it (`python3 -m pip install pyyaml`) or "
            f"remove {POLICY_FILENAME}. Refusing to continue: a policy file that "
            "silently does not apply is worse than no policy file."
        )
    return yaml


def load_rule_ids(directory: str, yaml_mod) -> dict:
    """Map every rule id defined under `directory` to the file that defines it.

    Used to validate `disable:` and `warn:` entries. A typo'd rule id is an error
    rather than a no-op, because a `disable` that disables nothing looks exactly
    like one that works right up until the rule fires in someone's CI.
    """
    found = {}
    for root, _dirs, files in os.walk(directory):
        for name in sorted(files):
            if not name.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    doc = yaml_mod.safe_load(fh)
            except (OSError, yaml_mod.YAMLError) as exc:
                raise PolicyError(f"cannot read rule file {path}: {exc}")
            if not isinstance(doc, dict):
                continue
            for rule in doc.get("rules") or []:
                if isinstance(rule, dict) and "id" in rule:
                    found[str(rule["id"])] = path
    return found


# --- schema validation --------------------------------------------------------
def _string_list(value, where: str) -> list:
    if not isinstance(value, list):
        raise PolicyError(f"{where} must be a list, got {type(value).__name__}")
    out = []
    for item in value:
        if not isinstance(item, str):
            raise PolicyError(f"{where} must contain only strings, got {item!r}")
        out.append(item)
    return out


def _reject_unknown(mapping: dict, allowed: set, where: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise PolicyError(
            f"{where}: unknown key(s) {', '.join(repr(k) for k in unknown)}. "
            f"Allowed here: {', '.join(sorted(allowed))}. "
            "Unknown keys are an error on purpose — a typo that silently does "
            "nothing is the failure mode this file exists to prevent."
        )


def parse_policy(path: str, yaml_mod) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = yaml_mod.safe_load(fh)
    except OSError as exc:
        raise PolicyError(f"cannot read {path}: {exc}")
    except yaml_mod.YAMLError as exc:
        raise PolicyError(f"{path} is not valid YAML: {exc}")

    if doc is None:
        # An empty file is a statement of intent that resolves to the defaults,
        # and it is the shape adopt.sh writes. Not an error.
        doc = {}
    if not isinstance(doc, dict):
        raise PolicyError(f"{path} must contain a mapping at the top level")

    _reject_unknown(doc, TOP_LEVEL_KEYS, POLICY_FILENAME)

    version = doc.get("version", SUPPORTED_VERSION)
    if version != SUPPORTED_VERSION:
        raise PolicyError(
            f"{POLICY_FILENAME}: version {version!r} is not supported by this "
            f"baseline (expected {SUPPORTED_VERSION})"
        )

    rules = doc.get("rules") or {}
    if not isinstance(rules, dict):
        raise PolicyError("'rules' must be a mapping")
    _reject_unknown(rules, RULES_KEYS, "rules")

    paths = doc.get("paths") or {}
    if not isinstance(paths, dict):
        raise PolicyError("'paths' must be a mapping")
    _reject_unknown(paths, PATHS_KEYS, "paths")

    groups = _string_list(rules["groups"], "rules.groups") if "groups" in rules else list(GROUPS)
    unknown_groups = [g for g in groups if g not in GROUPS]
    if unknown_groups:
        raise PolicyError(
            f"rules.groups: unknown group(s) {', '.join(repr(g) for g in unknown_groups)}. "
            f"Allowed: {', '.join(GROUPS)}"
        )

    extends = doc.get("extends")
    if extends is not None and not isinstance(extends, str):
        raise PolicyError("'extends' must be a string path relative to the repo root")

    if not groups and not extends:
        # Selecting no groups and adding nothing of your own leaves Semgrep with
        # no rules at all, which is a switched-off gate wearing a config file.
        # Allowed only alongside `extends`, where it means "our rules, not yours".
        raise PolicyError(
            "rules.groups is empty and no 'extends' is set, which would run no "
            "Semgrep rules at all. If you mean to run only your own rules, set "
            "'extends' as well; if you mean to turn Layer 2 off, do it in your "
            "workflow where it is visible, not in a policy file."
        )

    exclude = _string_list(paths.get("exclude") or [], "paths.exclude")
    for pattern in exclude:
        # MEASURED, semgrep 1.172.0: `--exclude` matches PATH COMPONENTS, not
        # gitignore-style globs. `legacy/**` — which is what everyone writes
        # first, because it is what .gitignore and every other tool accept —
        # excludes NOTHING and exits 0 without a word. `legacy` and `legacy/`
        # both work. This was found by ablating the exclude fixture: it passed
        # while proving nothing, because the directory had been called `vendor/`
        # and semgrep ignores that by default anyway.
        if "**" in pattern:
            raise PolicyError(
                f"paths.exclude: {pattern!r} contains '**', which semgrep's "
                "--exclude does not support — it matches path components, so "
                "this pattern would silently exclude nothing. Write "
                f"{pattern.split('/**')[0]!r} instead."
            )

    return {
        "groups": groups,
        "disable": _string_list(rules.get("disable") or [], "rules.disable"),
        "warn": _string_list(rules.get("warn") or [], "rules.warn"),
        "exclude": exclude,
        "extends": extends,
    }


# --- resolution ---------------------------------------------------------------
def resolve(target: str, baseline: str, baseline_path: str, explain: bool) -> dict:
    """Turn the policy file (or its absence) into the fully resolved decision.

    `baseline_path` is the --config value scan.sh will actually pass, which is NOT
    always `baseline`: under docker the rules are mounted at /baseline and the
    prefix semgrep generates changes with it. Getting this wrong is the bug this
    module's docstring is mostly about.
    """
    policy_file = os.path.join(target, POLICY_FILENAME)
    has_policy = os.path.isfile(policy_file)

    if not has_policy:
        # The no-policy path stays completely dependency-free: no YAML parser, no
        # rule inventory, no behaviour change for any repo adopted before this
        # existed. That is the whole compatibility story and it is worth keeping.
        resolved = {
            "policy_file": None,
            "groups": list(GROUPS),
            "disable": [],
            "warn": [],
            "exclude": [],
            "extends": None,
            "exclude_rule_args": [],
        }
        if explain:
            resolved["gate_rules"] = []
            resolved["warn_rules"] = []
        return resolved

    yaml_mod = _require_yaml()
    parsed = parse_policy(policy_file, yaml_mod)

    # Build the id inventory from exactly the sources that will be scanned, so a
    # rule id from a group the consumer did not select is reported as such rather
    # than accepted and then silently never matched.
    inventory = {}
    for group in parsed["groups"]:
        group_dir = os.path.join(baseline, "semgrep", group)
        for rid, src in load_rule_ids(group_dir, yaml_mod).items():
            inventory[rid] = ("%s/semgrep/%s" % (baseline_path.rstrip("/"), group), src)

    extends_rel = parsed["extends"]
    extends_abs = None
    if extends_rel:
        if os.path.isabs(extends_rel):
            raise PolicyError(
                f"'extends' must be relative to the repo root, got {extends_rel!r}"
            )
        extends_abs = os.path.normpath(os.path.join(target, extends_rel))
        if os.path.commonpath([os.path.realpath(extends_abs), os.path.realpath(target)]) != os.path.realpath(target):
            raise PolicyError(
                f"'extends' points outside the repository: {extends_rel!r}"
            )
        if not os.path.isdir(extends_abs):
            raise PolicyError(
                f"'extends' directory does not exist: {extends_rel!r}. "
                "A path that is not there would load no rules and exit 0."
            )
        for rid, src in load_rule_ids(extends_abs, yaml_mod).items():
            inventory[rid] = (extends_rel.rstrip("/"), src)

    # Every named rule must exist in what was actually selected.
    for field in ("disable", "warn"):
        for rid in parsed[field]:
            if rid not in inventory:
                raise PolicyError(
                    f"rules.{field}: no rule id {rid!r} in the selected groups "
                    f"({', '.join(parsed['groups']) or 'none'})"
                    + (f" or in {extends_rel!r}" if extends_rel else "")
                    + ". A rule id that matches nothing would silently do nothing."
                )

    both = sorted(set(parsed["disable"]) & set(parsed["warn"]))
    if both:
        raise PolicyError(
            f"rules: {', '.join(repr(r) for r in both)} listed in both 'disable' "
            "and 'warn'. Those mean opposite things; pick one."
        )

    # The prefixed form semgrep will actually match on, per rule, from the config
    # path that rule's group will be loaded from.
    exclude_rule_args = []
    for rid in parsed["disable"]:
        config_path, _src = inventory[rid]
        exclude_rule_args.append(semgrep_prefix(config_path) + rid)

    resolved = {
        "policy_file": POLICY_FILENAME,
        "groups": parsed["groups"],
        "disable": parsed["disable"],
        "warn": parsed["warn"],
        "exclude": parsed["exclude"],
        "extends": extends_rel,
        "exclude_rule_args": exclude_rule_args,
    }
    if explain:
        # The snapshot form: what the policy RESOLVES to, not what it says. Same
        # division of labour as configs/*/…snapshot.json — the resolved view is
        # the one worth asserting, because the written one has been wrong before.
        gated = sorted(set(inventory) - set(parsed["disable"]) - set(parsed["warn"]))
        resolved["gate_rules"] = gated
        resolved["warn_rules"] = sorted(parsed["warn"])
    return resolved


# --- semgrep argument emission ------------------------------------------------
def semgrep_args(resolved: dict, baseline_path: str, target_path: str) -> list:
    args = []
    for group in resolved["groups"]:
        args += ["--config", "%s/semgrep/%s" % (baseline_path.rstrip("/"), group)]
    if resolved["extends"]:
        args += ["--config", "%s/%s" % (target_path.rstrip("/"), resolved["extends"].strip("/"))]
    for pattern in resolved["exclude"]:
        args += ["--exclude", pattern]
    for rule_arg in resolved["exclude_rule_args"]:
        args += ["--exclude-rule", rule_arg]
    return args


# --- classification -----------------------------------------------------------
def path_is_excluded(path: str, patterns: list) -> bool:
    """Would this result's path have been excluded, if --exclude had worked?

    Deliberately a little eager: it matches a pattern against each path
    component and against the basename. The only thing it is used for is
    detecting that an exclusion did NOT take effect, so erring toward "yes,
    this should have been excluded" errs toward a loud failure rather than a
    quiet one.
    """
    import fnmatch  # noqa: PLC0415 — only needed on the classify path

    parts = path.replace(os.sep, "/").split("/")
    for raw in patterns:
        pattern = raw.rstrip("/")
        if not pattern:
            continue
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
        if fnmatch.fnmatch(path, pattern):
            return True
        # A multi-segment prefix such as `samples/policy`, which semgrep does
        # honour even though it is not a single component.
        if path.startswith(pattern + "/"):
            return True
    return False


# --- GitHub PR-diff annotations (#40) -----------------------------------------
#
# Every finding lives in job log output today. A reviewer sees a red check,
# opens the log, and reads a file:line they then have to go find. GitHub renders
# `::error file=…,line=…::message` directly onto the pull-request diff, and that
# is free on every plan — unlike SARIF upload, which needs Advanced Security on
# a private repo and is out for exactly the reason CodeQL is
# (docs/EVAL-vs-oss-tools.md §0).
#
# THIS IS A RENDERER, NEVER A VERDICT. It runs inside classify() so it reads the
# same gate/warn split the exit code comes from — a second traversal of
# `results` could disagree, and two computations of one thing is how the docker
# and native semgrep paths came to differ about --changed-only. It is called
# after the classification and before the return, and it cannot change either.
#
# GitHub silently drops annotations past a per-run limit it does not document,
# so there is an explicit cap here. A silent truncation reads as "that was all
# of them", which is the same failure shape as every gate bug in this repo, so
# the omitted count is always stated.
DEFAULT_MAX_ANNOTATIONS = 50


def _gha_escape(text: str) -> str:
    """Escape a workflow-command DATA value.

    Order matters: `%` first, or the escapes introduced below get re-escaped.
    A raw newline would end the command early and drop the rest of the message
    on the floor as if it were a log line.
    """
    return (
        str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    )


def _gha_escape_prop(text: str) -> str:
    """Escape a workflow-command PROPERTY value (file=…, title=…).

    Properties additionally need `:` and `,` escaped, since those are the
    delimiters. A rule id never contains them; a file path on a weird branch
    could, and a title carrying a message would.
    """
    return _gha_escape(text).replace(":", "%3A").replace(",", "%2C")


def emit_annotations(gate_raw: list, warn_raw: list, max_n: int, prefix: str = "") -> None:
    """Print one workflow command per finding, gating ones as errors.

    Deliberately defensive about the shape of each result. An annotation is
    cosmetic; a malformed finding must degrade to a less precise annotation, and
    never to an exception that would take the verdict down with it.
    """
    if max_n <= 0:
        total = len(gate_raw) + len(warn_raw)
        if total:
            print(f"  ({total} annotation(s) suppressed — the cap is 0)")
        return

    # Gating findings first: if anything is going to be cut, cut the warnings.
    ordered = [("error", r) for r in gate_raw] + [("warning", r) for r in warn_raw]
    shown, omitted = ordered[:max_n], len(ordered) - max_n

    for level, r in shown:
        try:
            rid = bare_id(r.get("check_id", "")) or "semgrep"
            path = r.get("path", "")
            start = r.get("start") if isinstance(r.get("start"), dict) else {}
            end = r.get("end") if isinstance(r.get("end"), dict) else {}
            extra = r.get("extra") if isinstance(r.get("extra"), dict) else {}
            message = extra.get("message") or rid
            props = [f"file={_gha_escape_prop(prefix + path)}"] if path else []
            if isinstance(start.get("line"), int):
                props.append(f"line={start['line']}")
                if isinstance(end.get("line"), int) and end["line"] >= start["line"]:
                    props.append(f"endLine={end['line']}")
            if isinstance(start.get("col"), int):
                props.append(f"col={start['col']}")
            props.append(f"title={_gha_escape_prop(rid)}")
            print(f"::{level} {','.join(props)}::{_gha_escape(message)}")
        except Exception as exc:  # noqa: BLE001 — see the docstring
            # Named, not swallowed. A silently missing annotation is the thing
            # this is supposed to fix.
            print(f"  (could not annotate one finding: {exc})", file=sys.stderr)

    if omitted > 0:
        # Said out loud on BOTH streams: stdout for the log, and a notice so it
        # is visible in the run summary next to the annotations it is about.
        print(
            f"::notice::{omitted} further Semgrep finding(s) are not annotated "
            f"(cap: {max_n}). The job log has all of them; the gate counted all "
            "of them."
        )
        print(f"  ({omitted} finding(s) beyond the annotation cap of {max_n})")


def classify(
    resolved: dict,
    results_path: str,
    annotate: bool = False,
    max_annotations: int = DEFAULT_MAX_ANNOTATIONS,
    annotate_prefix: str = "",
) -> int:
    try:
        with open(results_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        # Never a pass. A missing or corrupt result set means the scan did not
        # happen, and "the scan did not happen" must not look like "clean".
        print(f"error: cannot read semgrep results from {results_path}: {exc}", file=sys.stderr)
        return 2

    # --- errors: split "this file was not scanned" from "the scan failed" -----
    unparsed, fatal = [], []
    for err in data.get("errors", []):
        (unparsed if error_type(err) in PER_FILE_ERROR_TYPES else fatal).append(err)

    if fatal:
        first = fatal[0]
        print(
            f"error: semgrep reported {len(fatal)} error(s) that are not per-file "
            f"parse failures; refusing to treat the result as a finding set: "
            f"[{error_type(first)}] {first.get('message', '?')}",
            file=sys.stderr,
        )
        return 2

    # The files semgrep could not read. Deduplicated: PartialParsing is emitted
    # once per unparseable construct, so one file with three of them is three
    # errors and still one coverage hole.
    unparsed_files = sorted({e.get("path", "?") for e in unparsed})
    if unparsed_files:
        scanned = data.get("paths", {}).get("scanned", [])
        # NOTHING WAS SCANNED. `paths.scanned` is what semgrep looked at, not
        # what it managed to parse, so a tree it cannot read at all comes back
        # as "0 findings" with a full scanned list — the exact shape that must
        # never read as clean. One file readable is enough to call the run real;
        # zero is not.
        if scanned and len(unparsed_files) >= len(scanned):
            print(
                f"error: all {len(scanned)} file(s) semgrep looked at failed to "
                "parse, so no rule ran against anything. That is a failed scan, "
                "not a clean one.",
                file=sys.stderr,
            )
            for path in unparsed_files:
                print(f"  unparsed  {path}", file=sys.stderr)
            return 2

        # Not a gate. There is nothing a consumer can do about semgrep's parser,
        # and failing here is what trains people to ignore the check. But the
        # coverage loss gets a name, a count and a line each — invisible is the
        # thing it must not be.
        print("── Coverage ──")
        print(
            f"  {len(unparsed_files)} file(s) semgrep could not parse — "
            "NO RULE RAN AGAINST THEM:"
        )
        by_file: dict[str, str] = {}
        for err in unparsed:
            by_file.setdefault(err.get("path", "?"), error_type(err))
        for path in unparsed_files:
            print(f"  unparsed  {by_file.get(path, '?'):<16} {path}")
        if scanned:
            covered = len(scanned) - len(unparsed_files)
            print(f"  ({covered} of {len(scanned)} scanned file(s) actually parsed)")
        print("  This is a coverage gap, not a finding. It does not fail the gate.")
        print()

    disabled = set(resolved["disable"])
    warned = set(resolved["warn"])

    # The raw result alongside the (rid, path, line) tuple, so the annotator can
    # reach the message and column without walking `results` a second time and
    # risking a different answer about what gates.
    gate_raw, warn_raw = [], []
    gate, warn_hits, leaked, unexcluded = [], [], [], []
    for r in data.get("results", []):
        rid = bare_id(r.get("check_id", ""))
        path = r.get("path", "?")
        # `isinstance`, not `r.get("start", {}).get(...)`. semgrep's schema is
        # not a contract this repo controls, and a result whose `start` is not a
        # dict used to raise AttributeError straight out of here — an unhandled
        # traceback whose exit code happened to be 1, so the gate's verdict was
        # right by accident rather than by design. A finding this file cannot
        # fully read still COUNTS; only its line number is unknown.
        start = r.get("start")
        line = start.get("line", 0) if isinstance(start, dict) else 0
        entry = (rid, path, line)
        if resolved["exclude"] and path_is_excluded(path, resolved["exclude"]):
            unexcluded.append(entry)
        elif rid in disabled:
            leaked.append(entry)
        elif rid in warned:
            warn_hits.append(entry)
            warn_raw.append(r)
        else:
            gate.append(entry)
            gate_raw.append(r)

    if unexcluded:
        # Same class as the disabled-rule leak below: the knob was set and did
        # not take. semgrep's --exclude matches path components rather than
        # globs, so a pattern that looks right can quietly match nothing.
        files = sorted({e[1] for e in unexcluded})
        print(
            "error: paths.exclude did not take effect — findings were still "
            "reported in " + ", ".join(files[:5])
            + (f" (+{len(files) - 5} more)" if len(files) > 5 else "")
            + ". The pattern matched nothing semgrep recognises. Treating the "
            "policy as unreliable rather than applying it partially.",
            file=sys.stderr,
        )
        return 2

    if leaked:
        # The braces for the belt. `--exclude-rule` matched nothing, which means
        # the prefix this script computed is not the one semgrep generated — so
        # every other disabled rule in this policy is probably also not disabled.
        # Loud failure, not a silent partial policy.
        names = sorted({e[0] for e in leaked})
        print(
            "error: rule(s) " + ", ".join(names) + " are disabled by "
            f"{resolved['policy_file']} but still appear in the results. The "
            "--exclude-rule prefix this script computed did not match semgrep's. "
            "Treating the policy as unreliable rather than applying it partially.",
            file=sys.stderr,
        )
        return 2

    if resolved["policy_file"]:
        print("── Policy ──")
        print("  groups     " + (", ".join(resolved["groups"]) or "(none)"))
        if resolved["extends"]:
            print("  extends    " + resolved["extends"])
        if resolved["exclude"]:
            print("  excluded   " + ", ".join(resolved["exclude"]))
        if disabled:
            print("  disabled   " + ", ".join(sorted(disabled)))
        if warned:
            by_rule = {}
            for rid, _f, _l in warn_hits:
                by_rule[rid] = by_rule.get(rid, 0) + 1
            detail = ", ".join(
                "%s (%d)" % (r, by_rule.get(r, 0)) for r in sorted(warned)
            )
            print("  warn-only  " + detail)
        print()

    for rid, path, line in sorted(warn_hits, key=lambda e: (e[1], e[2], e[0])):
        # A warning has to be visible or the downgrade is just a delete with extra
        # steps. It goes to stdout, carries the same file:line as a gate finding,
        # and says outright that it is not failing the build.
        print(f"  warn  {rid:<52} {path}:{line}")
    if warn_hits:
        print(f"  ({len(warn_hits)} warn-only finding(s) — not gating)")
        print()

    # AFTER the classification, BEFORE the return. The verdict on the next line
    # is computed from `gate` and nothing here can reach it — which is the
    # property the annotation cap is tested against: `--annotate
    # --max-annotations 0` on a repo with findings still exits 1.
    if annotate:
        emit_annotations(gate_raw, warn_raw, max_annotations, annotate_prefix)

    print(f"semgrep_gate={len(gate)}")
    print(f"semgrep_warn={len(warn_hits)}")
    # Machine-readable alongside the other two, so the standing report and
    # scan.sh's summary read the same number the gate did rather than
    # re-deriving it from the pretty output.
    print(f"semgrep_unparsed={len(unparsed_files)}")
    return 1 if gate else 0


# --- CLI ----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_res = sub.add_parser("resolve", help="validate the policy and write the resolved form")
    p_res.add_argument("--target", required=True, help="the consuming repo")
    p_res.add_argument("--baseline", required=True, help="this repo, on the host")
    p_res.add_argument(
        "--baseline-path",
        default=None,
        help="the --config path semgrep will be given. Differs from --baseline "
        "under docker (/baseline), and the check_id prefix follows it.",
    )
    p_res.add_argument("--out", help="write the resolved policy JSON here")
    p_res.add_argument(
        "--explain",
        action="store_true",
        help="include the effective gate/warn rule id sets. This is the snapshot "
        "form — what the policy resolves to, not what the file says.",
    )

    p_args = sub.add_parser("args", help="print semgrep arguments, one per line")
    p_args.add_argument("--resolved", required=True)
    p_args.add_argument("--baseline-path", required=True)
    p_args.add_argument("--target-path", required=True)

    p_cls = sub.add_parser("classify", help="split results into gating and warn-only")
    p_cls.add_argument("--resolved", required=True)
    p_cls.add_argument("--results", required=True, help="semgrep --json-output file")
    p_cls.add_argument(
        "--annotate",
        action="store_true",
        help="also emit GitHub workflow commands so findings render on the PR "
        "diff. Additive only — it cannot change the exit code.",
    )
    p_cls.add_argument(
        "--max-annotations",
        type=int,
        default=DEFAULT_MAX_ANNOTATIONS,
        help="cap the annotations emitted; the omitted count is always stated. "
        "GitHub drops them past an undocumented per-run limit, and a silent "
        "truncation reads as 'that was all of them'.",
    )
    p_cls.add_argument(
        "--annotate-prefix",
        default="",
        help="prepended to each annotated path. Needed when the scan target is "
        "a subdirectory: semgrep reports paths relative to it, GitHub resolves "
        "them against the workspace root.",
    )

    args = ap.parse_args()

    try:
        if args.cmd == "resolve":
            baseline_path = args.baseline_path or args.baseline
            resolved = resolve(args.target, args.baseline, baseline_path, args.explain)
            text = json.dumps(resolved, indent=2, sort_keys=True) + "\n"
            if args.out:
                with open(args.out, "w", encoding="utf-8") as fh:
                    fh.write(text)
            else:
                sys.stdout.write(text)
            return 0

        with open(args.resolved, encoding="utf-8") as fh:
            resolved = json.load(fh)

        if args.cmd == "args":
            for a in semgrep_args(resolved, args.baseline_path, args.target_path):
                print(a)
            return 0

        return classify(
            resolved,
            args.results,
            annotate=args.annotate,
            max_annotations=args.max_annotations,
            annotate_prefix=args.annotate_prefix,
        )

    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
