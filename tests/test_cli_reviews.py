"""CLI reviews run beside CI and only record their verdict."""

import copy
import json
from datetime import timedelta
from unittest.mock import Mock

import pytest
from conftest import seed_model_choices
from test_runner import NOW, edit, item, pr_reply, setup  # noqa: F401
from test_stores import pg_store  # noqa: F401

from cplane import state


@pytest.fixture
def reviewing(setup, monkeypatch):  # noqa: F811 - imported pytest fixture
    runner, processes, github = setup
    runner.claude_reader = lambda: {
        "at": NOW.timestamp(),
        "rate_limits": {"five_hour": {"used_percentage": 1}},
    }
    monkeypatch.setattr(
        "cplane.review.prepare",
        lambda adapter, previous, token: {
            **{k: previous[k] for k in ("repo", "branch", "base", "repository")},
            "tip": previous["tip"],
        },
    )
    processes.stop = Mock()
    edit(runner, lambda s: s.update(stop_before_merge=False))
    return runner, processes, github


def open_pr(reviewing):
    runner, processes, github = reviewing
    runner.run()
    processes.finish("waiting", pr_reply())
    runner.run()
    github.checks.return_value = ("green", "")
    return runner, processes, github


def answer(processes, verdict):
    reply = (
        {"verdict": "pass", "title": "Reviewed", "body": "Tests pass"}
        if verdict == "pass"
        else {
            "verdict": "fix",
            "tickets": [
                {
                    "title": "Fix",
                    "files": ["a.py"],
                    "change": "Fix it",
                    "check": "pytest",
                }
            ],
            "test_files": ["test_a.py"],
        }
    )
    processes.finish("waiting", "```json\n" + json.dumps(reply) + "\n```")
    return reply


@pytest.mark.parametrize("verdict", ["pass", "fix"])
def test_cli_review_waits_then_records_and_merges(reviewing, verdict):
    runner, processes, github = open_pr(reviewing)
    assert len(processes.started) == 2
    review = processes.started[-1]
    assert (review["tool"], review["model"], review["effort"]) == (
        "claude",
        "sonnet",
        "medium",
    )
    assert review["review"] and "Change nothing" in review["prompt"]
    assert "The exact prompt." in review["prompt"]
    runner.run()
    github.checks.assert_called()
    github.merge.assert_not_called()
    reply = answer(processes, verdict)
    runner.run()
    github.merge.assert_called_once()
    job = runner.jobs["voice/W1"]
    assert job["review_verdict"] == verdict
    assert job["review_findings"] == (
        {k: reply[k] for k in ("title", "body")}
        if verdict == "pass"
        else reply["tickets"]
    )
    assert processes.started[-1]["resume"] == "session-1"
    assert processes.started[-1]["tool"] == "codex"


@pytest.mark.parametrize("failure", ["exit", "timeout", "invalid", "question", "poll"])
def test_cli_failed_review_records_missing_and_merges(reviewing, failure):
    runner, processes, github = open_pr(reviewing)
    if failure == "timeout":
        runner.clock = lambda: NOW + timedelta(minutes=21)
    elif failure == "poll":
        original = processes.poll
        processes.poll = lambda job: (
            (_ for _ in ()).throw(OSError("poll failed"))
            if job.get("review")
            else original(job)
        )
    else:
        processes.finish(
            None
            if failure == "exit"
            else "question"
            if failure == "question"
            else "waiting",
            "bad",
        )
    runner.run()
    github.merge.assert_called_once()
    assert runner.jobs["voice/W1"]["review_verdict"] == "missing"
    if failure in ("timeout", "poll"):
        processes.stop.assert_called_once()


def test_cli_review_keeps_owner_approval(reviewing):
    runner, processes, github = reviewing
    edit(runner, lambda s: s.update(stop_before_merge=True))
    open_pr(reviewing)
    answer(processes, "fix")
    runner.run()
    assert runner.jobs["voice/W1"]["review_verdict"] == "fix"
    assert item(runner)["attention"]["kind"] == "merge"
    github.merge.assert_not_called()
    edit(runner, lambda s: s["attention"].update(approved=True))
    runner.run()
    github.merge.assert_called_once()


def test_cli_strong_role_and_database_record(reviewing, pg_store, capsys):  # noqa: F811
    runner, processes, github = reviewing
    pg_store.import_file(runner.path)
    pg_store.slice_level("voice/W1", "strong", {})
    seed_model_choices(pg_store)
    pg_store.role_set("reviewer-strong", "codex", "gpt-6.1-sol", "high")
    runner, processes, github = open_pr(reviewing)
    review = processes.started[-1]
    assert (review["tool"], review["model"], review["effort"]) == (
        "codex",
        "gpt-6.1-sol",
        "high",
    )
    reply = answer(processes, "pass")
    runner.run()
    row = pg_store.slice_review("voice/W1")
    assert row == {
        "review_verdict": "pass",
        "review_findings": {k: reply[k] for k in ("title", "body")},
    }
    github.merge.assert_called_once()
    records = pg_store.run_record_list(slice_id="voice/W1")
    assert any(r.get("verdict") == "pass" for r in records)
    from cplane.cli import main

    assert main(["--state", str(runner.path), "show", "voice/W1"]) == 0
    assert 'review_verdict: "pass"' in capsys.readouterr().out
    pg_store.slice_outcome("voice/W1", verdict="accepted")
    assert pg_store.slice_review("voice/W1") == row


@pytest.mark.parametrize(
    "level,model", [("light", "sonnet"), ("standard", "sonnet"), ("strong", "opus")]
)
def test_cli_review_default_role_per_level(reviewing, pg_store, level, model):  # noqa: F811
    runner, _, _ = reviewing
    pg_store.import_file(runner.path)
    pg_store.slice_level("voice/W1", level, {})
    _, processes, _ = open_pr(reviewing)
    review = processes.started[-1]
    assert (review["tool"], review["model"], review["effort"]) == (
        "claude",
        model,
        "medium",
    )


@pytest.mark.parametrize("verdict", ["fix", "missing"])
def test_cli_database_records_nonpass_and_own_run(reviewing, pg_store, verdict):  # noqa: F811
    runner, _, _ = reviewing
    pg_store.import_file(runner.path)
    runner, processes, github = open_pr(reviewing)
    review = processes.started[-1]
    reply = answer(processes, "fix") if verdict == "fix" else None
    if verdict == "missing":
        processes.finish(None, "failed")
    runner.run()
    github.merge.assert_called_once()
    assert pg_store.slice_review("voice/W1") == {
        "review_verdict": verdict,
        "review_findings": reply["tickets"] if reply else None,
    }
    with pg_store.locked():
        records = pg_store.connection.execute(
            "SELECT verdict, outcome FROM cplane_run_records WHERE turn_key = %s",
            ("slice:" + review["run"],),
        ).fetchall()
    assert records == [("fix", "waiting") if reply else (None, "failed")]


def test_cli_timeout_setting_and_no_second_launch(reviewing, monkeypatch):
    monkeypatch.setenv("CPLANE_REVIEW_TIMEOUT_SECONDS", "10")
    runner, processes, github = open_pr(reviewing)
    runner.clock = lambda: NOW + timedelta(seconds=9)
    runner.run()
    github.merge.assert_not_called()
    assert len(processes.started) == 2
    runner.clock = lambda: NOW + timedelta(seconds=10)
    runner.run()
    github.merge.assert_called_once()
    assert runner.jobs["voice/W1"]["review_verdict"] == "missing"
    assert len(processes.started) == 3  # executor resumes for handover
    job = runner.jobs["voice/W1"]
    assert job["review_ended_at"] - job["review_requested_at"] == 10


def test_cli_review_counts_toward_shared_executor_limit(reviewing):
    runner, processes, _ = open_pr(reviewing)
    data = state.load(runner.path)
    first = data["slices"][0]
    for name in ("second", "third"):
        other = copy.deepcopy(first)
        other.update(
            id="example/" + name,
            repo="example/" + name,
            state="ready",
            session=None,
            pr=None,
            log=[],
        )
        (runner.repos / name).mkdir()
        data["slices"].append(other)
    state.save(runner.path, data)
    runner.run()
    assert len(processes.started) == 3  # one review plus one executor; third deferred
    assert processes.started[-1]["id"] == "example/second"
    assert runner.jobs["voice/W1"]["pr_review"]["phase"] == "running"
    assert "example/third" not in runner.jobs


def test_cli_timeout_cleanup_failure_still_merges_but_reserves_capacity(reviewing):
    runner, processes, github = open_pr(reviewing)
    processes.stop.side_effect = OSError("cleanup unavailable")
    runner.clock = lambda: NOW + timedelta(minutes=21)
    runner.run()
    github.merge.assert_called_once()
    job = runner.jobs["voice/W1"]
    assert job["review_verdict"] == "missing"
    assert job["pr_review"]["stop_pending"]
    assert job["phase"] == "merged"
    assert len(processes.started) == 2  # no executor beside a possibly live review
    processes.stop.side_effect = None
    runner.run()
    assert processes.started[-1]["resume"] == "session-1"
    assert processes.started[-1]["tool"] == "codex"


def test_cli_preparation_failure_records_missing_without_attention(
    reviewing, monkeypatch
):
    def fail(*args):
        raise state.StateError("synthetic preparation failure")

    monkeypatch.setattr("cplane.review.prepare", fail)
    runner, processes, github = open_pr(reviewing)
    runner.run()
    github.merge.assert_called_once()
    assert runner.jobs["voice/W1"]["review_verdict"] == "missing"
    assert item(runner)["attention"] is None
    assert not any(job.get("review") for job in processes.started)
