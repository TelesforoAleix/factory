"""Two limits per task, not one (design review, ADR-034 §5's cost discipline).

> Every automated task has both a monetary limit for metered providers; and a
> model-call limit, useful for subscriptions and unknown-cost providers.
> The first limit reached stops execution and creates a project-inbox request.

The second limit is the one that is easy to leave out and the one that matters
most here, because the adapters this phase ships are a deterministic fake and,
later, subscription-backed CLIs — where cost per call is *unknown*, not zero.

**Unknown cost stays unknown.** It is never replaced with a confident estimate,
because an estimate that is wrong in the safe direction hides a real overrun and
an estimate that is wrong the other way stops work that was affordable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from workbench.errors import BudgetExhausted


@dataclass
class Budget:
    """A task's spending envelope. ``max_cost`` of ``None`` means unmetered."""

    max_calls: int
    max_cost: float | None = None
    calls_used: int = 0
    cost_used: float = 0.0
    # Calls whose cost the provider did not report.
    unknown_cost_calls: int = 0

    def check(self) -> None:
        """Raise if a limit is already reached. Called *before* a call, never after."""
        if self.calls_used >= self.max_calls:
            raise BudgetExhausted(
                f"model-call budget exhausted: {self.calls_used}/{self.max_calls} calls used"
            )
        if self.max_cost is not None and self.cost_used >= self.max_cost:
            raise BudgetExhausted(
                f"monetary budget exhausted: {self.cost_used:.4f}/{self.max_cost:.4f} used"
            )

    def record(self, cost: float | None) -> None:
        """Record one completed call. ``None`` cost is recorded as unknown."""
        self.calls_used += 1
        if cost is None:
            self.unknown_cost_calls += 1
        else:
            self.cost_used += cost

    def as_dict(self) -> dict:
        return {
            "max_calls": self.max_calls,
            "max_cost": self.max_cost,
            "calls_used": self.calls_used,
            "cost_used": round(self.cost_used, 6),
            "unknown_cost_calls": self.unknown_cost_calls,
            "cost_is_complete": self.unknown_cost_calls == 0,
        }
