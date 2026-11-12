"""Validated, locked state updates. No executor is launched here."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
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
    for item in data["slices"]:
        if item.get('brief_id') and (item['brief_id'] != item['id'] or item['brief'] is not None):
            raise StateError('invalid state: stored brief must match the slice ID and have no file path')
    ids = [item["id"] for item in data["slices"]]
    if len(ids) != len(set(ids)):
        raise StateError("invalid state: slice ids must be unique")


def _file_load(path):
    with Path(path).open() as stream:
        data = json.load(stream)
    validate(data)
    return data


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


# Public compatibility facade. A locked pass reuses one store/transaction, including
# nested order mutations. Context-local binding also permits independent writers.
_ACTIVE = ContextVar("cplane_store", default=None)


def database_url():
    """Resolve the service's database credential without disclosing it in errors."""
    if 'CPLANE_DATABASE_URL_FILE' not in os.environ:
        return os.environ.get('CPLANE_DATABASE_URL')
    if 'CPLANE_DATABASE_URL' in os.environ:
        raise StateError('Set only one database URL setting')
    try:
        value = Path(os.environ['CPLANE_DATABASE_URL_FILE']).read_text().strip()
    except (OSError, UnicodeError, ValueError):
        raise StateError('Database URL file unavailable or invalid') from None
    if not value:
        raise StateError('Database URL file unavailable or invalid')
    return value


def postgres():
    return database_url() is not None


def store(path):
    active = _ACTIVE.get()
    if active is not None:
        return active
    from .stores import PostgresStore
    return PostgresStore(database_url())


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
