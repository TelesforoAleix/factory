"""Planner mutations; all persistence belongs to state.update."""
from .state import StateError


TRANSITIONS = {
    "planned": {"researching", "ready"},
    "researching": {"planned", "ready"},
    "ready": {"planned", "issued"},
    "issued": {"in review", "escalated", "awaiting handover"},
    "awaiting handover": {"in review", "escalated", "awaiting handover"},
    "escalated": {"issued"},
    "in review": {"accepted", "issued"},
    "accepted": set(),
}
KINDS = ("question", "escalation", "merge", "node-step", "owner-check")
FIELDS = ("repo", "feature", "title", "brief", "stop_before_merge", "depends_on")


def new_slice(slice_id):
    return dict(id=slice_id, repo="", feature="", title="", state="planned", brief=None,
                executor={"tool": "codex", "model": "gpt-6.1-sol"}, stop_before_merge=False,
                depends_on=[], slot=None, paused=False, session=None, pr=None,
                attention=None, log=[])


def change_for(args):
    def change(item, data, at):
        if args.command in ("add", "edit"):
            values = {key: getattr(args, key) for key in FIELDS if hasattr(args, key)}
            executor = {key: getattr(args, key) for key in ("tool", "model", "effort") if hasattr(args, key)}
            if hasattr(args, "new_id"):
                values["id"] = args.new_id
            if (args.command == "edit" and item["state"] in ("issued", "awaiting handover")
                    and (set(values) - {"title", "depends_on"} or executor)):
                raise StateError(f"{item['id']} is {item['state']}; only --title and --depends-on may be edited")
            item.update(values)
            item["executor"].update(executor)
        elif args.command == "state":
            target = args.target
            if args.force:
                if target != "planned" or not args.reason or not args.reason.strip():
                    raise StateError("--force requires target planned and a nonempty --reason")
            else:
                if args.reason:
                    raise StateError("--reason requires --force")
                if target not in TRANSITIONS[item["state"]]:
                    raise StateError(f"cannot move {item['id']} from {item['state']} to {target}: transition is not allowed")
            if target == "ready" and item["brief"] is None:
                raise StateError(f"{item['id']} needs a brief before ready")
            if args.session is not None:
                if item["state"] != "ready" or target != "issued" or args.force:
                    raise StateError("--session is only allowed for ready to issued")
                parts = args.session.split(":", 2)
                if len(parts) != 3 or parts[0] not in ("codex", "claude") or not all(parts):
                    raise StateError("--session must be <codex|claude>:<id>:<folder>")
                item["session"] = dict(zip(("tool", "id", "folder"), parts))
            elif item["state"] == "ready" and target == "issued":
                raise StateError("ready to issued requires --session <tool>:<id>:<folder>")
            if target == "planned":
                item["slot"] = None
            item["state"] = target
        elif args.command == "review":
            if not item["attention"] or item["attention"]["kind"] != "merge":
                raise StateError(f"{item['id']} has no merge attention to review")
            item["attention"]["review"] = dict(verdict=args.verdict, at=at,
                                               actor=getattr(args, "actor", "owner"))
            first_line = args.verdict.split("\n", 1)[0].rstrip("\r")
            return f"Reviewed {item['id']}: {first_line}", None
        elif args.command == "attention":
            if args.clear:
                if args.kind is not None or args.body is not None:
                    raise StateError("--clear cannot be combined with --kind or --body")
                item["attention"] = None
            else:
                if args.kind is None or args.body is None:
                    raise StateError("attention requires --kind and --body, or --clear")
                item["attention"] = dict(kind=args.kind, body=args.body, since=at,
                                         answer=None, approved=False)
                return f"Needs attention: {item['id']} ({args.kind}): {args.body}", None
        return None, None
    return change
