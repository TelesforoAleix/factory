"""Launcher Claude telemetry using synthetic fenced output and temporary folders."""

from datetime import timedelta
import json
import shutil
import subprocess
from unittest.mock import Mock

import pytest

from cplane import fence, launcher, runner, state
from test_runner import NOW, setup as setup


def reading(age=600):
    return {
        "at": NOW.timestamp() - age,
        "rate_limits": {
            "five_hour": {"used_percentage": 9, "resets_at": NOW.timestamp() + 7200},
            "seven_day": {"used_percentage": 32, "resets_at": NOW.timestamp() + 86400},
        },
    }


@pytest.fixture
def launcher_mode(monkeypatch):
    monkeypatch.setenv("CPLANE_USAGE_SOURCE", "launcher")
    monkeypatch.setattr(fence, "LOGIN_ROOT", None)


def test_launcher_stored_reading_selects_claude_reviewer(setup, launcher_mode):
    r, _, _ = setup
    r.instant = NOW
    r.jobs = {}
    r.claude_reader = runner.claude_usage
    r.runs.mkdir(parents=True)
    (r.runs / "claude-usage.json").write_text(json.dumps(reading()))
    assert r.choose(state.load(r.path)["slices"][0], review=True) == (
        "claude",
        "sonnet",
    )


@pytest.mark.parametrize(
    "outcome", ["success", "missing", "failed", "timeout", "malformed"]
)
def test_probe_keeps_only_last_windows(tmp_path, launcher_mode, monkeypatch, outcome):
    work = tmp_path / "work"
    runs = tmp_path / "runs"
    work.mkdir()
    runs.mkdir()
    monkeypatch.setenv("CPLANE_FENCE_COMMAND", "socket")
    monkeypatch.setattr(fence, "WORK_ROOT", work)
    monkeypatch.setattr(launcher, "WORK_ROOT", work)
    monkeypatch.setattr(launcher, "RUN_ROOT", runs)
    monkeypatch.setattr(fence, "own", Mock())
    monkeypatch.setattr(fence, "remove", lambda path, role: shutil.rmtree(path))
    monkeypatch.setattr(runner.time, "time", lambda: NOW.timestamp() - 600)
    marker = runs / "claude-usage.json"
    marker.write_text('{"previous":true}')
    windows = {
        "five_hour": {
            "utilization": 0.09,
            "resetsAt": NOW.timestamp() + 7200,
            "status": "allowed",
        },
        "seven_day": {
            "utilization": 0.32,
            "resetsAt": NOW.timestamp() + 86400,
            "status": "allowed",
        },
    }
    event = {"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": windows}}
    earlier = {
        "type": "rate_limit_event",
        "rate_limit_info": {
            "unifiedWindows": {
                "five_hour": {"utilization": 0.99, "resetsAt": 1},
                "seven_day": {"utilization": 0.99, "resetsAt": 1},
            }
        },
    }
    output = "\n".join(
        [
            "bad",
            json.dumps(earlier),
            json.dumps(event),
            json.dumps({"type": "result", "result": "ok"}),
        ]
    )
    if outcome == "missing":
        output = '{"type":"result","result":"ok"}'
    if outcome == "malformed":
        output += '\n{"type":"rate_limit_event","rate_limit_info":null}'
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if "run" in args:
            payload = launcher.translate(args[3:])
            assert payload["profile"] == "cli-run"
            assert payload["tool"] == "claude"
            assert payload["run_id"].startswith("claude-usage-")
            assert args[args.index("--") + 1 :] == [
                "claude",
                "-p",
                "--model",
                "haiku",
                "--output-format",
                "stream-json",
                "--verbose",
                "Reply with: ok",
            ]
            if outcome == "timeout":
                raise subprocess.TimeoutExpired(args, 120, output=output)
            return subprocess.CompletedProcess(args, int(outcome == "failed"), output)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(runner.subprocess, "run", run)
    if outcome == "timeout":
        with pytest.raises(subprocess.TimeoutExpired):
            runner.probe_claude_usage(runs)
    else:
        runner.probe_claude_usage(runs)
    assert "stop" in calls[-1]
    assert not list(work.iterdir())
    assert list(runs.iterdir()) == [marker]
    assert json.loads(marker.read_text()) == (
        reading() if outcome == "success" else {"previous": True}
    )


@pytest.mark.parametrize(
    "age,attempt_age,active,allowed,expected",
    [
        (600, None, 0, True, 0),
        (1800, None, 0, True, 0),
        (1801, None, 0, True, 1),
        (3601, 3599, 0, True, 0),
        (3601, 3600, 0, True, 1),
        (None, None, 0, True, 1),
        (None, None, 2, True, 0),
        (None, None, 0, False, 0),
    ],
)
def test_claude_probe_due_only_for_needed_choice(
    setup, launcher_mode, monkeypatch, age, attempt_age, active, allowed, expected
):
    r, _, _ = setup
    r.instant = NOW
    r._usage_probe_allowed = allowed
    r.jobs = {str(i): {"phase": "running"} for i in range(active)}
    r.claude_reader = runner.claude_usage
    r.runs.mkdir(parents=True)
    if age is not None:
        (r.runs / "claude-usage.json").write_text(json.dumps(reading(age)))
    if attempt_age is not None:
        (r.runs / "claude-usage-probe.json").write_text(
            json.dumps({"at": NOW.timestamp() - attempt_age})
        )
    probe = Mock(side_effect=OSError("synthetic failure"))
    monkeypatch.setattr(runner, "probe_claude_usage", probe)
    candidate = state.load(r.path)["slices"][0]
    r.choose(candidate)  # Codex choice must not probe Claude.
    probe.assert_not_called()
    for _ in range(2):
        choice = r.choose(candidate, review=True)
    assert probe.call_count == expected
    if age is None:
        assert choice is None
    else:
        assert json.loads((r.runs / "claude-usage.json").read_text()) == reading(age)


@pytest.mark.parametrize("reserved", ["review", "unrecovered"])
def test_claude_probe_reserves_other_executor_work(
    setup, launcher_mode, monkeypatch, reserved
):
    r, _, _ = setup
    r.instant = NOW
    r._usage_probe_allowed = True
    r.jobs = {"live": {"phase": "running"}}
    if reserved == "review":
        r.jobs["review"] = {"phase": "pr", "pr_review": {"phase": "running"}}
    else:
        r.data = {"slices": [{"id": "lost", "state": "issued", "attention": None}]}
    probe = Mock()
    monkeypatch.setattr(runner, "probe_claude_usage", probe)
    r.choose(state.load(r.path)["slices"][0], review=True)
    probe.assert_not_called()


def test_claude_probe_read_immediately_enables_review(
    setup, launcher_mode, monkeypatch
):
    r, _, _ = setup
    r.instant = NOW
    r._usage_probe_allowed = True
    r.jobs = {}
    r.claude_reader = runner.claude_usage

    def probe(runs):
        fresh = reading(0)
        fresh["at"] += 2
        r.clock = lambda: NOW + timedelta(seconds=2)
        (runs / "claude-usage.json").write_text(json.dumps(fresh))

    monkeypatch.setattr(runner, "probe_claude_usage", probe)
    candidate = state.load(r.path)["slices"][0]
    assert r.choose(candidate, review=True) == ("claude", "sonnet")
    candidate["executor"] = {"tool": "claude", "model": "opus"}
    assert r.choose(candidate) == ("claude", "opus")
