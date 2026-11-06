"""Choose the configured adapter by name (Phase 23.0, 23.0 brief §6.6).

One key in ``ops/project.json`` — ``"adapter": "fake" | "homelab"`` — and a
default of ``fake``, so a project that never asked for a real backend never
gets one. Nothing else is configurable here: the homelab adapter's URL is fixed
in its own module because loopback is not a per-project choice.
"""

from __future__ import annotations

from workbench.errors import ValidationError

ADAPTERS = ("fake", "homelab")
DEFAULT = "fake"


def make_adapter(name: str):
    if name == "fake":
        from workbench.adapters.fake import FakeAdapter
        return FakeAdapter()
    if name == "homelab":
        from workbench.adapters.homelab import HomelabAdapter
        return HomelabAdapter()
    raise ValidationError(
        f"unknown adapter {name!r} in project.json; expected one of {', '.join(ADAPTERS)}"
    )
