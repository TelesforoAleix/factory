"""Owner and planner commands for the scheduling state file."""
import argparse
from datetime import datetime, date, timedelta, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import subprocess

from . import state
from . import planner
from .eligibility import eligibility, observed, satisfied
from .times import LOCAL, parse_when
from .text_bounds import ATTENTION_LIMIT, LOG_LIMIT, cut


ANSWERABLE = ("question", "escalation", "node-step")
COMMANDS = ("slot", "unslot", "start", "pause", "resume", "approve", "answer", "install")


def change_for(command, argument=None):
    def change(item, data, at):
        warning = None
        notice = None
        if command in ("slot", "start"):
            if item["state"] != "ready":
                raise state.StateError(f"{item['id']} is not ready")
            completed = {s["id"] for s in data["slices"] if satisfied(s)}
            unmet = [key for key in item["depends_on"] if key not in completed]
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
        elif command == "install":
            from .installation import request_change
            return request_change(argument or "owner")(item, data, at)
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
        if item["state"] in ("accepted", "dropped"):
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
    digest_parser = commands.add_parser('digest', parents=[common], help='print the daily digest')
    digest_parser.add_argument('--date', help='local date of the 07:00 digest (YYYY-MM-DD)')
    chat = commands.add_parser('chat', parents=[common], help='manage Postgres chats')
    chats = chat.add_subparsers(dest='chat_command', required=True, parser_class=Parser)
    for name in ('list', 'open', 'read', 'unread', 'project', 'configure', 'defaults', 'archive', 'unarchive'):
        sub = chats.add_parser(name, parents=[common])
        if name == 'list':
            sub.add_argument('--kind', choices=('orchestrator', 'project', 'feature', 'legacy', 'secretary'))
            sub.add_argument('--project')
            sub.add_argument('--archived', action=argparse.BooleanOptionalAction, default=None)
        elif name == 'project':
            sub.add_argument('project')
        elif name == 'defaults':
            sub.add_argument('kind', nargs='?', choices=('orchestrator', 'project', 'feature', 'legacy', 'secretary'))
        else:
            sub.add_argument('id', type=int)
        if name in ('configure', 'defaults'):
            sub.add_argument('--tool', choices=('codex', 'claude'))
            sub.add_argument('--model')
            sub.add_argument('--effort', choices=('low', 'medium', 'high', 'xhigh', 'max', 'ultra'))
    slice_parser = commands.add_parser('slice', parents=[common], help='manage linked slice order')
    slice_commands = slice_parser.add_subparsers(dest='slice_command', required=True, parser_class=Parser)
    place = slice_commands.add_parser('place', parents=[common])
    link = slice_commands.add_parser('link', parents=[common])
    link.add_argument('id')
    link.add_argument('--corrects', required=True)
    place.add_argument('id')
    placement = place.add_mutually_exclusive_group(required=True)
    placement.add_argument('--before')
    placement.add_argument('--after')
    from .features import STAGES
    feature = commands.add_parser('feature', parents=[common], help='manage Postgres features')
    feature_commands = feature.add_subparsers(dest='feature_command', required=True, parser_class=Parser)
    for name in ('add', 'list', 'show', 'stage', 'move', 'section', 'history', 'revert', 'place', 'mark', 'title', 'close'):
        sub = feature_commands.add_parser(name, parents=[common])
        if name == 'add':
            sub.add_argument('project')
            sub.add_argument('title')
            sub.add_argument('--stage', choices=STAGES, default='shortlist')
        elif name == 'list':
            sub.add_argument('--project')
            sub.add_argument('--stage', choices=STAGES)
        else:
            sub.add_argument('id')
        if name in ('list', 'show'):
            sub.add_argument('--json', action='store_true')
        if name == 'title':
            sub.add_argument('title')
        elif name == 'close':
            sub.add_argument('--reason', required=True)
        elif name == 'stage':
            sub.add_argument('stage', choices=STAGES)
        elif name == 'place':
            placement = sub.add_mutually_exclusive_group(required=True)
            placement.add_argument('--top', action='store_true')
            placement.add_argument('--bottom', action='store_true')
            placement.add_argument('--before')
            placement.add_argument('--after')
        elif name == 'mark':
            sub.add_argument('mark', choices=('design', 'review'))
            sub.add_argument('--clear', action='store_true')
        elif name == 'move':
            sub.add_argument('project')
        elif name == 'section':
            sub.add_argument('section')
            sub.add_argument('--file', default='-', help='UTF-8 text file, or - for stdin (default)')
        elif name == 'history':
            sub.add_argument('--section')
        elif name == 'revert':
            sub.add_argument('revision', type=int)
    feature_commands.add_parser('export', parents=[common])
    importer = feature_commands.add_parser('import-backlog', parents=[common])
    importer.add_argument('file')
    importer.add_argument('--dry-run', action='store_true')
    inbox = commands.add_parser('inbox', parents=[common])
    inbox_commands = inbox.add_subparsers(dest='inbox_command', required=True, parser_class=Parser)
    inbox_commands.add_parser('list', parents=[common])
    show_entry = inbox_commands.add_parser('show', parents=[common])
    show_entry.add_argument('id', type=int)
    add_entry = inbox_commands.add_parser('add', parents=[common])
    add_entry.add_argument('text')
    add_entry.add_argument('--file', action='append', default=[])
    add_entry.add_argument('--kind', choices=('idea','link','file','message'))
    add_entry.add_argument('--target')
    add_entry.add_argument('--intent', choices=('explore','discuss'))
    transcript = inbox_commands.add_parser('transcript', parents=[common])
    transcript.add_argument('id', type=int)
    transcript.add_argument('text')
    idea = commands.add_parser('idea', parents=[common])
    ideas = idea.add_subparsers(dest='idea_command', required=True, parser_class=Parser)
    ideas.add_parser('list', parents=[common])
    new_idea = ideas.add_parser('add', parents=[common])
    new_idea.add_argument('title')
    new_idea.add_argument('--note', default='')
    new_idea.add_argument('--tag', action='append', default=[])
    for action in ('show','reject','tag','explore','promote'):
        sub = ideas.add_parser(action, parents=[common])
        sub.add_argument('id', type=int, nargs='+' if action in ('explore','promote') else None)
        if action == 'reject':
            sub.add_argument('--reason', required=True)
        if action == 'tag':
            sub.add_argument('tags', nargs='*')
        if action in ('explore','promote'):
            sub.add_argument('--project')
        if action == 'promote':
            sub.add_argument('--feature')
    skill = commands.add_parser('skill', parents=[common])
    skill_commands = skill.add_subparsers(dest='skill_command', required=True, parser_class=Parser)
    skill_list = skill_commands.add_parser('list', parents=[common])
    skill_list.add_argument('--project')
    for action in ('on', 'off'):
        switch = skill_commands.add_parser(action, parents=[common])
        switch.add_argument('name')
        switch.add_argument('project')
    models = commands.add_parser('models', parents=[common])
    model_commands = models.add_subparsers(dest='models_command', required=True, parser_class=Parser)
    model_commands.add_parser('list', parents=[common])
    update_models = model_commands.add_parser('update', parents=[common])
    update_models.add_argument('tool', choices=('codex', 'claude'))
    limits = commands.add_parser('limit', parents=[common])
    limit_commands = limits.add_subparsers(dest='limit_command', required=True, parser_class=Parser)
    limit_commands.add_parser('show', parents=[common])
    set_limit = limit_commands.add_parser('set', parents=[common])
    set_limit.add_argument('name', choices=('building_limit', 'waiting_limit', 'chat_auto_turns', 'executors', 'repository_runs'))
    set_limit.add_argument('value', type=int)
    project = commands.add_parser('project', parents=[common])
    projects = project.add_subparsers(dest='project_command', required=True, parser_class=Parser)
    projects.add_parser('list', parents=[common])
    active_project = projects.add_parser('active', parents=[common])
    active_project.add_argument('key')
    active_project.add_argument('value', nargs='?', choices=('on', 'off'))
    add_project = projects.add_parser('add', parents=[common])
    add_project.add_argument('key')
    add_project.add_argument('name')
    add_project.add_argument('--repository')
    set_project = projects.add_parser('set', parents=[common])
    set_project.add_argument('key')
    set_project.add_argument('--name')
    for command in (add_project, set_project):
        for field in ('about', 'public-url', 'repository-url'):
            command.add_argument('--' + field)
    view = commands.add_parser("pending", parents=[common], help="show pending slices")
    view.add_argument("--json", action="store_true", help="output grouped JSON")
    why = commands.add_parser("why", parents=[common], help="explain slice eligibility")
    why.add_argument("id")
    show = commands.add_parser("show", parents=[common], help="show one complete slice")
    show.add_argument("id")
    show.add_argument("--json", action="store_true", help="output slice JSON")
    show.add_argument("--final", action="store_true", help="show the latest final message")
    cut_prompt = commands.add_parser("cut-prompt", parents=[common], help="print cutter instructions and brief")
    cut_prompt.add_argument("id")
    cut_submit = commands.add_parser("cut-submit", parents=[common], help="submit a plan to the task queue")
    cut_submit.add_argument("id")
    cut_submit.add_argument("plan")
    cut_submit.add_argument("--repository", required=True)
    cut_submit.add_argument("--branch", required=True)
    cut_submit.add_argument("--base", required=True)
    for command in ("add", "edit"):
        sub = commands.add_parser(command, parents=[common], help=f"{command} a slice")
        if command == "edit":
            sub.add_argument("id")
            sub.add_argument("--id", dest="new_id", default=argparse.SUPPRESS)
        else:
            sub.add_argument("--id", required=True)
        for field in ("repo", "feature", "title", "brief", "model"):
            sub.add_argument(f"--{field.replace('_', '-')}", required=command == "add" and field in ("repo", "feature", "title"), default=argparse.SUPPRESS)
        association = sub.add_mutually_exclusive_group()
        association.add_argument('--feature-id', default=argparse.SUPPRESS)
        association.add_argument('--no-feature', default=argparse.SUPPRESS, metavar='REASON')
        sub.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max", "ultra"), default=argparse.SUPPRESS)
        sub.add_argument("--flow", choices=("cli", "tickets"), default=argparse.SUPPRESS)
        sub.add_argument("--tool", choices=("codex", "claude"), default=argparse.SUPPRESS)
        if command == "add":
            sub.add_argument("--level", choices=("light", "standard", "strong"), default="standard")
        sub.add_argument("--stop-before-merge", action=argparse.BooleanOptionalAction, default=argparse.SUPPRESS)
        sub.add_argument("--allowed-files", nargs="*", default=argparse.SUPPRESS, metavar="GLOB")
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
    attention.add_argument("--for", dest="recipient", choices=("owner", "planner"))
    review = commands.add_parser("review", parents=[common], help="record a planner review of merge attention")
    review.add_argument("id")
    review.add_argument("verdict")
    helps = {"install": "request a node install", "slot": "schedule a ready slice", "unslot": "clear a slot", "start": "slot a ready slice now", "pause": "set paused", "resume": "clear paused", "approve": "approve merge attention", "answer": "answer a question, escalation or node step"}
    for command in COMMANDS:
        sub = commands.add_parser(command, parents=[common], help=helps[command])
        sub.add_argument("id")
        if command in ("slot", "answer"):
            sub.add_argument("value", metavar="when" if command == "slot" else "text")
    installed = commands.add_parser("installed", parents=[common], help="record a hand install")
    installed.add_argument("id")
    installed.add_argument("sha")
    installed.add_argument("--note")
    commands.add_parser("migrate", parents=[common], help="apply Postgres migrations")
    transfer = commands.add_parser("import", parents=[common], help="import state and its outbox into empty Postgres")
    transfer.add_argument("path", help="source state JSON path")
    transfer = commands.add_parser("export", parents=[common], help="export state and notices in file format")
    transfer.add_argument("path", nargs="?", help="destination state JSON path (required with notices; otherwise stdout)")
    commands.add_parser("compact", parents=[common], help="bound oversized runner text in state")
    evaluation = commands.add_parser('eval', parents=[common])
    eval_commands = evaluation.add_subparsers(dest='eval_group', required=True, parser_class=Parser)
    importer = eval_commands.add_parser('import', parents=[common])
    importer.add_argument('folder')
    for group, actions in (('case', ('list',)), ('set', ('create', 'add', 'list', 'show')),
                           ('run', ('create', 'list', 'show', 'cancel'))):
        sub = eval_commands.add_parser(group, parents=[common])
        actions_parser = sub.add_subparsers(dest='eval_action', required=True, parser_class=Parser)
        for action in actions:
            command = actions_parser.add_parser(action, parents=[common])
            if group == 'case':
                from .evals import FILTERS
                for field, choices in FILTERS.items():
                    command.add_argument('--' + field.replace('_', '-'), choices=choices)
            elif group == 'set':
                if action in ('create', 'add', 'show'):
                    command.add_argument('id')
                if action == 'create':
                    command.add_argument('--title', required=True)
                    command.add_argument('--filter', required=True)
                    command.add_argument('--description', default='')
                if action == 'add':
                    command.add_argument('cases', nargs='+')
                if action in ('create', 'add'):
                    command.add_argument('--note', default='')
                if action == 'show':
                    command.add_argument('--version', type=int)
            elif action == 'create':
                command.add_argument('--title', required=True)
                command.add_argument('--set', dest='sets', action='append', required=True)
                command.add_argument('--configuration', action='append', required=True)
                command.add_argument('--repeats', type=int, required=True)
                command.add_argument('--at')
            elif action in ('show', 'cancel'):
                command.add_argument('id', type=int)
    runs = commands.add_parser('runs', parents=[common])
    runs_commands = runs.add_subparsers(dest='runs_command', required=True, parser_class=Parser)
    runs_show = runs_commands.add_parser('show', parents=[common])
    runs_show.add_argument('slice_id')
    runs_export = runs_commands.add_parser('export', parents=[common])
    runs_export.add_argument('--since', required=True)
    run = commands.add_parser('run', parents=[common])
    run.add_argument('--every', type=float, metavar='SECONDS', help='repeat passes and scheduled exports')
    run_commands = run.add_subparsers(dest='run_command', parser_class=Parser)
    for name in ('list', 'show', 'total', 'mark'):
        sub = run_commands.add_parser(name, parents=[common])
        if name == 'list':
            sub.add_argument('--slice', dest='slice_id')
            sub.add_argument('--project')
            sub.add_argument('--json', action='store_true')
        elif name == 'total':
            sub.add_argument('--slice', dest='slice_id', required=True)
        else:
            sub.add_argument('id', type=int)
        if name == 'mark':
            sub.add_argument('--clear', action='store_true')
    commands.add_parser("prime", parents=[common], help="send one minimal request to Claude and Codex to start their usage windows")
    commands.add_parser("install-primer", parents=[common], help="install the launchd job that runs prime at 06:00, 11:00, 16:00 and 21:00")
    commands.add_parser("uninstall-primer", parents=[common], help="remove the primer launchd job")
    commands.add_parser("primer-wake-plist", parents=[common], help="print the root wake-schedule LaunchDaemon plist; never installs it")
    return root


def feature_command(args):
    if not state.postgres():
        raise state.StateError('feature commands require Postgres (CPLANE_DATABASE_URL)')
    backend = state.store(None)
    command = args.feature_command
    actor = getattr(args, 'actor', 'owner')
    if command == 'export':
        from .feature_export import export
        export(backend.feature_export_snapshot())
        return 0
    elif command == 'import-backlog':
        text = Path(args.file).read_bytes().decode('utf-8')
        result = backend.feature_import_backlog(text, dry_run=args.dry_run, actor=actor)
    elif command == 'add':
        result = backend.feature_add(args.project, args.title, stage=args.stage, actor=actor)
    elif command == 'list':
        result = backend.feature_list(project=args.project, stage=args.stage)
    elif command == 'show':
        result = backend.feature_show(args.id)
    elif command == 'title':
        result = backend.feature_title(args.id, args.title, actor=actor)
    elif command == 'close':
        result = backend.feature_close(args.id, args.reason, actor=actor)
    elif command == 'stage':
        result = backend.feature_stage(args.id, args.stage, actor=actor)
    elif command == 'place':
        result = backend.feature_place(args.id, top=args.top, bottom=args.bottom, before=args.before, after=args.after, actor=actor)
    elif command == 'mark':
        result = backend.feature_mark(args.id, args.mark, clear=args.clear, actor=actor)
    elif command == 'move':
        result = backend.feature_move(args.id, args.project, actor=actor)
    elif command == 'section':
        text = sys.stdin.read() if args.file == '-' else Path(args.file).expanduser().read_text(encoding='utf-8')
        result = backend.feature_section(args.id, args.section, text, actor=actor)
    elif command == 'history':
        result = backend.feature_history(args.id, args.section)
    else:
        result = backend.feature_revert(args.id, args.revision, actor=actor)
    if command == 'list' and not args.json:
        print('\n'.join(f"{item['id']} [{item['stage']}] {item['title']}" for item in result) or '(none)')
    elif command == 'show' and not args.json:
        print(f"{result['id']} [{result['stage']}] {result['title']}")
        print(f"project: {result['project']}\nposition: {result['position']}\nparked from: {result['parked_from']}")
        print(f"design agreed: {result['design_agreed']}\nreview passed: {result['review_passed']}")
        print('aliases: ' + ', '.join(result['aliases']))
        for section in result['sections']:
            print(f"\n## {section['name']}\n\n{section['text']}")
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def eval_command(args):
    from . import evals
    if not state.postgres():
        raise state.StateError('eval commands require Postgres (CPLANE_DATABASE_URL or CPLANE_DATABASE_URL_FILE)')
    backend = state.store(None)
    actor = getattr(args, 'actor', 'owner')
    if args.eval_group == 'import':
        result = evals.import_folder(backend, args.folder)
    elif args.eval_group == 'case':
        result = evals.case_list(backend, **{key: getattr(args, key) for key in evals.FILTERS})
    elif args.eval_group == 'set':
        if args.eval_action == 'create':
            result = evals.set_create(backend, args.id, title=args.title, filters=json.loads(args.filter),
                                     description=args.description, note=args.note, actor=actor)
        elif args.eval_action == 'add':
            result = evals.set_add(backend, args.id, args.cases, note=args.note, actor=actor)
        elif args.eval_action == 'show':
            result = evals.set_show(backend, args.id, args.version)
        else:
            result = evals.set_list(backend)
    elif args.eval_action == 'create':
        result = evals.run_create(backend, title=args.title, sets=args.sets,
                                 configurations=[json.loads(c) for c in args.configuration],
                                 repeats=args.repeats, scheduled_for=args.at, actor=actor)
    elif args.eval_action == 'cancel':
        result = evals.run_cancel(backend, args.id)
    elif args.eval_action == 'show':
        result = evals.run_show(backend, args.id)
    else:
        result = evals.run_list(backend)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'eval':
            return eval_command(args)
        if args.command == 'runs':
            if not state.postgres():
                raise state.StateError('run record commands require Postgres (CPLANE_DATABASE_URL)')
            if args.runs_command == 'export':
                try:
                    since = datetime.combine(date.fromisoformat(args.since), datetime.min.time(), timezone.utc)
                except ValueError:
                    raise state.StateError('--since must be an ISO date (YYYY-MM-DD)') from None
                for row in state.store(None).run_record_export(since):
                    print(json.dumps(row, ensure_ascii=False, allow_nan=False))
                return 0
            print(json.dumps(state.store(None).run_record_list(slice_id=args.slice_id),
                             indent=2, ensure_ascii=False))
            return 0
        if args.command == 'run' and args.run_command:
            if not state.postgres():
                raise state.StateError('run record commands require Postgres (CPLANE_DATABASE_URL)')
            backend = state.store(None)
            if args.run_command == 'list':
                result = backend.run_record_list(slice_id=args.slice_id, project=args.project)
                if not args.json:
                    print('\n'.join(f"{r['id']} {r['kind']} {r['slice_id'] or r['session_id']} {r['tool']} {r['outcome']}" for r in result) or '(none)')
                    return 0
            elif args.run_command == 'show':
                result = backend.run_record_show(args.id)
            elif args.run_command == 'total':
                result = backend.run_record_total(args.slice_id)
            else:
                backend.run_record_mark(args.id, clear=args.clear)
                return 0
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        if args.command == 'chat':
            if not state.postgres():
                raise state.StateError('chat commands require Postgres (CPLANE_DATABASE_URL)')
            backend = state.store(None)
            command = args.chat_command
            if command == 'list':
                result = backend.chats(kind=args.kind, project=args.project, archived=args.archived)
            elif command == 'open':
                result = backend.chat_open(args.id)
            elif command in ('read', 'unread'):
                result = backend.chat_read(args.id, unread=command == 'unread')
            elif command in ('archive', 'unarchive'):
                result = backend.chat_archive(args.id, archived=command == 'archive')
            elif command == 'project':
                result = backend.create_project_chat(args.project)
            elif command == 'configure':
                result = backend.chat_configure(args.id, **{k: getattr(args, k) for k in ('tool', 'model', 'effort') if getattr(args, k) is not None})
            else:
                result = backend.chat_defaults(args.kind, chat_tool=args.tool, chat_model=args.model, effort=args.effort)
            # Resume IDs belong only to the runner.
            from .chats import public_chat_result
            print(json.dumps(public_chat_result(result), indent=2, ensure_ascii=False, default=str))
            return 0
        if args.command == 'skill':
            if not state.postgres():
                raise state.StateError('skill commands require Postgres (CPLANE_DATABASE_URL)')
            backend = state.store(None)
            if args.skill_command != 'list':
                backend.skill_set(args.name, args.project, args.skill_command == 'on')
            print(json.dumps(backend.skill_list(args.project), ensure_ascii=False))
            return 0
        if args.command == 'models':
            if not state.postgres():
                raise state.StateError('models commands require Postgres (CPLANE_DATABASE_URL)')
            backend = state.store(None)
            result = backend.model_list() if args.models_command == 'list' else backend.models_update(args.tool)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 1 if isinstance(result, dict) and result.get('status') == 'failed' else 0
        if args.command == 'limit':
            if not state.postgres():
                raise state.StateError('limit commands require Postgres (CPLANE_DATABASE_URL)')
            backend = state.store(None)
            result = backend.limit_show() if args.limit_command == 'show' else backend.limit_set(args.name, args.value)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == 'project':
            if not state.postgres():
                raise state.StateError('project commands require Postgres (CPLANE_DATABASE_URL)')
            backend = state.store(None)
            if args.project_command == 'list':
                result = backend.library_projects()
            elif args.project_command == 'active':
                result = backend.project_active(args.key, None if args.value is None else args.value == 'on',
                                                actor=getattr(args, 'actor', 'owner'))
            else:
                fields = {field: getattr(args, field) for field in ('name', 'about', 'public_url', 'repository_url')
                          if getattr(args, field) is not None}
                if args.project_command == 'set':
                    result = backend.project_set(args.key, actor=getattr(args, 'actor', 'owner'), **fields)
                else:
                    result = backend.project_add(args.key, repository=args.repository,
                                                 actor=getattr(args, 'actor', 'owner'), **fields)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command in ('inbox','idea'):
            if not state.postgres():
                raise state.StateError('Inbox and ideas require Postgres (CPLANE_DATABASE_URL)')
            backend = state.store(None)
            actor = getattr(args, 'actor', 'owner')
            action = getattr(args, args.command + '_command')
            if args.command == 'inbox':
                if action == 'list':
                    result = backend.inbox_list()
                elif action == 'show':
                    result = backend.inbox_show(args.id)
                elif action == 'transcript':
                    result = backend.inbox_transcript(args.id, args.text, actor=actor)
                else:
                    import mimetypes
                    from .inbox import FILE_LIMIT
                    files = []
                    for name in args.file:
                        path = Path(name)
                        with path.open('rb') as stream:
                            content = stream.read(FILE_LIMIT+1)
                        files.append(dict(name=path.name, media_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream', content=content))
                    result = backend.inbox_add(args.text, fields={k:getattr(args,k) for k in ('kind','target','intent') if getattr(args,k) is not None}, files=files)
            elif action == 'list':
                result = backend.idea_list()
            elif action == 'show':
                result = backend.idea_show(args.id)
            elif action == 'add':
                result = backend.idea_new(args.title,args.note,tags=args.tag,actor=actor)
            elif action == 'reject':
                result = backend.idea_reject(args.id,args.reason,actor=actor)
            elif action == 'tag':
                result = backend.idea_tag(args.id,args.tags,actor=actor)
            else:
                result = backend.idea_request(args.id,action=action,project=args.project,feature=getattr(args,'feature',None),actor=actor)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == 'slice':
            if not state.postgres():
                raise state.StateError('slice commands require Postgres (CPLANE_DATABASE_URL)')
            if args.slice_command == 'link':
                def link_change(item, data, at):
                    if args.id == args.corrects:
                        raise state.StateError('A slice cannot correct itself')
                    if not any(s['id'] == args.corrects for s in data['slices']):
                        raise state.StateError('Correction target slice not found')
                    state.store(None).slice_outcome(args.id, corrects=args.corrects)
                    return f'{args.id} corrects {args.corrects}', None
                path = Path(getattr(args, 'state', None) or os.environ.get('CPLANE_STATE')
                            or 'slices.json').expanduser()
                state.update(path, args.id, 'slice link', getattr(args, 'actor', 'owner'),
                             link_change, getattr(args, 'commit', False),
                             event=f'slice link: corrects {args.corrects}')
                return 0
            result = state.store(None).slice_place(args.id, before=args.before, after=args.after,
                                                  actor=getattr(args, 'actor', 'owner'))
            print(json.dumps(result))
            return 0
        if args.command == 'feature':
            return feature_command(args)
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
        if args.command in ("migrate", "import"):
            if not state.postgres():
                raise state.StateError("this command requires CPLANE_DATABASE_URL")
            backend = state.store(None)
            if args.command == "migrate":
                backend.migrate()
            else:
                backend.import_file(args.path)
            return 0
        path = getattr(args, "state", None) or os.environ.get("CPLANE_STATE")
        if not path and not state.postgres():
            raise state.StateError("provide --state or CPLANE_STATE")
        # In database mode this path remains the anchor for briefs/run metadata.
        path = Path(path or "slices.json").expanduser()
        if args.command == 'digest':
            from . import digest
            from .times import now
            try:
                today = now().astimezone(LOCAL)
                if args.date and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.date):
                    raise ValueError()
                day = date.fromisoformat(args.date) if args.date else today.date() - timedelta(days=today < digest.boundary(today.date()))
            except ValueError:
                raise state.StateError('--date must be an ISO date (YYYY-MM-DD)') from None
            end = digest.boundary(day)
            with state.locked(path) as backend:
                data = backend.load()
                records = (backend.run_record_list() + [r for r in backend.run_record_export(
                    end.astimezone(timezone.utc) - timedelta(hours=24)) if r['kind'] == 'task']) if state.postgres() else []
                print(digest.build(data, records, end))
            return 0
        if args.command == "export":
            with state.locked(path) as backend:
                payload = json.dumps(backend.load(), indent=2, ensure_ascii=False) + "\n"
                outbox = "".join(json.dumps(notice, ensure_ascii=False) + "\n"
                                 for _, notice in backend.notices())
            if args.path:
                destination = Path(args.path).expanduser()
                destination.write_text(payload)
                Path(str(destination) + ".outbox.jsonl").write_text(outbox)
            else:
                if outbox:
                    raise state.StateError("export contains notices; provide PATH with cplane export PATH to write state and its outbox")
                print(payload, end="")
        elif args.command == "run":
            from .runner import Runner, run_loop
            if args.every is None:
                Runner(path).run()
            else:
                run_loop(path, args.every)
        elif args.command == "compact":
            path = path.resolve()
            with state.locked(path):
                before = state.size(path)
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
                after = state.size(path)
            print(f"cut {logs} log entries and {attentions} attention bodies; size {before} -> {after} bytes")
        elif args.command in ("cut-prompt", "cut-submit"):
            from . import cut as cutter
            def brief_for(item):
                if item.get("brief_id"):
                    return state.store(path).stored_brief(item["brief_id"])
                if not item["brief"]:
                    raise state.StateError(f"{args.id} needs a brief")
                try:
                    return (path.resolve().parent / item["brief"]).read_text()
                except OSError:
                    raise state.StateError(f"{args.id}: brief cannot be read") from None
            if args.command == "cut-prompt":
                item = next((item for item in state.load(path)["slices"] if item["id"] == args.id), None)
                if item is None:
                    raise state.StateError(f"unknown slice: {args.id}")
                from .skills import instructions
                print(instructions("cut") + brief_for(item), end="")
            else:
                try:
                    plan = json.loads(Path(args.plan).read_text())
                except (OSError, ValueError):
                    raise state.StateError("plan.json cannot be read as JSON") from None
                cutter.validate_plan(plan)
                root = Path(__file__).resolve().parent.parent
                event = "cut-submit: skills " + cutter.skills_version(root)
                def change(item, data, at):
                    task_file = cutter.build_task_file(args.id, args.repository, args.branch, args.base, plan, brief_for(item))
                    ids = cutter.submit(task_file)
                    notice = f"Submitted {len(ids)} tickets for {args.id}: " + json.dumps(ids, ensure_ascii=False)
                    return notice, None
                with state.locked(path):
                    state.update_locked(path, args.id, args.command, getattr(args, "actor", "owner"), change,
                                        getattr(args, "commit", False), event=event)
        elif args.command == "pending":
            groups = pending(state.load(path))
            print(json.dumps(groups, indent=2, ensure_ascii=False) if args.json else render(groups))
        elif args.command == "why":
            with state.locked(path) as backend:
                data = backend.load()
                item = next((s for s in data['slices'] if s['id'] == args.id), None)
                if item is None:
                    raise state.StateError(f"unknown slice: {args.id}")
                limits = backend.limit_show() if state.postgres() else None
                print(json.dumps(eligibility(item, observed(data, path, limits=limits)), ensure_ascii=False))
        elif args.command == "show":
            from .executors import read_output
            item = next((item for item in state.load(path)["slices"] if item["id"] == args.id), None)
            if item is None:
                raise state.StateError(f"unknown slice: {args.id}")
            if state.postgres():
                backend = state.store(path)
                policy = backend.slice_policy(item['id'])
                item = dict(item, level=policy['level'] if policy else 'standard',
                            executor=backend.slice_executor(item))
            default_runs = '/srv/factory/runs'
            base = Path(os.environ.get('CPLANE_RUNS', default_runs)).expanduser().resolve()
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
                    if job.get('fence') and job.get('tool') == 'codex':
                        last = latest[1] / 'io/last.json'
                    if not final and last.exists():
                        try:
                            reply = json.loads(read_output(last) if job.get('fence') else last.read_text())
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
                from .installation import REQUEST, runs_path
                for entry in item['log']:
                    if entry['event'].startswith(REQUEST):
                        request = entry['event'][len(REQUEST):]
                        if not re.fullmatch('[0-9a-f]{32}', request):
                            continue
                        result = runs_path(path) / 'installs' / (request + '.json')
                        if result.exists():
                            print(f'install {request}: ' + result.read_text())
        elif args.command == "installed":
            from .installation import installable
            actor = getattr(args, "actor", "owner")
            if actor != "owner" and not re.fullmatch(r"chat:[A-Za-z0-9_-]+", actor):
                raise state.StateError("installed actor must be owner or chat:<id>")
            def record_install(item, data, at):
                if installable(item):
                    raise state.StateError("installable repositories must use cplane install")
                if not re.fullmatch(r"[0-9a-fA-F]{40}", args.sha) or not any(
                        entry['event'] == 'merged: ' + args.sha for entry in item['log']):
                    raise state.StateError("no matching full merge sha")
                event = f"Installed {args.sha}. By hand" + (f": {args.note}" if args.note else ".")
                item['log'].append(dict(at=at, actor=actor, event=event))
                return None, None
            state.update(path, args.id, args.command, actor, record_install,
                         getattr(args, "commit", False), event="hand install recorded")
        elif args.command in ("add", "edit", "state", "attention", "review"):
            event = note = None
            if args.command == "state":
                event = f"state: {args.target}"
                if args.force:
                    event += f" (forced: {args.reason})"
            from . import review
            change = review.planner_change(args) if args.command == 'review' else planner.change_for(args)
            if args.command == 'state' and args.target == 'dropped':
                base_change = change
                def change(item, data, at):
                    from .executors import Processes
                    from .installation import runs_path
                    for job_file in runs_path(path).glob('*/job.json'):
                        try:
                            job = json.loads(job_file.read_text())
                            if (job['id'] == item['id'] and job['phase'] == 'running'
                                    and not Processes().poll(job)[0]):
                                raise state.StateError(f"{item['id']} has a live executor")
                        except (OSError, ValueError, KeyError, TypeError) as error:
                            raise state.StateError(f"cannot verify executor status: {job_file}") from error
                    return base_change(item, data, at)
            if args.command in ('add', 'edit') and hasattr(args, 'allowed_files'):
                base_change = change
                def change(item, data, at):
                    if args.command == 'edit' and item['state'] in ('issued', 'awaiting handover'):
                        raise state.StateError(f"{item['id']} is {item['state']}; only --title and --depends-on may be edited")
                    result = base_change(item, data, at)
                    item['allowed_files'] = args.allowed_files
                    return result
            state.update(path, args.id, args.command, getattr(args, "actor", "owner"),
                         change, getattr(args, "commit", False),
                         create=(lambda: planner.new_slice(args.id)) if args.command == "add" else None,
                         event=event)
            if note:
                print(note, file=sys.stderr)
        else:
            warning = state.update(path, args.id, args.command, getattr(args, "actor", "owner"), change_for(args.command, getattr(args, "actor", "owner") if args.command == "install" else getattr(args, "value", None)), getattr(args, "commit", False))
            if warning:
                print(f"warning: {warning}", file=sys.stderr)
        return 0
    except (state.StateError, OSError, ValueError) as error:
        message = ('Feature export failed' if args.command == 'feature' and args.feature_command == 'export'
                   else ' '.join(str(error).splitlines()))
        print('cplane: ' + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
