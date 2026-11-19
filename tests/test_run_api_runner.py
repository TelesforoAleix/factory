"""Run API orchestration with synthetic state and an idempotent fake platform."""

import copy
import json
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from cplane.docs_verify import Snapshot

from cplane import state
from cplane.cli import main
from cplane.run_records import run_final
from cplane.runner import Runner, platform_paths

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


def pr_reply(node_steps=None, **extra):
    return block(
        {
            "branch": "slice/voice-W1",
            "title": "Deliver slice",
            "body": "Implemented and tested.",
            "node_steps": node_steps,
            **{"contract_changes": None, **extra},
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
                    body["mode"] == "write"
                    and self.requests[other]["mode"] == "write"
                    and self.requests[other]["repository"] == body["repository"]
                    and self.requests[other]["branch"] == body["branch"]
                    and (
                        record["status"] in ("queued", "running", "question", "waiting")
                        or record["status"] == "escalated"
                        and record["resumable"]
                    )
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
        record = self.records[key]
        if record["status"] == "running":
            raise NotResumable("Platform run not resumable")
        if (
            record["status"] in ("failed", "escalated", "cancelled", "done")
            and not record["resumable"]
        ):
            return self.get(key)
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
        if status == "waiting" and "status_reason" not in kwargs:
            kwargs["status_reason"] = "client_step"
        if status in ("done", "waiting"):
            assert all(
                self.records[parent]["status"] == "done"
                for parent in self.requests[key]["after"]
            )
        record.update(
            status=status,
            resumable=kwargs.pop("resumable", status not in ("failed", "cancelled")),
            commits=[TIP],
            final_message=body,
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


COMMIT_INSTRUCTION = (
    "Commit all of your work on this branch, in one or more commits with plain messages, before you end. "
    "Do not push and do not open a PR: the platform delivers your commits, and Factory opens the PR."
)


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
    assert COMMIT_INSTRUCTION in request["work"]["goal"]
    assert "If blocked before committing, commit nothing and explain why in the PR body; Factory raises that as a question." in request["work"]["goal"]
    assert not any(
        word in request["work"]["goal"].lower()
        for word in ("the fence", "bundle")
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


def test_empty_slice_delivery_raises_question_without_github_read(setup):
    r, api, gh = setup
    r.run()
    final = pr_reply() + "Blocked before committing: dependency unavailable."
    api.finish(current(r), body=final)
    api.records[current(r)]["commits"] = []
    r.run()
    assert item(r)["attention"]["kind"] == "question"
    assert item(r)["attention"]["body"] == final
    assert r.jobs["voice/W1"]["tip"] == BASE
    assert "github_read_failure_since" not in r.jobs["voice/W1"]
    gh.branch_tip.assert_not_called()
    gh.open.assert_not_called()


def test_slice_delivery_with_commits_opens_pr(setup):
    r, api, gh = setup
    r.run()
    api.finish(current(r), body=pr_reply())
    r.run()
    gh.branch_tip.assert_any_call("example/repo", "slice/voice-W1")
    gh.open.assert_called_once()


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


def reset_ready(r):
    for args in (
        ("state", "voice/W1", "planned", "--force", "--reason", "Retry terminal run"),
        ("state", "voice/W1", "ready"),
        ("start", "voice/W1"),
    ):
        with patch("cplane.state.now", return_value=NOW):
            assert main(["--state", str(r.path), "--actor", "planner", *args]) == 0


@pytest.mark.parametrize("flow", ["cli", "tickets"])
@pytest.mark.parametrize("status", ["failed", "escalated", "cancelled", "done"])
def test_reset_terminal_run_starts_new_attempt_with_current_base(setup, flow, status):
    r, api, gh = setup
    edit(r, lambda s: s.update(flow=flow))
    r.run()
    original = current(r)
    old_job = copy.deepcopy(r.jobs["voice/W1"])
    api.finish(original, status=status, resumable=False)
    r.run()
    reset_ready(r)
    gh.default_tip.return_value = TIP
    r.run()
    replacement = current(r)
    job = r.jobs["voice/W1"]
    assert replacement != original
    assert job["attempt"] == old_job["attempt"] + 1
    assert job["run"] != old_job["run"]
    assert len(list(r.runs.glob("*/job.json"))) == 2
    assert api.requests[replacement]["base_commit"] == TIP
    assert api.requests[replacement]["role"] == (
        "cut" if flow == "tickets" else "slice"
    )
    assert api.requests[original]["base_commit"] == BASE
    assert item(r)["state"] == "issued"
    assert item(r)["session"]["id"] == replacement
    assert item(r)["attention"] is None
    assert original not in api.cancels
    # A new result must not match the previous attempt's collected-turn marker.
    api.finish(replacement, kind="question", body="Retry question")
    r.run()
    assert item(r)["attention"]["body"] == "Retry question"
    edit(r, lambda s: s["attention"].update(answer="Retry answer"))
    r.run()
    assert next(iter(api.messages))[0] == replacement
    assert gh.default_tip.call_count == 2


def test_retry_attempt_is_saved_before_post_and_survives_restart(setup):
    r, api, gh = setup
    r.run()
    api.finish(current(r), status="failed", resumable=False)
    r.run()
    reset_ready(r)
    gh.default_tip.return_value = TIP
    api.lost_post = True
    r.run()
    replacement = next(reversed(api.requests))
    restarted = Runner(
        r.path,
        run_client=api,
        github=gh,
        git=Mock(),
        clock=lambda: NOW,
        runs=r.runs.parent,
    )
    restarted.run()
    assert current(restarted) == replacement
    assert restarted.jobs["voice/W1"]["attempt"] == 2
    assert api.calls[-1] == api.calls[-2]
    assert len(api.requests) == 2
    gh.default_tip.assert_called_with("example/repo")
    assert gh.default_tip.call_count == 2


@pytest.mark.parametrize("status", ["question", "waiting", "done", "escalated"])
def test_start_keeps_resumable_attempt_and_sends_message(setup, status):
    r, api, gh = setup
    r.run()
    original = current(r)
    old_job = copy.deepcopy(r.jobs["voice/W1"])
    for _ in range(2):
        api.finish(original, status=status)
        r.collect(r.data["slices"][0], r.jobs["voice/W1"])
        r.start(r.data["slices"][0])
    assert current(r) == original
    assert r.jobs["voice/W1"]["attempt"] == old_job["attempt"]
    assert len(api.requests) == 1
    assert next(iter(api.messages))[0] == original
    assert len(api.messages) == 2
    gh.default_tip.assert_called_once()


def test_retry_failed_ticket_releases_old_chain_before_new_cut(setup):
    r, api, gh = setup
    edit(r, lambda s: s.update(flow="tickets"))
    r.run()
    api.finish(current(r), body=block(dict(PLAN, node_steps=None)))
    r.run()
    tickets = [key for key, req in api.requests.items() if req["role"] == "ticket"]
    api.finish(tickets[0], status="failed")
    r.run()
    reset_ready(r)
    gh.default_tip.return_value = TIP
    r.run()
    replacement = api.requests[current(r)]
    assert replacement["role"] == "cut"
    assert replacement["base_commit"] == TIP
    assert replacement["after"] == []
    assert r.jobs["voice/W1"]["attempt"] == 2
    assert tickets[1] in api.cancels
    assert api.records[tickets[1]]["status"] == "cancelled"


def test_reset_while_paused_records_failure_without_cancelling_or_starting(setup):
    r, api, gh = setup
    r.run()
    original = current(r)
    edit(r, lambda s: s.update(paused=True))
    api.finish(original, status="failed")
    reset_ready(r)
    r.run()
    assert current(r) == original
    assert item(r)["state"] == "ready"
    assert not api.messages and not api.cancels and len(api.requests) == 1
    assert r.jobs["voice/W1"]["requests"]["slice"]["record"]["status"] == "failed"
    edit(r, lambda s: s.update(paused=False))
    gh.default_tip.return_value = TIP
    r.run()
    assert r.jobs["voice/W1"]["attempt"] == 2
    assert current(r) != original


def test_answer_message_ids_are_distinct_across_attempts(setup):
    r, api, _ = setup
    r.run()
    for attempt in (1, 2):
        api.finish(current(r), kind="question", body="Same question")
        r.run()
        edit(r, lambda s: s["attention"].update(answer="Same answer"))
        r.run()
        if attempt == 1:
            api.finish(current(r), status="failed")
            r.run()
            reset_ready(r)
            r.run()
    assert len(api.messages) == 2
    assert len({message_id for _, message_id in api.messages}) == 2
    assert len({message["text"] for message in api.messages.values()}) == 1


def test_reset_retires_failed_continuation_after_lost_message_response(
    setup, monkeypatch
):
    from cplane.run_platform import Unavailable

    r, api, _ = setup
    r.run()
    original = current(r)
    api.finish(original, kind="question", body="Which option?")
    r.run()
    send = api.message

    def lost_response(key, body):
        send(key, body)
        api.finish(key, status="failed")
        raise Unavailable("Message response unavailable")

    monkeypatch.setattr(api, "message", lost_response)
    edit(r, lambda s: s["attention"].update(answer="Use the first option"))
    r.run()
    assert r.jobs["voice/W1"]["requests"]["slice"].get("message")
    reset_ready(r)
    r.run()
    assert current(r) != original
    assert r.jobs["voice/W1"]["attempt"] == 2
    assert len(api.messages) == 1 and len(api.requests) == 2


def test_start_queued_attempt_keeps_saved_request(setup):
    r, api, gh = setup
    r.run()
    original = current(r)
    r.start(r.data["slices"][0])
    assert current(r) == original
    assert r.jobs["voice/W1"]["attempt"] == 1
    assert len(api.calls) == 1 and not api.messages
    gh.default_tip.assert_called_once()


def test_legacy_job_keeps_saved_request_then_restarts_as_attempt_two(setup):
    r, api, gh = setup
    r.run()
    original = current(r)
    job = r.jobs["voice/W1"]
    job.pop("attempt")
    r.save_job(job)
    r.run()
    assert current(r) == original and len(api.calls) == 1
    api.finish(original, status="failed")
    r.run()
    reset_ready(r)
    gh.default_tip.return_value = TIP
    r.run()
    assert current(r) != original
    assert r.jobs["voice/W1"]["attempt"] == 2


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
    assert COMMIT_INSTRUCTION not in req["work"]["goal"]
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
    assert COMMIT_INSTRUCTION in api.requests[cut_id]["work"]["goal"]
    api.finish(cut_id, body=block(dict(PLAN, node_steps=None)))
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
    job = r.jobs["voice/W1"]
    review = job["requests"][job["pr_review"]]["request"]
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
        r.jobs["voice/W1"]["requests"]["slice"]["record"]["final_message"]
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


@pytest.mark.parametrize("slice_state", ["accepted", "dropped", "issued"])
def test_old_runner_job_is_ignored(setup, slice_state):
    r, api, _ = setup
    r.run()
    path = next(r.runs.glob("*/job.json"))
    old_job = json.loads(path.read_text())
    del old_job["requests"]
    path.write_text(json.dumps(old_job))
    original_file = path.read_bytes()
    edit(r, lambda s: s.update(state=slice_state))
    before = item(r)
    calls = copy.deepcopy(api.calls)

    r.run()

    assert item(r)["state"] == before["state"]
    assert item(r)["attention"] == before["attention"]
    assert "voice/W1" not in r.jobs
    assert path.read_bytes() == original_file
    assert api.calls == calls and not api.cancels and not api.messages


def test_old_runner_job_does_not_block_fresh_start(setup):
    r, api, _ = setup
    path = r.runs / "old" / "job.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"id": "voice/W1", "started_ns": 1}))
    original_file = path.read_bytes()

    r.run()

    assert item(r)["state"] == "issued" and item(r)["attention"] is None
    assert len(api.calls) == 1 and current(r) in api.requests
    assert path.read_bytes() == original_file


def test_abandon_failure_does_not_reopen_accepted_slice(setup, monkeypatch, capsys):
    r, api, _ = setup
    r.run()
    edit(r, lambda s: s.update(state="accepted"))
    before = item(r)
    monkeypatch.setattr(r, "abandon", Mock(side_effect=RuntimeError("failure")))
    calls = copy.deepcopy(api.calls)

    r.run()

    assert item(r)["state"] == before["state"]
    assert item(r)["attention"] == before["attention"]
    assert api.calls == calls and not api.cancels and not api.messages
    assert "cplane: abandon failed voice/W1: RuntimeError" in capsys.readouterr().err


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
    assert request["work"]["allowed_files"] == ["cplane"]


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
    assert r.jobs["voice/W1"]["answers"] == [
        {"at": NOW.isoformat(), "question": "Choose", "answer": "Use A"}
    ]


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
    assert len(r.jobs["voice/W1"]["answers"]) == 1
    assert state.save == original


@pytest.mark.parametrize("flow", ["cli", "tickets"])
def test_review_goal_includes_delivered_answers_in_order(setup, flow):
    r, api, _ = setup
    edit(r, lambda s: s.update(flow=flow))
    r.run()
    key = current(r)
    for question, answer in [("Pause?", "Continue"), ("Which rule?", "Use B")]:
        api.finish(key, "question", "question", question)
        r.run()
        edit(r, lambda s, answer=answer: s["attention"].update(answer=answer))
        r.run()
    api.finish(key, body=pr_reply() if flow == "cli" else block(dict(PLAN, node_steps=None)))
    r.run()
    if flow == "tickets":
        for ticket, request in list(api.requests.items()):
            if request["role"] == "ticket":
                api.finish(ticket)
        r.run()
    job = r.jobs["voice/W1"]
    goal = job["requests"]["review-1"]["request"]["work"]["goal"]
    section = "Answers given during the slice (they replace the brief where they differ):"
    assert goal.index(job["brief"]) < goal.index(section) < goal.index("Runner assignment:")
    assert "Question: Pause?\nAnswer: Continue\n\nQuestion: Which rule?\nAnswer: Use B" in goal


def test_review_goal_omits_answers_section_when_empty(setup):
    r, api, _ = setup
    r.run()
    api.finish(current(r), body=pr_reply())
    r.run()
    goal = r.jobs["voice/W1"]["requests"]["review-1"]["request"]["work"]["goal"]
    assert "Answers given during the slice" not in goal


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


@pytest.mark.parametrize("steps", [None, "Install the merged commit", "legacy"])
def test_full_ticket_pr_review_has_no_repair_and_postmerge_handover(setup, steps, monkeypatch, capsys):
    r, api, gh = setup
    edit(r, lambda s: s.update(flow="tickets"))
    r.run()
    cut_run = current(r)
    api.finish(cut_run, body=block(dict(PLAN, node_steps=None if steps == "legacy" else steps)))
    r.run()
    if steps == "legacy":
        job = r.jobs["voice/W1"]
        job["task_file"].pop("node_steps")
        r.save_job(job)
    tickets = [key for key, req in api.requests.items() if req["role"] == "ticket"]
    api.finish(tickets[0])
    r.run()
    gh.open.assert_not_called()
    api.finish(tickets[1])
    r.run()
    job = r.jobs["voice/W1"]
    request = gh.open.call_args.args[1]
    assert request["title"] == item(r)["title"]
    assert request["body"] == "\n\n".join(
        f"- {ticket['title']}\n  Check: {ticket['check']}" for ticket in PLAN["tickets"]
    )
    assert job["phase"] == "pr" and not job.get("repair")
    review = job["requests"][job["pr_review"]]["run_id"]
    gh.checks.return_value = ("green", "")
    r.run()
    gh.merge.assert_not_called()
    api.finish(review, body=block({"verdict": "fix", **PLAN}))
    r.run()
    assert r.jobs["voice/W1"]["review_verdict"] == "fix"
    assert not any("repair-ticket" in key for key in api.requests)
    gh.merge.assert_called_once()
    assert not any(msg["text"].startswith("merged as ") for msg in api.messages.values())
    expected = None if steps == "legacy" else steps
    assert request["node_steps"] == expected
    if expected is None:
        assert item(r)["state"] == "in review"
    else:
        assert item(r)["attention"]["kind"] == "node-step"
        assert item(r)["attention"]["body"] == expected
    monkeypatch.setenv("CPLANE_RUNS", str(r.runs.parent))
    assert main(["--state", str(r.path), "show", "voice/W1", "--final"]) == 0
    output = capsys.readouterr().out
    final = json.loads(output.split("body: ", 1)[1])
    assert final == {"request": request, "review_verdict": "fix", "review_findings": PLAN["tickets"]}
    if expected is not None:
        edit(r, lambda s: s["attention"].update(answer="Installed"))
        r.run()
        assert item(r)["state"] == "in review"
        assert not any(msg["text"] in ("Installed", "merged as " + "c" * 40)
                       for msg in api.messages.values())
    assert len(api.requests) == 4


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
        "Plan follows.\n```python\nexample()\n```\n\n" + block(dict(PLAN, node_steps=None)),
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
    api.finish(current(r), body=block(dict(PLAN, node_steps=None)))
    r.run()
    first = next(key for key, req in api.requests.items() if req["role"] == "ticket")
    api.finish(first, status, kind, "Ticket needs attention", status_reason=reason)
    r.run()
    assert item(r)["attention"]["kind"] == expected
    assert (
        reason if status in ("failed", "cancelled") else "Ticket needs attention"
    ) in item(r)["attention"]["body"]


@pytest.mark.parametrize(
    "status,reason,kind",
    [
        ("done", None, "handover"),
        ("question", None, "question"),
        ("escalated", "executor_gave_up", "escalation"),
        ("waiting", "client_step", "waiting"),
    ],
)
def test_run_final_from_platform_status(status, reason, kind):
    record = {"status": status, "status_reason": reason, "final_message": "Verbatim body"}
    assert run_final(record) == {"kind": kind, "body": "Verbatim body"}


def test_run_final_accepts_object_and_missing_final():
    final = {"kind": "handover", "body": "Existing final"}
    assert run_final({"final_message": final}) is final
    assert run_final({"status": "done", "final_message": None}) is None
    assert (
        run_final(
            {"status": "waiting", "status_reason": "usage_limit", "final_message": "body"}
        )
        is None
    )


def test_done_slice_string_pr_request_opens_pr(setup):
    r, api, gh = setup
    r.run()
    api.finish(current(r), body=pr_reply())
    r.run()
    request = gh.open.call_args.args[1]
    assert request["title"] == "Deliver slice"
    assert request["body"] == "Implemented and tested."


@pytest.mark.parametrize(
    "paths,expected",
    [
        (None, None),
        ([], []),
        (["src/a.py", "tests/**", "src/*"], ["src/a.py", "tests", "src"]),
    ],
)
def test_platform_paths(paths, expected):
    assert platform_paths(paths) == expected


@pytest.mark.parametrize("path", ["src/*.py", "src/?", "src/[ab]", "a*/**", "**"])
def test_unexpressible_slice_path_escalates_before_post(setup, path):
    r, api, _ = setup
    edit(r, lambda s: s.update(allowed_files=[path]))
    r.run()
    assert not api.calls
    assert item(r)["attention"]["kind"] == "escalation"
    assert path in item(r)["attention"]["body"]


def test_ticket_paths_translated_in_post(setup):
    r, api, _ = setup
    edit(r, lambda s: s.update(flow="tickets", allowed_files=["src/**"]))
    plan = copy.deepcopy(PLAN)
    plan["node_steps"] = None
    plan["tickets"][0]["files"] = ["src/*"]
    plan["test_files"] = ["tests/**"]
    r.run()
    cut = current(r)
    assert api.requests[cut]["work"]["allowed_files"] == ["src"]
    api.finish(cut, body=block(plan))
    r.run()
    ticket = next(req for req in api.requests.values() if req["role"] == "ticket")
    assert ticket["work"]["allowed_files"] == ["src"]
    assert ticket["work"]["pinned_paths"] == ["tests"]


@pytest.mark.parametrize("field", ["files", "test_files"])
def test_unexpressible_ticket_path_escalates_before_ticket_posts(setup, field):
    r, api, _ = setup
    edit(r, lambda s: s.update(flow="tickets"))
    plan = copy.deepcopy(PLAN)
    plan["node_steps"] = None
    if field == "files":
        plan["tickets"][1]["files"] = ["src/*.py"]
    else:
        plan["test_files"] = ["tests/*.py"]
    r.run()
    api.finish(current(r), body=block(plan))
    r.run()
    assert all(req["role"] != "ticket" for req in api.requests.values())
    assert item(r)["attention"]["kind"] == "escalation"
    assert "*.py" in item(r)["attention"]["body"]


CHANGES = [{"name": "state-v1", "version": "2", "users": ["example/a", "example/b"]}]
SHA = "c" * 40


def merged(setup, reply, files=None, answer_steps=False):
    r, api, gh = setup
    if files is not None:
        gh.snapshot.return_value = Snapshot(SHA, files.get)
    r.run()
    original = current(r)
    api.finish(original, "done", "handover", reply)
    r.run()
    job = r.jobs["voice/W1"]
    api.finish(job["requests"][job["pr_review"]]["run_id"],
               body=block({"verdict": "pass", "title": "T", "body": "B"}))
    gh.checks.return_value = ("green", "")
    r.run()
    return r, api, original


@pytest.mark.parametrize("value,valid", [
    (None, True), (CHANGES, True), ("missing", False), ([], False), ("x", False),
    ([{"name": "n", "version": "1", "users": []}], False),
    ([{"name": "n", "version": "1"}], False),
    ([{"name": "n", "version": 1, "users": ["a/b"]}], False),
])
def test_pr_request_contract_changes(value, valid):
    request = {"branch": "b", "title": "t", "body": "x", "node_steps": None, "contract_changes": value}
    if value == "missing":
        del request["contract_changes"]
    if valid:
        assert Runner.pr_request(block(request), "b") == request
    else:
        with pytest.raises(state.StateError, match="invalid PR request"):
            Runner.pr_request(block(request), "b")


def test_instruction_names_contract_changes(setup):
    r, api, _ = setup
    r.run()
    goal = next(iter(api.requests.values()))["work"]["goal"]
    assert "contract_changes" in goal and "docs/contracts.md" in goal


def test_contract_change_attention_without_node_step(setup):
    r, api, original = merged(setup, pr_reply(contract_changes=CHANGES))
    att = item(r)["attention"]
    assert att["kind"] == "contract-change"
    assert "state-v1 2" in att["body"] and "example/a, example/b" in att["body"]
    assert "adapting slice in the same Feature" in att["body"]
    api.finish(original, body="Final handover")
    r.run()
    assert item(r)["state"] == "in review" and item(r)["attention"]["kind"] == "contract-change"


def test_contract_change_attention_after_node_step_answered(setup):
    r, api, original = merged(setup, pr_reply("Install it", contract_changes=CHANGES))
    assert item(r)["attention"]["kind"] == "node-step"
    edit(r, lambda s: s["attention"].update(answer="Installed"))
    r.run()
    api.finish(original, body="Final handover")
    r.run()
    assert item(r)["attention"]["kind"] == "contract-change"
    assert item(r)["state"] == "in review"


def test_graph_check_skipped_without_claims(setup):
    r, api, original = merged(setup, pr_reply(), files={})
    assert not any(e["event"].startswith("docs-graph") for e in item(r)["log"])
    assert item(r)["attention"] is None


def test_graph_check_passes_and_is_logged(setup):
    claims = {"version": 1, "repository": "example/repo", "parts": [], "claims": [], "relations": [], "contracts": []}
    r, api, original = merged(setup, pr_reply(), files={"docs/claims.json": json.dumps(claims)})
    assert any(e["event"] == f"docs-graph: pass at {SHA}" for e in item(r)["log"])
    assert item(r)["attention"] is None


def test_graph_check_failure_raises_attention(setup):
    r, api, original = merged(setup, pr_reply(), files={"docs/claims.json": "{"})
    assert any(e["event"] == f"docs-graph: fail at {SHA}" for e in item(r)["log"])
    att = item(r)["attention"]
    assert att["kind"] == "docs-graph" and "not valid JSON" in att["body"]


def test_old_job_request_reads_as_null(setup):
    r, api, original = merged(setup, pr_reply())
    job = r.jobs["voice/W1"]
    job["request"].pop("contract_changes")
    job.pop("pending_attention")
    r.after_merge(item(r), job)
    assert job["pending_attention"] == []
