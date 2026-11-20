"""The run-api pin, and Factory's own request bodies checked against it."""

import copy
from pathlib import Path

import pytest
from test_run_api_runner import TIP, block, current, edit, pr_reply, setup  # noqa: F401

from contracts import pins, sender
from cplane import run_platform

PIN = Path(__file__).resolve().parent.parent / "pins" / "run-api"


def problems(method, path, body):
    return sender.check(PIN, method, path, body)


def test_pin_is_valid():
    assert pins.verify(PIN) == []


def run_checks(api):
    """Every body the runner sent to the fake platform, checked against the pin."""
    errors = [
        error for body in api.calls for error in problems("POST", "/v1/runs", body)
    ]
    for (run_id, _), body in api.messages.items():
        errors += problems("POST", f"/v1/runs/{run_id}/messages", body)
    return errors


def test_slice_review_answer_and_completion_bodies(setup):  # noqa: F811
    r, api, gh = setup
    r.run()
    original = current(r)
    api.finish(original, "question", "question", "Which option?")
    r.run()
    edit(r, lambda s: s["attention"].update(answer="Use the first option."))
    r.run()
    api.finish(original, "waiting", "waiting", pr_reply())
    r.run()
    api.finish(original, body="Recorded")
    r.run()
    roles = {body["role"] for body in api.calls}
    assert roles == {"slice", "review"}
    texts = [body["text"] for body in api.messages.values()]
    assert "Use the first option." in texts
    assert any(text.startswith("Factory recorded") for text in texts)
    assert run_checks(api) == []


def test_cut_and_ticket_bodies(setup):  # noqa: F811
    from test_run_api_runner import PLAN

    r, api, _ = setup
    edit(r, lambda s: s.update(flow="tickets"))
    r.run()
    cut = current(r)
    api.finish(cut, body=block(dict(PLAN, node_steps=None)))
    r.run()
    for req in [q for q in api.requests.values() if q["role"] == "ticket"]:
        api.finish(req["request_id"])
    r.run()
    assert {body["role"] for body in api.calls} >= {"cut", "ticket", "review"}
    assert run_checks(api) == []


@pytest.mark.xfail(
    strict=True,
    reason="Factory sends {} to a cancel operation that defines no body; a follow-up sends no body",
)
def test_cancel_body(monkeypatch):
    sent = []

    def record(self, path, body=None, *, accepted=None):
        sent.append((path, body))
        return {"status": "cancelled"}

    monkeypatch.setattr(run_platform.Connection, "request", record)
    run_platform.Client.__new__(run_platform.Client).cancel("run-1")
    assert [path for path, _ in sent] == ["/v1/runs/run-1/cancel"]
    assert problems("POST", sent[0][0], sent[0][1]) == []


def test_misspelt_top_level_key_is_refused(setup):  # noqa: F811
    r, api, _ = setup
    r.run()
    body = copy.deepcopy(api.calls[0])
    body["reqest_id"] = body.pop("request_id")
    errors = problems("POST", "/v1/runs", body)
    assert any("reqest_id" in error for error in errors), errors
