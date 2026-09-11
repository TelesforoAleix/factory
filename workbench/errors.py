"""Workbench's refusal vocabulary.

Refusals are values, not surprises. Every one of these carries a human-readable
reason, because a refusal a person cannot act on is only marginally better than
a silent failure.
"""


class WorkbenchError(Exception):
    """Base class. Carries a reason meant to be shown to a person."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ValidationError(WorkbenchError):
    """A record is not valid. Nothing was written."""

    def __init__(self, reason: str, problems: list[str] | None = None):
        super().__init__(reason)
        self.problems = problems or []

    def __str__(self) -> str:
        if not self.problems:
            return self.reason
        return self.reason + "\n  - " + "\n  - ".join(self.problems)


class ApprovalRequired(WorkbenchError):
    """The action needs a human approval that does not exist or no longer binds."""


class BudgetExhausted(WorkbenchError):
    """A task budget limit was reached. Execution stops; the inbox gets a request."""


class CapabilityUnsupported(WorkbenchError):
    """The selected backend cannot satisfy an agent's requirements (ADR-034 §6).

    Raised *before* activation, and it names every missing requirement rather
    than the first, because a caller that fixes one at a time learns nothing.
    """

    def __init__(self, reason: str, missing: list[str]):
        super().__init__(reason)
        self.missing = missing

    def __str__(self) -> str:
        return f"{self.reason}: {', '.join(self.missing)}"


class ScopeViolation(WorkbenchError):
    """An agent attempted work outside its project or context scope."""


class ProtectedBranch(WorkbenchError):
    """A write to a protected branch was refused (acceptance step 11)."""
