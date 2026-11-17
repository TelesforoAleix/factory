"""Launcher Claude telemetry using synthetic fenced output and temporary folders."""

import json
import shutil
import subprocess
from unittest.mock import Mock

import pytest
from test_eval_execution import NOW
from test_eval_execution import setup as setup

from cplane import eval_execution as runner
from cplane import fence, launcher


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
