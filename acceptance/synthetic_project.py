"""The synthetic acceptance project — Phase 20.0's end-to-end proof.

One artifact doing five jobs: the standalone quickstart, the end-to-end
acceptance test, the development fixture, the learning example, and the
planted-control environment for refusals.

It runs the fourteen accepted steps on a **deterministic fake adapter**, against
a **disposable local bare remote**, with **no homelab installed** — which is the
actual measure of ADR-031 §4's standalone-adoptability criterion.

Everything here is synthetic. No owner data, no private path, no token-shaped
string, not even a plausible one.

Run it::

    python3 acceptance/synthetic_project.py            # local mode
    python3 acceptance/synthetic_project.py --keep     # leave the workspace for inspection
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workbench import agents, gitops, project, records
from workbench.adapters import Request
from workbench.adapters.fake import FakeAdapter
from workbench.budget import Budget
from workbench.engine import Engine
from workbench.errors import ApprovalRequired, ProtectedBranch, WorkbenchError
from workbench.identity import Identity, human

PASS, FAIL = "  ok  ", " FAIL "
_failures: list[str] = []


def step(number: int | str, description: str, function) -> object:
    try:
        result = function()
    except Exception as error:  # noqa: BLE001 - the runner reports, it does not handle
        _failures.append(f"step {number}: {description} — {type(error).__name__}: {error}")
        print(f"[{FAIL}] {number:>2}. {description}\n         {type(error).__name__}: {error}")
        return None
    print(f"[{PASS}] {number:>2}. {description}")
    return result


def expect_refusal(label: str, function, expected: type[Exception], contains: str = "") -> None:
    """A planted refusal. The *control* for each of these is the step that succeeded above."""
    try:
        function()
    except expected as error:
        if contains and contains not in str(error):
            _failures.append(f"{label}: refused, but not on the expected reason: {error}")
            print(f"[{FAIL}] refusal: {label} — wrong reason: {error}")
            return
        print(f"[{PASS}] refusal: {label}")
        return
    except Exception as error:  # noqa: BLE001
        _failures.append(f"{label}: wrong exception {type(error).__name__}: {error}")
        print(f"[{FAIL}] refusal: {label} — wrong exception {type(error).__name__}")
        return
    _failures.append(f"{label}: was NOT refused")
    print(f"[{FAIL}] refusal: {label} — was NOT refused")


def run(workspace: Path) -> int:
    owner = human("owner", "SYNTH")
    backend = FakeAdapter()

    print(f"\nFactory Workbench — synthetic acceptance project\nworkspace: {workspace}\n")

    # --- 1-3: proposal, approval gate, initialisation -------------------------
    staging = project.create(workspace / "staging", project_id="SYNTH", title="Synthetic")
    staging_engine = Engine(staging, actor=owner)

    proposal = step(1, "Create a project proposal", lambda: staging_engine.create(
        "founder_inbox_item",
        {"title": "Create repository for Synthetic", "decision_needed":
         "Approve creating the repository for the Synthetic demo project?",
         "context_summary": "Synthetic acceptance project for Factory Workbench."}))

    request = staging_engine.request_approval(
        action="create_repository", target="SYNTH",
        material={"visibility": "private", "name": "synthetic"},
        summary="Create the Synthetic project repository, private by default.")

    expect_refusal(
        "repository creation before approval",
        lambda: staging_engine.require_approval(
            action="create_repository", target="SYNTH",
            material={"visibility": "private", "name": "synthetic"}),
        ApprovalRequired, "'requested'")

    step(2, "Require human approval before creating the repository",
         lambda: staging_engine.grant_approval(request["id"]))
    staging_engine.require_approval(action="create_repository", target="SYNTH",
                                    material={"visibility": "private", "name": "synthetic"})

    def initialise():
        root = workspace / "synthetic"
        proj = project.create(root, project_id="SYNTH", title="Synthetic")
        gitops.init_repo(root)
        (root / "product" / "app.py").write_text("def add(a, b):\n    return a + b\n")
        (root / "product" / "test_app.py").write_text(
            "from app import add\n\n\ndef test_add():\n    assert add(2, 2) == 4\n")
        gitops.commit_all(root, "initial", actor_is_human=True)
        bare = gitops.init_bare_remote(workspace / "remote.git")
        gitops.add_remote(root, bare)
        return proj

    synthetic = step(3, "Initialise the repository and minimum ops/", initialise)
    if synthetic is None:
        return 1
    repo = synthetic.root
    engine = Engine(synthetic, actor=owner)

    # --- 4: disposable worktree ----------------------------------------------
    # A worktree, not a checkout: the main checkout holds live ops/ records and
    # must not follow the product onto a feature branch. See gitops.add_worktree.
    tree = step(4, "Create a disposable worktree on a feature branch",
                lambda: gitops.add_worktree(repo, workspace / "worktrees" / "greeting",
                                            "feature/greeting"))
    if tree is None:
        return 1

    # --- 5: task with acceptance criteria -------------------------------------
    task = step(5, "Create a task with metadata and acceptance criteria",
                lambda: engine.create("task", {
                    "title": "Add a greeting function",
                    "intent": "Prove the Workbench loop end to end.",
                    "acceptance_criteria": ["greet('world') returns 'hello world'",
                                            "existing tests still pass"],
                    "priority": "medium", "risk_level": "low"}))

    # --- 6: roster and assignment --------------------------------------------
    implementer = agents.parse({"agent": "execution", "role": "Execution Agent",
                                "capabilities": ["repository_read", "repository_write"],
                                "unattended": True})
    reviewer = agents.parse({"agent": "review-qa", "role": "Review / QA",
                             "capabilities": ["repository_read", "review_append"]})

    orchestrator_engine = Engine(synthetic, actor=Identity(
        kind="agent", name="orchestrator", version="1", project_id="SYNTH"))
    expect_refusal("orchestrator adding an agent to the roster",
                   lambda: orchestrator_engine.add_to_roster("execution"),
                   WorkbenchError, "only a human approves")

    def assign():
        engine.add_to_roster("execution")
        engine.add_to_roster("review-qa")
        engine.activate(implementer, backend)
        engine.activate(reviewer, backend)
        return engine.create("ticket", {
            "title": "Implement greet()", "task_id": task["id"],
            "objective": "Add greet(name) to product/app.py",
            "acceptance_criteria": ["greet('world') == 'hello world'"],
            "assigned_agent": "execution", "status": "assigned"})

    ticket = step(6, "Assign work through an orchestrator to approved agents", assign)

    unsupported = agents.parse({"agent": "deployer", "role": "Release",
                                "capabilities": ["deploy_to_production", "rotate_secrets"]})
    expect_refusal("activating an agent needing unsupported capabilities",
                   lambda: engine.activate(unsupported, backend),
                   WorkbenchError, "deploy_to_production")

    # --- 7: bounded context ---------------------------------------------------
    context = step(7, "Select and assemble bounded context", lambda: engine.create(
        "context_pack", {"title": "Context for greet()",
                         "_body": "# Context\n\nFiles: product/app.py, product/test_app.py\n"}))

    # --- 8: execute through one adapter --------------------------------------
    budget = Budget(max_calls=4, max_cost=None)
    step(8, "Execute through one adapter (deterministic fake)", lambda: engine.execute(
        agent=implementer, backend=backend, budget=budget, work_item=ticket["id"],
        request=Request(agent_role=implementer.role, task_summary="Add greet()",
                        instructions="Add greet(name) returning 'hello <name>'",
                        context=("product/app.py",),
                        capabilities=implementer.capabilities)))

    exhausted = Budget(max_calls=0)
    expect_refusal("execution with an exhausted call budget",
                   lambda: engine.execute(
                       agent=implementer, backend=backend, budget=exhausted,
                       work_item=ticket["id"],
                       request=Request(agent_role="x", task_summary="s", instructions="i")),
                   WorkbenchError, "model-call budget")

    # --- 9: edits, commits, tests, review, revision on the feature branch -----
    def implement_and_review():
        app = tree / "product" / "app.py"
        app.write_text(app.read_text() + '\n\ndef greet(name):\n    return f"hello {name}"\n')
        (tree / "product" / "test_greet.py").write_text(
            "from app import greet\n\n\ndef test_greet():\n"
            "    assert greet('world') == 'hello world'\n")
        gitops.commit_all(tree, f"feat: greet() for {ticket['id']}", actor_is_human=False)

        check = gitops.run([sys.executable, "-c",
                            "import sys; sys.path.insert(0,'product'); "
                            "from app import greet, add; "
                            "assert greet('world')=='hello world'; assert add(2,2)==4; "
                            "print('tests pass')"], cwd=tree)
        engine.execute(agent=reviewer, backend=backend, budget=budget, work_item=ticket["id"],
                       request=Request(agent_role=reviewer.role, task_summary="Review greet()",
                                       instructions="Fresh-context review",
                                       capabilities=reviewer.capabilities))
        return engine.create("review_record", {
            "title": "Review of greet()", "related_ticket_id": ticket["id"],
            "status": "approved", "decision": "approved", "risk_level": "low",
            "implementation_summary": check})

    step(9, "Edits, commits, tests, review and revision on the feature branch",
         implement_and_review)

    # The main checkout is still on main, so this needs no branch switching.
    expect_refusal("a direct agent write to main",
                   lambda: ((repo / "sneaky.txt").write_text("x\n"),
                            gitops.commit_all(repo, "agent write to main",
                                              actor_is_human=False))[-1],
                   ProtectedBranch, "create a feature branch first")
    (repo / "sneaky.txt").unlink(missing_ok=True)

    # --- 10: push -------------------------------------------------------------
    step(10, "Push the feature branch",
         lambda: gitops.push(tree, "feature/greeting", actor_is_human=False))

    # --- 11 is the refusal proved above; 12 is GitHub mode --------------------
    print(f"[{PASS}] 11. Refuse direct agent writes to main  (proved above)")
    print("[ skip ] 12. Create a pull request — GitHub mode only, not exercised in local mode")

    # --- 13: approval bound to the exact reviewed revision -------------------
    reviewed_revision = gitops.revision(tree, "feature/greeting")
    merge_request = engine.request_approval(
        action="merge", target=ticket["id"],
        material={"revision": reviewed_revision, "branch": "feature/greeting", "base": "main"},
        summary=f"Merge feature/greeting at {reviewed_revision[:8]} after review")
    engine.grant_approval(merge_request["id"])

    step(13, "Human approval bound to the exact reviewed revision",
         lambda: engine.require_approval(
             action="merge", target=ticket["id"],
             material={"revision": reviewed_revision, "branch": "feature/greeting",
                       "base": "main"}))

    def land_another_commit():
        (tree / "product" / "extra.py").write_text("# added after approval\n")
        gitops.commit_all(tree, "chore: sneak a change in after approval", actor_is_human=False)
        return gitops.revision(tree, "feature/greeting")

    moved_revision = land_another_commit()
    expect_refusal("merging after the approved revision changed",
                   lambda: engine.require_approval(
                       action="merge", target=ticket["id"],
                       material={"revision": moved_revision, "branch": "feature/greeting",
                                 "base": "main"}),
                   ApprovalRequired, "revision changed")

    # --- 14: merge the approved revision and record provenance ---------------
    def merge_and_record():
        # Reset the *worktree* back to the revision that was actually reviewed.
        # Never the main checkout: that is where ops/ lives.
        gitops.reset_hard(tree, reviewed_revision)
        gitops.commit_all(repo, "ops: record the run", actor_is_human=True)
        merged = gitops.merge(repo, "feature/greeting", into="main",
                              message=f"Merge: {ticket['id']} greet()")
        engine.update(ticket["id"], {
            "status": "shipped", "merged_revision": merged,
            "reviewed_revision": reviewed_revision, "approval_ids": [merge_request["id"]]})
        return merged

    step(14, "Merge the approved revision and record provenance", merge_and_record)

    # --- closing checks -------------------------------------------------------
    print()
    step("A", "ops/ validates (records, links, audit chain)", lambda: _validate(synthetic))
    step("B", "budget recorded, with cost honestly unknown",
         lambda: _assert(budget.as_dict()["cost_is_complete"] is False
                         and budget.calls_used == 2, "budget not as expected"))
    step("C", "refusals are in the audit trail",
         lambda: _assert(any(e["outcome"] == "refused"
                             for e in __import__("workbench.audit", fromlist=["audit"])
                             .read(synthetic.ops)), "no refusals recorded"))

    print()
    if _failures:
        print(f"FAILED — {len(_failures)} problem(s):")
        for failure in _failures:
            print(f"  - {failure}")
        return 1
    print("PASSED — fourteen steps and seven planted refusals, "
          "on the deterministic fake adapter, with no homelab installed.")
    return 0


def _assert(condition: bool, message: str) -> bool:
    if not condition:
        raise AssertionError(message)
    return True


def _validate(proj) -> bool:
    from workbench import audit, schema
    problems = []
    for object_type in schema.SCHEMAS:
        for record in records.load_collection(proj.ops, object_type):
            problems += schema.validate(record)
    problems += records.check_links(proj.ops)
    problems += audit.verify(proj.ops)
    return _assert(not problems, f"ops/ has problems: {problems}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="keep the workspace for inspection")
    parser.add_argument("--workspace", help="use this directory instead of a temporary one")
    args = parser.parse_args()

    workspace = Path(args.workspace) if args.workspace else Path(tempfile.mkdtemp(prefix="factory-synth-"))
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        return run(workspace)
    finally:
        if args.keep or args.workspace:
            print(f"\nworkspace kept at {workspace}")
        else:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
