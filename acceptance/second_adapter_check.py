#!/usr/bin/env python3
"""The second-adapter check — Phase 20.0 brief §8.1.3, run by Phase 23.0.

> ADR-035's second-adapter check — the same project runs on a second adapter
> **without its records changing**. This is what distinguishes a real
> abstraction from one implementation with an interface drawn around it.

Two scratch copies of a project are made from one source. One is configured
``"adapter": "fake"``, the other ``"adapter": "homelab"``. The same item gets the
same agent and the same question-shaped objective in both; the agent is added to
the roster in both; ``run`` is executed through the CLI in both. Then every file
under ``ops/`` and ``agents/`` is compared.

What is ALLOWED to differ, and nothing else:

* ``ops/project.json``: the ``adapter`` key (that is the configuration).
* ``ops/runs/RUN-*.json``: the ``Result`` fields the adapter fills -- ``output``,
  ``model``, ``cost``, ``tokens``, ``refused``, ``reason`` -- plus ``adapter`` (the
  backend's name) and ``request_id`` (the endpoint's correlation id; the fake has
  none).
* ``ops/audit/audit.jsonl``: per entry, ``detail.backend``, ``detail.model`` and
  ``detail.reason``.
* Timestamps and audit hashes everywhere: they differ between any two runs and
  say nothing about the adapter. They are normalised before comparing -- as is
  the scratch copy's own directory in the absolute paths the audit records.

Any other difference means a backend concept leaked into a record, and the
verdict is "not proved" with the diff. The verdict sentence is printed verbatim
in one of the two forms the 23.0 brief asks for.

Usage:
  python3 acceptance/second_adapter_check.py --source /path/to/factory-ops \\
      --item TASK-2026-0001 --agent execution-agent \\
      --objective "What is the difference between a socket unit and a service unit?"

The homelab side must be listening on 127.0.0.1:8766 -- on the MacBook, homelab's
``services/homelab-harness/dev-stub.py``; on the node, the real endpoint.
Exit 0 when proved; 1 otherwise.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

TS_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z")
HASH_RE = re.compile(r"\b[0-9a-f]{64}\b")

CHECK_TICKET = "TICKET-2026-9001"   # well clear of the legacy range

ALLOWED_RUN_FIELDS = {"output", "model", "cost", "tokens", "refused", "reason", "adapter", "request_id"}
ALLOWED_AUDIT_DETAIL = {"backend", "model", "reason"}


def cli(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "workbench.cli", "--project", str(project),
                           "--actor", "aleix", *args],
                          cwd=str(REPO), capture_output=True, text=True)


def prepare(source: Path, dest: Path, *, adapter: str, item: str, agent: str, objective: str) -> None:
    for sub in ("ops", "agents"):
        shutil.copytree(source / sub, dest / sub)
    (dest / "product").mkdir(exist_ok=True)
    meta = dest / "ops" / "project.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["adapter"] = adapter
    meta.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    # The item: same agent, same question-shaped objective, in both copies. Done
    # through the CLI so the record is written the way the Workbench writes it.
    #
    # A NEW ticket, not an update of a legacy one. OBSERVED 2026-09-13 (Phase 23.0
    # S3): `update` on a record whose file carries a slug suffix
    # (TICKET-2026-0002-core-agent-specs.yaml) writes TICKET-2026-0002.yaml beside
    # it -- records.path_for() derives the path from the id alone -- and find()
    # then returns the legacy file, so the update is silently invisible. A
    # Workbench defect against legacy records, reported in the 23.0 handover, not
    # fixed here. `item` names the task the new ticket belongs to.
    #
    # And an EXPLICIT id, for the sibling defect (OBSERVED the same day): ids.next_id()
    # matches stems against ^PREFIX-YEAR-SEQ$, so slug-suffixed legacy files are
    # invisible to it and it allocates TICKET-2026-0001 -- a duplicate of a legacy
    # id. Both go with the 18.2 legacy-records finding.
    r = cli(dest, "create", "ticket", "--title", "Second-adapter check",
            "--fields", json.dumps({"id": CHECK_TICKET, "task_id": item, "objective": objective,
                                    "acceptance_criteria": ["the run records an answer"],
                                    "assigned_agent": agent, "priority": "medium",
                                    "status": "assigned"}))
    r.check_returncode()
    r = cli(dest, "roster-add", agent)
    r.check_returncode()


ROOTS: list[str] = []   # the two scratch roots; the audit records absolute paths


def normalise(text: str) -> str:
    # The Workbench audits the absolute path of every record it writes
    # (engine.create -> detail.path). Between two scratch copies that path
    # differs by the copy's directory name and nothing else -- the check's own
    # layout, not the adapter -- so both roots become "<root>".
    for root in ROOTS:
        text = text.replace(root, "<root>")
    return HASH_RE.sub("<hash>", TS_RE.sub("<ts>", text))


def strip_allowed(rel: str, text: str) -> str:
    """Remove the fields the adapter is allowed to fill, so what remains must be identical."""
    if rel == "ops/project.json":
        data = json.loads(text)
        data.pop("adapter", None)
        return json.dumps(data, indent=2, sort_keys=True)
    if rel.startswith("ops/runs/") and rel.endswith(".json"):
        data = json.loads(text)
        for k in ALLOWED_RUN_FIELDS:
            data.pop(k, None)
        return json.dumps(data, indent=2, sort_keys=True)
    if rel == "ops/audit/audit.jsonl":
        out = []
        for line in text.splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            detail = entry.get("detail") or {}
            for k in ALLOWED_AUDIT_DETAIL:
                detail.pop(k, None)
            for k in ("hash", "prev_hash", "timestamp"):
                entry.pop(k, None)
            out.append(json.dumps(entry, sort_keys=True))
        return "\n".join(out)
    return text


def snapshot(root: Path) -> dict[str, str]:
    files = {}
    for sub in ("ops", "agents"):
        for p in sorted((root / sub).rglob("*")):
            if p.is_file():
                files[str(p.relative_to(root))] = p.read_text(encoding="utf-8")
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--item", required=True, help="the TASK the check's new ticket belongs to")
    ap.add_argument("--agent", default="execution-agent")
    ap.add_argument("--objective", required=True)
    ap.add_argument("--keep", action="store_true", help="keep the scratch copies")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="second-adapter-"))
    copies = {}
    for adapter in ("fake", "homelab"):
        dest = work / adapter
        ROOTS.append(str(dest.resolve()))
        ROOTS.append(str(dest))
        prepare(args.source, dest, adapter=adapter, item=args.item, agent=args.agent,
                objective=args.objective)
        r = cli(dest, "run", CHECK_TICKET)
        print(f"--- run on {adapter} (rc={r.returncode})")
        print(r.stdout.rstrip())
        if r.stderr.strip():
            print(r.stderr.rstrip())
        if r.returncode != 0:
            print(f"\nrun on {adapter} did not complete; the check cannot proceed.")
            return 1
        copies[adapter] = snapshot(dest)

    fake, home = copies["fake"], copies["homelab"]
    if set(fake) != set(home):
        print("\nFILE SETS DIFFER:", sorted(set(fake) ^ set(home)))
        print("the adapter interface is not proved, because the two runs wrote different files")
        return 1

    print("\n=== raw differences (timestamps and hashes normalised) -- for the handover ===")
    raw_diff_files = []
    for rel in sorted(fake):
        a, b = normalise(fake[rel]).splitlines(), normalise(home[rel]).splitlines()
        if a != b:
            raw_diff_files.append(rel)
            for line in difflib.unified_diff(a, b, f"fake/{rel}", f"homelab/{rel}", lineterm="", n=0):
                print(line)
    if not raw_diff_files:
        print("(none)")

    print("\n=== residual differences after removing the fields the adapter may fill ===")
    leaks = []
    for rel in sorted(fake):
        a = normalise(strip_allowed(rel, fake[rel])).splitlines()
        b = normalise(strip_allowed(rel, home[rel])).splitlines()
        if a != b:
            leaks.append(rel)
            for line in difflib.unified_diff(a, b, f"fake/{rel}", f"homelab/{rel}", lineterm="", n=0):
                print(line)
    if not leaks:
        print("(none)")

    print(f"\nscratch copies: {work}" + ("" if args.keep else " (removed)"))
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)

    print()
    if leaks:
        print("the adapter interface is not proved, because these records changed beyond the "
              f"Result fields: {', '.join(leaks)}")
        return 1
    print("the adapter interface is proved")
    print(f"(files that differed only in Result fields, the adapter name, the request id, "
          f"or the project's adapter key: {', '.join(raw_diff_files) or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
