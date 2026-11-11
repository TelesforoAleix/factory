import copy
import json
import os
import fcntl
from pathlib import Path
from contextlib import contextmanager, nullcontext

import pytest


class SyntheticStore:
    """Temporary file-backed test double for command and projection tests."""
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.outbox = Path(str(self.path) + '.outbox.jsonl')

    @contextmanager
    def locked(self):
        with Path(str(self.path) + '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield self

    def mutation(self):
        return nullcontext()

    def load(self):
        from cplane import state
        return state._file_load(self.path)

    def save(self, data, notices=()):
        from cplane import state
        state.validate(data)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
        self.append_notices(notices)

    def append_notices(self, notices, *, ensure_ascii=False):
        if notices:
            with self.outbox.open('a') as stream:
                for notice in notices:
                    stream.write(json.dumps(notice, ensure_ascii=ensure_ascii) + '\n')
                stream.flush()
                os.fsync(stream.fileno())

    def notices(self, after=0):
        if not self.outbox.exists():
            return []
        return [(i, json.loads(line)) for i, line in enumerate(self.outbox.read_text().splitlines(), 1) if i > after]

    def snapshot(self):
        return self.path.read_bytes(), self.outbox.read_bytes() if self.outbox.exists() else None

    def size(self):
        return self.path.stat().st_size

    def commit(self, command, slice_id):
        pass


@pytest.fixture(autouse=True)
def synthetic_store(monkeypatch):
    from cplane import state
    original = state.store
    def store(path):
        if state._ACTIVE.get() is not None or state.postgres():
            return original(path)
        return SyntheticStore(path)
    monkeypatch.setattr(state, 'store', store)
    return original


@pytest.fixture(autouse=True)
def isolated_runs(tmp_path, monkeypatch):
    # Keep tests away from any real local settings such as roles-command.
    monkeypatch.setenv("CPLANE_RUNS", str(tmp_path / "isolated" / "runs"))


@pytest.fixture
def slice_data():
    return {
        "id": "voice/W1", "repo": "example/repo", "feature": "example",
        "title": "First slice", "state": "ready", "brief": "briefs/W1.md",
        "executor": {"tool": "codex", "model": "example-model"},
        "stop_before_merge": True, "depends_on": [], "slot": None,
        "paused": False, "session": None, "pr": None, "attention": None, "log": [],
    }


@pytest.fixture
def make_state(tmp_path, slice_data):
    def make(items=None):
        path = tmp_path / "slices.json"
        path.write_text(json.dumps({"version": 1, "slices": copy.deepcopy(items if items is not None else [slice_data])}))
        return path
    return make


def attention(kind):
    return {"kind": kind, "body": "Please respond", "since": "2026-10-15T12:00:00+02:00", "answer": None, "approved": False}


_POSTGRES_RESULTS = []


def pytest_runtest_logreport(report):
    if report.when == 'call' and dict(report.user_properties).get('postgres17'):
        _POSTGRES_RESULTS.append(report.outcome)


def pytest_terminal_summary(terminalreporter):
    if _POSTGRES_RESULTS:
        passed = _POSTGRES_RESULTS.count('passed')
        terminalreporter.write_line(f'Postgres 17: {passed} passed, {len(_POSTGRES_RESULTS) - passed} failed')


def seed_model_choices(store):
    """Explicit synthetic choices for tests that exercise configuration writes."""
    from psycopg.types.json import Jsonb
    from cplane.roles import EFFORTS
    names = ['model', 'test', 'synthetic-cheap', 'synthetic', 'synthetic-model', 'synthetic-a', 'synthetic-b', 'synthetic-c',
             'synthetic-d', 'synthetic-cli', 'synthetic-default', 'synthetic-codex',
             'synthetic-claude', 'example-model', 'gpt-5.3-codex', 'gpt-6-luna',
             'gpt-6.1-terra', 'gpt-6.1-sol', 'opus', 'sonnet']
    with store.mutation():
        for tool in ('codex', 'claude'):
            for model in names:
                store.connection.execute(
                    'INSERT INTO cplane_models (tool, model, label, efforts) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                    (tool, model, model, Jsonb(list(EFFORTS if tool == 'codex' else EFFORTS[:-1]))))
