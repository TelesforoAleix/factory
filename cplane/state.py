"""Validated, locked state updates. No executor is launched here."""
from contextlib import contextmanager
from contextvars import ContextVar
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


def _file_load(path):
    with Path(path).open() as stream:
        data = json.load(stream)
    validate(data)
    return data


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True)
    if result.returncode:
        raise StateError(f"git {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def _file_commit(path, outbox, command, slice_id):
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
    with locked(path):
        return update_locked(path, slice_id, command, actor, change, commit,
                             create=create, event=event)


def _update_locked(path, slice_id, command, actor, change, commit=False, *, create=None, event=None):
    """The shared command path for callers already holding the store lock."""
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
    notices = [] if notice is None else [{"at": at, "id": slice_id, "event": command, "text": notice}]
    save(path, data, notices)
    if commit:
        commit_state(path, outbox, command, slice_id)
    return warning


def _file_save(path, data):
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


# Public compatibility facade. A locked pass reuses one store/transaction, including
# nested order mutations. Context-local binding also permits independent writers.
_ACTIVE = ContextVar("cplane_store", default=None)


def postgres():
    return "CPLANE_DATABASE_URL" in os.environ


def store(path):
    active = _ACTIVE.get()
    if active is not None:
        return active
    from .stores import FileStore, PostgresStore
    return PostgresStore(os.environ["CPLANE_DATABASE_URL"]) if postgres() else FileStore(path)


@contextmanager
def locked(path):
    if _ACTIVE.get() is not None:
        yield _ACTIVE.get()
        return
    backend = store(path)
    with backend.locked():
        token = _ACTIVE.set(backend)
        try:
            yield backend
        finally:
            _ACTIVE.reset(token)


def load(path):
    return store(path).load()


def save(path, data, notices=()):
    store(path).save(data, notices)


def append_notices(path, notices, *, ensure_ascii=False):
    store(path).append_notices(notices, ensure_ascii=ensure_ascii)


def snapshot(path):
    return store(path).snapshot()


def size(path):
    return store(path).size()


def commit_state(path, outbox, command, slice_id):
    if not postgres():
        store(path).commit(command, slice_id)


def update_locked(path, slice_id, command, actor, change, commit=False, *, create=None, event=None):
    backend = store(path)
    with backend.mutation():
        token = _ACTIVE.set(backend)
        try:
            return _update_locked(path, slice_id, command, actor, change, commit,
                                  create=create, event=event)
        finally:
            _ACTIVE.reset(token)
