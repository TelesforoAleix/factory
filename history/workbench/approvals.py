"""Approvals bound to one immutable proposed action (ADR-034, design review).

> An approval is bound to one immutable proposed action, including its target
> and relevant revision. Changing a branch, diff, repository, visibility, merge
> commit, or other material input invalidates the approval.

The binding is a **fingerprint**: a hash over the action, its target and every
material input. An approval carries the fingerprint it was granted against, and
is checked by recomputing the fingerprint at the moment of action. If anything
material changed, the hashes differ and the approval does not bind.

This is the mechanism behind acceptance step 13 and refusal 8. Note what it is
*not*: approving a pull request number is not approving a revision, because the
pull request can gain commits afterwards.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from workbench.errors import ApprovalRequired

DEFAULT_EXPIRY_DAYS = 7  # The design review left the default undecided; this is configurable.


def fingerprint(action: str, target: str, material: dict) -> str:
    """Hash the action, its target, and every input that must not change."""
    payload = {"action": action, "target": target, "material": material}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_request(*, approval_id: str, project_id: str, action: str, target: str,
                  material: dict, requested_by: str, summary: str,
                  expiry_days: int = DEFAULT_EXPIRY_DAYS) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "template_version": "0.1",
        "object_type": "approval",
        "id": approval_id,
        "title": f"Approve: {action} on {target}",
        "status": "requested",
        "project_id": project_id,
        "request_summary": summary,
        "related_object_ids": [target],
        "requested_by": requested_by,
        "bound_action": action,
        "bound_target": target,
        "bound_fingerprint": fingerprint(action, target, material),
        "bound_material": material,
        "decision": None,
        "approved_by": None,
        "approved_at": None,
        "expires_at": (now + timedelta(days=expiry_days)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "created_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def grant(approval: dict, approver: str) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    granted = dict(approval)
    granted.update({"status": "approved", "decision": "approved",
                    "approved_by": approver, "approved_at": now})
    return granted


def check(approval: dict | None, *, action: str, target: str, material: dict) -> None:
    """Raise :class:`ApprovalRequired` unless this approval binds this exact action.

    Every refusal names *why*, because "not approved" is indistinguishable from
    "approved something slightly different" to the person trying to act.
    """
    if approval is None:
        raise ApprovalRequired(f"{action} on {target} requires human approval; none exists")

    if approval.get("status") != "approved":
        raise ApprovalRequired(
            f"approval {approval.get('id')} is {approval.get('status')!r}, not 'approved'"
        )

    if approval.get("bound_action") != action or approval.get("bound_target") != target:
        raise ApprovalRequired(
            f"approval {approval.get('id')} is bound to "
            f"{approval.get('bound_action')} on {approval.get('bound_target')}, "
            f"not {action} on {target}"
        )

    expires_at = approval.get("expires_at")
    if expires_at and _parse_time(expires_at) < datetime.now(timezone.utc):
        raise ApprovalRequired(f"approval {approval.get('id')} expired at {expires_at}")

    current = fingerprint(action, target, material)
    if approval.get("bound_fingerprint") != current:
        was = approval.get("bound_material") or {}
        changed = sorted({k for k in set(was) | set(material) if was.get(k) != material.get(k)})
        raise ApprovalRequired(
            f"approval {approval.get('id')} no longer binds: "
            f"{', '.join(changed) or 'the action'} changed since it was granted"
        )
