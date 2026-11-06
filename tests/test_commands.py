import copy
import json
from datetime import datetime

import pytest

from cplane.cli import main, pending, render
from cplane.state import load
from conftest import attention


@pytest.mark.parametrize("command,value,field,expected", [
    ("slot", "2026-10-19T03:00:00+02:00", "slot", "2026-10-19T03:00:00+02:00"),
    ("unslot", None, "slot", None),
    ("pause", None, "paused", True),
    ("resume", None, "paused", False),
])
def test_simple_commands(make_state, slice_data, command, value, field, expected):
    slice_data["slot"] = "2026-10-16T06:00:00+02:00"
    slice_data["paused"] = command == "resume"
    slice_data["log"] = [{"at": "2026-10-15T00:00:00+02:00", "actor": "old", "event": "created"}]
    path = make_state([slice_data])
    args = [command, "voice/W1"] + ([value] if value else [])
    assert main(["--state", str(path), "--actor", "tester", *args]) == 0
    item = load(path)["slices"][0]
    assert item[field] == expected
    assert item["log"][0] == slice_data["log"][0]
    assert item["log"][-1]["actor"] == "tester"
    assert item["log"][-1]["event"] == command
    assert datetime.fromisoformat(item["log"][-1]["at"]).utcoffset() is not None
    outbox = path.with_name(path.name + ".outbox.jsonl")
    assert outbox.exists() == (command == "slot")
    if outbox.exists():
        notice = json.loads(outbox.read_text())
        assert set(notice) == {"at", "id", "event", "text"}
        assert notice["event"] == command


def test_start(make_state):
    path = make_state()
    before = datetime.now().astimezone()
    assert main(["start", "voice/W1", "--state", str(path)]) == 0
    item = load(path)["slices"][0]
    assert before <= datetime.fromisoformat(item["slot"]) <= datetime.now().astimezone()
    assert item["state"] == "ready"
    assert item["session"] is None
    assert json.loads(path.with_name(path.name + ".outbox.jsonl").read_text())["event"] == "start"


def test_effort_add_edit_and_show(make_state, capsys):
    path = make_state([])
    assert main(["--state", str(path), "add", "--id", "voice/W2", "--repo", "example/repo",
                 "--feature", "example", "--title", "Second", "--effort", "xhigh"]) == 0
    item = load(path)["slices"][0]
    assert item["executor"]["effort"] == "xhigh"
    assert main(["--state", str(path), "edit", "voice/W2", "--effort", "low"]) == 0
    assert load(path)["slices"][0]["executor"]["effort"] == "low"
    assert main(["--state", str(path), "show", "voice/W2", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["executor"]["effort"] == "low"


@pytest.mark.parametrize("command,kind", [("approve", "merge"), ("answer", "question"), ("answer", "escalation")])
def test_attention_success(make_state, slice_data, command, kind):
    slice_data["attention"] = attention(kind)
    slice_data["stop_before_merge"] = False
    path = make_state([slice_data])
    args = [command, "voice/W1"] + (["Yes, proceed\nwith care"] if command == "answer" else [])
    assert main([*args, "--state", str(path)]) == 0
    item = load(path)["slices"][0]
    assert item["log"][-1]["actor"] == "owner"
    assert item["attention"]["approved" if command == "approve" else "answer"] == (True if command == "approve" else "Yes, proceed\nwith care")
    lines = path.with_name(path.name + ".outbox.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == command


@pytest.mark.parametrize("command", ["slot", "start"])
@pytest.mark.parametrize("status", ["planned", "researching", "issued", "awaiting handover", "in review", "accepted", "escalated"])
def test_not_ready_refused(make_state, slice_data, capsys, command, status):
    slice_data["state"] = status
    path = make_state([slice_data])
    before = path.read_bytes()
    args = [command, "voice/W1"] + (["tomorrow 06:00"] if command == "slot" else [])
    assert main(["--state", str(path), *args]) == 1
    assert path.read_bytes() == before
    assert capsys.readouterr().err == "cplane: voice/W1 is not ready\n"
    assert not path.with_name(path.name + ".outbox.jsonl").exists()


@pytest.mark.parametrize("command,kind", [(command, kind) for command in ("approve", "answer") for kind in (None, "question", "escalation", "merge", "node-step", "owner-check") if not ((command == "approve" and kind == "merge") or (command == "answer" and kind in ("question", "escalation", "node-step")))])
def test_wrong_attention_refused(make_state, slice_data, capsys, command, kind):
    slice_data["attention"] = attention(kind) if kind else None
    path = make_state([slice_data])
    before = path.read_bytes()
    args = [command, "voice/W1"] + (["reply"] if command == "answer" else [])
    assert main(["--state", str(path), *args]) == 1
    assert path.read_bytes() == before
    assert len(capsys.readouterr().err.splitlines()) == 1


@pytest.mark.parametrize("command", ["slot", "unslot", "start", "pause", "resume", "approve", "answer"])
def test_unknown_id(make_state, capsys, command):
    path = make_state()
    before = path.read_bytes()
    value = ["tomorrow 06:00"] if command == "slot" else ["reply"] if command == "answer" else []
    assert main(["--state", str(path), command, "missing/W0", *value]) == 1
    assert path.read_bytes() == before
    assert capsys.readouterr().err == "cplane: unknown slice: missing/W0\n"


@pytest.mark.parametrize("command", ["slot", "start"])
@pytest.mark.parametrize("accepted", [True, False])
def test_dependencies(make_state, slice_data, capsys, command, accepted):
    dependency = copy.deepcopy(slice_data)
    dependency.update(id="other/W0", state="accepted" if accepted else "planned")
    slice_data["depends_on"] = ["other/W0"] + ([] if accepted else ["missing/W0"])
    path = make_state([slice_data, dependency])
    assert main(["--state", str(path), command, "voice/W1", *(["tomorrow 06:00"] if command == "slot" else [])]) == 0
    assert load(path)["slices"][0]["slot"]
    warning = capsys.readouterr().err
    assert warning == ("" if accepted else "warning: unmet dependencies: other/W0, missing/W0\n")


def test_bad_time_unchanged(make_state, capsys):
    path = make_state()
    before = path.read_bytes()
    assert main(["--state", str(path), "slot", "voice/W1", "not a time"]) == 1
    assert path.read_bytes() == before
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_config_and_missing_state(make_state, monkeypatch, capsys):
    monkeypatch.delenv("CPLANE_STATE", raising=False)
    assert main(["pending"]) == 1
    assert "provide --state or CPLANE_STATE" in capsys.readouterr().err
    path = make_state()
    monkeypatch.setenv("CPLANE_STATE", str(path))
    assert main(["pending", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"][0]["id"] == "voice/W1"
    monkeypatch.setenv("CPLANE_STATE", "/nonexistent-state.json")
    assert main(["--state", str(path), "pending"]) == 0
    capsys.readouterr()
    assert main(["pending"]) == 1
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_pending_groups_and_order(make_state, slice_data, capsys):
    def item(key, **changes):
        return dict(copy.deepcopy(slice_data), id=f"project/{key}", **changes)
    items = [item("late", slot="2026-10-17T01:00:00+02:00"),
             item("early", slot="2026-10-16T08:00:00+02:00"),
             item("middle", slot="2026-10-16T08:30:00+02:00", paused=True),
             item("question", attention=attention("question")),
             item("merge", attention=attention("merge")),
             item("answered", attention=dict(attention("question"), answer="done")),
             item("approved", attention=dict(attention("merge"), approved=True)),
             item("issued", state="issued", slot="2026-10-15T00:00:00+02:00"),
             item("handover", state="awaiting handover"), item("planned", state="planned"),
             item("research", state="researching"), item("done", state="accepted"),
             item("review", state="in review"), item("escalated", state="escalated")]
    path = make_state(items)
    groups = pending(load(path))
    ids = {key: [s["id"].split("/")[1] for s in values] for key, values in groups.items()}
    assert ids == {"needs attention": ["escalated", "merge", "question", "review"],
                   "scheduled": ["early", "middle", "late"], "ready": ["answered", "approved"],
                   "running": ["handover", "issued"], "planned": ["planned", "research"]}
    text = render(groups)
    assert text.index("2026-10-16") < text.index("08:00 +0200") < text.index("08:30 +0200") < text.index("2026-10-17")
    assert "[paused]" in text
    assert main(["--state", str(path), "pending", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == groups
    assert main(["--state", str(path), "pending"]) == 0
    assert capsys.readouterr().out.rstrip() == text


@pytest.mark.parametrize("kind", ["escalation", "node-step", "owner-check"])
def test_other_attention_groups(slice_data, kind):
    slice_data["attention"] = attention(kind)
    assert pending({"slices": [slice_data]})["needs attention"] == [slice_data]


def test_parser_errors_one_line(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["start"])
    assert exc.value.code != 0
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_compact_bounds_oversized_text_and_is_idempotent(make_state, slice_data, capsys):
    slice_data['log'] = [{"at": "2026-10-15T00:00:00+02:00", "actor": "runner", "event": "x" * 800_000}]
    slice_data['attention'] = attention('question')
    slice_data['attention']['body'] = 'body ' * 3_000
    slice_data['attention']['answer'] = 'owner answer ' * 100
    path = make_state([slice_data])
    before = path.stat().st_size

    assert main(['--state', str(path), 'compact']) == 0
    output = capsys.readouterr().out
    first = load(path)['slices'][0]
    after = path.stat().st_size
    assert after < before
    assert 'cut 1 log entries and 1 attention bodies' in output
    assert len(first['log'][0]['event']) <= 500
    assert len(first['attention']['body']) <= 8_000
    assert first['attention']['answer'] == 'owner answer ' * 100
    compacted = path.read_bytes()

    assert main(['--state', str(path), 'compact']) == 0
    assert path.read_bytes() == compacted
    assert 'cut 0 log entries and 0 attention bodies' in capsys.readouterr().out


@pytest.mark.parametrize('tool', ['codex', 'claude'])
def test_stop_before_merge_requires_review(make_state, slice_data, capsys, tool):
    slice_data['executor']['tool'] = tool
    slice_data['attention'] = attention('merge')
    path = make_state()
    before = path.read_bytes()
    assert main(['--state', str(path), 'approve', 'voice/W1']) == 1
    assert 'needs a recorded planner review' in capsys.readouterr().err
    assert path.read_bytes() == before
    assert not path.with_name(path.name + '.outbox.jsonl').exists()
    assert main(['--state', str(path), '--actor', 'planner', 'review', 'voice/W1', 'Ready to merge']) == 0
    review = load(path)['slices'][0]['attention']['review']
    assert main(['--state', str(path), 'approve', 'voice/W1']) == 0
    recorded = load(path)['slices'][0]['attention']
    assert recorded['approved'] is True
    assert recorded['review'] == review


def test_answer_node_step_and_pending(make_state, slice_data):
    slice_data["state"] = "in review"
    slice_data["attention"] = attention("node-step")
    path = make_state([slice_data])
    assert pending(load(path))["needs attention"]
    assert main(["--state", str(path), "answer", "voice/W1", "done"]) == 0
    assert load(path)["slices"][0]["attention"]["answer"] == "done"
    assert pending(load(path))["needs attention"][0]["id"] == "voice/W1"  # in review still needs attention
    slice_data["state"] = "issued"
    slice_data["attention"] = {**attention("node-step"), "answer": "done"}
    assert pending({"slices": [slice_data]})["needs attention"] == []
