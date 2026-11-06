"""Validated, locked state updates. No executor is launched here."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile
from importlib.resources import files
from datetime import datetime

from jsonschema import Draft202012Validator, FormatChecker

from .times import now


class StateError(Exception):
    pass


formats = FormatChecker()


@formats.checks("date-time", raises=(ValueError, TypeError))
def offset_timestamp(value):
    if not isinstance(value, str):
        return True  # type is checked by the schema
    return "T" in value.upper() and datetime.fromisoformat(value).utcoffset() is not None


SCHEMA = json.loads(files("schema").joinpath("slices.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=formats)


def validate(data):
    error = next(VALIDATOR.iter_errors(data), None)
    if error:
        location = ".".join(map(str, error.absolute_path)) or "state"
        raise StateError(f"invalid state at {location}: {error.message}")
    ids = [item["id"] for item in data["slices"]]
    if len(ids) != len(set(ids)):
        raise StateError("invalid state: slice ids must be unique")


def load(path):
    with Path(path).open() as stream:
        data = json.load(stream)
    validate(data)
    return data


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True)
    if result.returncode:
        raise StateError(f"git {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def commit_state(path, outbox, command, slice_id):
    probe = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"], text=True, capture_output=True)
    if probe.returncode:
        return
    root = Path(probe.stdout.strip())
    paths = [str(path.relative_to(root))]
    if outbox.exists():
        paths.append(str(outbox.relative_to(root)))
    git(root, "add", "--", *paths)
    # --only keeps unrelated staged changes out of this commit.
    git(root, "commit", "--only", "-m", f"cplane: {command} {slice_id}", "--", *paths)
    last_error = None
    for _ in range(3):
        try:
            git(root, "pull", "--rebase")
        except StateError as error:
            if (Path(git(root, "rev-parse", "--absolute-git-dir")) / "rebase-merge").exists() or (Path(git(root, "rev-parse", "--absolute-git-dir")) / "rebase-apply").exists():
                git(root, "rebase", "--abort")
                raise StateError(f"{error}; rebase aborted, local commit retained") from error
            last_error = error
            continue
        try:
            git(root, "push")
            return
        except StateError as error:
            last_error = error
    raise StateError(f"git sync failed after 3 attempts; local commit retained: {last_error}")


def update(path, slice_id, command, actor, change, commit=False, *, create=None, event=None):
    path = Path(path).expanduser().resolve()
    # A stable sidecar inode is necessary: locking the replaced file loses exclusion.
    with Path(str(path) + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return update_locked(path, slice_id, command, actor, change, commit,
                             create=create, event=event)


def update_locked(path, slice_id, command, actor, change, commit=False, *, create=None, event=None):
    """The shared command path for callers already holding the state sidecar lock."""
    outbox = Path(str(path) + ".outbox.jsonl")
    data = load(path)
    item = next((item for item in data["slices"] if item["id"] == slice_id), None)
    if create is not None:
        if item is not None:
            raise StateError(f"slice already exists: {slice_id}")
        item = create()
        data["slices"].append(item)
    elif item is None:
        raise StateError(f"unknown slice: {slice_id}")
    at = now().isoformat()
    notice, warning = change(item, data, at)
    item["log"].append({"at": at, "actor": actor, "event": event or command})
    save(path, data)
    if notice is not None:
        with outbox.open("a") as stream:
            stream.write(json.dumps({"at": at, "id": slice_id, "event": command, "text": notice}, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    if commit:
        commit_state(path, outbox, command, slice_id)
    return warning


def save(path, data):
    """Validate and atomically replace state; caller holds the sidecar lock."""
    validate(data)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
            temp = stream.name
            os.fchmod(stream.fileno(), path.stat().st_mode & 0o777)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)
