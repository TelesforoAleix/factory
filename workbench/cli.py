"""The command-line surface.

A surface, not an implementation: every command here resolves to a call on
:class:`workbench.engine.Engine`. The local server is a second surface over the
same engine, and ADR-036's validation requires that a write issued through
either produces byte-identical ``ops/`` output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from workbench import agents as agents_module
from workbench import audit, project, records, schema
from workbench.engine import Engine
from workbench.errors import WorkbenchError
from workbench.identity import human


def _engine(args) -> Engine:
    proj = project.open_project(Path(args.project))
    return Engine(proj, actor=human(args.actor, proj.project_id))


def cmd_init(args) -> int:
    proj = project.create(Path(args.path), project_id=args.project_id, title=args.title)
    print(f"created project {proj.project_id} at {proj.root}")
    print(f"  ops/            {len(schema.MINIMUM_COLLECTIONS)} collections")
    print(f"  agents/         references Factory (ADR-028: reference, not copy)")
    return 0


def cmd_create(args) -> int:
    fields = json.loads(args.fields) if args.fields else {}
    if args.title:
        fields["title"] = args.title
    record = _engine(args).create(args.type, fields)
    print(f"created {record['id']}")
    return 0


def cmd_update(args) -> int:
    record = _engine(args).update(args.id, json.loads(args.changes))
    print(f"updated {record['id']}")
    return 0


def cmd_status(args) -> int:
    record = _engine(args).set_status(args.id, args.status)
    print(f"{record['id']} -> {record['status']}")
    return 0


def cmd_show(args) -> int:
    proj = project.open_project(Path(args.project))
    record = records.find(proj.ops, args.id)
    print(json.dumps({k: v for k, v in record.items() if k != "_path"}, indent=2, default=str))
    return 0


def cmd_list(args) -> int:
    proj = project.open_project(Path(args.project))
    found = records.load_collection(proj.ops, args.type)
    if not found:
        print(f"no {args.type} records")
        return 0
    for record in found:
        print(f"{record.get('id'):<24} {record.get('status',''):<16} {record.get('title','')}")
    return 0


def cmd_approve(args) -> int:
    approval = _engine(args).grant_approval(args.id)
    print(f"approved {approval['id']} — bound to {approval['bound_action']} "
          f"on {approval['bound_target']}")
    return 0


def cmd_roster_add(args) -> int:
    _engine(args).add_to_roster(args.agent, scope=args.scope)
    print(f"added {args.agent} to the roster ({args.scope}-scoped)")
    return 0


def cmd_validate(args) -> int:
    proj = project.open_project(Path(args.project))
    problems: list[str] = []
    for object_type in schema.SCHEMAS:
        for record in records.load_collection(proj.ops, object_type):
            for problem in schema.validate(record):
                problems.append(f"{Path(record['_path']).name}: {problem}")
    problems += [f"link: {p}" for p in records.check_links(proj.ops)]
    problems += [f"audit: {p}" for p in audit.verify(proj.ops)]

    if problems:
        print(f"{len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("ops/ is valid: records, links and audit chain all check out")
    return 0


def cmd_audit(args) -> int:
    proj = project.open_project(Path(args.project))
    for entry in audit.read(proj.ops):
        mark = "REFUSED" if entry["outcome"] == "refused" else "ok"
        print(f"{entry['timestamp']}  {mark:<8} {entry['action']:<18} "
              f"{entry['target']:<24} {entry['actor']}")
        if entry["outcome"] == "refused":
            print(f"    reason: {entry['detail'].get('reason','')}")
    return 0


def cmd_serve(args) -> int:
    from workbench.server import serve
    serve(Path(args.project), host=args.host, port=args.port, actor=args.actor)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="factory", description="Factory Workbench")
    parser.add_argument("--project", default=".", help="project root or its ops/ directory")
    parser.add_argument("--actor", default="owner", help="who is acting")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a project and its minimum ops/")
    p.add_argument("path"); p.add_argument("--project-id", required=True)
    p.add_argument("--title", default="Untitled project"); p.set_defaults(func=cmd_init)

    p = sub.add_parser("create", help="create a record")
    p.add_argument("type", choices=sorted(schema.SCHEMAS))
    p.add_argument("--title"); p.add_argument("--fields", help="JSON object of fields")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("update", help="update a record")
    p.add_argument("id"); p.add_argument("changes", help="JSON object of changes")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("status", help="set a record's status")
    p.add_argument("id"); p.add_argument("status"); p.set_defaults(func=cmd_status)

    p = sub.add_parser("show", help="print one record"); p.add_argument("id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("list", help="list a collection")
    p.add_argument("type", choices=sorted(schema.SCHEMAS)); p.set_defaults(func=cmd_list)

    p = sub.add_parser("approve", help="grant an approval (humans only)")
    p.add_argument("id"); p.set_defaults(func=cmd_approve)

    p = sub.add_parser("roster-add", help="add an agent to the project roster")
    p.add_argument("agent"); p.add_argument("--scope", default="team", choices=("task", "team"))
    p.set_defaults(func=cmd_roster_add)

    p = sub.add_parser("validate", help="check records, links and the audit chain")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("audit", help="print the audit trail")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("serve", help="run the local dashboard server")
    p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except WorkbenchError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
