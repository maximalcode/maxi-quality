"""OFFLINE protocol simulator. Direct hook calls here are never host evidence."""

import json
import os
from pathlib import Path
import subprocess
import sys


def emit(value):
    print(json.dumps(value))


def hook(event, payload):
    path = Path.cwd() / ".claude/settings.json"
    settings = json.loads(path.read_text()) if path.exists() else {}
    for group in settings.get("hooks", {}).get(event, []):
        for entry in group["hooks"]:
            result = subprocess.run(entry["command"], shell=True, input=json.dumps(payload),
                                    capture_output=True, text=True,
                                    env={**os.environ, "CLAUDE_PROJECT_DIR": str(Path.cwd())})
            emit({"type": "system", "subtype": "hook_response", "hook_event": event,
                  "session_id": "offline-protocol-session", "exit_code": result.returncode,
                  "outcome": "success", "stdout": result.stdout})
            if result.stdout.strip():
                output = json.loads(result.stdout)
                if output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
                    return False
    return True


if "--version" in sys.argv:
    print("2.1.236 (Claude Code)")
elif "--help" in sys.argv:
    print("--include-hook-events --no-session-persistence --tools")
elif "auth" in sys.argv:
    emit({"loggedIn": True})
else:
    payload = {"cwd": str(Path.cwd()), "session_id": "offline-protocol-session"}
    if sys.argv[sys.argv.index("--tools") + 1] == "Bash":
        command = sys.argv[-1].splitlines()[-1]
        emit({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "id": "offline-tool", "input": {"command": command}}]}})
        allowed = hook("PreToolUse", {**payload, "tool_name": "Bash", "tool_input": {"command": command}})
        if allowed:
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            error = result.returncode != 0
        else:
            error = True
        emit({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "offline-tool", "is_error": error}]}})
    hook("Stop", payload)
    emit({"type": "result", "is_error": False})
