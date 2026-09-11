"""Execution identity, attached by the runtime rather than claimed (ADR-034 §11).

An agent does not get an OS account or a credential because it exists. It gets a
**logical identity** that the trusted runtime attaches to every action, carrying
the agent, its version, the project, the work item and the assignment.

The model supplies a proposed operation and its arguments, and nothing else. It
cannot claim another identity, switch project, or manufacture a grant — not
because it is asked not to, but because the fields it would have to set are not
read from anything it produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Identity:
    """Who is acting. Frozen: an identity is never edited mid-action."""

    kind: str          # "human" | "agent" | "system"
    name: str
    version: str | None = None
    project_id: str | None = None
    work_item: str | None = None
    assignment: str | None = None
    # Capabilities this identity is approved for, per ADR-034 §12's roster.
    capabilities: frozenset[str] = field(default_factory=frozenset)
    # The records/paths this identity may touch (ADR-034 §7 target scope).
    scope: frozenset[str] = field(default_factory=frozenset)

    def __str__(self) -> str:
        base = f"{self.kind}:{self.name}"
        return f"{base}@{self.version}" if self.version else base

    def is_human(self) -> bool:
        return self.kind == "human"

    def in_scope(self, target: str) -> bool:
        """Empty scope means unrestricted, which only humans and system get."""
        if not self.scope:
            return self.kind in ("human", "system")
        return target in self.scope


def human(name: str, project_id: str | None = None) -> Identity:
    return Identity(kind="human", name=name, project_id=project_id)


SYSTEM = Identity(kind="system", name="workbench")
