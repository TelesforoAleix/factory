import copy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

from cplane import state
from cplane.cli import change_for, main


def test_schema_is_valid():
    Draft202012Validator.check_schema(state.SCHEMA)


@pytest.mark.parametrize("field,value", [
    ("state", "unknown"), ("paused", 1), ("slot", "2026-10-15T12:00:00"),
    ("slot", "bad"), ("id", "bad"), ("executor", {"tool": "other", "model": "x"}),
    ("session", {"tool": "codex"}), ("pr", "1"), ("stop_before_merge", "yes"),
    ("depends_on", "other/W1"), ("attention", {"kind": "other"}), ("log", [{}]),
])
def test_schema_failure_keeps_bytes(make_state, field, value):
    path = make_state()
    before = path.read_bytes()
    def break_schema(item, data, at):
        item[field] = value
        return "notice", None
    with pytest.raises(state.StateError, match="invalid state"):
        state.update(path, "voice/W1", "test", "owner", break_schema)
    assert path.read_bytes() == before
    assert not Path(str(path) + ".outbox.jsonl").exists()


def test_duplicate_ids(make_state, slice_data):
    path = make_state([slice_data, copy.deepcopy(slice_data)])
    with pytest.raises(state.StateError, match="unique"):
        state.load(path)


def test_invalid_input_refused(make_state, capsys):
    path = make_state()
    path.write_text('{"version": 2, "slices": []}')
    before = path.read_bytes()
    assert main(["--state", str(path), "pause", "voice/W1"]) == 1
    assert path.read_bytes() == before
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_rename_failure_keeps_bytes(make_state, monkeypatch):
    path = make_state()
    before = path.read_bytes()
    def fail(*args):
        raise OSError("rename failed")
    monkeypatch.setattr(state.os, "replace", fail)
    with pytest.raises(OSError, match="rename failed"):
        state.update(path, "voice/W1", "pause", "owner", change_for("pause"))
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".slices.json.*"))


def test_mode_preserved(make_state):
    path = make_state()
    path.chmod(0o600)
    state.update(path, "voice/W1", "pause", "owner", change_for("pause"))
    assert path.stat().st_mode & 0o777 == 0o600


def test_two_concurrent_writers(make_state):
    path = make_state()
    code = """
import sys
from cplane.state import update
from cplane.cli import change_for
print('ready', flush=True)
update(sys.argv[1], 'voice/W1', sys.argv[2], sys.argv[2], change_for(sys.argv[2], '2026-10-19T03:00:00+02:00'))
"""
    with Path(str(path) + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        processes = [subprocess.Popen([sys.executable, "-c", code, str(path), command], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for command in ("slot", "pause")]
        try:
            for process in processes:
                assert process.stdout.readline().strip() == "ready"
                assert process.poll() is None
            fcntl.flock(lock, fcntl.LOCK_UN)
            for process in processes:
                _, err = process.communicate(timeout=20)
                assert process.returncode == 0, err
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()
    item = state.load(path)["slices"][0]
    assert item["slot"] == "2026-10-19T03:00:00+02:00"
    assert item["paused"] is True
    assert sorted(entry["event"] for entry in item["log"]) == ["pause", "slot"]


def test_outbox_append(make_state):
    path = make_state()
    for command in ("slot", "start"):
        state.update(path, "voice/W1", command, "owner", change_for(command, "2026-10-19T03:00:00+02:00"))
    lines = Path(str(path) + ".outbox.jsonl").read_text().splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["slot", "start"]


def test_version_one_attention_without_review_still_validates(make_state, slice_data):
    from conftest import attention
    slice_data['attention'] = attention('merge')
    path = make_state()
    assert state.load(path) == dict(version=1, slices=[slice_data])


@pytest.mark.parametrize('review', [
    None, 'approved', {},
    {'verdict': 'OK', 'at': '2026-10-19T12:00:00+02:00'},
    {'verdict': 1, 'at': '2026-10-19T12:00:00+02:00', 'actor': 'planner'},
    {'verdict': 'OK', 'at': '2026-10-19T12:00:00', 'actor': 'planner'},
    {'verdict': 'OK', 'at': 'bad', 'actor': 'planner'},
    {'verdict': 'OK', 'at': '2026-10-19T12:00:00+02:00', 'actor': None},
    {'verdict': 'OK', 'at': '2026-10-19T12:00:00+02:00', 'actor': 'planner', 'extra': True},
])
def test_malformed_review_rejected(make_state, slice_data, review):
    from conftest import attention
    slice_data['attention'] = dict(attention('merge'), review=review)
    with pytest.raises(state.StateError, match='invalid state'):
        state.load(make_state())
