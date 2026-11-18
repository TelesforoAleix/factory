"""Planner mutations; all persistence belongs to state.update."""
from . import state
from .state import StateError

TRANSITIONS = {
    "planned": {"researching", "ready"},
    "researching": {"planned", "ready"},
    "ready": {"planned", "issued"},
    "issued": {"in review", "escalated", "awaiting handover"},
    "awaiting handover": {"in review", "escalated", "awaiting handover"},
    "escalated": {"issued", "ready"},
    "in review": {"accepted", "issued"},
    "accepted": set(),
    "dropped": set(),
}
for _source in TRANSITIONS.keys() - {"accepted", "dropped"}:
    TRANSITIONS[_source].add("dropped")

KINDS = ("question", "escalation", "merge", "node-step", "owner-check")
FIELDS = ("flow", "repo", "feature", "feature_id", "no_feature", "title", "brief", "stop_before_merge", "depends_on")


def new_slice(slice_id):
    return {"id": slice_id, "repo": "", "feature": "", "title": "", "state": "planned", "brief": None,
                "executor": {"tool": "codex", "model": "gpt-6.1-sol"}, "stop_before_merge": False,
                "depends_on": [], "slot": None, "paused": False, "session": None, "pr": None,
                "attention": None, "log": []}


def change_for(args):
    def change(item, data, at):
        if args.command in ("add", "edit"):
            values = {key: getattr(args, key) for key in FIELDS if hasattr(args, key)}
            level = getattr(args, 'level', None)
            if hasattr(args, "new_id"):
                values["id"] = args.new_id
            if (args.command == "edit" and item["state"] in ("issued", "awaiting handover")
                    and (set(values) - {"title", "depends_on"} or level is not None)):
                raise StateError(f"{item['id']} is {item['state']}; only --title and --depends-on may be edited")
            if 'no_feature' in values:
                from .features import bounded
                bounded(values['no_feature'], 'No-feature reason')
            feature_id = values.get('feature_id', item.get('feature_id')) if 'no_feature' not in values else None
            if feature_id:
                if not state.postgres():
                    raise StateError('Validating feature_id requires Postgres (CPLANE_DATABASE_URL)')
                # Runs inside state.update's locked transaction; keep the supplied alias.
                state.store(None)._feature(feature_id)
            if 'no_feature' in values:
                item.pop('feature_id', None)
            elif 'feature_id' in values:
                if not values['feature_id']:
                    raise StateError('Removing a feature requires --no-feature REASON')
                item.pop('no_feature', None)
            if not values.get('feature_id', item.get('feature_id')) and not values.get('no_feature', item.get('no_feature')):
                raise StateError('A slice requires --feature-id or --no-feature REASON')
            if item.get('brief_id') and set(values) & {'brief', 'id', 'repo', 'feature_id', 'no_feature'}:
                raise StateError('Stored brief identity and repository are immutable; create a new slice')
            if state.postgres() and (args.command == 'add' or level is not None or 'id' in values):
                backend = state.store(None)
                policy = backend.slice_policy(item['id'])
                selected_level = level or (policy['level'] if policy else 'standard')
                backend.slice_level(values.get('id', item['id']), selected_level)
                if values.get('id') and values['id'] != item['id']:
                    backend.connection.execute('DELETE FROM cplane_slice_levels WHERE slice_id = %s', (item['id'],))
            elif level is not None:
                # v1 documents have no level field. File-backed synthetic use
                # records the selection on the normal validated mutation log.
                item['log'].append({"at": at, "actor": getattr(args, 'actor', 'owner'), "event": 'level: ' + level})
            item.update(values)
        elif args.command == "state":
            target = args.target
            if item["state"] == "dropped":
                raise StateError(f"{item['id']} is dropped and cannot transition")
            if args.force:
                if target != "planned" or not args.reason or not args.reason.strip():
                    raise StateError("--force requires target planned and a nonempty --reason")
            else:
                if args.reason:
                    raise StateError("--reason requires --force")
                if target not in TRANSITIONS[item["state"]]:
                    raise StateError(f"cannot move {item['id']} from {item['state']} to {target}: transition is not allowed")
            if target == "dropped" and item["state"] in ("issued", "awaiting handover") and not item["paused"]:
                raise StateError(f"{item['id']} must be paused before dropping")
            if target == "ready" and item["brief"] is None and not item.get("brief_id"):
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
            if item["state"] == "escalated" and target == "ready":
                item["log"].append({"at": at, "actor": getattr(args, "actor", "owner"),
                                    "event": "restart requested: " + ((item.get("session") or {}).get("id") or "")})
            item["state"] = target
        elif args.command == "review":
            if not item["attention"] or item["attention"]["kind"] != "merge":
                raise StateError(f"{item['id']} has no merge attention to review")
            item["attention"]["review"] = {"verdict": args.verdict, "at": at,
                                               "actor": getattr(args, "actor", "owner")}
            first_line = args.verdict.split("\n", 1)[0].rstrip("\r")
            return f"Reviewed {item['id']}: {first_line}", None
        elif args.command == "attention":
            if args.recipient is not None:
                if args.clear or args.kind is not None or args.body is not None:
                    raise StateError("--for cannot be combined with --clear, --kind or --body")
                attention = item["attention"]
                if (not attention or attention["kind"] not in ("merge", "node-step", "question", "escalation")
                        or (attention["kind"] == "merge" and attention["approved"])
                        or (attention["kind"] != "merge" and attention["answer"] is not None)):
                    raise StateError(f"{item['id']} has no open attention")
                attention["for"] = args.recipient
                return f"Attention recipient: {item['id']} ({args.recipient})", None
            if args.clear:
                if args.kind is not None or args.body is not None:
                    raise StateError("--clear cannot be combined with --kind or --body")
                item["attention"] = None
            else:
                if args.kind is None or args.body is None:
                    raise StateError("attention requires --kind and --body, or --clear")
                item["attention"] = {"kind": args.kind, "body": args.body, "since": at,
                                         "answer": None, "approved": False}
                return f"Needs attention: {item['id']} ({args.kind}): {args.body}", None
        return None, None
    return change
