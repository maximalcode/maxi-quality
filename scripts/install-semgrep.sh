#!/usr/bin/env bash
#
# maxi-quality — install the PINNED semgrep with a PINNED interpreter.
#
#   install-semgrep.sh <semgrep-version> <bin-dir>
#
# WHY THIS EXISTS AT ALL
#
# Layer 2 used to pin semgrep to an exact version and then install it with
# `pipx install "semgrep==$VERSION"`, which builds its venv from the AMBIENT
# `python3`. On ubuntu-latest that is >= 3.11 and the pin resolves; on a stock
# macOS self-hosted runner it is Apple's 3.9.6, and semgrep >= 1.137.0 declares
# Requires-Python >= 3.10. The job did not degrade — it failed in three seconds
# having scanned nothing, behind pip's 400-line "Ignored the following versions"
# wall (#131).
#
# A pin that depends on an undeclared ambient dependency is not a pin, it is a
# pin plus a hope about the host. That is the defect class `no-ambient-clock`
# exists to catch, and the baseline was doing to itself what it forbids
# consumers from doing. The invariant this file encodes:
#
#   THE VERSION OF PYTHON THAT INSTALLS A PINNED TOOL IS AS PINNED AS THE TOOL.
#
# WHY IT IS A SCRIPT AND NOT FOUR MORE LINES IN actions/layer2/action.yml
#
# The failure only reproduces on a host whose python3 is too old, and no runner
# this repo can rent is such a host — a GitHub macOS image ships 3.12+. As a
# script it is driven with a shim PATH (the pattern `tool-resolution` already
# uses for scan.sh), so the 3.9 case is proven on ubuntu-latest instead of being
# argued about. A ladder that cannot be tested is how the two resolution
# policies in this repo drifted apart in the first place.

set -Eeuo pipefail

VERSION="${1:?usage: install-semgrep.sh <semgrep-version> <bin-dir>}"
BIN_DIR="${2:?usage: install-semgrep.sh <semgrep-version> <bin-dir>}"

# The interpreter the pin is installed WITH. Same 3.12 that quality.yml's
# python-version input defaults to, so a consumer reading either finds one
# answer rather than two.
PINNED_PYTHON="3.12"

# semgrep's own floor, and the ONE source of truth for both the comparison and
# the error message. When semgrep raises its Requires-Python, this moves with
# it — and the failure keeps naming a requirement instead of a pip wall.
MIN_MAJOR=3
MIN_MINOR=10
MIN_PYTHON="${MIN_MAJOR}.${MIN_MINOR}"

mkdir -p "$BIN_DIR"
PATH="$BIN_DIR:$PATH"
export PATH

have() { command -v "$1" >/dev/null 2>&1; }

fatal() {
  echo "::error::$*" >&2
  exit 1
}

# Version is read from `-V` output rather than by executing a `sys.version_info`
# snippet. Two reasons: an interpreter that is too old to run semgrep is also an
# interpreter whose syntax support we should not be assuming anything about, and
# `-V` is what a PATH shim can honestly emulate — which is what makes the 3.9
# case testable at all.
py_minor() {
  local out
  out="$("$1" -V 2>&1)" || return 1
  [[ "$out" =~ ^Python\ ([0-9]+)\.([0-9]+) ]] || return 1
  printf '%s %s' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
}

py_is_adequate() {
  local parts major minor
  parts="$(py_minor "$1")" || return 1
  read -r major minor <<<"$parts"
  (( major > MIN_MAJOR || (major == MIN_MAJOR && minor >= MIN_MINOR) ))
}

# --- the ladder --------------------------------------------------------------
#
# uv first, and not merely as a preference: `uv tool install --python 3.12`
# takes the host's interpreter out of the equation entirely, because uv fetches
# the interpreter it needs rather than hoping for one. Everything below it is a
# fallback that still has to ASK what the host has.

install_via_uv() {
  have uv || return 1
  echo "semgrep ${VERSION}: installing via uv on a fetched Python ${PINNED_PYTHON}"
  # UV_PYTHON_DOWNLOADS is set explicitly rather than relied on: it defaults to
  # automatic, but a machine-level uv.toml can turn it off, and a fallback that
  # silently depends on host configuration is the bug this file exists to fix.
  UV_TOOL_BIN_DIR="$BIN_DIR" UV_PYTHON_DOWNLOADS=automatic \
    uv tool install --python "$PINNED_PYTHON" "semgrep==${VERSION}"
}

install_via_pipx() {
  local candidate py=""
  # The pin first, then descending known-good names, then bare python3 — which
  # is checked like any other candidate rather than trusted like it used to be.
  for candidate in "python${PINNED_PYTHON}" python3.13 python3.12 python3.11 python3.10 python3; do
    have "$candidate" || continue
    if py_is_adequate "$candidate"; then py="$candidate"; break; fi
  done

  if [[ -z "$py" ]]; then
    local found="none"
    if have python3; then found="$(python3 -V 2>&1 || echo unknown)"; fi
    # ONE line, naming what is required and what was found. The old failure
    # surfaced pip's "Ignored the following versions" wall, which buries the
    # single fact that matters under every semgrep release ever published.
    fatal "semgrep ${VERSION} requires Python >= ${MIN_PYTHON}, and this runner has ${found}." \
          "Install uv (preferred — it fetches its own interpreter) or a Python >= ${MIN_PYTHON}," \
          "or point the 'runner' input at a host that has one."
  fi

  echo "semgrep ${VERSION}: no uv on this runner; installing via pipx on ${py}"
  if ! have pipx; then
    # Bootstrapped with the interpreter we CHOSE, not with the ambient one:
    # a pipx whose own venv is 3.9 cannot install a 3.10-only package however
    # it is invoked afterwards. PEP 668 marks a Homebrew/system Python's
    # environment as externally managed, hence the second attempt.
    "$py" -m pip install --quiet --user pipx 2>/dev/null \
      || "$py" -m pip install --quiet --user --break-system-packages pipx
    PATH="$("$py" -m site --user-base)/bin:$PATH"
    export PATH
    if [[ -n "${GITHUB_PATH:-}" ]]; then
      "$py" -m site --user-base | sed 's|$|/bin|' >> "$GITHUB_PATH"
    fi
  fi
  # --python pins the venv pipx builds. PIPX_BIN_DIR puts the shim in the same
  # directory the action already puts gitleaks and osv-scanner in, and has
  # already added to GITHUB_PATH — so where semgrep lands stops depending on
  # whether ~/.local/bin happened to be on PATH.
  PIPX_BIN_DIR="$BIN_DIR" pipx install --python "$py" "semgrep==${VERSION}"
}

install_via_uv || install_via_pipx

# THE PIN IS VERIFIED, NOT ASSUMED. An installer that succeeded while resolving
# a different version is exactly the outcome every line above exists to prevent,
# and it would otherwise be discovered as a rule that quietly stopped existing.
installed="$(semgrep --version 2>/dev/null | head -1 || true)"
[[ "$installed" == "$VERSION" ]] \
  || fatal "installed semgrep is '${installed:-not on PATH}', expected '${VERSION}'."
echo "semgrep ${installed} ready in ${BIN_DIR}"
