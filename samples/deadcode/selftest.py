#!/usr/bin/env python3
"""Exercise the dead-code action's changed-file selection with real Git history."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / "actions/deadcode"
SCRIPT = yaml.safe_load((ACTION / "action.yml").read_text())["runs"]["steps"][0]["run"]


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        # Fixture identities are synthetic; no global Git config or network.
        self.env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
        self.git(self.source, "init", "-b", "main")
        self.commit("existing.txt")
        self.git(self.source, "checkout", "-b", "feature")
        self.commit("feature.txt")
        self.git(self.source, "checkout", "main")
        self.commit("base-only.txt")
        self.git(self.source, "checkout", "-b", "pr-merge")
        self.git(self.source, "merge", "--no-ff", "feature", "-m", "Synthetic PR merge")
        self.git(self.source, "update-ref", "refs/pull/1/merge", "HEAD")
        self.checkout_ref("refs/pull/1/merge", "merge-checkout")

    def checkout_ref(self, ref, directory):
        self.checkout = self.root / directory
        self.checkout.mkdir()
        self.git(self.checkout, "init")
        self.git(self.checkout, "remote", "add", "origin", self.source.as_uri())
        self.git(self.checkout, "fetch", "--depth=1", "origin", ref)
        self.git(self.checkout, "checkout", "--detach", "FETCH_HEAD")
        (self.checkout / "package").mkdir()

    def git(self, cwd, *args):
        return subprocess.run(
            ["git", *args], cwd=cwd, env=self.env, check=True,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()

    def commit(self, name):
        (self.source / name).write_text(name + "\n")
        self.git(self.source, "add", name)
        self.git(self.source, "commit", "-m", "Add " + name)

    def run_action(self, base="origin/main"):
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", SCRIPT],
            cwd=self.checkout,
            env={**self.env, "ACTION_PATH": str(ACTION), "TOOL": "knip",
                 "DIR": "package", "MODE": "auto", "GATE_EXPORTS": "false",
                 "CHANGED_ONLY": base, "KNIP_MIN": "6.31.0",
                 "RUNNER_TEMP": str(self.root)},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

    def test_shallow_pull_request_merge_selects_feature_file(self):
        self.assertEqual(self.git(self.checkout, "rev-parse", "--is-shallow-repository"), "true")
        result = self.run_action()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.root / "mq-changed.txt").read_text().splitlines(), ["feature.txt"])
        self.assertIn("knip is not installed", result.stdout)

    def test_shallow_branch_excludes_changes_only_on_base(self):
        self.checkout_ref("refs/heads/feature", "branch-checkout")
        result = self.run_action()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.root / "mq-changed.txt").read_text().splitlines(), ["feature.txt"])

    def test_branch_with_more_than_200_commits_gets_full_history(self):
        parent = self.git(self.source, "rev-parse", "feature")
        tree = self.git(self.source, "rev-parse", "feature^{tree}")
        for index in range(205):
            parent = self.git(self.source, "commit-tree", tree, "-p", parent,
                              "-m", f"Feature history {index}")
        self.git(self.source, "update-ref", "refs/heads/feature", parent)
        self.checkout_ref("refs/heads/feature", "old-branch-checkout")
        result = self.run_action()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.root / "mq-changed.txt").read_text().splitlines(), ["feature.txt"])
        self.assertEqual(self.git(self.checkout, "rev-parse", "--is-shallow-repository"), "false")

    def test_full_checkout_stays_full(self):
        self.git(self.checkout, "fetch", "--unshallow", "origin", "refs/pull/1/merge")
        result = self.run_action()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.root / "mq-changed.txt").read_text().splitlines(), ["feature.txt"])
        self.assertEqual(self.git(self.checkout, "rev-parse", "--is-shallow-repository"), "false")

    def test_older_visible_merge_base_does_not_include_files_already_on_main(self):
        self.git(self.source, "checkout", "-b", "merged-feature", "main")
        self.commit("feature.txt")
        parent = self.git(self.source, "rev-parse", "HEAD")
        tree = self.git(self.source, "rev-parse", "HEAD^{tree}")
        for index in range(205):
            parent = self.git(self.source, "commit-tree", tree, "-p", parent,
                              "-m", f"Feature history {index}")
        old_base = self.git(self.source, "rev-parse", "main^")
        old_tree = self.git(self.source, "rev-parse", old_base + "^{tree}")
        side = self.git(self.source, "commit-tree", old_tree, "-p", old_base, "-m", "Side branch")
        merged = self.git(self.source, "commit-tree", tree, "-p", parent, "-p", side,
                          "-m", "Merge older side branch")
        self.git(self.source, "update-ref", "refs/heads/merged-feature", merged)
        self.checkout_ref("refs/heads/merged-feature", "merged-branch-checkout")
        result = self.run_action()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((self.root / "mq-changed.txt").read_text().splitlines(), ["feature.txt"])

    def test_missing_base_fails_loudly(self):
        result = self.run_action("origin/missing")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("::error::changed-only base ref 'origin/missing' cannot be resolved", result.stdout)
        self.assertFalse((self.root / "mq-changed.txt").exists())

    def test_incomplete_remote_history_fails_instead_of_guessing(self):
        shallow_origin = self.root / "shallow-origin"
        self.git(self.root, "clone", "--depth=1", "--no-single-branch",
                 self.source.as_uri(), str(shallow_origin))
        self.git(shallow_origin, "branch", "main", "origin/main")
        # Both refs resolve, but the replacement remote cannot supply parents.
        self.git(self.checkout, "fetch", "--depth=1", "origin", "main")
        self.git(self.checkout, "remote", "set-url", "origin", shallow_origin.as_uri())
        result = self.run_action()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("history remains shallow", result.stdout)
        self.assertFalse((self.root / "mq-changed.txt").exists())

    def test_unrelated_base_fails_loudly(self):
        tree = self.git(self.source, "rev-parse", "main^{tree}")
        unrelated = self.git(self.source, "commit-tree", tree, "-m", "Unrelated root")
        self.git(self.source, "update-ref", "refs/heads/unrelated", unrelated)
        result = self.run_action("origin/unrelated")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("resolves but has no merge base with HEAD", result.stdout)
        self.assertFalse((self.root / "mq-changed.txt").exists())

    def test_full_scan_does_not_fetch_or_create_changed_list(self):
        result = self.run_action("")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("knip is not installed", result.stdout)
        self.assertFalse((self.root / "mq-changed.txt").exists())
        self.assertEqual(self.git(self.checkout, "rev-parse", "--is-shallow-repository"), "true")


if __name__ == "__main__":
    unittest.main()
