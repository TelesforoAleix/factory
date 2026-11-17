"""Run API orchestration with synthetic state and an idempotent fake platform."""

import copy
import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from cplane import state
from cplane.runner import Runner

NOW = datetime(2026, 11, 17, tzinfo=UTC)
BASE, TIP = "a" * 40, "b" * 40
PLAN = {
    "tickets": [
        {
            "title": f"Ticket {i}",
            "files": [f"cplane/file{i}.py"],
            "change": f"Change {i}",
            "check": f"pytest -k ticket{i}",
        }
        for i in (1, 2)
    ],
    "test_files": ["tests/test_contract.py"],
}


def block(value, prose=""):
    return "```json\n" + json.dumps(value) + "\n```\n" + prose


def pr_reply(node_steps=None):
    return block(
        {
            "branch": "slice/voice-W1",
            "title": "Deliver slice",
            "body": "Implemented and tested.",
            "node_steps": node_steps,
        }
    )


class FakeRuns:
    def __init__(self):
        self.requests, self.records, self.messages, self.cancels = {}, {}, {}, []
        self.lost_post = False
        self.calls = []

    def submit(self, body):
        self.calls.append(copy.deepcopy(body))
        key = body["request_id"]
        if key in self.requests:
            assert self.requests[key] == body
        else:
            ancestors, pending = set(), list(body["after"])
            while pending:
                predecessor = pending.pop()
                assert predecessor in self.requests
                if predecessor not in ancestors:
                    ancestors.add(predecessor)
                    pending.extend(self.requests[predecessor]["after"])
            for other, record in self.records.items():
                if (
                    self.requests[other]["repository"] == body["repository"]
                    and self.requests[other]["branch"] == body["branch"]
                    and record["status"]
                    in ("queued", "running", "question", "waiting", "escalated")
                ):
                    assert other in ancestors, "branch_busy"
            self.requests[key] = copy.deepcopy(body)
            self.records[key] = {
                "contract": 1,
                "run_id": key,
                "request_id": key,
                "status": "queued",
                "status_reason": None,
                "final_message": None,
                "resumable": False,
                "resume_at": None,
                "commits": [],
                "executor": {"harness": "codex", "model": "platform-selected"},
                "updated_at": "0",
            }
        if self.lost_post:
            self.lost_post = False
            from cplane.run_platform import Unavailable

            raise Unavailable("Platform run response unavailable")
        return key

    def get(self, key):
        return copy.deepcopy(self.records[key])

    def message(self, key, body):
        identity = key, body["message_id"]
        if identity in self.messages:
            assert self.messages[identity] == body
        else:
            self.messages[identity] = copy.deepcopy(body)
            self.records[key].update(
                status="queued", final_message=None, resumable=False
            )
        return self.get(key)

    def find(self, request_id):
        return request_id if request_id in self.records else None

    def cancel(self, key):
        from cplane.run_platform import NotResumable

        self.cancels.append(key)
        if self.records[key]["status"] == "running":
            raise NotResumable("Platform run not resumable")
        self.records[key].update(status="cancelled", resumable=False)
        return self.get(key)

    @property
    def started(self):
        turns = [
            {
                "id": req["attribution"]["slice"],
                "branch": req["branch"],
                "prompt": req["work"]["goal"],
            }
            for req in self.requests.values()
        ]
        for (run_id, _), message in self.messages.items():
            turns.append(
                {
                    "id": self.requests[run_id]["attribution"]["slice"],
                    "prompt": message["text"],
                    "resume": run_id,
                }
            )
        return turns

    def finish(
        self, key=None, status="done", kind="handover", body="Completed", **kwargs
    ):
        key = key or next(reversed(self.records))
        if kind == "question":
            status = "question"
        record = self.records[key]
        if status in ("done", "waiting"):
            assert all(
                self.records[parent]["status"] == "done"
                for parent in self.requests[key]["after"]
            )
        record.update(
            status=status,
            resumable=True,
            commits=[TIP],
            final_message={"kind": kind, "body": body},
            updated_at=str(int(record["updated_at"]) + 1),
            **kwargs,
        )


@pytest.fixture
def setup(tmp_path, slice_data, make_state, monkeypatch):
    slice_data.update(slot=NOW.isoformat(), stop_before_merge=False)
    path = make_state()
    brief = tmp_path / "briefs/W1.md"
    brief.parent.mkdir()
    brief.write_text(
        "# Task\n\n## Fixed decisions\nKeep the contract.\n\n## Do not\nChange unrelated files.\n"
    )
    api, github = FakeRuns(), Mock()
    github.is_public.return_value = False
    github.default_tip.return_value = BASE
    github.branch_tip.return_value = TIP
    github.changes.return_value = (1, [])
    github.open.return_value = 12
    github.checks.return_value = ("pending", "")
    github.merge_info.return_value = {"state": "OPEN", "headRefOid": TIP}
    github.merge.return_value = "c" * 40
    github.owner_approval.return_value = None
    r = Runner(
        path,
        run_client=api,
        github=github,
        git=Mock(),
        clock=lambda: NOW,
        runs=tmp_path / "runs",
        repos=tmp_path / "repos",
    )
    r.repos.mkdir()
    return r, api, github


def item(r):
    return state.load(r.path)["slices"][0]


def edit(r, fn):
    data = state.load(r.path)
    fn(data["slices"][0])
    state.save(r.path, data)


def current(r):
    job = r.jobs["voice/W1"]
    return job["requests"][job["active"]]["run_id"]


def test_slice_request_and_poll_after_restart(setup):
    r, api, gh = setup
    r.run()
    request = next(iter(api.requests.values()))
    assert {
        k: request[k]
        for k in (
            "contract",
            "repository",
            "base_commit",
            "branch",
            "role",
            "mode",
            "level",
            "after",
        )
    } == {
        "contract": 1,
        "repository": "example/repo",
        "base_commit": BASE,
        "branch": "slice/voice-W1",
        "role": "slice",
        "mode": "write",
        "level": "standard",
        "after": [],
    }
    assert request["work"]["goal"].startswith("# Task\n")
    assert "Runner assignment: use branch slice/voice-W1" in request["work"]["goal"]
    assert not any(
        word in request["work"]["goal"].lower()
        for word in ("the fence", "bundle", "push")
    )
    assert not {"tool", "model", "effort", "limits"} & request.keys()
    restarted = Runner(
        r.path,
        run_client=api,
        github=gh,
        git=Mock(),
        clock=lambda: NOW,
        runs=r.runs.parent,
    )
    restarted.run()
    assert len(api.calls) == 1
    gh.default_tip.assert_called_once()


def test_restart_resends_identical_request_saved_before_post(setup):
    r, api, gh = setup
    api.lost_post = True
    r.run()
    saved = json.loads(next(r.runs.glob("*/job.json")).read_text())
    assert saved["requests"][saved["active"]]["request"] == api.calls[0]
    restarted = Runner(
        r.path,
        run_client=api,
        github=gh,
        git=Mock(),
        clock=lambda: NOW,
        runs=r.runs.parent,
    )
    restarted.run()
    assert len(api.requests) == 1 and len(api.calls) == 2
    assert api.calls[0] == api.calls[1]
    assert item(restarted)["attention"] is None


@pytest.mark.parametrize(
    "status,reason,kind,attention",
    [
        ("question", None, "question", "question"),
        ("escalated", None, "escalation", "escalation"),
        ("failed", "push_refused", None, "escalation"),
        ("cancelled", "cancelled_by_client", None, "escalation"),
        ("waiting", "client_step", "waiting", "node-step"),
    ],
)
def test_status_attention(setup, status, reason, kind, attention):
    r, api, _ = setup
    r.run()
    api.finish(current(r), status, kind, "Result body", status_reason=reason)
    r.run()
    actual = item(r)["attention"]
    assert actual["kind"] == attention
    assert (reason if status in ("failed", "cancelled") else "Result body") in actual[
        "body"
    ]


def test_usage_wait_is_platform_owned_and_has_no_attention(setup):
    r, api, _ = setup
    r.run()
    key = current(r)
    api.finish(
        key,
        "waiting",
        None,
        "",
        status_reason="usage_limit",
        resume_at="2026-11-18T00:00:00Z",
    )
    r.run()
    assert item(r)["attention"] is None
    assert "2026-11-18" in item(r)["log"][-1]["event"]
    assert not api.messages and len(api.requests) == 1
    from cplane.eligibility import eligibility

    assert eligibility(item(r), r.eligibility_data())["reason"] == "usage_limit"
    api.records[key].update(status="running", final_message=None)
    r.run()
    assert not api.messages


def test_answer_and_merge_notice_are_messages_to_original_run(setup):
    r, api, gh = setup
    r.run()
    original = current(r)
    api.finish(original, "question", "question", "Which option?")
    r.run()
    edit(r, lambda s: s["attention"].update(answer="Use the first option."))
    r.run()
    assert next(iter(api.messages.values()))["text"] == "Use the first option."
    assert next(iter(api.messages))[0] == original
    api.finish(original, "done", "handover", pr_reply())
    r.run()
    review = r.jobs["voice/W1"]["requests"]["review-1"]["run_id"]
    req = api.requests[review]
    assert (
        req["role"] == "review" and req["mode"] == "read" and req["base_commit"] == TIP
    )
    assert req["work"]["history"] == "full"
    api.finish(
        review,
        body=block(
            {"verdict": "pass", "title": "Reviewed", "body": "Tests pass"},
            "Extra prose.",
        ),
    )
    gh.checks.return_value = ("green", "")
    r.run()
    assert any(
        key[0] == original and msg["text"] == "merged as " + "c" * 40
        for key, msg in api.messages.items()
    )
    api.finish(original, body="Final handover")
    r.run()
    assert item(r)["state"] == "in review"
    assert len(api.requests) == 2


def test_ticket_chain_and_read_review(setup):
    r, api, _ = setup
    edit(r, lambda s: s.update(flow="tickets"))
    r.run()
    cut_id = current(r)
    assert (
        api.requests[cut_id]["role"] == "cut"
        and api.requests[cut_id]["mode"] == "write"
    )
    api.finish(cut_id, body=block(PLAN))
    r.run()
    tickets = [req for req in api.requests.values() if req["role"] == "ticket"]
    assert len(tickets) == 2
    assert tickets[0]["after"] == [api.requests[cut_id]["request_id"]]
    assert tickets[1]["after"] == [tickets[0]["request_id"]]
    for n, req in enumerate(tickets):
        assert req["work"]["allowed_files"] == PLAN["tickets"][n]["files"]
        assert req["work"]["pinned_paths"] == PLAN["test_files"]
        assert req["work"]["check_command"] == PLAN["tickets"][n]["check"]
        assert PLAN["tickets"][n]["change"] in req["work"]["goal"]
        api.finish(req["request_id"])
    r.run()
    review = api.requests[current(r)]
    assert review["role"] == "review" and review["mode"] == "read"
    assert review["base_commit"] == TIP and review["after"] == [
        tickets[-1]["request_id"]
    ]


@pytest.mark.parametrize("kind", ["handover", "waiting"])
def test_review_fenced_json_with_following_prose(setup, kind):
    r, api, _ = setup
    r.run()
    api.finish(current(r), "done", "handover", pr_reply())
    r.run()
    review = r.jobs["voice/W1"]["requests"]["review-1"]["run_id"]
    api.finish(
        review,
        "done" if kind == "handover" else "waiting",
        kind,
        block({"verdict": "fix", **PLAN}, "Here are the findings."),
    )
    r.run()
    assert r.jobs["voice/W1"]["review_verdict"] == "fix"


def test_pause_collects_without_delivery_then_unpause_uses_same_run(setup):
    r, api, gh = setup
    r.run()
    original = current(r)
    edit(r, lambda s: s.update(paused=True))
    api.finish(original, "done", "handover", pr_reply())
    r.run()
    assert not api.cancels and not api.messages and len(api.requests) == 1
    gh.open.assert_not_called()
    assert (
        r.jobs["voice/W1"]["requests"]["slice"]["record"]["final_message"]["body"]
        == pr_reply()
    )
    edit(r, lambda s: s.update(paused=False))
    r.run()
    gh.open.assert_called_once()
    assert current(r) == original


def test_pause_holds_answer_and_new_ready_slice(setup):
    r, api, _ = setup
    edit(r, lambda s: s.update(paused=True))
    r.run()
    assert not api.requests
    edit(r, lambda s: s.update(paused=False))
    r.run()
    api.finish(current(r), "question", "question", "Choose")
    r.run()
    edit(r, lambda s: (s.update(paused=True), s["attention"].update(answer="Answer")))
    r.run()
    assert not api.messages
    edit(r, lambda s: s.update(paused=False))
    r.run()
    assert len(api.messages) == 1


def test_abandon_retries_running_cancel_and_cancels_resumable(setup):
    r, api, _ = setup
    r.run()
    key = current(r)
    api.records[key]["status"] = "running"
    edit(r, lambda s: s.update(state="dropped", paused=True))
    r.run()
    r.run()
    assert api.cancels == [key, key]
    api.finish(key, "question", "question", "Question")
    r.run()
    assert api.records[key]["status"] == "cancelled"
    assert not api.messages
    assert item(r)["state"] == "dropped"


def test_platform_capacity_does_not_limit_submissions(setup, slice_data):
    r, api, _ = setup
    data = state.load(r.path)
    for i in range(3):
        new = copy.deepcopy(data["slices"][0])
        new.update(id=f"other/{i}", repo=f"example/repo{i}", allowed_files=[f"file{i}"])
        data["slices"].append(new)
    state.save(r.path, data)
    r.run()
    assert len(api.requests) == 4


@pytest.mark.parametrize("level", ["light", "standard", "strong"])
def test_slice_level_and_work_policy_are_forwarded(setup, level):
    r, api, _ = setup
    edit(
        r,
        lambda s: (
            s["log"].append(
                {"at": NOW.isoformat(), "actor": "planner", "event": "level: " + level}
            ),
            s.update(allowed_files=["cplane/**"]),
        ),
    )
    r.run()
    request = api.requests[current(r)]
    assert request["level"] == level
    assert request["work"]["allowed_files"] == ["cplane/**"]


def test_lost_message_response_retries_saved_message_id(setup, monkeypatch):
    r, api, _ = setup
    r.run()
    key = current(r)
    api.finish(key, "question", "question", "Choose")
    r.run()
    edit(r, lambda s: s["attention"].update(answer="Use A"))
    original = api.message
    count = [0]

    def lost(identity, body):
        result = original(identity, body)
        count[0] += 1
        if count[0] == 1:
            from cplane.run_platform import Unavailable

            raise Unavailable("Platform response unavailable")
        return result

    monkeypatch.setattr(api, "message", lost)
    r.run()
    saved = r.jobs["voice/W1"]["requests"]["slice"]["message"]
    r.run()
    assert count[0] == 2 and len(api.messages) == 1
    assert next(iter(api.messages.values())) == saved
    assert item(r)["attention"] is None


def test_lost_state_after_message_does_not_send_another_turn(setup, monkeypatch):
    r, api, _ = setup
    r.run()
    key = current(r)
    api.finish(key, "question", "question", "Choose")
    r.run()
    edit(r, lambda s: s["attention"].update(answer="Use A"))
    original = state.save
    with monkeypatch.context() as m:
        m.setattr(state, "save", Mock(side_effect=OSError("interrupted state save")))
        with pytest.raises(OSError):
            r.run()
    assert len(api.messages) == 1
    r.run()
    assert len(api.messages) == 1 and item(r)["attention"] is None
    assert state.save == original


def test_no_slice_process_or_usage_call_is_possible(setup, monkeypatch):
    from cplane import executors, fence, launcher

    blocked = Mock(side_effect=AssertionError("local execution forbidden"))
    monkeypatch.setattr(executors.Processes, "start", blocked)
    monkeypatch.setattr(fence.Fence, "prepare", blocked)
    monkeypatch.setattr(launcher, "usage", blocked)
    r, api, _ = setup
    r.run()
    api.finish(current(r), "question", "question", "Choose")
    r.run()
    edit(r, lambda s: s["attention"].update(answer="Use A"))
    r.run()
    blocked.assert_not_called()


def test_waiting_pr_result_completes_same_run_before_review(setup):
    r, api, _ = setup
    r.run()
    key = current(r)
    api.finish(key, "waiting", "waiting", pr_reply())
    r.run()
    assert len(api.requests) == 1
    message = next(iter(api.messages.values()))
    assert message["text"].startswith("Factory recorded your result.")
    api.finish(key, body="Result recorded")
    r.run()
    assert api.records[key]["status"] == "done"
    assert len(api.requests) == 2
    assert r.jobs["voice/W1"]["requests"]["review-1"]["request"]["after"] == [
        api.requests[key]["request_id"]
    ]


def test_abandon_lost_submit_response_only_looks_up_and_cancels(setup):
    r, api, _ = setup
    api.lost_post = True
    r.run()
    edit(r, lambda s: s.update(state="dropped", paused=True))
    r.run()
    assert len(api.calls) == 1
    assert api.records[next(iter(api.records))]["status"] == "cancelled"


def test_full_ticket_review_repair_and_postmerge_handover(setup):
    r, api, gh = setup
    edit(r, lambda s: s.update(flow="tickets"))
    r.run()
    api.finish(current(r), body=block(PLAN))
    r.run()
    for key, req in list(api.requests.items()):
        if req["role"] == "ticket":
            api.finish(key)
    r.run()
    api.finish(current(r), body=block({"verdict": "fix", **PLAN}))
    r.run()
    repairs = [key for key in api.requests if "repair-ticket" in key]
    assert len(repairs) == 2
    for key in repairs:
        api.finish(key)
    r.run()
    assert r.jobs["voice/W1"]["active"] == "review-2"
    review = current(r)
    api.finish(
        review, body=block({"verdict": "pass", "title": "Complete", "body": "Passed"})
    )
    r.run()
    gh.checks.return_value = ("green", "")
    r.run()
    assert any(
        key[0] == review and msg["text"].startswith("merged as ")
        for key, msg in api.messages.items()
    )
    api.finish(review, body="Ticket flow delivered and reviewed.")
    r.run()
    assert item(r)["state"] == "in review"
    assert len(api.requests) == 7


def test_review_question_routes_answer_to_review_run(setup):
    r, api, gh = setup
    r.run()
    original = current(r)
    api.finish(original, body=pr_reply())
    r.run()
    review = r.jobs["voice/W1"]["requests"]["review-1"]["run_id"]
    api.finish(review, "question", "question", "Review needs a decision")
    r.run()
    assert item(r)["attention"]["body"] == "Review needs a decision"
    edit(r, lambda s: s["attention"].update(answer="Use the documented rule"))
    r.run()
    assert next(iter(api.messages))[0] == review
    assert current(r) == original
    api.finish(
        review, body=block({"verdict": "pass", "title": "Reviewed", "body": "Passed"})
    )
    gh.checks.return_value = ("green", "")
    r.run()
    gh.merge.assert_called_once()


def test_review_usage_wait_is_visible_without_attention(setup):
    from cplane.eligibility import eligibility

    r, api, _ = setup
    r.run()
    api.finish(current(r), body=pr_reply())
    r.run()
    review = r.jobs["voice/W1"]["requests"]["review-1"]["run_id"]
    api.finish(
        review,
        "waiting",
        None,
        "",
        status_reason="usage_limit",
        resume_at="2026-11-18T00:00:00Z",
    )
    r.run()
    assert item(r)["attention"] is None
    assert eligibility(item(r), r.eligibility_data())["reason"] == "usage_limit"


@pytest.mark.parametrize("kind", ["handover", "waiting"])
def test_cut_accepts_plan_after_prose_and_earlier_code_block(setup, kind):
    r, api, _ = setup
    edit(r, lambda s: s.update(flow="tickets"))
    r.run()
    key = current(r)
    api.finish(
        key,
        "done" if kind == "handover" else "waiting",
        kind,
        "Plan follows.\n```python\nexample()\n```\n\n" + block(PLAN),
    )
    r.run()
    if kind == "waiting":
        assert len(api.requests) == 1 and len(api.messages) == 1
        api.finish(key, body="Recorded")
        r.run()
    assert len([req for req in api.requests.values() if req["role"] == "ticket"]) == 2


def test_guard_paths_need_owner_github_review(setup):
    r, api, gh = setup
    r.run()
    api.finish(current(r), body=pr_reply())
    r.run()
    review = r.jobs["voice/W1"]["requests"]["review-1"]["run_id"]
    api.finish(
        review, body=block({"verdict": "pass", "title": "Reviewed", "body": "Passed"})
    )
    gh.changes.return_value = (4, ["compose.yaml"])
    gh.checks.return_value = ("green", "")
    r.run()
    assert item(r)["attention"]["kind"] == "merge"
    assert "compose.yaml" in item(r)["attention"]["body"]
    gh.merge.assert_not_called()
    gh.owner_approval.return_value = 3
    r.run()
    gh.merge.assert_called_once()


def test_new_write_tip_gets_a_new_read_review(setup):
    r, api, gh = setup
    r.run()
    key = current(r)
    api.finish(key, body=pr_reply())
    r.run()
    review = r.jobs["voice/W1"]["requests"]["review-1"]["run_id"]
    api.finish(
        review, body=block({"verdict": "pass", "title": "Reviewed", "body": "Passed"})
    )
    gh.checks.return_value = ("red", "test")
    r.run()
    assert "test" in item(r)["attention"]["body"]
    edit(r, lambda s: s["attention"].update(answer="Fix the failing test"))
    r.run()
    gh.branch_tip.return_value = "d" * 40
    api.finish(key, body=pr_reply())
    r.run()
    fresh = r.jobs["voice/W1"]["requests"]["review-2"]["request"]
    assert fresh["base_commit"] == "d" * 40 and fresh["mode"] == "read"
    assert len(api.requests) == 3


def test_each_waiting_result_gets_its_own_completion_message(setup):
    r, api, gh = setup
    r.run()
    key = current(r)
    api.finish(key, "waiting", "waiting", pr_reply())
    r.run()
    api.finish(key, body="Recorded")
    r.run()
    review = r.jobs["voice/W1"]["requests"]["review-1"]["run_id"]
    api.finish(
        review, body=block({"verdict": "pass", "title": "Reviewed", "body": "Passed"})
    )
    gh.checks.return_value = ("red", "test")
    r.run()
    edit(r, lambda s: s["attention"].update(answer="Fix the test"))
    r.run()
    api.finish(key, "waiting", "waiting", pr_reply())
    r.run()
    completions = [
        body["message_id"]
        for (identity, _), body in api.messages.items()
        if identity == key and body["text"].startswith("Factory recorded")
    ]
    assert len(completions) == len(set(completions)) == 2


@pytest.mark.parametrize(
    "status,reason,kind,expected",
    [
        ("question", None, "question", "question"),
        ("escalated", None, "escalation", "escalation"),
        ("waiting", "client_step", "waiting", "node-step"),
        ("failed", "check_failed", None, "escalation"),
        ("cancelled", "cancelled_by_client", None, "escalation"),
    ],
)
def test_ticket_run_statuses_raise_attention(setup, status, reason, kind, expected):
    r, api, _ = setup
    edit(r, lambda s: s.update(flow="tickets"))
    r.run()
    api.finish(current(r), body=block(PLAN))
    r.run()
    first = next(key for key, req in api.requests.items() if req["role"] == "ticket")
    api.finish(first, status, kind, "Ticket needs attention", status_reason=reason)
    r.run()
    assert item(r)["attention"]["kind"] == expected
    assert (
        reason if status in ("failed", "cancelled") else "Ticket needs attention"
    ) in item(r)["attention"]["body"]
