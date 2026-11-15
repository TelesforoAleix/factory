import json
from contextlib import contextmanager

from cplane import cli, digest, state


def test_why_observes_after_unlock(slice_data, monkeypatch, capsys):
    locked = False
    data = {"version": 1, "slices": [slice_data]}
    limits = {"executors": 1, "repository_runs": 1}

    class Backend:
        def load(self):
            assert locked
            return data

        def limit_show(self):
            assert locked
            return limits

    @contextmanager
    def lock(path):
        nonlocal locked
        locked = True
        try:
            yield Backend()
        finally:
            locked = False

    def observe(snapshot, path, *, limits):
        assert not locked
        assert snapshot is data
        assert limits == {"executors": 1, "repository_runs": 1}
        return snapshot

    monkeypatch.setattr(state, "locked", lock)
    monkeypatch.setattr(state, "postgres", lambda: True)
    monkeypatch.setattr(cli, "observed", observe)
    assert cli.main(["why", slice_data["id"]]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "ready"}


def test_digest_builds_after_unlock(make_state, monkeypatch, capsys):
    path = make_state()
    real_lock = state.locked
    locked = False

    @contextmanager
    def lock(path):
        nonlocal locked
        with real_lock(path) as backend:
            locked = True
            try:
                yield backend
            finally:
                locked = False

    def build(data, records, end):
        assert not locked
        return "synthetic digest"

    monkeypatch.setattr(state, "locked", lock)
    monkeypatch.setattr(digest, "build", build)
    assert cli.main(["--state", str(path), "digest", "--date", "2026-11-01"]) == 0
    assert capsys.readouterr().out == "synthetic digest\n"


def test_export_serializes_after_unlock(make_state, monkeypatch, capsys):
    path = make_state()
    real_lock = state.locked
    real_dumps = json.dumps
    locked = False

    @contextmanager
    def lock(path):
        nonlocal locked
        with real_lock(path) as backend:
            locked = True
            try:
                yield backend
            finally:
                locked = False

    def dumps(*args, **kwargs):
        assert not locked
        return real_dumps(*args, **kwargs)

    monkeypatch.setattr(state, "locked", lock)
    monkeypatch.setattr(cli.json, "dumps", dumps)
    assert cli.main(["--state", str(path), "export"]) == 0
    assert json.loads(capsys.readouterr().out)["slices"][0]["id"] == "voice/W1"
