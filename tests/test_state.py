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




def test_mode_preserved(make_state):
    path = make_state()
    path.chmod(0o600)
    state.update(path, "voice/W1", "pause", "owner", change_for("pause"))
    assert path.stat().st_mode & 0o777 == 0o600




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


def test_slice_final_is_optional_and_validated(make_state, slice_data):
    from cplane import state
    path = make_state()
    assert 'final' not in state.load(path)['slices'][0]
    slice_data['final'] = {'kind': 'handover', 'body': 'done', 'at': '2026-01-01T00:00:00Z'}
    state.save(path, {'version': 1, 'slices': [slice_data]})
    assert state.load(path)['slices'][0]['final'] == slice_data['final']


@pytest.mark.parametrize('brief_id, file_brief', [('FAC-F1-S2', None), ('FAC-F1-S1', 'file.md')])
def test_stored_brief_identity_is_unambiguous(slice_data, brief_id, file_brief):
    slice_data.update(id='FAC-F1-S1', brief_id=brief_id, brief=file_brief)
    with pytest.raises(state.StateError, match='stored brief'):
        state.validate(dict(version=1, slices=[slice_data]))
