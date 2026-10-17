"""Small durable journal for deliberate, project-local Guardian updates."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile

PENDING_NAME = "guardian-update-pending.json"


class PendingUpdateError(ValueError):
    """A pending transition cannot be recovered without risking user changes."""


def pending_path(metadata: Path) -> Path:
    return metadata / PENDING_NAME


def read_pending(metadata: Path) -> dict | None:
    path = pending_path(metadata)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PendingUpdateError(f"pending Guardian update journal is unreadable: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise PendingUpdateError("pending Guardian update journal has an unsupported format")
    return value


def write_pending(metadata: Path, value: dict) -> None:
    metadata.mkdir(parents=True, exist_ok=True)
    path = pending_path(metadata)
    fd, temporary = tempfile.mkstemp(prefix=".guardian-update-", dir=metadata)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(metadata, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def remove_pending(metadata: Path) -> None:
    pending_path(metadata).unlink(missing_ok=True)


def encode_snapshot(snapshot: dict[str, tuple[str, bytes | str, int] | None],
                    new_values: dict[str, tuple[str, bytes | str] | None]) -> dict:
    paths = {}
    for name, old in snapshot.items():
        if old is None:
            old_value = None
        elif old[0] == "file":
            old_value = {"kind": "file", "value": base64.b64encode(old[1]).decode(),
                         "mode": old[2]}
        else:
            old_value = {"kind": "symlink", "value": old[1]}
        new = new_values.get(name)
        if new is None:
            new_value = None
        elif new[0] == "file":
            new_value = {"kind": "file", "value": base64.b64encode(new[1]).decode()}
        else:
            new_value = {"kind": "symlink", "value": new[1]}
        paths[name] = {"before": old_value, "candidate": new_value}
    return paths


def current_value(root: Path, name: str) -> dict | None:
    path = root / name
    if path.is_symlink():
        return {"kind": "symlink", "value": os.readlink(path)}
    if path.is_file():
        return {"kind": "file", "value": base64.b64encode(path.read_bytes()).decode()}
    return None


def same_content(left: dict | None, right: dict | None) -> bool:
    """Compare snapshotted content and object kind, ignoring file mode metadata."""
    if left is None or right is None:
        return left is right
    return left.get("kind") == right.get("kind") and left.get("value") == right.get("value")


def restore_value(root: Path, name: str, value: dict | None) -> None:
    path = root / name
    if path.is_symlink() or path.is_file():
        path.unlink()
    if value is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if value["kind"] == "symlink":
        path.symlink_to(value["value"])
    else:
        path.write_bytes(base64.b64decode(value["value"]))
        before = value.get("mode")
        if before is not None:
            os.chmod(path, before)


def process_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        state = subprocess.check_output(["ps", "-o", "stat=", "-p", str(pid)],
                                        text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return True
    return bool(state) and not state.startswith(("Z", "X"))


def recover(root: Path, metadata: Path, pending: dict) -> None:
    """Restore only when no recorded process is live and all candidate bytes match."""
    active = [pid for pid in (pending.get("setup_pid"), pending.get("checker_pid"),
                              pending.get("recovery_pid"))
              if process_alive(pid) and pid != os.getpid()]
    if active:
        raise PendingUpdateError("Guardian update is still running; wait for it to finish before recovery")
    conflicts = [name for name, entry in pending.get("paths", {}).items()
                 if not any(same_content(current_value(root, name), snapshot)
                            for snapshot in (entry.get("candidate"), entry.get("before")))]
    if conflicts:
        raise PendingUpdateError("pending update found changed project files; preserved them and "
                                 "refused recovery: " + ", ".join(conflicts))
    pending["recovery_pid"] = os.getpid()
    write_pending(metadata, pending)
    for name, entry in pending["paths"].items():
        restore_value(root, name, entry.get("before"))
    remove_pending(metadata)
