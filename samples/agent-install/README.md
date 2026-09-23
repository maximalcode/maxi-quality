# Agent contract installation

Run the complete suite from the repository root:

```bash
python3 samples/agent-install/test_install.py -v
```

Run one named scenario, or select related tests:

```bash
python3 samples/agent-install/test_install.py AdoptionTests.test_readoption_is_idempotent_with_owned_settings -v
python3 samples/agent-install/test_install.py -k shared -v
```

Requires Python 3.10+, Bash and Git; no Python packages or network access.
The existing `adopt` CI check runs the same full command. Verbose output names
all scenarios; a failed command reports its arguments, working directory,
exit status, stdout and stderr. Commands time out after 60 seconds.

Each test owns a fresh temporary directory, repositories and home directory.
Git configuration and runtime-launcher overrides inherited from the caller are
isolated. Shared installation writes only inside that test's home. Paths include
spaces, and Git and the filesystem are real. Temporary trees are removed after
each test, including failures. Tests can run individually or in simultaneous
suite processes without relying on another test's files.

`fixture.py` owns this setup and command execution. `adoption_cases.py` tests the
public adoption command; `test_install.py` also tests the installer command
independently of the shell. Expected profiles and preservation rules are stated
in the tests, not derived by importing installation helpers. The fresh-install
case additionally retains the original installed guard fingerprint assertion.

## Coverage transferred from the workflow

The 18 former agent shell steps are covered by 22 named adoption tests. The
region step is split into five independently runnable cases; the idempotence
case now builds its own settings fixture instead of using the preceding step's
tree. This table maps the previous assertions to their new home; test names
below are methods of `AdoptionTests` and carry the `test_` prefix.

| Former scenario | Test suffix | Preserved observations |
| --- | --- | --- |
| Fresh install refuses | `fresh_install_runs_a_refusing_hook` | Full settings, checksum, installed files, Stop refusal and remedy, cache ignored by Git and fingerprint. |
| Agent contract only | `agent_writes_only_the_contract` | Enumerate every changed/untracked path in a tree with three languages; no workflow. |
| Conflicting surfaces | `combined_surface_flags_refuse_without_writes` | All three combinations, exit 3, two remedies, untouched tree. |
| Printed adoption commands | `printed_adoption_commands_run_from_their_reported_cwd` | Run emitted shell text from adopter and baseline, including self-adoption, paths with spaces and non-Git trees without a language. |
| Language offer | `language_offer_matches_actual_detection` | All 13 markers/empty cases; offered command count agrees with real language detection. |
| Inert flags | `inert_flags_are_reported_and_have_no_effect` | Default and non-default ref, no-workflow, force not inert, no false warning or effects. |
| Whole gate remedy | `printed_recorder_runs_the_whole_gate` | Paste exact instruction; failing second half records failure and blocks, passing gate permits Stop. |
| Profile agreement | `installed_files_settings_and_prose_agree` | With/without manifests, own prose, rule counts, deny rules, script inventory and orphan removal. |
| Instruction region | `region_refresh_preserves_edits_until_forced`; `incomplete_region_refuses`; `instruction_symlink_is_followed_and_reported`; `dangling_instruction_symlink_returns_partial_success`; `region_recorder_command_runs_in_both_install_shapes` | Idempotence, stale refresh, edits retained, force, malformed region, link target and reported path, exit 7, copied/shared fenced recorder commands create receipts. |
| Wrong repository | `cross_repo_recorder_refuses_without_receipts` | Exit 3 and no receipts in either tree; correct adopted and baseline-layout invocation still work. |
| Shared shim | `shared_shim_refuses_absent_body_and_runs_when_installed` | Only a small shim, missing-body refusal, commit denied/ordinary command allowed, explicit body install, pasted recorder and successful Stop. Also covers a home path with spaces. |
| Transitions | `mode_and_profile_transitions_leave_resolvable_wiring` | Copied/shared/copied, narrowed profile, missing-script verification, own broken hook preserved. |
| Existing settings | `merge_preserves_owned_settings_and_prose` | Own keys, permissions, hook content/order, one Bash group, baseline rules, ignore entries and unterminated prose. |
| Repeat installation | `readoption_is_idempotent_with_owned_settings` | Git diff empty and no untracked files after another adoption. |
| Invalid settings | `invalid_settings_refuse_without_any_writes` | All eight malformed/null shapes, exit 6, no tree changes or traceback. |
| Empty settings | `empty_settings_take_the_full_baseline` | Empty file accepts the complete baseline with manifests. |
| Explicit opt-in | `other_surfaces_never_install_the_agent_contract` | Default, hooks, force, dry-run and editor do not install agent files or instructions. |
| Agent preview | `agent_dry_run_names_changes_without_writing` | No writes, with scripts, settings and instructions named in output. |

## Installer ownership coverage

The six `InstallationTests` cases retain their separate observations:

- The installer alone installs all four copied/shared and manifest profiles.
  Each generated recorder command runs and the installed Stop hook accepts it.
- Repository adoption never publishes or refreshes shared code; explicit shared
  updates preserve unrelated files and include only usable runtime scripts.
- A shared dry run preserves both absent and existing runtimes.
- Ignore-file updates preserve original bytes, line endings and idempotence.
- Undecodable settings refuse before writes with exit 6.
- Undecodable instructions remain intact while enforcement installs with exit 7.

`samples/agent-guard/` continues to test runtime behavior in the baseline's own
layout. These installation tests exercise the different layout produced by
adoption. Language, editor and general CLI workflow tests retain their existing
coverage; this suite does not run their build tools.
