"""Platform contract exercised over loopback using synthetic tasks and credentials."""
# ruff: noqa: F811 - shared pytest fixtures

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_eval_runner import execution, step  # noqa: F401
from test_evals import cases  # noqa: F401
from test_stores import pg_store  # noqa: F401

from cplane import eval_platform, evals


@pytest.fixture
def server(monkeypatch, tmp_path):
    # Generate ephemeral authentication material; never place a key in a fixture.
    import secrets

    key = secrets.token_urlsafe(32)
    key_file = tmp_path / "credential"
    key_file.write_text(key + "\n")
    key_file.chmod(0o600)
    monkeypatch.setenv("CPLANE_EVAL_TASK_KEY_FILE", str(key_file))
    calls, replies = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.respond()

        def do_GET(self):
            self.respond()

        def respond(self):
            assert self.headers["Authorization"] == "Bearer " + key
            body = (
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.command == "POST"
                else None
            )
            calls.append((self.command, self.path, body))
            status, response = replies.pop(0)
            if status == "lost":
                self.close_connection = True
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("CPLANE_EVAL_TASK_URL", f"http://127.0.0.1:{http.server_port}")
    yield calls, replies
    http.shutdown()
    thread.join()
    http.server_close()


def create_platform(store):
    with store.mutation():
        store.connection.execute(
            "UPDATE cplane_eval_cases SET kind='ticket', start_commit=%s, "
            "start_branch='eval/pr53-t1', pinned_paths=ARRAY['tests/test_small.py']",
            ("b" * 40,),
        )
    return evals.run_create(
        store,
        title="Platform",
        sets=["synthetic"],
        repeats=1,
        configurations=[
            {
                "id": "pi-base",
                "harness": "pi",
                "model": "base",
                "route": "platform",
                "configuration": "base",
            }
        ],
    )


def response(status="done", retry=False):
    attempts = [
        {
            "number": 1,
            "status": "failed" if retry or status == "failed" else "done",
            "started_at": "2026-11-15T10:00:00Z",
            "ended_at": "2026-11-15T10:00:10Z",
            "configuration_hash": "synthetic",
            "reason": None,
            "usage": {
                "steps": 1,
                "fresh_tokens": 10,
                "cached_tokens": 5,
                "output_tokens": 3,
                "cost_usd": 0.1,
            },
        }
    ]
    if retry:
        attempts.append(
            dict(
                attempts[0],
                number=2,
                status="done",
                started_at="2026-11-15T10:00:12Z",
                ended_at="2026-11-15T10:00:20Z",
            )
        )
    return {
        "task": 42,
        "status": status,
        "reason": "check_failed" if status == "failed" else None,
        "attempts": attempts,
        "diff_base64": base64.b64encode(b"synthetic patch\n").decode(),
    }


@pytest.mark.parametrize("status", [201, 409])
def test_submit_contract_and_no_executor_place(pg_store, execution, server, status):
    runner, processes, adapter = execution
    run = create_platform(pg_store)
    calls, replies = server
    replies.append((status, {"task": 42}))
    runner.room = Mock(side_effect=AssertionError("must not take a place"))
    runner.codex_reader = runner.claude_reader = Mock(
        side_effect=AssertionError("must not read usage")
    )
    runner.jobs = {"slice": {"phase": "running", "repository": "example/public"}}
    step(pg_store, runner)
    (attempt,) = evals.run_show(pg_store, run["id"])["attempts"]
    assert attempt["platform_task"] == 42 and attempt["state"] == "running"
    assert not processes.started and not adapter.prepare_eval.called
    assert calls == [
        (
            "POST",
            "/v1/tasks/eval",
            {
                "attempt": f"factory-{attempt['id']}",
                "repository": "example/public",
                "branch": "eval/pr53-t1",
                "base_commit": "b" * 40,
                "title": "Small",
                "goal": "Synthetic task",
                "allowed_files": ["small.py"],
                "check_command": "uv run pytest tests/test_small.py",
                "pinned_paths": ["tests/test_small.py"],
                "eval": {
                    "set": f"run{run['id']}",
                    "case": "public.pr53-t1",
                    "configuration": "base",
                },
            },
        )
    ]
    replies.append((200, {"task": 42, "status": "running"}))
    step(pg_store, runner)
    assert len(calls) == 2
    assert not any(j.get("eval_attempt") for j in runner.jobs.values())


@pytest.mark.parametrize("status", [401, 422, 503])
def test_http_errors_remain_planned_and_do_not_record_body(
    pg_store, execution, server, status, caplog
):
    runner, _, _ = execution
    run = create_platform(pg_store)
    server[1].append((status, {"error": "private server diagnostic"}))
    step(pg_store, runner)
    (attempt,) = evals.run_show(pg_store, run["id"])["attempts"]
    assert attempt["state"] == "planned" and attempt["platform_task"] is None
    assert f"HTTP {status}" in caplog.text
    assert "private server diagnostic" not in caplog.text
    assert "private server diagnostic" not in json.dumps(attempt)


def test_lost_response_then_conflict_and_single_attempt(pg_store, execution, server):
    runner, _, _ = execution
    run = create_platform(pg_store)
    server[1].extend([("lost", None), (409, {"task": 42})])
    step(pg_store, runner)
    assert evals.run_show(pg_store, run["id"])["attempts"][0]["state"] == "planned"
    step(pg_store, runner)
    assert server[0][0][2] == server[0][1][2]
    assert evals.run_show(pg_store, run["id"])["attempts"][0]["platform_task"] == 42
    # Another due run must not submit while the recovered task is running.
    other = create_platform(pg_store)
    server[1].append((200, {"status": "queued"}))
    step(pg_store, runner)
    assert len(server[0]) == 3
    assert evals.run_show(pg_store, other["id"])["attempts"][0]["state"] == "planned"


@pytest.mark.parametrize(
    "status,retry",
    [
        ("done", False),
        ("failed", False),
        ("done", True),
        ("escalated", False),
        ("cancelled", False),
    ],
)
def test_collect_grades_metrics_and_patch(pg_store, execution, server, status, retry):
    runner, _, _ = execution
    run = create_platform(pg_store)
    server[1].extend([(201, {"task": 42}), (200, response(status, retry))])
    step(pg_store, runner)
    step(pg_store, runner)
    saved = evals.run_show(pg_store, run["id"])
    (attempt,) = saved["attempts"]
    assert saved["state"] == "done"
    assert attempt["state"] == ("done" if status == "done" else "failed")
    if status in ("done", "failed"):
        assert attempt["result"] == {
            "tests": "pass" if status == "done" else "fail",
            "first": "fail" if retry or status == "failed" else "pass",
            "attempts": 2 if retry else 1,
            "reason": "check_failed" if status == "failed" else None,
        }
    else:
        assert "tests" not in attempt["result"]
    n = 2 if retry else 1
    assert attempt["metrics"] == {
        "wall_seconds": 20 if retry else 10,
        "input_tokens": 15 * n,
        "output_tokens": 3 * n,
        "cost_usd": 0.1 * n,
    }
    target = Path(attempt["output_ref"])
    assert target.read_bytes() == b"synthetic patch\n"
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert runner.jobs == {}


def test_timeout_leaves_task_alone(pg_store, execution, server):
    from psycopg.types.json import Jsonb

    runner, _, _ = execution
    run = create_platform(pg_store)
    server[1].append((201, {"task": 42}))
    step(pg_store, runner)
    with pg_store.mutation():
        pg_store.connection.execute(
            "UPDATE cplane_eval_attempts SET metrics=%s",
            (Jsonb({"started_at": time.time() - 3601}),),
        )
    step(pg_store, runner)
    (attempt,) = evals.run_show(pg_store, run["id"])["attempts"]
    assert attempt["state"] == "failed" and attempt["result"] == {
        "error": "Attempt timed out"
    }
    assert len(server[0]) == 1 and attempt["platform_task"] == 42


@pytest.mark.parametrize(
    "setting", ["CPLANE_EVAL_TASK_URL", "CPLANE_EVAL_TASK_KEY_FILE"]
)
def test_missing_settings_stays_planned(
    pg_store, execution, server, monkeypatch, setting, caplog
):
    runner, _, _ = execution
    run = create_platform(pg_store)
    monkeypatch.delenv(setting)
    step(pg_store, runner)
    assert evals.run_show(pg_store, run["id"])["attempts"][0]["state"] == "planned"
    assert caplog.text.count("Platform eval settings unavailable") == 1
    assert server[0] == []


def test_client_secret_file_and_sanitized_errors(monkeypatch, tmp_path, server):
    path = tmp_path / "missing"
    monkeypatch.setenv("CPLANE_EVAL_TASK_KEY_FILE", str(path))
    with pytest.raises(eval_platform.Unavailable, match="key file unavailable"):
        eval_platform.Client()
    path.write_text("")
    with pytest.raises(eval_platform.Unavailable, match="key file unavailable"):
        eval_platform.Client()


def test_client_redacts_reflected_credential(server):
    client = eval_platform.Client()
    server[1].append((200, {"reason": client.key}))
    assert client.get(42) == {"reason": "[redacted]"}


@pytest.mark.parametrize("status", [201, 409])
def test_client_submit_with_fake_server(server, status):
    server[1].append((status, {"task": 42}))
    assert eval_platform.Client().submit({"attempt": "synthetic"}) == 42


@pytest.mark.parametrize("diff", [None, ""])
def test_missing_and_empty_diff_unknown_metrics(pg_store, execution, server, diff):
    runner, _, _ = execution
    run = create_platform(pg_store)
    task = response()
    task["diff_base64"] = diff
    task["diff_too_large"] = diff is None
    task["attempts"][0]["usage"] = {}
    server[1].extend([(201, {"task": 42}), (200, task)])
    step(pg_store, runner)
    step(pg_store, runner)
    (attempt,) = evals.run_show(pg_store, run["id"])["attempts"]
    assert attempt["metrics"] == {"wall_seconds": 10}
    if diff is None:
        assert attempt["output_ref"] is None
    else:
        assert Path(attempt["output_ref"]).read_bytes() == b""
