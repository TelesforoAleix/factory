# ruff: noqa: F811 - imported pytest fixture
"""Wire responses and credential handling use a loopback fake API."""

import json
from pathlib import Path

import pytest
from test_eval_platform import server  # noqa: F401

from cplane.run_platform import Client, NotResumable, Unavailable


@pytest.mark.parametrize("status", [200, 201])
def test_idempotent_create_response(server, status):
    calls, replies = server
    replies.append((status, {"run_id": "synthetic-run"}))
    assert (
        Client().submit({"contract": 1, "request_id": "request-1"}) == "synthetic-run"
    )
    assert calls == [("POST", "/v1/runs", {"contract": 1, "request_id": "request-1"})]


def test_poll_message_cancel(server):
    calls, replies = server
    client = Client()
    replies.extend(
        [
            (200, {"status": "question"}),
            (200, {"status": "queued"}),
            (200, {"status": "cancelled"}),
        ]
    )
    assert client.get("synthetic-run")["status"] == "question"
    message = {"contract": 1, "message_id": "answer-1", "text": "Use A"}
    assert client.message("synthetic-run", message)["status"] == "queued"
    assert client.cancel("synthetic-run")["status"] == "cancelled"
    assert calls[1:] == [
        ("POST", "/v1/runs/synthetic-run/messages", message),
        ("POST", "/v1/runs/synthetic-run/cancel", {}),
    ]


@pytest.mark.parametrize(
    "status,error",
    [
        (409, "not_resumable"),
        (409, "role_not_available"),
        (401, "PRIVATE"),
        (422, "PRIVATE"),
        (503, "PRIVATE"),
    ],
)
def test_errors_never_reflect_response(server, status, error):
    server[1].append((status, {"error": error, "message": "PRIVATE server body"}))
    with pytest.raises(
        NotResumable if error == "not_resumable" else Unavailable
    ) as caught:
        Client().cancel("synthetic-run")
    assert "PRIVATE" not in str(caught.value)


def test_lost_response_and_malformed_record(server):
    server[1].append(("lost", {}))
    with pytest.raises(Unavailable):
        Client().submit({"contract": 1})
    server[1].append((200, {"status": "invented"}))
    with pytest.raises(Unavailable):
        Client().get("synthetic-run")


def test_key_redacted_from_nested_final(server, monkeypatch):
    import os

    secret = Path(os.environ["CPLANE_EVAL_TASK_KEY_FILE"]).read_text().strip()
    server[1].append(
        (200, {"status": "done", "final_message": {"kind": "handover", "body": secret}})
    )
    value = Client().get("synthetic-run")
    assert secret not in json.dumps(value)
    assert value["final_message"]["body"] == "[redacted]"
