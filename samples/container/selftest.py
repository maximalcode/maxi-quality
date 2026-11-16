#!/usr/bin/env python3
"""quality.yml's `container-image` input, proven rather than asserted.

    python3 samples/container/selftest.py            # structure + shims
    python3 samples/container/selftest.py --docker   # ...and the real image

WHAT THIS IS FOR

`container-image` puts every job of the reusable workflow inside a container.
What a step can assume in there is not what it can assume on a hosted runner,
and nothing else in this repo's CI runs in one: steps are root, there is no
sudo, HOME is /github/home, cargo lives where the image put it, and the
checkout belongs to another user so git refuses to read it. Each of those was
a real failure before it was a line in the workflow.

ci.yml cannot simply call quality.yml with the input set — this repo's tree is
full of planted bugs, so the call would be red by design. So this does what
`detect-fixtures` and `coverage-input` already do: it EXTRACTS the shipped step
bodies out of quality.yml and the composite actions and runs them, verbatim,
under the conditions a job container imposes. There is no second copy to drift.

THREE LAYERS, CHEAPEST FIRST

1. Structure. Every job carries the container key and the identical
   prerequisites step, and the default is the empty string. Runs anywhere.
2. Shims. The prerequisites step and the semgrep installer's apt rung, driven
   with a fake PATH so "root with apt", "not root" and "nothing missing" are
   all reachable on one machine. Runs anywhere.
3. Docker. The detect job, the Rust job and the Layer 2 action, as root inside
   rust:1.97.1-bookworm, on a checkout owned by uid 1001. Needs Docker, the
   network, and a few minutes.

The Docker layer copies the fixture INTO the container and chowns it rather
than bind-mounting it, because a bind mount's apparent owner depends on the
host (Docker Desktop presents it as the container's own user), and the
ownership mismatch is the condition under test.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/quality.yml"
ACTIONS = {name: ROOT / "actions" / name / "action.yml"
           for name in ("layer2", "deadcode", "coverage")}

IMAGE = "rust:1.97.1-bookworm"
IMAGE_EXPR = "${{ inputs.container-image }}"
PREREQ = "Container prerequisites"
PREREQ_IF = "inputs.container-image != ''"
# The words a job may put in NEEDS. Anything else is a typo that the step
# would hand to apt as a package name.
NEEDS_WORDS = {"git", "curl", "jq", "python3", "pyyaml", "pipx"}

failures: list[str] = []


def check(ok: bool, message: str) -> bool:
    if not ok:
        failures.append(message)
        print(f"::error::{message}")
    return ok


def load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text())


def step_named(steps: list[dict], name: str) -> dict:
    found = [s for s in steps if s.get("name") == name]
    if len(found) != 1:
        sys.exit(f"::error::expected exactly one step named {name!r}, found {len(found)}")
    return found[0]


# --- 1. structure ------------------------------------------------------------

def structure() -> str:
    wf = load(WORKFLOW)
    # PyYAML reads the bare key `on` as the boolean True.
    inputs = (wf.get("on") or wf[True])["workflow_call"]["inputs"]

    spec = inputs.get("container-image")
    if check(spec is not None, "quality.yml has no container-image input"):
        # '' is the whole compatibility story: it is what every existing
        # caller passes by not passing anything.
        check(spec.get("default") == "",
              f"container-image must default to the empty string, not {spec.get('default')!r}")
        check(spec.get("type") == "string", "container-image must be a string input")

    bodies = {}
    for name, job in wf["jobs"].items():
        check(job.get("container") == {"image": IMAGE_EXPR},
              f"job '{name}': container must be exactly {{image: {IMAGE_EXPR}}}, "
              f"got {job.get('container')!r} — a job without it runs on the host "
              "while its siblings run in the image")
        steps = job["steps"]
        first = steps[0]
        if not check(first.get("name") == PREREQ,
                     f"job '{name}': the first step must be '{PREREQ}', not "
                     f"{first.get('name') or first.get('uses')!r}"):
            continue
        check(first.get("if") == PREREQ_IF,
              f"job '{name}': '{PREREQ}' must be guarded by `if: {PREREQ_IF}` — "
              "without it the step runs apt and edits ~/.gitconfig on a plain runner")
        check("actions/checkout@" in str(steps[1].get("uses")),
              f"job '{name}': checkout must come directly after '{PREREQ}', "
              "so git exists before it and the checkout is trusted after it")
        words = set((first.get("env") or {}).get("NEEDS", "").split())
        check(bool(words) and words <= NEEDS_WORDS,
              f"job '{name}': NEEDS is {sorted(words)}, allowed words are {sorted(NEEDS_WORDS)}")
        check("git" in words, f"job '{name}': NEEDS must include git — checkout needs it")
        bodies[name] = first.get("run", "")

    distinct = set(bodies.values())
    check(len(distinct) == 1,
          f"'{PREREQ}' differs between jobs ({len(distinct)} variants across "
          f"{sorted(bodies)}) — the copies must be byte-identical; only NEEDS may differ")

    # "No sudo" as a property of the shipped shell, not a habit. Comment lines
    # are dropped first: two of them explain why sudo is NOT used.
    shipped = [(f"quality.yml job '{n}'", s) for n, j in wf["jobs"].items() for s in j["steps"]]
    for name, path in ACTIONS.items():
        shipped += [(f"actions/{name}", s) for s in load(path)["runs"]["steps"]]
    for where, step in shipped:
        code = "\n".join(line for line in (step.get("run") or "").splitlines()
                         if not line.lstrip().startswith("#"))
        check(not re.search(r"\bsudo\b", code),
              f"{where}, step {step.get('name')!r}: calls sudo — a job container "
              "runs as root and has no sudo binary")

    print(f"structure: {len(bodies)} jobs carry the container key and one identical "
          f"'{PREREQ}' step")
    return next(iter(distinct)) if distinct else ""


# --- 2. shims ----------------------------------------------------------------

BASE_UTILS = ("bash", "env", "mkdir", "head", "cat", "chmod", "grep", "sed")


class Shim:
    """A PATH holding only what a test puts there."""

    def __init__(self, tmp: pathlib.Path, name: str):
        self.dir = tmp / name
        self.dir.mkdir()
        self.log = tmp / f"{name}.log"
        self.log.write_text("")
        for util in BASE_UTILS:
            target = shutil.which(util)
            if target is None:
                sys.exit(f"::error::this host has no {util}")
            (self.dir / util).symlink_to(target)

    def add(self, name: str, body: str) -> None:
        path = self.dir / name
        path.write_text(f"#!/usr/bin/env bash\nLOG={self.log}\nSHIM={self.dir}\n{body}\n")
        path.chmod(0o755)

    def run(self, argv: list[str], **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                              env={"PATH": str(self.dir), **env})

    def logged(self) -> str:
        return self.log.read_text()


LOGGING_GIT = 'echo "git $*" >> "$LOG"'
# An apt-get that "installs" by dropping a working command into the shim PATH,
# which is what makes the step's own re-check of PATH observable.
FAKE_APT = '''echo "apt-get $*" >> "$LOG"
[[ "$1" == install ]] || exit 0
for a in "$@"; do
  case "$a" in jq|pipx|curl|git|python3)
    printf '#!/usr/bin/env bash\\necho "%s $*" >> %s\\n' "$a" "$LOG" > "$SHIM/$a"; chmod +x "$SHIM/$a" ;;
  esac
done'''


def shims(prereq_body: str) -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        script = tmp / "prereq.sh"
        script.write_text(prereq_body)

        def prereq(shim: Shim, needs: str) -> subprocess.CompletedProcess:
            return shim.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", str(script)],
                            NEEDS=needs, GITHUB_WORKSPACE="/__w/repo/repo", HOME=str(tmp))

        # Nothing missing: no package manager is touched, the checkout is trusted.
        s = Shim(tmp, "present")
        s.add("git", LOGGING_GIT)
        s.add("jq", "exit 0")
        s.add("id", "echo 0")
        s.add("apt-get", FAKE_APT)
        r = prereq(s, "git jq")
        check(r.returncode == 0, f"prerequisites failed with every tool present: {r.stdout}{r.stderr}")
        check("apt-get" not in s.logged(), "prerequisites ran apt with nothing missing")
        check("git config --global --add safe.directory /__w/repo/repo" in s.logged(),
              "prerequisites did not mark the workspace as a safe directory")

        # Root with apt: the missing tools are installed, with no sudo anywhere.
        s = Shim(tmp, "root")
        s.add("git", LOGGING_GIT)
        s.add("id", "echo 0")
        s.add("apt-get", FAKE_APT)
        s.add("python3", "exit 1")  # no PyYAML: `import yaml` fails
        r = prereq(s, "git jq python3 pyyaml pipx")
        check(r.returncode == 0, f"prerequisites failed as root with apt: {r.stdout}{r.stderr}")
        log = s.logged()
        check(re.search(r"apt-get install .*\bjq python3-yaml pipx\b", log) is not None,
              f"root + apt did not install exactly the missing tools; apt saw: {log!r}")
        check("git config --global --add safe.directory" in log,
              "prerequisites installed tools and then never trusted the workspace")

        # uv already satisfies "something that can install semgrep".
        s = Shim(tmp, "uv")
        s.add("git", LOGGING_GIT)
        s.add("uv", "exit 0")
        s.add("id", "echo 0")
        s.add("apt-get", FAKE_APT)
        r = prereq(s, "git pipx")
        check(r.returncode == 0 and "apt-get" not in s.logged(),
              f"an image with uv was still told to install pipx: {s.logged()!r}")

        # Not root: it must stop, name what is missing, and install nothing.
        s = Shim(tmp, "user")
        s.add("git", LOGGING_GIT)
        s.add("id", "echo 1000")
        s.add("apt-get", FAKE_APT)
        r = prereq(s, "git jq")
        check(r.returncode != 0, "prerequisites passed as a non-root user with jq missing")
        check("::error::" in r.stdout and "jq" in r.stdout,
              f"the non-root failure does not name the missing tool: {r.stdout!r}")
        check(s.logged() == "", f"a refused run still touched the system: {s.logged()!r}")

        # No apt at all (alpine, fedora): same refusal, even as root.
        s = Shim(tmp, "noapt")
        s.add("git", LOGGING_GIT)
        s.add("id", "echo 0")
        r = prereq(s, "git jq")
        check(r.returncode != 0 and "jq" in r.stdout,
              "prerequisites did not refuse on an image without apt")

        # --- the semgrep installer's last rung --------------------------------
        version = re.search(r'^SEMGREP_PIN="([0-9.]+)"', (ROOT / "scripts/scan.sh").read_text(),
                            re.M).group(1)
        installer = [str(ROOT / "scripts/install-semgrep.sh"), version]
        pipless_python = ('[[ "$1" == "-V" ]] && echo "Python 3.12.7" && exit 0\n'
                          '[[ "$1" == "-m" && "$2" == "pip" ]] && exit 1\nexit 0')
        fake_pipx_via_apt = '''echo "apt-get $*" >> "$LOG"
[[ "$1" == install ]] || exit 0
cat > "$SHIM/pipx" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do case "$a" in semgrep==*) v="${a#semgrep==}";; esac; done
printf '#!/usr/bin/env bash\\necho %s\\n' "$v" > "$PIPX_BIN_DIR/semgrep"
chmod +x "$PIPX_BIN_DIR/semgrep"
EOF
chmod +x "$SHIM/pipx"'''

        s = Shim(tmp, "semgrep-root")
        s.add("python3", pipless_python)
        s.add("id", "echo 0")
        s.add("apt-get", fake_pipx_via_apt)
        r = s.run(installer + [str(tmp / "bin-root")])
        check(r.returncode == 0,
              f"no pip, no pipx, root with apt: the installer still failed: {r.stdout}{r.stderr}")
        check("apt-get install" in s.logged() and "pipx" in s.logged(),
              f"the installer did not reach for the image's pipx: {s.logged()!r}")
        check("sudo" not in s.logged(), "the installer used sudo")

        s = Shim(tmp, "semgrep-user")
        s.add("python3", pipless_python)
        s.add("id", "echo 1000")
        s.add("apt-get", fake_pipx_via_apt)
        r = s.run(installer + [str(tmp / "bin-user")])
        out = r.stdout + r.stderr
        check(r.returncode != 0, "no pip, no pipx, not root: the installer claimed success")
        check("needs uv, pipx or pip" in out,
              f"that failure does not say what is needed: {out!r}")
        check(s.logged() == "", f"a non-root run still called apt: {s.logged()!r}")

    print("shims: prerequisites and the semgrep installer install as root with apt, "
          "refuse otherwise, and never call sudo")


# --- 3. docker ---------------------------------------------------------------

# What the runner does around a step, reduced to what these steps rely on: its
# own shell line, the three job-container paths, and GITHUB_PATH being applied
# between steps. `prepare` builds the foreign-owned checkout.
DRIVER_HEAD = r'''
set -uo pipefail
export HOME=/github/home GITHUB_WORKSPACE=/__w/repo/repo RUNNER_TEMP=/__w/_temp
export RUNNER_OS=Linux RUNNER_ARCH=X64 GITHUB_ACTIONS=true
export GITHUB_STEP_SUMMARY=/__w/_temp/summary.md

die() { echo "::error::$*"; exit 1; }

prepare() {
  mkdir -p /github/home /__w/_temp /__w/repo
  cp -a "/fixtures/$1" /__w/repo/repo
  if [[ -n "${2:-}" ]]; then cp -a "/fixtures/$2" "/__w/repo/$2"; fi
  chown -R 1001:1001 /github/home /__w/repo
  [[ "$(id -u)" == 0 ]] || die "the image does not run as root, so this proves nothing"
  [[ ! -O /__w/repo/repo ]] || die "the checkout is owned by this user — the fixture lost the condition under test"
}

# step <id> <cwd> [VAR=value ...]
step() {
  local id="$1" cwd="$2" rc=0; shift 2
  echo "--- step: $id"
  : > /__w/_temp/path
  ( cd "$cwd" && env "$@" GITHUB_PATH=/__w/_temp/path GITHUB_OUTPUT="/__w/_temp/$id.out" \
      bash --noprofile --norc -e -o pipefail "/steps/$id.sh" ) || rc=$?
  while IFS= read -r p; do
    if [[ -n "$p" ]]; then PATH="$p:$PATH"; fi
  done < /__w/_temp/path
  export PATH
  return "$rc"
}
'''

DETECT = r'''
prepare rust-clean
command -v jq >/dev/null && die "the image now ships jq — this no longer tests installing it"
step prereq "$GITHUB_WORKSPACE" NEEDS="$NEEDS_DETECT" || die "prerequisites failed in the detect job"
step scan "$GITHUB_WORKSPACE" LANGS=auto || die "detection failed inside the container"
cat /__w/_temp/scan.out
grep -qx 'rust_dirs=\["."\]' /__w/_temp/scan.out || die "detection did not find the crate at the root"
grep -qx 'has_rust=true' /__w/_temp/scan.out || die "has_rust is not true"
grep -qx 'has_ts=false' /__w/_temp/scan.out || die "detection invented a TypeScript project"
echo "OK: detection runs as root in the image and finds the crate"
'''

RUST = r'''
prepare rust-clean rust
[[ ! -d "$HOME/.cargo/bin" ]] || die "~/.cargo/bin exists in the image — the cargo-deny fallback is no longer exercised"
git -C "$GITHUB_WORKSPACE" status >/dev/null 2>&1 && die "git already trusts the checkout — the ownership condition is not reproduced"
step prereq "$GITHUB_WORKSPACE" NEEDS="$NEEDS_RUST" || die "prerequisites failed in the rust job"
git -C "$GITHUB_WORKSPACE" status >/dev/null || die "git still refuses the checkout after the prerequisites step"
step cargo-path "$GITHUB_WORKSPACE" || die "the PATH step failed"
step toolchain "$GITHUB_WORKSPACE" RUST_VERSION="$RUST_VERSION" || die "the pinned toolchain did not install as root"
step cargo-deny "$GITHUB_WORKSPACE" CARGO_DENY_SHA256="$CARGO_DENY_SHA256" || die "cargo-deny did not install"
[[ "$(command -v cargo-deny)" == "$CARGO_HOME/bin/cargo-deny" ]] \
  || die "cargo-deny landed at '$(command -v cargo-deny)', expected $CARGO_HOME/bin"
step gate "$GITHUB_WORKSPACE" || die "the clean fixture failed the Rust gate inside the container"
# The gate has to still GATE in there. A job that goes green on everything
# because of where it ran is the failure this whole repo exists to prevent.
if step gate /__w/repo/rust > /__w/_temp/bad.log 2>&1; then
  cat /__w/_temp/bad.log; die "samples/rust PASSED the Rust gate inside the container"
fi
tail -15 /__w/_temp/bad.log
# ...and red for the RIGHT reason. A missing binary or a permission error also
# exits non-zero, and would make this assertion pass while proving nothing.
# rustfmt is the first check in the step and samples/rust carries formatting
# bait, so its diff is the finding that has to be there.
grep -q '^Diff in /__w/repo/rust/' /__w/_temp/bad.log \
  || die "samples/rust failed, but not on the formatting finding it is baited with"
echo "OK: the Rust job gates as root in the image — clean passes, samples/rust fails"
'''

LAYER2 = r'''
prepare rust-clean
export GITHUB_ACTION_PATH=/mq/actions/layer2
python3 -c 'import yaml' 2>/dev/null && die "the image now ships PyYAML — this no longer tests installing it"
git -C "$GITHUB_WORKSPACE" status >/dev/null 2>&1 && die "git already trusts the checkout — the ownership condition is not reproduced"
# NO prerequisites step: this is the action on its own, as a caller's own
# container job would run it.
step install "$GITHUB_WORKSPACE" \
  SEMGREP_VERSION="$SEMGREP_VERSION" GITLEAKS_VERSION="$GITLEAKS_VERSION" OSV_VERSION="$OSV_VERSION" \
  GITLEAKS_SHA256= OSV_SHA256= || die "Layer 2 could not install its tools as root in the image"
step scan "$GITHUB_WORKSPACE" TARGET="$GITHUB_WORKSPACE" WORKSPACE="$GITHUB_WORKSPACE" \
  JSON_OUT= SBOM_OUT= LICENSES= NO_FAIL=false CHANGED_ONLY= ANNOTATE=true MAX_ANNOTATIONS=50 \
  || die "Layer 2 failed on the clean fixture inside the container"
cat /__w/_temp/scan.out
grep -q '^gitleaks=clean' /__w/_temp/scan.out || die "Gitleaks did not report clean — it needs git to read the checkout"
grep -q '^semgrep=clean' /__w/_temp/scan.out || die "Semgrep did not report clean"
# Scoped to the step: nothing may have been written to the global config.
[[ ! -e "$HOME/.gitconfig" ]] || die "the action wrote $HOME/.gitconfig: $(cat "$HOME/.gitconfig")"
git -C "$GITHUB_WORKSPACE" status >/dev/null 2>&1 && die "the trust outlived the step that needed it"

# The helper the other two actions share, on a directory BELOW the root.
( . /mq/scripts/git-trust.sh
  trust_checkout "$GITHUB_WORKSPACE/src"
  git -C "$GITHUB_WORKSPACE/src" rev-parse HEAD >/dev/null ) \
  || die "trust_checkout did not find the repository root from a subdirectory"
echo "OK: Layer 2 installs and scans as root in the image, and leaves no global git config"
'''


def write_steps(directory: pathlib.Path, bodies: dict[str, str]) -> None:
    for name, body in bodies.items():
        (directory / f"{name}.sh").write_text(body)


def fixture(dest: pathlib.Path, source: pathlib.Path) -> None:
    """A committed checkout: Gitleaks reads history, so there has to be some."""
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns("target"))
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
           "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    for argv in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", *argv], cwd=dest, env=env, check=True)


def docker(prereq_body: str, platform: str | None, only: str | None) -> None:
    wf = load(WORKFLOW)
    jobs = wf["jobs"]
    inputs = (wf.get("on") or wf[True])["workflow_call"]["inputs"]
    layer2 = load(ACTIONS["layer2"])

    def needs(job: str) -> str:
        return jobs[job]["steps"][0]["env"]["NEEDS"]

    rust_steps = jobs["rust"]["steps"]
    deny = step_named(rust_steps, "Pinned cargo-deny (checksum-verified)")
    scenarios = {
        "detect": (DETECT, {
            "prereq": prereq_body,
            "scan": next(s for s in jobs["detect"]["steps"] if s.get("id") == "scan")["run"],
        }, {"NEEDS_DETECT": needs("detect")}),
        "rust": (RUST, {
            "prereq": prereq_body,
            "cargo-path": step_named(
                rust_steps, "Put cargo's user bin dir on PATH (self-hosted runners)")["run"],
            "toolchain": step_named(rust_steps, "Pinned Rust toolchain")["run"],
            "cargo-deny": deny["run"],
            "gate": step_named(rust_steps, "Format, lint and audit")["run"],
        }, {"NEEDS_RUST": needs("rust"),
            "RUST_VERSION": inputs["rust-version"]["default"],
            "CARGO_DENY_SHA256": deny["env"]["CARGO_DENY_SHA256"]}),
        "layer2": (LAYER2, {
            "install": step_named(layer2["runs"]["steps"], "Install pinned tools")["run"],
            "scan": step_named(layer2["runs"]["steps"], "Layer 2 scan")["run"],
        }, {"SEMGREP_VERSION": layer2["inputs"]["semgrep-version"]["default"],
            "GITLEAKS_VERSION": layer2["inputs"]["gitleaks-version"]["default"],
            "OSV_VERSION": layer2["inputs"]["osv-scanner-version"]["default"]}),
    }

    with tempfile.TemporaryDirectory() as raw:
        tmp = pathlib.Path(raw)
        fixtures = tmp / "fixtures"
        fixtures.mkdir()
        fixture(fixtures / "rust-clean", ROOT / "samples/rust-clean")
        fixture(fixtures / "rust", ROOT / "samples/rust")

        for name, (script, bodies, env) in scenarios.items():
            if only and name != only:
                continue
            steps = tmp / f"steps-{name}"
            steps.mkdir()
            write_steps(steps, bodies)
            (steps / "driver.sh").write_text(DRIVER_HEAD + script)
            argv = ["docker", "run", "--rm"]
            if platform:
                argv += ["--platform", platform]
            for key, value in env.items():
                argv += ["-e", f"{key}={value}"]
            argv += ["-v", f"{fixtures}:/fixtures:ro", "-v", f"{steps}:/steps:ro",
                     "-v", f"{ROOT}:/mq:ro", IMAGE, "bash", "/steps/driver.sh"]
            print(f"=== docker: {name} (as root in {IMAGE})", flush=True)
            result = subprocess.run(argv)
            check(result.returncode == 0,
                  f"container scenario '{name}' failed (exit {result.returncode}) — see the log above")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docker", action="store_true",
                        help=f"also run the shipped steps as root inside {IMAGE}")
    parser.add_argument("--platform", default=None,
                        help="passed to docker run, e.g. linux/amd64 on an arm64 host")
    parser.add_argument("--scenario", choices=("detect", "rust", "layer2"), default=None,
                        help="run one container scenario instead of all three")
    args = parser.parse_args()

    prereq_body = structure()
    if prereq_body:
        shims(prereq_body)
    if args.docker and not failures:
        docker(prereq_body, args.platform, args.scenario)
    elif not args.docker:
        print("docker: skipped (pass --docker to run the shipped steps inside the image)")

    if failures:
        print(f"\nFAIL — {len(failures)} problem(s)")
        return 1
    print("\nOK: container-image is wired into every job"
          + (" and the shipped steps run as root inside the image" if args.docker else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
