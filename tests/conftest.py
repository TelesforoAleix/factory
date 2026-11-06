import copy
import json

import pytest


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
