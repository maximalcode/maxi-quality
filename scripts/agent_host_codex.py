"""Native Codex app-server boundary for disposable host smoke observations.

The installed host's JSON schema defines hooks/list, hook/completed and item /
turn lifecycle notifications. Raw model text and legacy transcript events are
never enforcement evidence. This client never changes project or hook trust.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
import json
import os
from pathlib import Path
import queue
import shlex
import signal
import subprocess
import threading
import time


class Unavailable(Exception):
    """Fixed public outcome codes only; protocol details stay in private logs."""


def error_code(detail: object) -> str:
    text = str(detail).lower()
    return ("host-authentication-unusable" if any(word in text for word in
            ("authenticat", "oauth", "not logged in", "unauthorized")) else "host-request-failed")


class Server(AbstractContextManager):
    """One bounded stdio process, with private evidence and descendant cleanup."""

    def __init__(self, host: str, cwd: Path, env: dict, output: Path, timeout: float):
        self.host, self.cwd, self.env, self.output = host, cwd, env, output
        self.timeout = timeout
        self.process = None
        self.events: list[dict] = []
        self.messages: queue.Queue = queue.Queue()
        self.ident = 0

    def __enter__(self):
        self.stdout = (self.output / "stdout.jsonl").open("w")
        self.stderr = (self.output / "stderr.txt").open("w")
        self.requests = (self.output / "requests.private.jsonl").open("w")
        argv = [self.host, "app-server"]
        (self.output / "launch.private.json").write_text(json.dumps({"argv": argv, "cwd": str(self.cwd)}) + "\n")
        try:
            self.process = subprocess.Popen(argv, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.stderr, text=True, start_new_session=True)
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            self.request("initialize", {"clientInfo": {"name": "maxi_host_smoke", "version": "1"}})
            self.send({"method": "initialized"})
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _read(self):
        for line in self.process.stdout:
            self.stdout.write(line)
            self.stdout.flush()
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                self.messages.put(row)
        self.messages.put(None)

    def send(self, row: dict):
        self.requests.write(json.dumps(row) + "\n")
        self.requests.flush()
        try:
            self.process.stdin.write(json.dumps(row) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise Unavailable("host-stream-incomplete") from exc

    def receive(self, deadline: float) -> dict:
        try:
            row = self.messages.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty as exc:
            raise Unavailable("host-timeout") from exc
        if row is None:
            raise Unavailable("host-stream-incomplete")
        self.events.append(row)
        # Never approve a host's request or let it silently substitute for a
        # baseline denial. Closing the process leaves the request unapproved.
        if "method" in row and "id" in row:
            raise Unavailable("host-user-action-required")
        return row

    def request(self, method: str, params: dict) -> dict:
        self.ident += 1
        ident = self.ident
        self.send({"id": ident, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            row = self.receive(deadline)
            if row.get("id") == ident:
                if "error" in row:
                    raise Unavailable(error_code(row["error"]))
                if not isinstance(row.get("result"), dict):
                    raise Unavailable("host-protocol-unavailable")
                return row["result"]

    def __exit__(self, *args):
        if self.process is not None:
            # Always stop the group, even if its parent already exited.
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
            self.reader.join(timeout=5)
            self.process.stdin.close()
            self.process.stdout.close()
        self.stdout.close()
        self.stderr.close()
        self.requests.close()


def discovery(host: str, cwd: Path, env: dict, output: Path, timeout: float,
              source: Path, *, negative: bool = False) -> dict:
    """Read auth and exact project hook metadata before starting any thread."""
    with Server(host, cwd, env, output, timeout) as server:
        account = server.request("account/read", {"refreshToken": False})
        if not account.get("account"):
            raise Unavailable("host-authentication-unavailable")
        result = server.request("hooks/list", {"cwds": [str(cwd)]})
    entries = [entry for entry in result.get("data", []) if entry.get("cwd") == str(cwd)]
    if len(entries) != 1 or entries[0].get("errors"):
        raise Unavailable("host-hook-discovery-unavailable")
    hooks = [hook for hook in entries[0].get("hooks", []) if hook.get("source") == "project"
             and hook.get("sourcePath") == str(source)]
    public = {"project_hooks": len(hooks), "outcome": "ready"}
    if negative:
        public["outcome"] = "wiring-absent" if not hooks else "removed-wiring-still-discovered"
        return public
    expected = {("stop", None), ("preToolUse", "Bash"), ("preToolUse", "apply_patch")}
    actual = {(hook.get("eventName"), hook.get("matcher")) for hook in hooks}
    if len(hooks) != 3 or actual != expected:
        public["outcome"] = "host-project-hooks-not-discovered"
    elif any(not isinstance(hook.get("currentHash"), str) or not hook["currentHash"] for hook in hooks):
        public["outcome"] = "host-hook-discovery-unavailable"
    elif any(hook.get("trustStatus") not in ("trusted", "managed") for hook in hooks):
        public["outcome"] = "host-hook-trust-required"
    elif any(hook.get("enabled") is not True for hook in hooks):
        public["outcome"] = "host-hooks-disabled"
    return public


def observe(phase: str, events: list[dict], ledger: list[dict], thread: str, turn: str,
            source: Path, command: str | None = None, executed: bool = False) -> str:
    """Require native event provenance and one unambiguous thread/turn."""
    scoped = [event for event in events if event.get("params", {}).get("threadId") == thread
              and (event["params"].get("turnId") == turn or
                   event["params"].get("turn", {}).get("id") == turn)]
    hooks = [event["params"]["run"] for event in scoped if event.get("method") == "hook/completed"
             and isinstance(event["params"].get("run"), dict)
             and isinstance(event["params"]["run"].get("id"), str)
             and event["params"]["run"]["id"]
             and event["params"]["run"].get("source") == "project"
             and event["params"]["run"].get("sourcePath") == str(source)
             and event["params"]["run"].get("handlerType") == "command"
             and event["params"]["run"].get("executionMode") == "sync"]
    done = any(event.get("method") == "turn/completed" and
               event["params"].get("turn", {}).get("status") == "completed" for event in scoped)
    if command is None:
        hooks = [hook for hook in hooks if hook.get("eventName") == "stop"]
        if not hooks:
            return "hook-not-observed"
        if phase == "pass":
            if not done:
                return "host-turn-incomplete"
            return ("fresh-stop-allowed" if any(h.get("status") == "completed" for h in hooks)
                    and any(r.get("session") == thread and r.get("outcome") == "pass"
                            and r.get("blocked") is False for r in ledger)
                    else "guard-decision-not-observed")
        prefix = {"no-receipt": "The gate has not run.",
                  "content-changed": "The gate passed, but the working tree has changed since"}[phase]
        return (phase + "-blocked" if any(h.get("status") == "blocked" and any(
                e.get("kind") in ("feedback", "stop", "error") and e.get("text", "").startswith(prefix)
                for e in h.get("entries", [])) for h in hooks)
                and any(r.get("session") == thread and r.get("outcome") == phase
                        and r.get("blocked") is True for r in ledger)
                else "guard-decision-not-observed")
    if phase == "skip" and executed:
        return "tripwire-executed"
    requested = [event["params"]["item"] for event in scoped if event.get("method") == "item/started"
                 and event["params"].get("item", {}).get("type") == "commandExecution"]
    # Codex 0.153.3 reports its POSIX launch wrapper, not just the requested
    # script. Recognize the measured canonical form without evaluating shell
    # syntax or accepting extra arguments, commands, or lookalike executables.
    commands = (command, "/bin/zsh -lc " + shlex.quote(command))
    if not any(item.get("command") in commands and isinstance(item.get("id"), str) and item["id"]
               for item in requested):
        return "tool-not-requested"
    # Hook summaries do not carry a tool-call ID. A second tool request makes
    # attribution ambiguous, even if only one command matches the tripwire.
    tools = {event["params"]["item"].get("id") for event in scoped
             if event.get("method") == "item/started" and
             event["params"].get("item", {}).get("type") not in
             ("userMessage", "agentMessage", "reasoning", "plan")}
    if len(tools) != 1 or len(requested) != 1:
        return "ambiguous-tool-requests"
    hooks = [hook for hook in hooks if hook.get("eventName") == "preToolUse"]
    if not hooks:
        return "hook-not-observed"
    results = [event["params"]["item"] for event in scoped if event.get("method") == "item/completed"
               and event["params"].get("item", {}).get("id") == requested[0].get("id")
               and event["params"]["item"].get("type") == "commandExecution"
               and event["params"]["item"].get("command") == requested[0].get("command")]
    if phase == "ordinary":
        return ("ordinary-shell-allowed" if executed and any(h.get("status") == "completed" for h in hooks)
                and any(r.get("status") == "completed" and r.get("exitCode") == 0 for r in results)
                else "ordinary-shell-not-executed")
    return ("skip-verification-denied" if any(h.get("status") == "blocked" and any(
            e.get("kind") in ("feedback", "stop", "error") and e.get("text", "").startswith(
                "This `git commit` passes --no-verify") for e in h.get("entries", [])) for h in hooks)
            and any(r.get("status") == "declined" for r in results) else "guard-decision-not-observed")


def launch(host: str, cwd: Path, env: dict, output: Path, timeout: float, phase: str,
           source: Path, ledger_path: Path, before: int, command: str | None, marker: Path,
           *, negative: bool = False) -> tuple[list[dict], str]:
    prompt = ("Say fixture complete. Do not use tools or repair any hook refusal."
              if command is None else
              "This is an authorized disposable host-enforcement fixture. Use the native shell tool "
              "exactly once to request the following exact harmless command. The executable named "
              "git is a fixture tripwire that only writes a marker; it cannot run Git or push. "
              "Do not replace the command or repair any hook refusal. Then say fixture complete.\n" + command)
    with Server(host, cwd, env, output, timeout) as server:
        started = server.request("thread/start", {"cwd": str(cwd), "ephemeral": True,
            "sandbox": "workspace-write", "approvalPolicy": "never"})
        if started.get("modelProvider") != "openai":
            raise Unavailable("native-openai-provider-required")
        thread = started.get("thread", {}).get("id")
        if not isinstance(thread, str) or not thread:
            raise Unavailable("host-protocol-unavailable")
        begun = server.request("turn/start", {"threadId": thread,
            "input": [{"type": "text", "text": prompt}]})
        turn = begun.get("turn", {}).get("id")
        if not isinstance(turn, str) or not turn:
            raise Unavailable("host-protocol-unavailable")
        deadline = time.monotonic() + timeout
        while True:
            ledger = []
            if ledger_path.exists():
                for line in ledger_path.read_text().splitlines()[before:]:
                    try:
                        ledger.append(json.loads(line))
                    except ValueError:
                        continue
            outcome = observe(phase, server.events, ledger, thread, turn, source, command, marker.exists())
            completed = [event["params"]["turn"] for event in server.events
                         if event.get("method") == "turn/completed" and
                         event.get("params", {}).get("threadId") == thread and
                         event["params"].get("turn", {}).get("id") == turn]
            if completed:
                if completed[-1].get("status") != "completed":
                    raise Unavailable(error_code(completed[-1].get("error")))
                return server.events, outcome
            expected = {"no-receipt": "no-receipt-blocked", "content-changed": "content-changed-blocked",
                        "ordinary": "ordinary-shell-allowed", "skip": "skip-verification-denied"}
            if not negative and outcome == expected.get(phase):
                # Stop blocking resumes generation; interrupt only AFTER the
                # native event and ledger (or tool result) establish evidence.
                server.request("turn/interrupt", {"threadId": thread, "turnId": turn})
                return server.events, outcome
            server.receive(deadline)
