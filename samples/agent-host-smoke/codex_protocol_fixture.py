"""OFFLINE native protocol simulator; direct calls here are never live evidence."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

MODE = os.environ.get("SMOKE_CODEX_PROTOCOL", "trusted")
THREAD = "offline-codex-thread"
TURN = "offline-codex-turn"


def emit(value):
    print(json.dumps(value), flush=True)


def notify(method, **params):
    emit({"method": method, "params": {"threadId": THREAD, "turnId": TURN, **params}})


def source():
    common = subprocess.check_output(["git", "rev-parse", "--git-common-dir"], text=True).strip()
    return (Path(common).resolve().parent / ".codex/hooks.json")


def metadata():
    path = source()
    data = json.loads(path.read_text()) if path.exists() else {}
    return [{"eventName": event[0].lower() + event[1:], "matcher": group.get("matcher"),
             "source": "project", "sourcePath": str(path), "enabled": MODE != "disabled",
             "trustStatus": MODE if MODE in ("untrusted", "modified") else "trusted",
             "currentHash": "" if MODE == "missing-hash" else "offline-hash", "key": str(index), "handlerType": "command",
             "command": entry["command"], "isManaged": False, "displayOrder": index,
             "timeoutSec": 60}
            for event, groups in data.get("hooks", {}).items()
            for index, group in enumerate(groups) for entry in group["hooks"]]


def hook(event, payload):
    if MODE == "silent":
        return True
    allowed = True
    for entry in metadata():
        if entry["eventName"] != event:
            continue
        if event == "preToolUse" and entry["matcher"] != payload.get("tool_name"):
            continue
        notify("hook/started", run={"id": "offline-" + event, "eventName": event,
            "source": "project", "sourcePath": str(source()), "handlerType": "command",
            "executionMode": "sync", "status": "running"})
        result = subprocess.run(entry["command"], shell=True, input=json.dumps(payload),
                                capture_output=True, text=True)
        output = json.loads(result.stdout) if result.stdout.strip() else {}
        reason = output.get("reason") or output.get("hookSpecificOutput", {}).get("permissionDecisionReason")
        blocked = output.get("decision") == "block" or output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        notify("hook/completed", run={"id": "offline-" + event, "eventName": event,
            "source": "project", "sourcePath": str(source()), "scope": "turn",
            "handlerType": "command", "executionMode": "sync", "startedAt": 1,
            "displayOrder": 0, "status": "blocked" if blocked else "completed",
            "entries": [{"kind": "feedback", "text": reason}] if reason else []})
        allowed = allowed and not blocked
    return allowed


if "--version" in sys.argv:
    print("codex-cli 0.153.3")
    sys.exit()
if sys.argv[1:] != ["app-server"]:
    raise SystemExit("OFFLINE fixture rejects non-native launch")
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    params = request.get("params", {})
    if method == "initialized":
        continue
    result = {}
    if method == "initialize":
        assert params["capabilities"]["experimentalApi"] is True
        if MODE == "no-experimental-api":
            emit({"id": request["id"], "error": {"code": -32602, "message": "experimental API unavailable"}})
            continue
        result = {"userAgent": "offline", "platformFamily": "unix", "platformOs": "offline"}
    elif method == "account/read":
        result = {"account": None if MODE == "no-auth" else {"type": "chatgpt"}, "requiresOpenaiAuth": True}
    elif method == "hooks/list":
        result = {"data": [{"cwd": params["cwds"][0], "errors": [], "warnings": [],
                            "hooks": [] if MODE == "absent" or (MODE == "subdirectory-absent" and Path.cwd().name == "subdirectory") else metadata()}]}
    elif method == "thread/start":
        assert params["cwd"] == str(Path.cwd())
        assert params["ephemeral"] is True
        assert params["experimentalRawEvents"] is True
        assert "model" not in params and "config" not in params
        assert params["sandbox"] == "workspace-write"
        result = {"thread": {"id": THREAD}, "modelProvider": "openai"}
    elif method == "turn/start":
        if MODE == "expired-auth":
            emit({"id": request["id"], "error": {"code": -1, "message": "Authentication token expired"}})
            continue
        emit({"id": request["id"], "result": {"turn": {"id": TURN}}})
        payload = {"cwd": str(Path.cwd()), "session_id": THREAD}
        prompt = params["input"][0]["text"]
        if "exact harmless command" in prompt:
            command = prompt.splitlines()[1]
            if MODE != "no-raw-events":
                notify("rawResponseItem/completed", item={"type": "custom_tool_call", "name": "exec",
                    "id": "offline-raw", "call_id": "offline-call",
                    "input": "text(await tools.exec_command({cmd:" + json.dumps(command) + "}));\n"})
            item = {"id": "offline-command", "type": "commandExecution",
                    "command": "/bin/zsh -lc " + shlex.quote(command),
                    "cwd": str(Path.cwd()), "commandActions": [], "status": "inProgress"}
            allowed = hook("preToolUse", {**payload, "tool_name": "Bash", "tool_input": {"command": command}})
            if allowed:
                notify("item/started", item=item, startedAtMs=1)
                code = subprocess.run(command, shell=True).returncode
                notify("item/completed", item={**item, "status": "completed",
                       "exitCode": code}, completedAtMs=2)
        allowed = hook("stop", payload)
        # A blocked native Stop CONTINUES; the client must interrupt when it has
        # adequate hook/ledger evidence, not wait for a successful turn.
        if allowed:
            notify("turn/completed", turn={"id": TURN, "status": "completed", "items": [], "error": None})
        continue
    elif method == "turn/interrupt":
        if MODE == "late-tripwire" and "exact harmless command" in prompt and "--no-verify" in command:
            subprocess.run(command, shell=True, check=True)
        emit({"id": request["id"], "result": {}})
        notify("turn/completed", turn={"id": TURN, "status": "interrupted", "items": [], "error": None})
        continue
    else:
        raise SystemExit("Unexpected native method: " + str(method))
    emit({"id": request["id"], "result": result})
