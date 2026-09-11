"""Execution adapters — how Workbench invokes AI work (ADR-035 §4).

The load-bearing property, stated in ADR-035 §4:

> From Workbench's side, "run this through homelab" and "run this through Claude
> Code" are **the same shape of adapter**.

So the interface must not leak backend-specific concepts. It carries a bounded
request and returns a bounded result; it does not accept a model name, a
provider, a binary path, or a prompt template, because accepting any of those
would make the next adapter either special-cased or impossible.

Only the deterministic fake is fixed for this phase. A real adapter is Phase 23's
business, and the second-adapter check in the Phase 20.0 brief §8.1.3 is what
proves this interface is real rather than one implementation with an interface
drawn around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Request:
    """What an adapter is asked to do.

    Note what is absent: no model, no provider, no temperature, no system
    prompt. The agent's *role* is its declaration of need (ADR-034 §5); choosing
    a model from that is the backend's job, not the caller's.
    """

    agent_role: str
    task_summary: str
    instructions: str
    context: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    # Non-authoritative hints. ADR-034 §5: hints, never selectors.
    priority: str = "medium"
    complexity: str = "medium"


@dataclass(frozen=True)
class Result:
    output: str
    # None means the provider did not report a cost. It stays None.
    cost: float | None = None
    tokens: int | None = None
    model: str | None = None
    refused: bool = False
    reason: str = ""


class Adapter(Protocol):
    """What every adapter must provide."""

    name: str

    def capabilities(self) -> tuple[str, ...]:
        """Portable capabilities this backend can satisfy."""

    def tools(self) -> tuple[str, ...]:
        """Concrete tool names this backend implements."""

    def execute(self, request: Request) -> Result:
        """Run one bounded unit of work."""
