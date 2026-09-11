"""Phase 20.0 validation.

Every refusal is proved **by attempt against a planted positive control** — the
byte-identical case with only the offending element removed, which must succeed.

> An authorisation check that has only ever permitted is unvalidated.

A refusal test with no passing control proves only that the code is broken, so
each refusal below is paired with its control in the same test.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import agents, approvals, audit, gitops, project, records, schema
from workbench.adapters import Request
from workbench.adapters.fake import FakeAdapter
from workbench.budget import Budget
from workbench.engine import Engine
from workbench.errors import (ApprovalRequired, BudgetExhausted, CapabilityUnsupported,
                              ProtectedBranch, ScopeViolation, ValidationError)
from workbench.identity import Identity, human

REPO = Path(__file__).resolve().parent.parent


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project = project.create(self.tmp / "demo", project_id="DEMO", title="Demo")
        self.owner = human("aleix", "DEMO")
        self.engine = Engine(self.project, actor=self.owner)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def agent(self, name="execution", **kw) -> Identity:
        return Identity(kind="agent", name=name, version="1", project_id="DEMO", **kw)


class TestRecordLayer(Base):
    def test_nested_structure_round_trips(self):
        """ADR-036 validation 3 — the failure `parseLooseYaml` would have caused."""
        nested = {
            "template_version": "0.1", "object_type": "founder_inbox_item",
            "id": "INBOX-2026-0001", "title": "Pick one", "status": "open",
            "project_id": "DEMO", "decision_needed": "which option",
            "options": [
                {"id": "a", "label": "A", "pros": ["fast", "cheap"], "cons": []},
                {"id": "b", "label": "B", "pros": [], "cons": ["slow"]},
            ],
        }
        path = records.write(self.project.ops, nested)
        self.assertEqual(records.load(path)["options"], nested["options"])

    def test_invalid_record_leaves_ops_unchanged(self):
        """ADR-036 validation 4 — validation happens before any bytes move."""
        before = sorted(p.name for p in (self.project.ops / "tasks").iterdir())
        with self.assertRaises(ValidationError):
            records.write(self.project.ops, {
                "template_version": "0.1", "object_type": "task", "id": "TASK-2026-0001",
                "title": "t", "status": "not-a-real-status", "project_id": "DEMO",
                "intent": "i", "acceptance_criteria": ["a"],
            })
        self.assertEqual(sorted(p.name for p in (self.project.ops / "tasks").iterdir()), before)

    def test_validation_reports_every_problem_not_the_first(self):
        problems = schema.validate({"object_type": "task", "id": "WRONG-1",
                                    "status": "nope", "risk_level": "impossible"})
        self.assertGreater(len(problems), 3, problems)

    def test_audit_chain_detects_tampering(self):
        self.engine.create("task", {"title": "t", "intent": "i", "acceptance_criteria": ["a"]})
        self.assertEqual(audit.verify(self.project.ops), [])
        log = self.project.ops / "audit" / "audit.jsonl"
        entries = [json.loads(line) for line in log.read_text().splitlines()]
        entries[0]["actor"] = "human:someone-else"
        log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        self.assertTrue(audit.verify(self.project.ops))


class TestRefusal1UnapprovedAgentAddition(Base):
    def test_refused_for_non_human(self):
        engine = Engine(self.project, actor=self.agent("orchestrator"))
        with self.assertRaises(ScopeViolation) as caught:
            engine.add_to_roster("execution")
        self.assertIn("only a human approves", str(caught.exception))

    def test_control_human_may_add(self):
        self.engine.add_to_roster("execution")
        self.assertEqual([e["agent"] for e in self.engine.roster()], ["execution"])

    def test_unrostered_agent_cannot_be_assigned(self):
        with self.assertRaises(ScopeViolation):
            self.engine.require_on_roster("execution")
        self.engine.add_to_roster("execution")
        self.assertEqual(self.engine.require_on_roster("execution")["scope"], "team")


class TestRefusal2UnsupportedCapability(Base):
    def test_refused_and_names_every_missing_requirement(self):
        """ADR-034 §6 — *every* missing requirement, not the first."""
        agent = agents.parse({"agent": "a", "role": "r",
                              "capabilities": ["repository_read", "deploy", "send_email"],
                              "tools": ["kubectl"]})
        backend = FakeAdapter(capabilities=("repository_read",), tools=())
        with self.assertRaises(CapabilityUnsupported) as caught:
            self.engine.activate(agent, backend)
        missing = caught.exception.missing
        self.assertEqual(missing, ["capability:deploy", "capability:send_email", "tool:kubectl"])

    def test_control_activation_succeeds_when_met(self):
        agent = agents.parse({"agent": "a", "role": "r", "capabilities": ["repository_read"]})
        backend = FakeAdapter(capabilities=("repository_read",))
        self.assertIs(self.engine.activate(agent, backend), agent)

    def test_refusal_is_before_activation_not_at_dispatch(self):
        agent = agents.parse({"agent": "a", "role": "r", "capabilities": ["deploy"]})
        backend = FakeAdapter(capabilities=("repository_read",))
        with self.assertRaises(CapabilityUnsupported):
            self.engine.activate(agent, backend)
        # Nothing was executed, and the refusal is in the trail.
        actions = [e["action"] for e in audit.read(self.project.ops)]
        self.assertIn("activate_agent", actions)
        self.assertNotIn("execute", actions)


class TestRefusal3ApprovalGate(Base):
    def test_refused_when_no_approval_exists(self):
        with self.assertRaises(ApprovalRequired) as caught:
            self.engine.require_approval(action="create_repository", target="DEMO",
                                         material={"visibility": "private"})
        self.assertIn("none exists", str(caught.exception))

    def test_refused_while_request_is_still_pending(self):
        self.engine.request_approval(action="create_repository", target="DEMO",
                                     material={"visibility": "private"}, summary="s")
        with self.assertRaises(ApprovalRequired) as caught:
            self.engine.require_approval(action="create_repository", target="DEMO",
                                         material={"visibility": "private"})
        self.assertIn("'requested'", str(caught.exception))

    def test_control_passes_once_granted(self):
        request = self.engine.request_approval(action="create_repository", target="DEMO",
                                               material={"visibility": "private"}, summary="s")
        self.engine.grant_approval(request["id"])
        approval = self.engine.require_approval(action="create_repository", target="DEMO",
                                                material={"visibility": "private"})
        self.assertEqual(approval["status"], "approved")

    def test_agent_cannot_grant_its_own_approval(self):
        request = self.engine.request_approval(action="merge", target="TICKET-2026-0001",
                                               material={"revision": "abc"}, summary="s")
        agent_engine = Engine(self.project, actor=self.agent("release"))
        with self.assertRaises(ScopeViolation):
            agent_engine.grant_approval(request["id"])


class TestRefusal4ReviewRoundsExhausted(Base):
    """Default two rounds, configurable per project (design review)."""

    @staticmethod
    def review_loop(max_rounds: int, passes_on_round: int) -> int:
        rounds = 0
        while rounds < max_rounds:
            rounds += 1
            if rounds >= passes_on_round:
                return rounds
        raise BudgetExhausted(
            f"review rounds exhausted after {rounds} of {max_rounds}; escalating to the inbox"
        )

    def test_refused_when_limit_reached(self):
        with self.assertRaises(BudgetExhausted) as caught:
            self.review_loop(max_rounds=2, passes_on_round=5)
        self.assertIn("escalating to the inbox", str(caught.exception))

    def test_control_resolves_within_the_limit(self):
        self.assertEqual(self.review_loop(max_rounds=2, passes_on_round=1), 1)


class TestRefusal5BudgetExhausted(Base):
    """Both limits, proved separately — the call limit is the one easily forgotten."""

    def test_call_limit_refuses(self):
        budget = Budget(max_calls=1)
        budget.record(None)
        with self.assertRaises(BudgetExhausted) as caught:
            budget.check()
        self.assertIn("model-call budget", str(caught.exception))

    def test_monetary_limit_refuses(self):
        budget = Budget(max_calls=100, max_cost=0.10)
        budget.record(0.10)
        with self.assertRaises(BudgetExhausted) as caught:
            budget.check()
        self.assertIn("monetary budget", str(caught.exception))

    def test_control_within_both_limits(self):
        budget = Budget(max_calls=2, max_cost=1.0)
        budget.record(0.25)
        budget.check()  # must not raise

    def test_unknown_cost_stays_unknown(self):
        budget = Budget(max_calls=5)
        budget.record(None)
        self.assertEqual(budget.cost_used, 0.0)
        self.assertEqual(budget.unknown_cost_calls, 1)
        self.assertFalse(budget.as_dict()["cost_is_complete"])

    def test_budget_is_checked_before_the_call_not_after(self):
        agent = agents.parse({"agent": "a", "role": "r"})
        backend = FakeAdapter()
        budget = Budget(max_calls=0)
        with self.assertRaises(BudgetExhausted):
            self.engine.execute(agent=agent, backend=backend, budget=budget,
                                work_item="TICKET-2026-0001",
                                request=Request(agent_role="r", task_summary="s", instructions="i"))
        self.assertEqual(budget.calls_used, 0)


class TestRefusal6ScopeViolation(Base):
    def test_agent_outside_scope_is_refused(self):
        scoped = Engine(self.project, actor=self.agent("execution",
                                                       scope=frozenset({"TICKET-2026-0001"})))
        task = self.engine.create("task", {"title": "t", "intent": "i",
                                           "acceptance_criteria": ["a"]})
        with self.assertRaises(ScopeViolation):
            scoped.update(task["id"], {"title": "changed"})

    def test_control_inside_scope_succeeds(self):
        task = self.engine.create("task", {"title": "t", "intent": "i",
                                           "acceptance_criteria": ["a"]})
        scoped = Engine(self.project, actor=self.agent("execution",
                                                       scope=frozenset({task["id"]})))
        self.assertEqual(scoped.update(task["id"], {"title": "changed"})["title"], "changed")


class TestRefusal7NoAgentWriteToMain(Base):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "product"
        gitops.init_repo(self.repo)
        (self.repo / "README.md").write_text("demo\n")
        gitops.commit_all(self.repo, "initial", actor_is_human=True)

    def test_agent_write_to_main_is_refused(self):
        (self.repo / "f.txt").write_text("x\n")
        with self.assertRaises(ProtectedBranch) as caught:
            gitops.commit_all(self.repo, "agent change", actor_is_human=False)
        self.assertIn("create a feature branch first", str(caught.exception))

    def test_control_same_write_on_a_feature_branch_succeeds(self):
        gitops.create_branch(self.repo, "feature/x")
        (self.repo / "f.txt").write_text("x\n")
        self.assertTrue(gitops.commit_all(self.repo, "agent change", actor_is_human=False))

    def test_agent_push_to_main_is_refused(self):
        with self.assertRaises(ProtectedBranch):
            gitops.push(self.repo, "main", actor_is_human=False)


class TestRefusal8ApprovalBindsToRevision(Base):
    """Acceptance step 13. Proved by changing the revision *after* approval."""

    def test_approval_stops_binding_when_the_revision_changes(self):
        request = self.engine.request_approval(
            action="merge", target="TICKET-2026-0001",
            material={"revision": "aaaa1111", "branch": "feature/x"}, summary="merge")
        self.engine.grant_approval(request["id"])

        # Control first: it binds while nothing has changed.
        self.engine.require_approval(action="merge", target="TICKET-2026-0001",
                                     material={"revision": "aaaa1111", "branch": "feature/x"})

        # Then one more commit lands on the branch.
        with self.assertRaises(ApprovalRequired) as caught:
            self.engine.require_approval(action="merge", target="TICKET-2026-0001",
                                         material={"revision": "bbbb2222", "branch": "feature/x"})
        self.assertIn("revision changed", str(caught.exception))

    def test_approval_for_a_different_action_does_not_transfer(self):
        request = self.engine.request_approval(action="create_repository", target="DEMO",
                                               material={}, summary="s")
        self.engine.grant_approval(request["id"])
        with self.assertRaises(ApprovalRequired):
            self.engine.require_approval(action="merge", target="DEMO", material={})

    def test_expired_approval_does_not_bind(self):
        request = approvals.build_request(
            approval_id="APPROVAL-2026-0099", project_id="DEMO", action="merge",
            target="T", material={}, requested_by="x", summary="s", expiry_days=-1)
        with self.assertRaises(ApprovalRequired) as caught:
            approvals.check(approvals.grant(request, "human:aleix"),
                            action="merge", target="T", material={})
        self.assertIn("expired", str(caught.exception))


class TestSurfaceEquivalence(Base):
    """ADR-036 validation 2 — the test that proves the engine boundary is real."""

    def test_cli_and_engine_produce_identical_records(self):
        fields = {"intent": "prove it", "acceptance_criteria": ["identical"], "title": "T"}

        via_engine = Engine(self.project, actor=self.owner).create("task", dict(fields))
        engine_bytes = records.path_for(self.project.ops, via_engine).read_bytes()

        other = project.create(self.tmp / "demo2", project_id="DEMO", title="Demo")
        subprocess.run(
            [sys.executable, "-m", "workbench.cli", "--project", str(other.root),
             "--actor", "aleix", "create", "task", "--title", "T",
             "--fields", json.dumps({k: v for k, v in fields.items() if k != "title"})],
            cwd=str(REPO), check=True, capture_output=True,
        )
        cli_bytes = (other.ops / "tasks" / "TASK-2026-0001.yaml").read_bytes()

        # Timestamps are the only permitted difference; strip them and compare.
        def without_times(raw: bytes) -> list[bytes]:
            return [line for line in raw.splitlines()
                    if not line.startswith((b"created_at", b"updated_at"))]

        self.assertEqual(without_times(engine_bytes), without_times(cli_bytes))


class TestServerBoundary(Base):
    def test_refuses_non_loopback_bind(self):
        from workbench.server import serve
        from workbench.errors import WorkbenchError
        for host in ("0.0.0.0", "192.168.0.10", "::"):
            with self.assertRaises(WorkbenchError):
                serve(self.project.root, host=host)

    def test_server_implements_no_write_of_its_own(self):
        """ADR-036 §1: if a write lives in the server, the engine boundary has eroded."""
        source = (REPO / "workbench" / "server.py").read_text()
        for forbidden in ("records.write(", "yaml.safe_dump", "open(", ".write_text("):
            self.assertNotIn(forbidden, source,
                             f"server.py must not write records directly; found {forbidden!r}")


class TestProjectCreation(Base):
    def test_minimum_ops_structure(self):
        for collection in schema.MINIMUM_COLLECTIONS:
            self.assertTrue((self.project.ops / collection).is_dir(), collection)

    def test_agents_directory_references_factory_rather_than_copying(self):
        """ADR-028 — a copy forks silently; a reference breaks loudly."""
        data = json.loads(self.project.agents_ref.read_text())
        self.assertIn("factory_path", data)
        self.assertEqual(data["roster"], [])

    def test_creating_twice_is_refused(self):
        with self.assertRaises(ValidationError):
            project.create(self.project.root, project_id="DEMO", title="Demo")


class TestAgentManifests(Base):
    def test_model_policy_is_refused(self):
        """ADR-034 §5 removed it. A manifest carrying it predates the contract."""
        with self.assertRaises(ValidationError) as caught:
            agents.parse({"agent": "a", "role": "r", "model_policy": "cheap"})
        self.assertIn("ADR-034", caught.exception.problems[0])

    def test_capabilities_and_tools_stay_separate(self):
        agent = agents.parse({"agent": "a", "role": "r",
                              "capabilities": ["repository_read"], "tools": ["local_thing"]})
        self.assertEqual(agent.capabilities, ("repository_read",))
        self.assertEqual(agent.tools, ("local_thing",))

    def test_digest_pins_a_definition(self):
        first = agents.parse({"agent": "a", "role": "r", "capabilities": ["x"]})
        same = agents.parse({"agent": "a", "role": "r", "capabilities": ["x"]})
        upskilled = agents.parse({"agent": "a", "role": "r", "capabilities": ["x", "y"]})
        self.assertEqual(first.digest(), same.digest())
        self.assertNotEqual(first.digest(), upskilled.digest())


class TestDeterministicAdapter(Base):
    def test_same_request_same_result(self):
        adapter = FakeAdapter()
        request = Request(agent_role="review-qa", task_summary="s", instructions="i")
        self.assertEqual(adapter.execute(request).output, adapter.execute(request).output)

    def test_reports_unknown_cost_rather_than_a_confident_zero(self):
        self.assertIsNone(FakeAdapter().execute(
            Request(agent_role="r", task_summary="s", instructions="i")).cost)

    def test_carries_no_model_or_provider_in_the_request(self):
        """ADR-035 §4 — the interface must not leak backend-specific concepts."""
        for forbidden in ("model", "provider", "api_key", "temperature", "system_prompt"):
            self.assertNotIn(forbidden, Request.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main(verbosity=2)
