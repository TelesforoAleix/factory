"""A deterministic fake adapter.

This ships **before** any real adapter, and the reason is in the Phase 20.0
brief: an acceptance test that needs a live model is not repeatable. It is also
the planted-control environment — it can be told to refuse, so a refusal path can
be proved without waiting for a real backend to misbehave.

Deterministic means: same request in, same result out, every time, on any
machine. No clock, no randomness, no network.
"""

from __future__ import annotations

import hashlib

from workbench.adapters import Request, Result


class FakeAdapter:
    """Returns a stable, derived response. Costs nothing and calls nothing."""

    name = "fake"

    def __init__(self, *, capabilities: tuple[str, ...] = ("repository_read", "repository_write",
                                                           "review_append", "run_tests"),
                 tools: tuple[str, ...] = (),
                 refuse: tuple[str, ...] = ()):
        # `refuse` names capabilities this instance pretends not to support at
        # execution time, for planted-control tests.
        self._capabilities = capabilities
        self._tools = tools
        self._refuse = refuse

    def capabilities(self) -> tuple[str, ...]:
        return self._capabilities

    def tools(self) -> tuple[str, ...]:
        return self._tools

    def execute(self, request: Request) -> Result:
        for capability in request.capabilities:
            if capability in self._refuse:
                return Result(
                    output="",
                    refused=True,
                    reason=f"fake adapter configured to refuse capability {capability!r}",
                )

        seed = "\x00".join(
            (request.agent_role, request.task_summary, request.instructions) + tuple(request.context)
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        output = (
            f"[fake:{digest}] {request.agent_role} completed: {request.task_summary}"
        )
        # Cost is None, not 0.0: the fake makes no metered call, and claiming a
        # confident zero would train the system to trust a number it did not get.
        return Result(output=output, cost=None, tokens=None, model="deterministic-fake")
