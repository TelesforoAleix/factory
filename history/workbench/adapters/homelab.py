"""The ``homelab`` adapter — the Workbench's second adapter (Phase 23.0).

The first real implementation of the ``Adapter`` protocol, and therefore the
test of whether that protocol is real or drawn around the fake (Phase 20.0
brief §8.1.3, ADR-035 §4). It speaks to homelab's endpoint — the harness — on
loopback: ``POST http://127.0.0.1:8766/v1/request``. The URL is fixed here and
not configurable per project, because loopback is not a choice (ADR-038 §2);
tests pass another port through the constructor and nothing else does.

What this adapter does NOT do, and why each absence is the point:

* It does not name a model or a provider. ``Request.agent_role`` is forwarded as
  the endpoint's ``role`` — the routing key, and the only thing on the wire that
  selects anything (ADR-034 §5). ``Result.model`` is whatever the endpoint
  reports back, echoed for the record.
* It does not claim who it is. The endpoint attaches origin itself; this adapter
  declares a label, ``X-Homelab-Client: workbench``, which the endpoint records
  as ``client_declared`` — a label, not an identity (23.0 brief §6.10).
* It does not retry, loop, or fall back. A refusal is a ``Result`` with
  ``refused=True`` and the endpoint's refusal *kind* leading ``reason``; an
  unreachable endpoint is the same shape with ``endpoint_unreachable``. The
  Workbench's ``Budget`` counts the call either way.
* It advertises no capabilities and no tools. The endpoint in 23.0 answers
  questions; it executes nothing. An agent that declares a capability is
  therefore refused *at activation* by ``check_compatibility`` (ADR-034 §6) —
  which is the honest statement of what Phase 19 has to build.

The one translation this adapter performs, and where it comes from: Factory's
``Request.priority`` vocabulary is the ticket schema's (``low, medium, high,
urgent``); the endpoint's is the model helper's (``low, normal, high,
critical``). ``_PRIORITY`` maps one to the other. ``complexity`` shares a
vocabulary and passes through. Neither is a selector on either side.

``Request`` and ``Result`` are unchanged by this file. One thing did not fit:
the endpoint returns a ``request_id`` that the Workbench's audit line should
carry so the two audit trails can be joined, and ``Result`` has no field for it.
Rather than extend ``Result`` in passing (ADR-035 §4 says that is a finding and
an ADR, not a convenience), the adapter exposes it out of band as
``last_request_id`` and the ``run`` command records it when present. That leak
is named in the Phase 23.0 handover.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from workbench.adapters import Request, Result

ENDPOINT = "http://127.0.0.1:8766/v1/request"
CLIENT_LABEL = "workbench"

# Factory ticket/task priority -> the endpoint's (the model helper's) enum.
_PRIORITY = {"low": "low", "medium": "normal", "high": "high",
             "urgent": "critical", "critical": "critical"}

# The endpoint's refusal kinds, as documented in
# homelab/services/homelab-harness/README.md §2. Listed so a reader of this file
# knows every shape a refusal can take; the code does not special-case them.
REFUSAL_KINDS = (
    "bad_request", "identity_in_body", "too_large", "needs_decomposition",
    "not_a_request", "unclassifiable", "helper_unavailable",
    "unknown_role", "ineligible", "exhausted", "error",
)


class HomelabAdapter:
    """Run one bounded request through homelab's endpoint on loopback."""

    name = "homelab"

    def __init__(self, *, url: str = ENDPOINT, timeout: float = 300.0):
        # `url` exists for tests, which stand up a stub on another port. Nothing
        # in the Workbench passes it; the project configuration cannot.
        self._url = url
        self._timeout = timeout
        self.last_request_id: str | None = None

    def capabilities(self) -> tuple[str, ...]:
        return ()

    def tools(self) -> tuple[str, ...]:
        return ()

    def build_payload(self, request: Request) -> dict:
        """The endpoint request. Separate so a test can inspect it without a socket."""
        priority = _PRIORITY.get(request.priority)
        if priority is None:
            raise ValueError(f"priority {request.priority!r} has no endpoint equivalent")
        question = request.instructions
        if request.task_summary:
            question = f"{request.task_summary}\n\n{request.instructions}"
        return {
            "v": 1,
            "kind": "question",
            "role": request.agent_role,
            "question": question,
            "context": [{"text": item, "source": None} for item in request.context],
            "capabilities": list(request.capabilities),
            "priority": priority,
            "complexity": request.complexity,
        }

    def execute(self, request: Request) -> Result:
        self.last_request_id = None
        try:
            payload = self.build_payload(request)
        except ValueError as exc:
            return Result(output="", refused=True, reason=f"bad_request: {exc}")

        data = json.dumps(payload).encode("utf-8")
        http = urllib.request.Request(
            self._url, data=data, method="POST",
            headers={"Content-Type": "application/json", "X-Homelab-Client": CLIENT_LABEL},
        )
        try:
            with urllib.request.urlopen(http, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # The endpoint answers every refusal with a JSON body and a 4xx/5xx
            # status; the body is the answer, the status is for humans.
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except ValueError:
                return Result(output="", refused=True,
                              reason=f"endpoint_unreachable: HTTP {exc.code} without a JSON body")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return Result(output="", refused=True, reason=f"endpoint_unreachable: {exc}")

        if not isinstance(body, dict):
            return Result(output="", refused=True, reason="endpoint_unreachable: reply was not an object")
        self.last_request_id = body.get("request_id")

        if body.get("ok") is True and isinstance(body.get("text"), str):
            # cost None, not 0.0: the endpoint reports none for subscription
            # providers and unknown stays unknown (ADR-033).
            return Result(output=body["text"], cost=None, tokens=None, model=body.get("model"))

        kind = body.get("kind") or "error"
        message = body.get("message") or ""
        stage = body.get("stage") or "endpoint"
        return Result(output="", refused=True, model=None,
                      reason=f"{kind}: {message} [{stage}]")
