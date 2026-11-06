"""Project-local object identifiers.

``v0-operating-objects.md`` fixes the shape as ``<PREFIX>-<YEAR>-<NNNN>``, one
file per object. IDs are allocated by scanning the collection directory rather
than by keeping a counter file: a counter is a second source of truth that can
disagree with the filesystem, and recovering from that disagreement is worse
than the scan is slow.
"""

from __future__ import annotations

import re
from pathlib import Path

PREFIXES = {
    "task": "TASK",
    "ticket": "TICKET",
    "run": "RUN",
    "interaction": "INTERACTION",
    "founder_inbox_item": "INBOX",
    "approval": "APPROVAL",
    "context_pack": "CP",
    "review_record": "REVIEW",
    "release": "RELEASE",
    "learning_candidate": "LEARN",
}

_ID_RE = re.compile(r"^(?P<prefix>[A-Z]+)-(?P<year>\d{4})-(?P<seq>\d{4,})$")


def is_valid(object_id: str) -> bool:
    return bool(_ID_RE.match(object_id or ""))


def parse(object_id: str) -> tuple[str, int, int]:
    match = _ID_RE.match(object_id or "")
    if not match:
        raise ValueError(f"not a Factory object id: {object_id!r}")
    return match["prefix"], int(match["year"]), int(match["seq"])


def next_id(collection_dir: Path, object_type: str, year: int) -> str:
    """Allocate the next free id for ``object_type`` in ``collection_dir``.

    Scans existing filenames. Gaps are not reused: a reused id would make two
    different objects share an identifier across git history, which is exactly
    the sort of thing that is discovered much later and cannot be repaired.
    """
    prefix = PREFIXES.get(object_type)
    if prefix is None:
        raise ValueError(f"no id prefix registered for object type {object_type!r}")

    highest = 0
    if collection_dir.is_dir():
        for path in collection_dir.iterdir():
            match = _ID_RE.match(path.stem)
            if match and match["prefix"] == prefix and int(match["year"]) == year:
                highest = max(highest, int(match["seq"]))
    return f"{prefix}-{year}-{highest + 1:04d}"
