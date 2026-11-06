"""Agent definitions: portable capabilities, optional concrete tools (ADR-034).

> Factory agents declare portable capabilities. Execution backends provide
> concrete tools.

Two separate fields, deliberately (ADR-034 §4). ``capabilities`` is what a
reusable catalogue agent declares; ``tools`` names exact backend-specific tools
and is how a user says "portability is not wanted here". Merging them would make
that distinction invisible in a diff.

``model_policy`` is **removed**. An agent's *role* is its declaration of need —
see ADR-034 §5, which preserves ADR-026 §4 while changing its form.

Manifests are JSON (ADR-031 §11).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from workbench.errors import CapabilityUnsupported, ValidationError

# A field whose presence means the manifest predates ADR-034.
REMOVED_FIELDS = ("model_policy",)


@dataclass(frozen=True)
class Agent:
    name: str
    role: str
    version: str = "0.1.0"
    context: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    unattended: bool = False
    description: str = ""

    def digest(self) -> str:
        """Content digest, so a work item can pin the exact definition used.

        ADR-034 §12: definitions are live, tasks are pinned. An upskilled agent
        takes effect for its *next* task; this is what lets a completed task say
        which version actually ran.
        """
        import hashlib
        payload = json.dumps(
            {
                "name": self.name, "role": self.role, "version": self.version,
                "context": list(self.context), "skills": list(self.skills),
                "capabilities": list(self.capabilities), "tools": list(self.tools),
                "unattended": self.unattended,
            },
            sort_keys=True, separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def parse(data: dict, *, source: str = "<memory>") -> Agent:
    problems = []
    for key in ("agent", "role"):
        if not data.get(key):
            problems.append(f"missing required field {key!r}")

    for removed in REMOVED_FIELDS:
        if removed in data:
            problems.append(
                f"field {removed!r} was removed by ADR-034 §5 — an agent's role is its "
                f"declaration of need, and agents never name a model or a tier"
            )

    if problems:
        raise ValidationError(f"agent manifest {source} is not valid", problems)

    return Agent(
        name=data["agent"],
        role=data["role"],
        version=str(data.get("version", "0.1.0")),
        context=tuple(data.get("context") or ()),
        skills=tuple(data.get("skills") or ()),
        capabilities=tuple(data.get("capabilities") or ()),
        tools=tuple(data.get("tools") or ()),
        unattended=bool(data.get("unattended", False)),
        description=data.get("description", ""),
    )


def load(path: Path) -> Agent:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path.name} is not valid JSON: {exc}") from exc
    return parse(data, source=path.name)


def load_catalogue(directory: Path) -> dict[str, Agent]:
    """Load every manifest in a directory.

    One bad manifest fails **that manifest**, not the catalogue: refusing to
    load anything because one file is malformed turns a typo into an outage.
    The caller decides what to do with the collected problems.
    """
    catalogue: dict[str, Agent] = {}
    if not directory.is_dir():
        return catalogue
    for path in sorted(directory.glob("*.json")):
        agent = load(path)
        catalogue[agent.name] = agent
    return catalogue


def check_compatibility(agent: Agent, backend) -> None:
    """Refuse activation unless the backend advertises everything required.

    ADR-034 §6: checked **before activation**, and it names *every* missing
    requirement rather than the first. "Load now, discover refusal at dispatch"
    is explicitly rejected — it starts work that cannot finish.
    """
    advertised_capabilities = set(backend.capabilities())
    advertised_tools = set(backend.tools())

    missing = [f"capability:{c}" for c in agent.capabilities if c not in advertised_capabilities]
    missing += [f"tool:{t}" for t in agent.tools if t not in advertised_tools]

    if missing:
        raise CapabilityUnsupported(
            f"backend {backend.name!r} cannot activate agent {agent.name!r}; missing",
            sorted(missing),
        )
