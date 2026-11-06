"""Owner and planner commands for the scheduling state file."""
import argparse
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys

from . import state
from . import planner
from .times import LOCAL, parse_when
from .text_bounds import ATTENTION_LIMIT, LOG_LIMIT, cut


ANSWERABLE = ("question", "escalation", "node-step")
COMMANDS = ("slot", "unslot", "start", "pause", "resume", "approve", "answer")


def change_for(command, argument=None):
    def change(item, data, at):
        warning = None
        notice = None
        if command in ("slot", "start"):
            if item["state"] != "ready":
                raise state.StateError(f"{item['id']} is not ready")
            accepted = {s["id"] for s in data["slices"] if s["state"] == "accepted"}
            unmet = [key for key in item["depends_on"] if key not in accepted]
            if unmet:
                warning = "unmet dependencies: " + ", ".join(unmet)
            item["slot"] = at if command == "start" else parse_when(argument)
            notice = f"{'Started' if command == 'start' else 'Slotted'} {item['id']} at {item['slot']}"
        elif command == "unslot":
            item["slot"] = None
        elif command in ("pause", "resume"):
            item["paused"] = command == "pause"
        elif command == "approve":
            if not item["attention"] or item["attention"]["kind"] != "merge":
                raise state.StateError(f"{item['id']} has no merge attention")
            if item["stop_before_merge"] and "review" not in item["attention"]:
                raise state.StateError(f"{item['id']} needs a recorded planner review before approval; use cplane review")
            item["attention"]["approved"] = True
            notice = f"Approved merge for {item['id']}"
        elif command == "answer":
            if not item["attention"] or item["attention"]["kind"] not in ANSWERABLE:
                raise state.StateError(f"{item['id']} has no question, escalation or node-step attention")
            item["attention"]["answer"] = argument
            notice = f"Answered {item['id']}: {argument}"
        else:
            raise state.StateError(f"unknown command: {command}")
        return notice, warning
    return change


def pending(data):
    groups = {key: [] for key in ("needs attention", "scheduled", "ready", "running", "planned")}
    for item in data["slices"]:
        attention = item["attention"]
        unresolved = attention and (
            (attention["kind"] == "merge" and not attention["approved"])
            or (attention["kind"] in ANSWERABLE and attention["answer"] is None)
            or attention["kind"] == "owner-check"
        )
        if item["state"] == "accepted":
            continue
        if unresolved or item["state"] in ("in review", "escalated"):
            key = "needs attention"
        elif item["state"] in ("issued", "awaiting handover"):
            key = "running"
        elif item["slot"]:
            key = "scheduled"
        elif item["state"] == "ready":
            key = "ready"
        else:
            key = "planned"
        groups[key].append(item)
    for key, items in groups.items():
        if key == "scheduled":
            items.sort(key=lambda s: (datetime.fromisoformat(s["slot"]), s["id"]))
        else:
            items.sort(key=lambda s: s["id"])
    return groups


def render(groups):
    lines = []
    for group, items in groups.items():
        lines.append(group)
        day = None
        for item in items:
            prefix = "  "
            if group == "scheduled":
                local = datetime.fromisoformat(item["slot"]).astimezone(LOCAL)
                if local.date() != day:
                    day = local.date()
                    lines.append(f"  {day.isoformat()}")
                prefix = f"    {local.strftime('%H:%M %z')} "
            flags = " [paused]" if item["paused"] else ""
            lines.append(f"{prefix}{item['id']} — {item['title']}{flags}")
        if not items:
            lines.append("  (none)")
    return "\n".join(lines)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, f"cplane: {message}\n")


def parser():
    common = Parser(add_help=False)
    common.add_argument("--state", default=argparse.SUPPRESS, help="state JSON path (or CPLANE_STATE)")
    common.add_argument("--actor", default=argparse.SUPPRESS, help="log actor (default: owner)")
    common.add_argument("--commit", action="store_true", default=argparse.SUPPRESS, help="commit and sync state repository")
    root = Parser(description="A scheduler's state file and its commands", parents=[common])
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    view = commands.add_parser("pending", parents=[common], help="show pending slices")
    view.add_argument("--json", action="store_true", help="output grouped JSON")
    show = commands.add_parser("show", parents=[common], help="show one complete slice")
    show.add_argument("id")
    show.add_argument("--json", action="store_true", help="output slice JSON")
    show.add_argument("--final", action="store_true", help="show the latest final message")
    for command in ("add", "edit"):
        sub = commands.add_parser(command, parents=[common], help=f"{command} a slice")
        if command == "edit":
            sub.add_argument("id")
            sub.add_argument("--id", dest="new_id", default=argparse.SUPPRESS)
        else:
            sub.add_argument("--id", required=True)
        for field in ("repo", "feature", "title", "brief", "model"):
            sub.add_argument(f"--{field}", required=command == "add" and field in ("repo", "feature", "title"), default=argparse.SUPPRESS)
        sub.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max", "ultra"), default=argparse.SUPPRESS)
        sub.add_argument("--tool", choices=("codex", "claude"), default=argparse.SUPPRESS)
        if command == "add":
            sub.add_argument("--role", default="cutter", help="role whose first cli route sets tool, model and effort when neither --tool nor --model is given (read from the local roles-command; default: cutter)")
        sub.add_argument("--stop-before-merge", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS)
        sub.add_argument("--depends-on", nargs="*", action="extend", default=argparse.SUPPRESS, metavar="ID")
    move = commands.add_parser("state", parents=[common], help="move a slice between planning states")
    move.add_argument("id")
    move.add_argument("target", metavar="state")
    move.add_argument("--session")
    move.add_argument("--force", action="store_true")
    move.add_argument("--reason")
    attention = commands.add_parser("attention", parents=[common], help="record or clear attention")
    attention.add_argument("id")
    attention.add_argument("--kind", choices=planner.KINDS)
    attention.add_argument("--body")
    attention.add_argument("--clear", action="store_true")
    review = commands.add_parser("review", parents=[common], help="record a planner review of merge attention")
    review.add_argument("id")
    review.add_argument("verdict")
    helps = {"slot": "schedule a ready slice", "unslot": "clear a slot", "start": "slot a ready slice now", "pause": "set paused", "resume": "clear paused", "approve": "approve merge attention", "answer": "answer a question, escalation or node step"}
    for command in COMMANDS:
        sub = commands.add_parser(command, parents=[common], help=helps[command])
        sub.add_argument("id")
        if command in ("slot", "answer"):
            sub.add_argument("value", metavar="when" if command == "slot" else "text")
    commands.add_parser("compact", parents=[common], help="bound oversized runner text in state")
    for command in ("run", "install-agent", "uninstall-agent"):
        commands.add_parser(command, parents=[common])
    commands.add_parser("prime", parents=[common], help="send one minimal request to Claude and Codex to start their usage windows")
    commands.add_parser("install-primer", parents=[common], help="install the launchd job that runs prime at 06:00, 11:00, 16:00 and 21:00")
    commands.add_parser("uninstall-primer", parents=[common], help="remove the primer launchd job")
    commands.add_parser("primer-wake-plist", parents=[common], help="print the root wake-schedule LaunchDaemon plist; never installs it")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command in ("prime", "install-primer", "uninstall-primer", "primer-wake-plist"):
            from . import primer
            if args.command == "prime":
                return 0 if primer.prime() else 1
            if args.command == "install-primer":
                primer.install()
            elif args.command == "uninstall-primer":
                primer.uninstall()
            else:
                print(primer.wake_plist(), end="")
            return 0
        if args.command == "uninstall-agent":
            from .agent import uninstall
            uninstall()
            return 0
        path = getattr(args, "state", None) or os.environ.get("CPLANE_STATE")
        if not path:
            raise state.StateError("provide --state or CPLANE_STATE")
        path = Path(path).expanduser()
        if args.command == "install-agent":
            from .agent import install
            install(path.resolve(), commit=getattr(args, "commit", False))
        elif args.command == "run":
            from .runner import Runner
            Runner(path).run()
        elif args.command == "compact":
            path = path.resolve()
            with Path(str(path) + ".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                before = path.stat().st_size
                data = state.load(path)
                logs = attentions = 0
                for item in data["slices"]:
                    for entry in item["log"]:
                        event = entry["event"]
                        if len(event) > LOG_LIMIT:
                            entry["event"] = cut(event, LOG_LIMIT)
                            logs += 1
                    attention = item["attention"]
                    if attention and len(attention["body"]) > ATTENTION_LIMIT:
                        attention["body"] = cut(attention["body"], ATTENTION_LIMIT)
                        attentions += 1
                if logs or attentions:
                    state.save(path, data)
                    if getattr(args, "commit", False):
                        state.commit_state(path, Path(str(path) + ".outbox.jsonl"), "compact", "state")
                after = path.stat().st_size
            print(f"cut {logs} log entries and {attentions} attention bodies; size {before} -> {after} bytes")
        elif args.command == "pending":
            groups = pending(state.load(path))
            print(json.dumps(groups, indent=2, ensure_ascii=False) if args.json else render(groups))
        elif args.command == "show":
            item = next((item for item in state.load(path)["slices"] if item["id"] == args.id), None)
            if item is None:
                raise state.StateError(f"unknown slice: {args.id}")
            base = Path(os.environ.get('CPLANE_RUNS', '~/Library/Application Support/cplane/runs')).expanduser().resolve()
            runs = base / hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:20]
            latest = None
            for job_path in runs.glob('*/job.json'):
                try:
                    job = json.loads(job_path.read_text())
                except (OSError, ValueError):
                    continue
                if job.get('id') == args.id and (latest is None or job.get('started_ns', 0) > latest[0]):
                    latest = (job.get('started_ns', 0), job_path.parent, job)
            if args.final:
                if latest is None:
                    print('final: unavailable (no run recorded)')
                else:
                    job = latest[2]
                    final = job.get('final')
                    last = latest[1] / ('last.json' if job.get('tool') == 'codex' else 'claude.json')
                    if not final and last.exists():
                        try:
                            reply = json.loads(last.read_text())
                            final = reply if job.get('tool') == 'codex' else reply.get('structured_output')
                        except (OSError, ValueError, AttributeError):
                            final = None
                    if isinstance(final, dict) and isinstance(final.get('kind'), str) and isinstance(final.get('body'), str):
                        print(f"kind: {final['kind']}\nbody: {final['body']}")
                    else:
                        print('final: unavailable')
            elif args.json:
                print(json.dumps(item, indent=2, ensure_ascii=False))
            else:
                details = "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in item.items())
                folder = str(latest[1]) if latest else '(none)'
                print(details + f'\nrun: {folder}')
        elif args.command in ("add", "edit", "state", "attention", "review"):
            event = note = None
            if args.command == "add" and not hasattr(args, "tool") and not hasattr(args, "model"):
                from . import roles
                route, why = roles.lookup(args.role, roles.command_file())
                if route is None:
                    note = f"roles: {why}; using built-in defaults"
                else:
                    args.tool, args.model = route["tool"], route["model"]
                    if "effort" in route and not hasattr(args, "effort"):
                        args.effort = route["effort"]
            if args.command == "state":
                event = f"state: {args.target}"
                if args.force:
                    event += f" (forced: {args.reason})"
            state.update(path, args.id, args.command, getattr(args, "actor", "owner"),
                         planner.change_for(args), getattr(args, "commit", False),
                         create=(lambda: planner.new_slice(args.id)) if args.command == "add" else None,
                         event=event)
            if note:
                print(note, file=sys.stderr)
        else:
            warning = state.update(path, args.id, args.command, getattr(args, "actor", "owner"), change_for(args.command, getattr(args, "value", None)), getattr(args, "commit", False))
            if warning:
                print(f"warning: {warning}", file=sys.stderr)
        return 0
    except (state.StateError, OSError, ValueError) as error:
        print("cplane: " + " ".join(str(error).splitlines()), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
