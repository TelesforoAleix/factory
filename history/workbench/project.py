"""Project lifecycle: open an existing project, or create one.

A project is a directory containing ``ops/``. Workbench is pointed at either the
project root or the ``ops/`` directory itself and works out which it was given —
the design review asked for both, and guessing wrong is cheap to detect.

``agents/`` in a project **references** Factory's catalogue rather than copying
it (ADR-028). Factory's own ``design/project-workspace-layout.md`` calls it a
"synced copy"; that document predates ADR-028 and the ADR wins. A copy forks
silently; a reference breaks loudly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from workbench import schema
from workbench.errors import ValidationError

PROJECT_FILE = "project.json"


@dataclass(frozen=True)
class Project:
    root: Path
    ops: Path
    project_id: str
    # Which execution adapter `run` uses (Phase 23.0). Read from project.json's
    # "adapter" key; absent means "fake" -- a project gets a real backend only
    # by saying so.
    adapter: str = "fake"

    @property
    def agents_ref(self) -> Path:
        return self.root / "agents" / "factory-ref.json"


def locate(path: Path) -> tuple[Path, Path]:
    """Given a project root or its ``ops/``, return ``(root, ops)``."""
    path = path.expanduser().resolve()
    if path.name == "ops" and path.is_dir():
        return path.parent, path
    if (path / "ops").is_dir():
        return path, path / "ops"
    raise ValidationError(
        f"{path} is not a Factory project: expected an 'ops/' directory here or to be given one"
    )


def open_project(path: Path) -> Project:
    root, ops = locate(path)
    meta_path = ops / PROJECT_FILE
    if not meta_path.is_file():
        raise ValidationError(f"{ops} has no {PROJECT_FILE}; it is not an initialised project")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    project_id = meta.get("project_id")
    if not project_id:
        raise ValidationError(f"{meta_path} has no project_id")
    adapter = meta.get("adapter", "fake")
    if adapter not in ("fake", "homelab"):
        raise ValidationError(f"{meta_path}: adapter must be 'fake' or 'homelab', not {adapter!r}")
    return Project(root=root, ops=ops, project_id=project_id, adapter=adapter)


def create(root: Path, *, project_id: str, title: str, factory_ref: str = "..") -> Project:
    """Create a project and the minimum valid ``ops/`` (acceptance step 3).

    Creates every collection directory rather than only the ones used so far: a
    reader who opens the project should be able to see its shape, and an empty
    directory is a cheaper way to say "reviews go here" than documentation is.
    """
    root = root.expanduser().resolve()
    ops = root / "ops"
    if (ops / PROJECT_FILE).exists():
        raise ValidationError(f"{root} already contains an initialised project")

    for collection in schema.MINIMUM_COLLECTIONS:
        (ops / collection).mkdir(parents=True, exist_ok=True)
        keep = ops / collection / ".gitkeep"
        if not any(p for p in (ops / collection).iterdir()):
            keep.write_text("", encoding="utf-8")

    (ops / PROJECT_FILE).write_text(
        json.dumps({"project_id": project_id, "title": title,
                    "workbench_version": "0.1.0"}, indent=2) + "\n",
        encoding="utf-8",
    )

    agents_dir = root / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "factory-ref.json").write_text(
        json.dumps(
            {
                "_comment": "A reference to Factory's catalogue, not a copy (ADR-028). "
                            "A copy forks silently; a reference breaks loudly.",
                "factory_path": factory_ref,
                "roster": [],
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    (root / "product").mkdir(parents=True, exist_ok=True)
    return Project(root=root, ops=ops, project_id=project_id)
