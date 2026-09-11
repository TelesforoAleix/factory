"""The audit trail: every write, with actor, time, target and previous hash.

Factory's own ``DASH-405`` asked for *"audit trail and rollback/previous-hash
metadata for mutations"*. This is that.

The trail is append-only JSONL under ``ops/audit/``. It is **not** the source of
truth — git is — but it answers "what did Workbench do, in what order, on whose
behalf" without requiring anyone to read a commit graph, and it records actions
that never reached a commit at all, refusals included.

The previous-hash chain means a deleted or edited entry is detectable. It is not
tamper-*proof*: anyone who can write the file can recompute the chain. It makes
accidental loss visible, which is the threat that actually occurs here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _canonical(entry: dict) -> bytes:
    return json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")


def entry_hash(entry: dict) -> str:
    without_own_hash = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(_canonical(without_own_hash)).hexdigest()


def _log_path(ops_dir: Path) -> Path:
    return ops_dir / "audit" / "audit.jsonl"


def read(ops_dir: Path) -> list[dict]:
    path = _log_path(ops_dir)
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def append(ops_dir: Path, *, actor: str, action: str, target: str,
           outcome: str = "applied", detail: dict | None = None) -> dict:
    """Append one entry and return it.

    ``outcome`` is ``applied`` or ``refused``. **Refusals are recorded too** —
    a trail that only shows successes cannot answer "did anyone try", which is
    the question an audit trail exists for.
    """
    existing = read(ops_dir)
    previous = existing[-1]["hash"] if existing else GENESIS
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "actor": actor,
        "action": action,
        "target": target,
        "outcome": outcome,
        "detail": detail or {},
        "previous_hash": previous,
    }
    entry["hash"] = entry_hash(entry)

    path = _log_path(ops_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def verify(ops_dir: Path) -> list[str]:
    """Check the hash chain. Empty list means intact."""
    problems = []
    previous = GENESIS
    for index, entry in enumerate(read(ops_dir)):
        if entry.get("previous_hash") != previous:
            problems.append(f"entry {index} ({entry.get('action')}): previous_hash does not chain")
        if entry.get("hash") != entry_hash(entry):
            problems.append(f"entry {index} ({entry.get('action')}): hash does not match content")
        previous = entry.get("hash")
    return problems
