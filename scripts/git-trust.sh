#!/usr/bin/env bash
#
# maxi-quality — let git read a checkout this user does not own.
#
#   . git-trust.sh
#   trust_checkout <directory>
#
# SOURCED, not executed: its whole effect is three exported variables, and a
# child process cannot export into its parent.
#
# WHY THIS EXISTS
#
# Inside a job container the steps run as root, and the workspace the runner
# mounts into it belongs to the runner's own user. Git refuses to open a
# repository whose owner is not the current user:
#
#   fatal: detected dubious ownership in repository at '/__w/repo/repo'
#
# Every composite action here runs git — Gitleaks walks history, the dead-code
# ratchet and the patch gate both diff against a base — so in a container all
# three stopped there. actions/checkout does not prevent it: the safe.directory
# it adds goes into a temporary global config that it removes again before the
# step ends (measured on runner 2.338.2 — the setting is gone in the next step).
#
# WHY THE ENVIRONMENT AND NOT `git config --global`
#
# An action cannot tell a job container from a self-hosted machine, and on the
# second `--global` is a real person's ~/.gitconfig, edited by a scan and never
# cleaned up — one more line per run. GIT_CONFIG_COUNT/KEY/VALUE scope the
# setting to this step's processes and their children (gitleaks and semgrep
# both shell out to git) and leave nothing behind.
#
# Git reads safe.directory from the environment since 2.38; before that only
# the system and global files counted. On an older git this is therefore a
# no-op and git's own message — which names the fix — is what the user sees,
# exactly as before this file existed.
#
# WHY ONLY WHEN THE OWNER DIFFERS
#
# So that on every runner where git already worked, this changes nothing at
# all — not even the environment. The exception is granted for the one
# repository the caller pointed at, never as `*`: the ownership check is a real
# defence against a hostile repository's config, and the workspace is the only
# repository this step was asked to trust.

trust_checkout() {
  local top n
  # Physical path: git compares safe.directory with the path it discovered
  # from the real working directory, and a symlinked spelling does not match.
  top="$(cd "${1:-.}" 2>/dev/null && pwd -P)" || return 0
  # The setting names the repository's ROOT, and the directory handed in may
  # sit below it (a monorepo scanning services/api).
  while [[ "$top" != / && ! -e "$top/.git" ]]; do
    top="$(dirname "$top")"
  done
  if [[ ! -e "$top/.git" ]]; then
    return 0
  fi
  if [[ -O "$top" && -O "$top/.git" ]]; then
    return 0
  fi
  # Appended, so a caller's own GIT_CONFIG_* entries survive.
  n="${GIT_CONFIG_COUNT:-0}"
  export "GIT_CONFIG_KEY_${n}=safe.directory"
  export "GIT_CONFIG_VALUE_${n}=${top}"
  export GIT_CONFIG_COUNT=$((n + 1))
  echo "git: ${top} is owned by another user (a job container); trusting it for this step only"
}
