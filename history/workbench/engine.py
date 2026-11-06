"""The write engine. **Every write goes through here** (ADR-036 §1).

    surfaces (CLI, local server)  ->  engine  ->  records  ->  ops/ + git

The engine is what makes the surfaces interchangeable. A CLI invocation and an
HTTP request from the dashboard reach the same method with the same arguments
and produce byte-identical output — which the phase proves rather than asserts,
because if it were ever false there would be two definitions of a valid write
and nobody would find out until they disagreed.

The server does **not** implement writes. It calls this.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from workbench import agents as agents_module
from workbench import approvals, audit, ids, records, schema
from workbench.adapters import Request
from workbench.budget import Budget
from workbench.errors import ScopeViolation, ValidationError
from workbench.identity import Identity
from workbench.project import Project


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Engine:
    """Validated, audited writes against one project's ``ops/``."""

    def __init__(self, project: Project, *, actor: Identity):
        self.project = project
        self.actor = actor

    # -- internals ---------------------------------------------------------

    def _audit(self, action: str, target: str, *, outcome: str = "applied",
               detail: dict | None = None) -> None:
        audit.append(self.project.ops, actor=str(self.actor), action=action,
                     target=target, outcome=outcome, detail=detail or {})

    def _refuse(self, action: str, target: str, error: Exception):
        """Record a refusal before raising it.

        A refusal that leaves no trace cannot answer "did anything try this",
        which is most of what an audit trail is for.
        """
        self._audit(action, target, outcome="refused", detail={"reason": str(error)})
        raise error

    def _require_scope(self, action: str, target: str) -> None:
        if not self.actor.in_scope(target):
            self._refuse(action, target, ScopeViolation(
                f"{self.actor} may not act on {target}: outside its approved scope"
            ))

    # -- record operations -------------------------------------------------

    def create(self, object_type: str, fields: dict) -> dict:
        spec = schema.get(object_type)
        collection = self.project.ops / spec.collection
        year = datetime.now(timezone.utc).year

        record = {
            "template_version": "0.1",
            "object_type": object_type,
            "id": fields.get("id") or ids.next_id(collection, object_type, year),
            "project_id": self.project.project_id,
            "created_at": _now(),
            "updated_at": _now(),
            **{k: v for k, v in fields.items() if k != "id"},
        }
        record.setdefault("status", spec.statuses[0] if spec.statuses else "open")

        try:
            path = records.write(self.project.ops, record)
        except ValidationError as error:
            self._refuse("create", record["id"], error)
        self._audit("create", record["id"], detail={"path": str(path), "type": object_type})
        return record

    def update(self, object_id: str, changes: dict) -> dict:
        self._require_scope("update", object_id)
        record = records.find(self.project.ops, object_id)
        updated = {**record, **changes, "updated_at": _now()}
        try:
            records.write(self.project.ops, updated)
        except ValidationError as error:
            self._refuse("update", object_id, error)
        self._audit("update", object_id, detail={"fields": sorted(changes)})
        return updated

    def set_status(self, object_id: str, status: str) -> dict:
        return self.update(object_id, {"status": status})

    # -- approvals ---------------------------------------------------------

    def request_approval(self, *, action: str, target: str, material: dict,
                         summary: str) -> dict:
        approval_id = ids.next_id(self.project.ops / "approvals", "approval",
                                  datetime.now(timezone.utc).year)
        request = approvals.build_request(
            approval_id=approval_id, project_id=self.project.project_id,
            action=action, target=target, material=material,
            requested_by=str(self.actor), summary=summary,
        )
        records.write(self.project.ops, request)
        self._audit("request_approval", approval_id,
                    detail={"for_action": action, "for_target": target})
        return request

    def grant_approval(self, approval_id: str) -> dict:
        """Only a human grants an approval (ADR-034 §12)."""
        if not self.actor.is_human():
            self._refuse("grant_approval", approval_id, ScopeViolation(
                f"{self.actor} is not human; only a human may grant an approval"
            ))
        approval = records.find(self.project.ops, approval_id)
        granted = approvals.grant(approval, str(self.actor))
        records.write(self.project.ops, granted)
        self._audit("grant_approval", approval_id)
        return granted

    def find_approval(self, *, action: str, target: str) -> dict | None:
        for approval in records.load_collection(self.project.ops, "approval"):
            if approval.get("bound_action") == action and approval.get("bound_target") == target:
                return approval
        return None

    def require_approval(self, *, action: str, target: str, material: dict) -> dict:
        """Check that an approval binds this exact action, or refuse."""
        approval = self.find_approval(action=action, target=target)
        try:
            approvals.check(approval, action=action, target=target, material=material)
        except Exception as error:
            self._refuse(action, target, error)
        self._audit("approval_checked", target,
                    detail={"approval": approval.get("id"), "for_action": action})
        return approval

    # -- agents ------------------------------------------------------------

    def activate(self, agent: agents_module.Agent, backend) -> agents_module.Agent:
        """Check compatibility **before** work begins (ADR-034 §6)."""
        try:
            agents_module.check_compatibility(agent, backend)
        except Exception as error:
            self._refuse("activate_agent", agent.name, error)
        self._audit("activate_agent", agent.name,
                    detail={"backend": backend.name, "digest": agent.digest()})
        return agent

    def add_to_roster(self, agent_name: str, *, scope: str = "team") -> dict:
        """Add an agent to the project roster. Humans only (ADR-034 §12)."""
        if not self.actor.is_human():
            self._refuse("add_to_roster", agent_name, ScopeViolation(
                f"{self.actor} may not add an agent to the roster; "
                f"an orchestrator may recommend through the inbox, but only a human approves"
            ))
        if scope not in ("task", "team"):
            raise ValidationError(f"roster scope must be 'task' or 'team', not {scope!r}")
        import json
        ref_path = self.project.agents_ref
        data = json.loads(ref_path.read_text(encoding="utf-8"))
        roster = data.setdefault("roster", [])
        if not any(entry["agent"] == agent_name for entry in roster):
            roster.append({"agent": agent_name, "scope": scope, "added_by": str(self.actor),
                           "added_at": _now()})
        ref_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self._audit("add_to_roster", agent_name, detail={"scope": scope})
        return data

    def roster(self) -> list[dict]:
        import json
        ref_path = self.project.agents_ref
        if not ref_path.is_file():
            return []
        return json.loads(ref_path.read_text(encoding="utf-8")).get("roster", [])

    def require_on_roster(self, agent_name: str) -> dict:
        for entry in self.roster():
            if entry["agent"] == agent_name:
                return entry
        self._refuse("assign", agent_name, ScopeViolation(
            f"agent {agent_name!r} is not on this project's roster; "
            f"a human must add it before it can be assigned work"
        ))

    # -- execution ---------------------------------------------------------

    def execute(self, *, agent: agents_module.Agent, backend, request, budget: Budget,
                work_item: str) -> "object":
        """Run one bounded unit of work, budget checked **before** the call."""
        try:
            budget.check()
        except Exception as error:
            self._refuse("execute", work_item, error)

        result = backend.execute(request)
        budget.record(result.cost)

        self._audit(
            "execute", work_item,
            outcome="refused" if result.refused else "applied",
            detail={
                "agent": agent.name, "digest": agent.digest(), "backend": backend.name,
                "model": result.model, "budget": budget.as_dict(),
                "reason": result.reason,
            },
        )
        return result

    # -- the smallest action that calls the configured adapter (Phase 23.0) ---

    def run(self, item_id: str, backend, *, max_calls: int = 1) -> tuple[dict, "object"]:
        """Run one work item through ``backend`` and record what came back.

        The 23.0 brief §6.6's "smallest Workbench action that calls the
        configured adapter": build a ``Request`` from the item, call the
        adapter once, record a ``run`` object (an existing type, existing
        statuses -- no 94th status) and link it from the item. Results are the
        client's to record (23.0 brief §6.3): the endpoint returns and forgets,
        this is where the answer lives.

        What the Request is made of, and what it is not:
          agent_role   the item's ``assigned_agent``. Factory has no JSON agent
                       manifests yet (roles are prose under agents/roles/), so
                       the roster name is the role key -- named in the handover.
          task_summary the item's title.
          instructions ``objective`` (ticket) or ``intent`` (task).
          context      empty. Nothing on an item is *selected content*; context
                       assembly is Phase 23.2's, and the endpoint adds nothing.
          capabilities the agent's -- none, for a roster-name agent; a backend
                       that advertises none refuses one that declares any, at
                       activation, before any call (ADR-034 §6).
          priority     the item's, in Factory's vocabulary; the adapter maps.
        """
        item = records.find(self.project.ops, item_id)
        if item.get("object_type") not in ("ticket", "task"):
            self._refuse("run", item_id, ValidationError(
                f"{item_id} is a {item.get('object_type')}; run takes a ticket or a task"))
        agent_name = item.get("assigned_agent")
        if not agent_name:
            self._refuse("run", item_id, ValidationError(f"{item_id} has no assigned_agent"))
        self.require_on_roster(agent_name)
        agent = agents_module.parse({"agent": agent_name, "role": agent_name},
                                    source=f"{item_id}.assigned_agent")
        self.activate(agent, backend)

        instructions = item.get("objective") or item.get("intent") or ""
        request = Request(
            agent_role=agent.role,
            task_summary=str(item.get("title", "")),
            instructions=str(instructions),
            context=(),
            capabilities=agent.capabilities,
            priority=str(item.get("priority", "medium")),
        )
        budget = Budget(max_calls=max_calls, max_cost=None)
        result = self.execute(agent=agent, backend=backend, request=request,
                              budget=budget, work_item=item_id)

        link = "related_ticket_id" if item["object_type"] == "ticket" else "related_task_id"
        run = self.create("run", {
            "status": "refused" if result.refused else "succeeded",
            "run_type": "execution",
            "agent_id": agent.name,
            "agent_digest": agent.digest(),
            "adapter": backend.name,
            # The endpoint's correlation id, when the adapter has one. Out of
            # band because Result carries no such field -- see adapters/homelab.py.
            "request_id": getattr(backend, "last_request_id", None),
            link: item_id,
            "model": result.model,
            "cost": result.cost,
            "tokens": result.tokens,
            "refused": result.refused,
            "reason": result.reason,
            "output": result.output,
            "budget": budget.as_dict(),
        })
        run_ids = list(item.get("run_ids") or [])
        run_ids.append(run["id"])
        self.update(item_id, {"run_ids": run_ids})
        return run, result
