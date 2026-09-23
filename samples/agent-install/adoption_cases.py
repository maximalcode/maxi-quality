"""Public adoption scenarios formerly embedded in the adopt CI job."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
from pathlib import Path

from fixture import ADOPT, BASELINE, InstallationFixture


class AdoptionTests(InstallationFixture):
    def stop(self, *, shared: bool = False) -> str:
        script = "shim.py" if shared else "stop-gate.py"
        return self.run_command(
            [sys.executable, str(self.repo / ".claude/agent-guard" / script),
             *(["stop-gate"] if shared else [])],
            {"cwd": str(self.repo), "hook_event_name": "Stop"})

    def recorder_instruction(self, output: str) -> str:
        doc = json.loads(output)
        self.assertEqual(doc.get("decision"), "block", output)
        lines = [line.strip() for line in doc["reason"].splitlines()
                 if "record-gate" in line]
        self.assertEqual(len(lines), 1, output)
        self.assertFalse(any(char in lines[0] for char in "&|;<>`"), lines[0])
        return lines[0]

    def printed_commands(self, output: str) -> list[str]:
        return [line.strip() for line in output.splitlines()
                if re.match(r"^\s+\S*adopt\.sh(?:\s|$)", line)]

    def check_printed(self, output: str, count: int, *, cwd: Path | None = None) -> None:
        commands = self.printed_commands(output)
        self.assertEqual(len(commands), count, output)
        for command in commands:
            # Execute exactly the emitted shell text, including its quoting.
            self.run_command(["bash", "-c", command + " --dry-run"], cwd=cwd)

    def resolves(self) -> None:
        for groups in self.settings()["hooks"].values():
            for group in groups:
                for entry in group["hooks"]:
                    command = entry.get("command", "")
                    if "/.claude/agent-guard/" in command:
                        argv = shlex.split(command.replace("${CLAUDE_PROJECT_DIR}", str(self.repo)))
                        self.assertTrue(Path(argv[1]).is_file(), command)

    def prepare_owned_settings(self) -> dict:
        self.write("package.json", '{"name":"demo"}\n')
        own = {
            "model": "opus",
            "permissions": {"deny": ["Read(/.env)"], "allow": ["Bash(ls:*)"]},
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "python3 tools/mine.py", "timeout": 9}]}]},
        }
        self.write(".claude/settings.json", json.dumps(own))
        self.write("CLAUDE.md", "# Their CLAUDE.md\n\ntheir last line, no newline")
        self.write(".gitignore", "node_modules/\n")
        self.commit()
        self.samples()
        return own

    def test_fresh_install_runs_a_refusing_hook(self) -> None:
        self.write("package.json", '{"name":"demo"}\n')
        self.commit()
        self.samples()
        self.adopt()
        for name in (".claude/settings.json", ".claude/agent-guard/guard.py",
                     ".claude/agent-guard/stop-gate.py", "CLAUDE.md", ".gitignore"):
            self.assertTrue((self.repo / name).is_file(), name)
        baseline = json.loads((BASELINE / "configs/agent/settings.json").read_text())
        self.assertEqual(self.settings(), baseline)
        self.assertRegex(self.read("CLAUDE.md"),
                         r"<!-- BEGIN maxi-quality agent-guard sha256:[0-9a-f]+ -->")
        self.assertIn(".claude/agent-guard-receipt.json", self.read(".gitignore").splitlines())
        self.write("package.json", "ungated\n")
        output = self.stop()
        self.assertEqual(json.loads(output)["decision"], "block", output)
        self.assertIn(".claude/agent-guard/record-gate.py", output)
        self.assertFalse((self.repo / "scripts/agent-guard").exists())
        self.assertTrue((self.repo / ".claude/agent-guard/__pycache__").is_dir())
        self.assertNotIn("pycache", self.run_command(["git", "status", "--porcelain"]))
        # Preserve the separate fingerprint assertion from the original
        # scenario: Git ignoring a cache does not prove the guard ignores it.
        seen = self.run_command([sys.executable, "-c",
                                "import sys; sys.path.insert(0, '.claude/agent-guard'); "
                                "from guard import changed_files; "
                                "print([p for p in changed_files('.') if 'pycache' in p])"])
        self.assertEqual(seen.strip(), "[]")

    def test_agent_writes_only_the_contract(self) -> None:
        for name, body in {"package.json": '{"name":"demo"}', "tsconfig.json": "{}",
                           "pyproject.toml": '[project]\nname = "demo"\nversion = "0.1.0"\n',
                           "P.csproj": '<Project Sdk="Microsoft.NET.Sdk"></Project>'}.items():
            self.write(name, body)
        (self.repo / "src").mkdir()
        self.commit()
        self.adopt()
        for name in (".claude/settings.json", ".claude/agent-guard/stop-gate.py",
                     "CLAUDE.md", ".gitignore"):
            self.assertTrue((self.repo / name).exists(), name)
        # Do not exclude ignored files: installation just wrote .gitignore.
        changed = (self.run_command(["git", "ls-files", "--others"])
                   + self.run_command(["git", "diff", "--name-only"]))
        stray = [name for name in changed.splitlines()
                 if not name.startswith(".claude/") and name not in {"CLAUDE.md", ".gitignore"}]
        self.assertEqual(stray, [])
        self.assertFalse((self.repo / ".github/workflows/quality.yml").exists())

    def test_combined_surface_flags_refuse_without_writes(self) -> None:
        for flags in (("--editor",), ("--hooks",), ("--editor", "--hooks")):
            with self.subTest(flags=flags):
                self.create_repo("combo " + " ".join(flags))
                self.write("package.json", '{"name":"demo"}')
                self.commit()
                before = self.snapshot(self.repo)
                output = self.adopt(*flags, expected=3)
                self.assertGreaterEqual(sum("adopt.sh" in line for line in output.splitlines()), 2)
                self.assertEqual(self.snapshot(self.repo), before)
                self.assertEqual(self.run_command(["git", "status", "--porcelain"]), "")

    def test_printed_adoption_commands_run_from_their_reported_cwd(self) -> None:
        self.write("package.json", '{"name":"demo"}')
        for flag in ("--editor", "--hooks"):
            with self.subTest(flag=flag):
                self.check_printed(self.adopt(flag, expected=3), 2)
        result = self.run_result(["./scripts/adopt.sh", str(self.repo), "--agent", "--editor"],
                                 cwd=BASELINE, expected=3)
        self.check_printed(result.stdout + result.stderr, 2, cwd=BASELINE)
        result = self.run_result(["./scripts/adopt.sh", ".", "--agent", "--editor"],
                                 cwd=BASELINE, expected=3)
        output = result.stdout + result.stderr
        self.check_printed(output, 1, cwd=BASELINE)
        self.assertIn("--agent", output)
        self.check_printed(self.adopt(), 1)
        self.create_repo("another repo with spaces")
        self.write("package.json", '{"name":"demo"}')
        self.check_printed(self.adopt("--hooks", expected=3), 2)
        # No language and no Git repository: this population is admitted by
        # --agent, but a suggested language-layer command would fail.
        self.create_repo("no-language", git=False)
        self.check_printed(self.adopt(), 0)
        self.create_repo("no-language-combo", git=False)
        output = self.adopt("--editor", expected=3)
        self.check_printed(output, 1)
        self.assertIn("--agent", output)

    def test_language_offer_matches_actual_detection(self) -> None:
        markers = ("demo.csproj", "demo.sln", "demo.slnx", "tsconfig.json", "package.json",
                   "pyproject.toml", "requirements.txt", "uv.lock", "Cargo.toml", "pom.xml",
                   "build.gradle", "build.gradle.kts", "__none__")
        for marker in markers:
            with self.subTest(marker=marker):
                self.create_repo(marker, git=False)
                if marker != "__none__":
                    self.write(marker, "")
                language = self.run_result([*ADOPT, str(self.repo), "--dry-run"], expected=None)
                self.assertIn(language.returncode, (0, 1, 3), language.stdout + language.stderr)
                output = self.adopt()
                self.assertEqual(len(self.printed_commands(output)),
                                 1 if language.returncode == 0 else 0,
                                 language.stdout + language.stderr + output)

    def test_inert_flags_are_reported_and_have_no_effect(self) -> None:
        self.write("package.json", '{"name":"demo"}')
        self.assertIn("--ref does nothing on this", self.adopt("--ref", "v1"))
        self.create_repo("inert-all")
        self.write("package.json", '{"name":"demo"}')
        output = self.adopt("--force", "--no-workflow", "--ref", "v1.0.9")
        for flag in ("--no-workflow", "--ref"):
            self.assertIn(flag, output)
        self.assertNotIn("--force does nothing", output)
        self.assertFalse((self.repo / ".github").exists())
        for path in self.repo.rglob("*"):
            if path.is_file() and ".git" not in path.relative_to(self.repo).parts:
                self.assertNotIn(b"v1.0.9", path.read_bytes(), str(path))
        self.create_repo("inert-none")
        self.write("package.json", '{"name":"demo"}')
        self.assertNotIn("does nothing on this", self.adopt())

    def test_printed_recorder_runs_the_whole_gate(self) -> None:
        self.write("package.json", '{"name":"demo"}')
        self.adopt()
        self.write(".claude/agent-guard.json",
                   json.dumps({"gate_command": "test -f package.json && test -f NOPE"}))
        self.write("package.json", "ungated\n")
        line = self.recorder_instruction(self.stop())
        result = self.run_result(["bash", "-c", line], expected=None)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(self.read(".claude/agent-guard-receipt.json"))["verdict"], "fail")
        self.assertIn("FAILED", self.stop())
        self.write(".claude/agent-guard.json",
                   json.dumps({"gate_command": "test -f package.json && test -f .gitignore"}))
        line = self.recorder_instruction(self.stop())
        self.run_command(["bash", "-c", line])
        self.assertEqual(self.stop().strip(), "")

    def test_installed_files_settings_and_prose_agree(self) -> None:
        for samples in (False, True):
            with self.subTest(samples=samples):
                self.create_repo(f"profile-{samples}")
                self.write("CLAUDE.md", "# consumer\n\nOur own rules.\n")
                if samples:
                    self.samples()
                self.adopt()
                settings = self.settings()
                commands = [entry["command"] for groups in settings["hooks"].values()
                            for group in groups for entry in group["hooks"]]
                deny = settings["permissions"]["deny"]
                prose = self.read("CLAUDE.md")
                self.assertIn("Our own rules.", prose)
                self.assertIn("three hooks and two deny rules" if samples
                              else "two hooks and one deny rule", prose)
                self.assertEqual(any("sample-guard.py" in c for c in commands), samples)
                self.assertEqual(any("samples/expected" in r for r in deny), samples)
                self.assertTrue(any("stop-gate.py" in c for c in commands))
                self.assertTrue(any("no-verify" in c for c in commands))
                self.assertTrue(any("agent-guard-receipt" in r for r in deny))
                if not samples:
                    self.assertNotIn("samples/", prose)
                else:
                    self.assertIn("samples/expected/**", self.read(".claude/settings.json"))
                for path in (self.repo / ".claude/agent-guard").glob("*.py"):
                    self.assertNotEqual(path.name, "selftest.py")
                    self.assertTrue(path.name in {"guard.py", "record-gate.py"}
                                    or any(path.name in c for c in commands), path.name)
                self.assertEqual((self.repo / ".claude/agent-guard/sample-guard.py").exists(), samples)
                if not samples:
                    shutil.copy2(BASELINE / "scripts/agent-guard/selftest.py",
                                 self.repo / ".claude/agent-guard/selftest.py")
                    self.adopt()
                    self.assertFalse((self.repo / ".claude/agent-guard/selftest.py").exists())

    def test_region_refresh_preserves_edits_until_forced(self) -> None:
        self.write("CLAUDE.md", "# consumer\n\nOur own rules.\n")
        self.adopt()
        self.commit()
        self.adopt()
        self.run_command(["git", "diff", "--exit-code"])
        # The public region command plants a valid but stale profile, just as
        # an older installation would. Expectations do not import its helpers.
        self.run_command([sys.executable, str(BASELINE / "scripts/agent-region.py"), "apply",
                          "--fragment", str(BASELINE / "configs/agent/CLAUDE.fragment.md"),
                          "--target", str(self.repo / "CLAUDE.md"),
                          "--samples", "yes", "--shared", "no"])
        self.assertIn("three hooks and two deny rules", self.read("CLAUDE.md"))
        self.adopt()
        self.assertIn("two hooks and one deny rule", self.read("CLAUDE.md"))
        self.assertIn("Our own rules.", self.read("CLAUDE.md"))
        self.write("CLAUDE.md", self.read("CLAUDE.md").replace(
            "They are not advice", "MY EDIT. They are not advice", 1))
        before = (self.repo / "CLAUDE.md").read_bytes()
        output = self.adopt(expected=7)
        self.assertEqual((self.repo / "CLAUDE.md").read_bytes(), before)
        self.assertIn("MY EDIT", self.read("CLAUDE.md"))
        self.assertIn("edited since it was installed", output)
        self.adopt("--force")
        self.assertNotIn("MY EDIT", self.read("CLAUDE.md"))
        self.write("CLAUDE.md", self.read("CLAUDE.md").replace(
            "They are not advice", "EDIT AGAIN. They are not advice", 1))
        self.adopt(expected=7)
        self.assertIn("EDIT AGAIN", self.read("CLAUDE.md"))

    def test_incomplete_region_refuses(self) -> None:
        half = self.write("half.md", "# x\n<!-- BEGIN maxi-quality agent-guard sha256:dead -->\nbody\n")
        before = half.read_bytes()
        self.run_command([sys.executable, str(BASELINE / "scripts/agent-region.py"), "apply",
                          "--fragment", str(BASELINE / "configs/agent/CLAUDE.fragment.md"),
                          "--target", str(half), "--samples", "yes", "--shared", "no"], expected=4)
        self.assertEqual(half.read_bytes(), before)

    def test_instruction_symlink_is_followed_and_reported(self) -> None:
        self.write("AGENTS.md", "# Real\n\nProse.\n")
        link = self.repo / "CLAUDE.md"
        link.symlink_to("AGENTS.md")
        self.commit()
        output = self.adopt()
        self.assertTrue(link.is_symlink())
        self.assertIn("BEGIN maxi-quality agent-guard", self.read("AGENTS.md"))
        self.assertIn(str(self.repo / "AGENTS.md"), output)

    def test_dangling_instruction_symlink_returns_partial_success(self) -> None:
        link = self.repo / "CLAUDE.md"
        link.symlink_to("NOPE.md")
        self.commit()
        self.adopt(expected=7)
        self.assertTrue(link.is_symlink())
        self.assertFalse((self.repo / "NOPE.md").exists())

    def test_region_recorder_command_runs_in_both_install_shapes(self) -> None:
        self.run_command([*ADOPT, "--install-shared"])
        for shared in (False, True):
            with self.subTest(shared=shared):
                self.create_repo(f"region-command-{shared}")
                self.write("CLAUDE.md", "# C\n")
                self.write(".claude/agent-guard.json", '{"gate_command":"true"}')
                self.adopt(*(["--shared"] if shared else []))
                text = self.read("CLAUDE.md")
                region = text[text.index("<!-- BEGIN maxi-quality agent-guard"):
                              text.index("<!-- END maxi-quality agent-guard -->")]
                match = re.search(r"```bash\n(.+?)\n```", region, re.S)
                self.assertIsNotNone(match, region)
                assert match is not None
                command = match.group(1).strip()
                self.assertTrue(command, region)
                self.run_command(["bash", "-c", command])
                self.assertTrue((self.repo / ".claude/agent-guard-receipt.json").is_file())

    def test_cross_repo_recorder_refuses_without_receipts(self) -> None:
        repos = []
        for name in ("A", "B"):
            repos.append(self.create_repo(name))
            self.adopt()
            self.write(".claude/agent-guard.json", '{"gate_command":"true"}')
        first, second = repos
        self.write("work.txt", "ungated\n")
        result = self.run_result([sys.executable,
                                  str(second / ".claude/agent-guard/record-gate.py"), "--gate"],
                                 cwd=first, expected=3)
        for repo in repos:
            self.assertFalse((repo / ".claude/agent-guard-receipt.json").exists())
        self.assertIn("belongs to", result.stdout + result.stderr)
        self.run_command([sys.executable, ".claude/agent-guard/record-gate.py", "--gate"])
        self.assertTrue((second / ".claude/agent-guard-receipt.json").exists())
        self.run_command([sys.executable, str(BASELINE / "scripts/agent-guard/record-gate.py"),
                          "--gate"], cwd=first)

    def test_shared_shim_refuses_absent_body_and_runs_when_installed(self) -> None:
        self.adopt("--shared")
        self.write(".claude/agent-guard.json", '{"gate_command":"true"}')
        installed = self.repo / ".claude/agent-guard"
        self.assertEqual(sorted(p.name for p in installed.iterdir()), ["shim.py"])
        self.assertLess(len((installed / "shim.py").read_text().splitlines()), 150)
        self.assertRegex(self.read(".claude/settings.json"), r"shim[.]py.*stop-gate")
        self.write("work.txt", "ungated\n")
        output = self.stop(shared=True)
        self.assertEqual(json.loads(output)["decision"], "block", output)
        self.assertIn("install-shared", output)
        shim = [sys.executable, str(installed / "shim.py"), "no-verify-guard"]
        denial = self.run_command(shim, {"tool_input": {"command": "git commit -m x"}})
        self.assertEqual(json.loads(denial)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.run_command(shim, {"tool_input": {"command": "ls -la"}}).strip(), "")
        self.run_command([*ADOPT, "--install-shared"])
        self.assertTrue((self.runtime / "stop-gate.py").is_file())
        self.assertFalse((self.runtime / "selftest.py").exists())
        line = self.recorder_instruction(self.stop(shared=True))
        self.run_command(["bash", "-c", line])
        self.assertTrue((self.repo / ".claude/agent-guard-receipt.json").is_file())
        self.assertEqual(self.stop(shared=True).strip(), "")

    def test_mode_and_profile_transitions_leave_resolvable_wiring(self) -> None:
        self.run_command([*ADOPT, "--install-shared"])
        for flags in ((), ("--shared",), ()):
            self.adopt(*flags)
            self.resolves()
        self.create_repo("narrowing")
        self.samples()
        self.adopt()
        self.resolves()
        self.assertIn("sample-guard", self.read(".claude/settings.json"))
        shutil.rmtree(self.repo / "samples")
        self.adopt()
        self.resolves()
        self.assertNotIn("sample-guard", self.read(".claude/settings.json"))
        (self.repo / ".claude/agent-guard/stop-gate.py").unlink()
        self.run_command([sys.executable, str(BASELINE / "scripts/agent-settings.py"), "verify",
                          "--target", str(self.repo / ".claude/settings.json"),
                          "--root", str(self.repo)], expected=1)
        self.create_repo("own-broken-hook")
        self.adopt()
        settings = self.settings()
        settings["hooks"]["Stop"][0]["hooks"].append(
            {"type": "command", "command": 'python3 "${CLAUDE_PROJECT_DIR}/theirs.py"'})
        self.write(".claude/settings.json", json.dumps(settings))
        self.adopt()
        self.assertIn("theirs.py", self.read(".claude/settings.json"))

    def test_merge_preserves_owned_settings_and_prose(self) -> None:
        own = self.prepare_owned_settings()
        self.adopt()
        settings = self.settings()
        baseline = json.loads((BASELINE / "configs/agent/settings.json").read_text())
        self.assertEqual(settings["model"], own["model"])
        self.assertEqual(settings["permissions"]["allow"], own["permissions"]["allow"])
        self.assertEqual(settings["permissions"]["deny"][0], "Read(/.env)")
        mine = [entry for group in settings["hooks"]["PreToolUse"] for entry in group["hooks"]
                if entry["command"] == "python3 tools/mine.py"]
        self.assertEqual(mine, own["hooks"]["PreToolUse"][0]["hooks"])
        groups = [group for group in settings["hooks"]["PreToolUse"] if group.get("matcher") == "Bash"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["hooks"][0]["command"], "python3 tools/mine.py")
        want = {entry["command"] for groups in baseline["hooks"].values()
                for group in groups for entry in group["hooks"]}
        have = {entry["command"] for groups in settings["hooks"].values()
                for group in groups for entry in group["hooks"]}
        self.assertTrue(want <= have, want - have)
        for rule in baseline["permissions"]["deny"]:
            self.assertIn(rule, settings["permissions"]["deny"])
        self.assertIn("node_modules/", self.read(".gitignore").splitlines())
        self.assertIn("their last line, no newline", self.read("CLAUDE.md").splitlines())
        self.assertEqual(self.read("CLAUDE.md").splitlines()[0], "# Their CLAUDE.md")

    def test_readoption_is_idempotent_with_owned_settings(self) -> None:
        # Build the entire scenario here; the old CI step depended on the
        # previous merge test's /tmp/ag-own tree.
        self.prepare_owned_settings()
        self.adopt()
        self.commit()
        self.adopt()
        self.run_command(["git", "diff", "--exit-code"])
        self.assertEqual(self.run_command(["git", "ls-files", "--others", "--exclude-standard"]), "")

    def test_invalid_settings_refuse_without_any_writes(self) -> None:
        invalid = {
            "oops": '{"hooks": "oops"}', "comma": '{"hooks": {},}',
            "hooksnull": '{"hooks": null}', "eventnull": '{"hooks": {"Stop": null}}',
            "permnull": '{"permissions": null}', "denynull": '{"permissions": {"deny": null}}',
            "toplevel": 'null', "denyobj": '{"permissions": {"deny": [{"tool": "Edit"}]}}',
        }
        for name, body in invalid.items():
            with self.subTest(shape=name):
                self.create_repo(name, git=False)
                self.write("package.json", '{"name":"demo"}')
                self.write(".claude/settings.json", body)
                before = self.snapshot(self.repo)
                output = self.adopt(expected=6)
                self.assertEqual(self.snapshot(self.repo), before)
                self.assertNotIn("Traceback (most recent call last)", output)

    def test_empty_settings_take_the_full_baseline(self) -> None:
        self.create_repo("empty-settings", git=False)
        self.write("package.json", '{"name":"demo"}')
        self.write(".claude/settings.json", "")
        self.samples()
        self.adopt()
        self.assertEqual(self.settings(),
                         json.loads((BASELINE / "configs/agent/settings.json").read_text()))

    def test_other_surfaces_never_install_the_agent_contract(self) -> None:
        for flags in ((), ("--hooks",), ("--force",), ("--dry-run",), ("--editor",)):
            with self.subTest(flags=flags):
                self.create_repo("optin " + repr(flags))
                self.write("package.json", '{"name":"demo"}')
                self.run_command([*ADOPT, str(self.repo), "--no-workflow", *flags])
                self.assertFalse((self.repo / ".claude").exists())
                if (self.repo / "CLAUDE.md").exists():
                    self.assertNotIn("maxi-quality agent-guard", self.read("CLAUDE.md"))

    def test_agent_dry_run_names_changes_without_writing(self) -> None:
        self.create_repo("dry-run", git=False)
        self.write("package.json", '{"name":"demo"}')
        before = self.snapshot(self.repo)
        output = self.adopt("--dry-run")
        self.assertEqual(self.snapshot(self.repo), before)
        for name in ("stop-gate.py", "CLAUDE.md", "settings.json"):
            self.assertIn(name, output)
