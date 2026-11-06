"""One locked scheduling pass. Adapters keep external effects fakeable."""
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import uuid

from . import state
from .orders import Collector
from .executors import Processes, atomic_json, CLAUDE_PARAGRAPH
from .text_bounds import ATTENTION_LIMIT, LOG_LIMIT, cut, cut_line
from .times import now

CODEX_WORKTREES = Path.home() / '.codex/worktrees'
WORKTREE_MAX_AGE = 7 * 24 * 60 * 60


def codex_usage(folder=None):
    windows = codex_limits(folder)
    if not windows:
        return None
    used = []
    for window in windows:
        if window.get('resets_at') is not None and window['resets_at'] <= time.time():
            used.append(0)
        elif isinstance(window.get('used_percent'), (int, float)):
            used.append(window['used_percent'])
    return max(used) if used else None


def codex_limits(folder=None):
    """The non-null windows (5-hour primary, weekly secondary) of the newest report."""
    paths = Path(folder or Path.home() / '.codex/sessions').rglob('*.jsonl')
    newest_first = sorted(paths, key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for session in newest_first:
        # Walk backwards: the last non-null capacity report is the current one.
        for line in reversed(session.read_text(errors='replace').splitlines()):
            try:
                limits = json.loads(line).get('payload', {}).get('rate_limits')
                windows = [limits[k] for k in ('primary', 'secondary')
                           if isinstance(limits.get(k), dict)] if limits else []
                if windows:
                    return windows
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
    return None


def usage_limit_message(tail):
    for line in tail.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if event.get('type') != 'turn.failed':
            continue
        error = event.get('error')
        message = error.get('message', '') if isinstance(error, dict) else ''
        if isinstance(message, str) and re.search(r'usage limit', message, re.I):
            return message
    return None


def claude_usage(path=None):
    try:
        return json.loads(Path(path or Path.home() / '.claude/usage-now.json').read_text())
    except (OSError, ValueError):
        return None


class Git:
    def tidy(self, path, *, now=None):
        path = Path(path)
        name = path.name
        def call(*args):
            result = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True)
            if result.returncode:
                print(f'{name}: git {" ".join(args)} failed: {(result.stderr or result.stdout).strip()}', file=sys.stderr)
            return result

        head = call('symbolic-ref', '-q', 'HEAD')
        if head.returncode == 1:
            status = call('status', '--porcelain')
            if status.returncode == 0 and not status.stdout:
                default = call('symbolic-ref', '--short', 'refs/remotes/origin/HEAD')
                branch = default.stdout.strip().removeprefix('origin/') if default.returncode == 0 else 'main'
                if branch:
                    call('switch', branch)

        listed = call('worktree', 'list', '--porcelain')
        if listed.returncode:
            return
        root = CODEX_WORKTREES.resolve()
        timestamp = time.time() if now is None else now.timestamp()
        for block in listed.stdout.strip().split('\n\n'):
            first = next((line[9:] for line in block.splitlines() if line.startswith('worktree ')), None)
            if not first:
                continue
            worktree = Path(first)
            try:
                resolved = worktree.resolve()
                resolved.relative_to(root)
                if timestamp - worktree.stat().st_mtime <= WORKTREE_MAX_AGE:
                    continue
            except (OSError, ValueError):
                continue
            call('worktree', 'remove', str(worktree))
        call('worktree', 'prune')

    def pull(self, path):
        probe = subprocess.run(['git', '-C', str(path.parent), 'rev-parse', '--show-toplevel'],
                               capture_output=True, text=True)
        if not probe.returncode:
            state.git(Path(probe.stdout.strip()), 'pull', '--rebase', '--autostash')

    def commit(self, path):
        state.commit_state(path, Path(str(path) + '.outbox.jsonl'), 'run', 'pass')

    def branch(self, path):
        result = subprocess.run(['git', '-C', str(path), 'branch', '--show-current'],
                                capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else ''


class GitHub:
    def repository(self, path):
        result = subprocess.run(['git', '-C', str(path), 'remote', 'get-url', 'origin'],
                                text=True, capture_output=True)
        remote = result.stdout.strip()
        if result.returncode or not remote:
            raise state.StateError(f'missing GitHub origin: {path}')
        match = re.fullmatch(r'(?:https://|ssh://git@|git@)(?:github\.com[:/])([^/]+)/([^/]+?)(?:\.git)?', remote)
        if not match:
            raise state.StateError(f'origin is not a GitHub repository: {remote}')
        return f'{match.group(1)}/{match.group(2)}'

    def call(self, repo, *args):
        result = subprocess.run(['gh', *args, '-R', repo], text=True, capture_output=True)
        if result.returncode:
            raise state.StateError('gh: ' + (result.stderr.strip() or result.stdout.strip()))
        return result.stdout.strip()

    def open(self, repo, request):
        # Recover an already-created PR if a previous pass stopped before saving its number.
        existing = json.loads(self.call(repo, 'pr', 'list', '--head', request['branch'], '--state', 'open', '--json', 'number'))
        if existing:
            return existing[0]['number']
        url = self.call(repo, 'pr', 'create', '--head', request['branch'], '--title', request['title'], '--body', request['body'])
        return int(url.rstrip('/').split('/')[-1])

    def find_pr(self, repo, branch):
        if not branch:
            return None
        prs = json.loads(self.call(repo, 'pr', 'list', '--head', branch, '--state', 'all',
                                   '--json', 'number,createdAt'))
        if not prs:
            return None
        newest = max(prs, key=lambda pr: pr.get('createdAt', ''))
        return newest['number']

    def checks(self, repo, number):
        info = json.loads(self.call(repo, 'pr', 'view', str(number), '--json', 'statusCheckRollup'))
        pending = False
        rollup = info['statusCheckRollup']
        # A stalled hosted runner is cancelled on one of two runs; the other run may pass.
        passed = {c.get('name') for c in rollup
                  if c.get('name') and (c.get('conclusion') or c.get('state')) == 'SUCCESS'}
        for check in rollup:
            conclusion = check.get('conclusion') or check.get('state')
            if conclusion == 'CANCELLED' and check.get('name') in passed:
                continue
            if conclusion in ('FAILURE', 'ERROR', 'CANCELLED', 'TIMED_OUT', 'ACTION_REQUIRED', 'STARTUP_FAILURE'):
                return 'red', check.get('name') or check.get('context', 'check')
            if conclusion not in ('SUCCESS', 'NEUTRAL', 'SKIPPED'):
                pending = True
        return ('pending' if pending else 'green'), ''

    def is_open(self, repo, number):
        info = json.loads(self.call(repo, 'pr', 'view', str(number), '--json', 'state'))
        return info['state'] == 'OPEN'

    def merge(self, repo, number):
        info = json.loads(self.call(repo, 'pr', 'view', str(number), '--json', 'state,mergeCommit'))
        if info['state'] != 'MERGED':
            self.call(repo, 'pr', 'merge', str(number), '--squash')
            info = json.loads(self.call(repo, 'pr', 'view', str(number), '--json', 'state,mergeCommit'))
        return info['mergeCommit']['oid']


class Runner:
    def __init__(self, path, *, processes=None, github=None, git=None, clock=now,
                 codex_reader=codex_usage, claude_reader=claude_usage, runs=None, repos=None, orders=None):
        self.path = Path(path).expanduser().resolve()
        self.orders = orders or Collector()
        self.processes = processes or Processes()
        self.github = github or GitHub()
        self.git = git or Git()
        self.clock = clock
        self.codex_reader, self.claude_reader = codex_reader, claude_reader
        base = Path(runs or os.environ.get('CPLANE_RUNS', '~/Library/Application Support/cplane/runs')).expanduser().resolve()
        self.runs = base / hashlib.sha256(str(self.path).encode()).hexdigest()[:20]
        self.repos = Path(repos or os.environ.get('CPLANE_REPOS', '~/Code')).expanduser().resolve()
        self.notices = []

    def log(self, item, event, notice=False):
        event = cut_line(event, LOG_LIMIT)
        item['log'].append({'at': self.at, 'actor': 'runner', 'event': event})
        if notice:
            self.notices.append({'at': self.at, 'id': item['id'], 'event': event.split(':')[0], 'text': event})

    def defer(self, item, reason):
        if not item['log'] or item['log'][-1]['event'] != reason:
            self.log(item, reason)

    def attention(self, item, kind, body):
        body = cut(body, ATTENTION_LIMIT)
        item['attention'] = {'kind': kind, 'body': body, 'since': self.at, 'answer': None, 'approved': False}
        if kind == 'escalation':
            item['state'] = 'escalated'
        first_line = body.partition('\n')[0]
        self.log(item, f'{kind}: {first_line}', True)

    def slice_failure(self, item, stage):
        lines = traceback.format_exc().strip().splitlines()
        summary = f'{stage} failed: {lines[-1] if lines else "unknown error"}'
        self.attention(item, 'escalation', summary + ('\n' + '\n'.join(lines[-8:]) if lines else ''))

    def github_repo(self, item):
        return self.github.repository(self.repo(item))

    def save_job(self, job):
        atomic_json(Path(job['run']) / 'job.json', job)

    def choose(self, item, resume=False):
        model = item['executor']['model']
        if resume:
            tool = item['session']['tool']
            model = self.jobs[item['id']]['model']
        else:
            tool = item['executor']['tool']
        if tool == 'codex':
            if any(j['phase'] == 'usage-limit-wait' and j['reset_at'] > self.instant.timestamp()
                   for j in self.jobs.values()):
                return None
            codex = self.codex_reader()
            if isinstance(codex, (int, float)) and 0 <= codex < 99:
                return 'codex', model
            return None
        usage = self.claude_reader()
        if usage:
            try:
                age = self.instant.timestamp() - usage['at']
                window = usage['rate_limits']['five_hour']
                used = window.get('used_percentage')
                reset = window.get('resets_at')
                expired = reset is not None and reset <= self.instant.timestamp()
                if expired:
                    used = 0
                if (expired or 0 <= age < 3600) and isinstance(used, (int, float)) and 0 <= used < 90:
                    return 'claude', model if resume or model in ('opus', 'sonnet') else ('opus' if 'sol' in model.lower() else 'sonnet')
            except (KeyError, TypeError):
                pass
        return None

    def room(self, item):
        paused = {s['id'] for s in self.data['slices'] if s['paused']}
        active = [j for j in self.jobs.values()
                  if j['phase'] == 'running' and j['id'] not in paused]
        # An issued session whose local run files are missing still occupies a slot.
        unknown = [s for s in self.data['slices'] if s['id'] not in self.jobs
                   and s['state'] in ('issued', 'awaiting handover') and not s['attention']
                   and not s['paused']]
        running = sorted([j['id'] for j in active] + [s['id'] for s in unknown])
        if len(running) >= 2:
            return f"deferred: executor limit (running: {', '.join(running)})"
        repo = self.repo(item)
        busy = next((j['id'] for j in active if j['repo'] == str(repo)), None)
        if busy is None:
            busy = next((s['id'] for s in unknown if self.repo(s) == repo), None)
        return f'deferred: repository busy ({busy})' if busy else None

    def repo(self, item):
        name = item['repo'].split('/')[-1]
        if name in ('', '.', '..') or '\\' in name:
            raise state.StateError('invalid repository name')
        return (self.repos / name).resolve()

    def launch(self, item, prompt, resume=False):
        reason = self.room(item)
        if reason:
            self.defer(item, reason)
            return False
        choice = self.choose(item, resume)
        if choice is None:
            self.defer(item, 'deferred: capacity unavailable')
            return False
        tool, model = choice
        effort = item['executor'].get('effort', 'low' if 'luna' in model.lower() else 'medium')
        folder = self.repo(item)
        if not folder.is_dir():
            raise state.StateError(f'missing repository: {folder}')
        run = self.runs / uuid.uuid4().hex
        run.mkdir(parents=True, mode=0o700)
        if tool == 'claude' and not resume:
            prompt += CLAUDE_PARAGRAPH
        previous = self.jobs.get(item['id'])
        job = {'id': item['id'], 'repo': str(folder), 'run': str(run), 'tool': tool,
               'model': model, 'effort': effort, 'prompt': prompt, 'started_ns': time.time_ns(),
               'session': item['session']['id'] if resume else '',
               'resume': item['session']['id'] if resume else None, 'phase': 'running'}
        # Persist intent before starting; an ambiguous handoff reserves a slot.
        if resume and previous and previous.get('noticed') is not None:
            job['noticed'] = previous['noticed']
        self.save_job(job)
        try:
            job['pid'] = self.processes.start(job)
        except OSError as error:
            atomic_json(run / 'exit.json', {'error': str(error)})
            self.log(item, f'launch failed: {error}')
        self.save_job(job)
        self.jobs[item['id']] = job
        item['session'] = {'tool': tool, 'id': job['session'], 'folder': str(folder)}
        item['state'] = 'issued'
        item['attention'] = None
        self.log(item, 'resumed' if resume else 'started', True)
        return True

    def collect(self, item, job):
        if job['phase'] != 'running':
            return
        done, session, final, tail = self.processes.poll(job)
        if session:
            job['session'] = session
        item['session'] = {'tool': job['tool'], 'id': job['session'], 'folder': job['repo']}
        item['state'] = 'issued'
        if not done:
            self.save_job(job)
            self.log(item, 'collect: still running')
            return
        # Save the reply for replay if state persistence is interrupted.
        job['final'], job['tail'] = final, tail
        job['phase'] = 'ended'
        self.save_job(job)
        self.apply_final(item, job)

    def limit_reset(self, message):
        """The reset time named in a usage-limit message, if it is still ahead."""
        match = re.search(r'try again at (?:([A-Za-z]{3}) (\d{1,2})(?:st|nd|rd|th)?, (\d{4}) )?'
                          r'(\d{1,2}:\d{2}\s*[AP]M)', message, re.I)
        if not match:
            return None
        try:
            clock = datetime.strptime(match[4].upper().replace(' ', ''), '%I:%M%p').time()
            if match[1]:
                day = datetime.strptime(f'{match[1].title()} {match[2]} {match[3]}', '%b %d %Y')
                retry = self.instant.replace(year=day.year, month=day.month, day=day.day,
                                             hour=clock.hour, minute=clock.minute,
                                             second=0, microsecond=0)
            else:
                retry = self.instant.replace(hour=clock.hour, minute=clock.minute,
                                             second=0, microsecond=0)
                if retry <= self.instant:
                    retry += timedelta(days=1)
        except ValueError:
            return None
        return retry.timestamp() if retry > self.instant else None

    def apply_final(self, item, job):
        final = job.get('final')
        cut_message = (usage_limit_message(job.get('tail', ''))
                       if job['tool'] == 'codex' and not final else None)
        if job['tool'] == 'codex' and job.get('pr'):
            item['pr'] = job['pr']
        if job['tool'] == 'codex' and final and item['pr'] is None:
            branch = self.git.branch(job['repo'])
            item['pr'] = self.github.find_pr(self.github_repo(item), branch)
            if item['pr'] is None:
                named = re.findall(r'(?:/pull/|\bPR\s+#)(\d+)', final['body'], re.I)
                if named:
                    item['pr'] = int(named[-1])
        if cut_message:
            now_ts = self.instant.timestamp()
            reset_at, limit = self.limit_reset(cut_message), None
            if reset_at is None:
                windows = [w for w in (codex_limits() or [])
                           if isinstance(w.get('used_percent'), (int, float)) and w['used_percent'] >= 99
                           and isinstance(w.get('resets_at'), (int, float)) and w['resets_at'] > now_ts]
                if windows:
                    reset_at = float(max(w['resets_at'] for w in windows))
            if reset_at is None:
                reset_at, limit = (self.instant + timedelta(minutes=60)).timestamp(), 'fixed'
            else:
                limit = reset_at
            job['phase'], job['reset_at'] = 'usage-limit-wait', reset_at
            resume_time = datetime.fromtimestamp(reset_at, self.instant.tzinfo)
            resumes = resume_time.strftime('%H:%M' if resume_time.date() == self.instant.date() else '%b %d %H:%M')
            noticed = job.get('noticed')
            same = noticed == limit == 'fixed' or (
                isinstance(noticed, (int, float)) and isinstance(limit, (int, float))
                and abs(noticed - limit) < 60)  # a message names the minute, a report the second
            if not same:
                job['noticed'] = limit
            self.log(item, f"cut by Codex's usage limit; resumes after {resumes}", not same)
        elif not final:
            tail = job.get('tail', '')
            first, _, rest = tail.partition('\n')
            summary = first if re.match(r'(?:codex|claude) exec exited \d+: ', first) else 'the run ended without a final message'
            detail = rest if summary == first else tail
            self.attention(item, 'escalation', summary + ('\n\n' + detail if detail else ''))
        elif final['kind'] == 'handover':
            item['state'], item['attention'] = 'in review', None
            self.log(item, 'finished', True)
        elif final['kind'] in ('question', 'escalation'):
            self.attention(item, final['kind'], final['body'])
        elif (job['tool'] == 'codex' and final['kind'] == 'waiting'
              and (job.get('pr') or (item['pr'] is not None
                   and self.github.is_open(self.github_repo(item), item['pr'])))):
            # Keep the number with the collected reply so a failed state save can replay it.
            item['pr'] = job['pr'] = job.get('pr') or item['pr']
            job['phase'] = 'pr'
        elif job['tool'] == 'claude' and re.match(r'\s*```', final['body']):
            match = re.match(r'\s*```(?:json)?\s*\n(.*?)\n```', final['body'], re.S)
            try:
                request = json.loads(match[1]) if match else None
                if not isinstance(request, dict) or set(request) != {'branch', 'title', 'body', 'node_steps'}:
                    raise ValueError('expected branch, title, body, node_steps')
                if not all(isinstance(request[k], str) and request[k] for k in ('branch', 'title', 'body')):
                    raise ValueError('invalid PR fields')
                if request['node_steps'] is not None and not isinstance(request['node_steps'], str):
                    raise ValueError('invalid node_steps')
            except ValueError as error:
                self.attention(item, 'escalation', 'invalid Claude PR request: ' + str(error))
            else:
                job['request'], job['phase'] = request, 'pr'
                item['pr'] = self.github.open(self.github_repo(item), request)
                self.log(item, f'opened PR: {item["pr"]}', True)
        else:
            self.attention(item, 'node-step', final['body'])
        if job['phase'] == 'ended':
            job['phase'] = 'collected'
        self.log(item, 'collected turn: ' + Path(job['run']).name)
        self.save_job(job)

    def merge(self, item, job):
        sha = self.github.merge(self.github_repo(item), item['pr'])
        job['phase'], job['sha'] = 'merged', sha
        self.save_job(job)
        self.log(item, f'merged: {sha}', True)
        item['attention'] = None
        if job['request']['node_steps'] is not None:
            self.attention(item, 'node-step', job['request']['node_steps'])
            job['phase'] = 'node-step'
            self.save_job(job)

    def deliver(self, item):
        job = self.jobs.get(item['id'])
        attention = item['attention']
        if (job and job['phase'] == 'usage-limit-wait' and not attention
                and not item['paused']
                and self.instant.timestamp() >= job['reset_at']):
            self.launch(item, 'Your turn was cut by the usage limit. Your uncommitted work is in your working tree. Continue the slice.', resume=True)
            return
        if attention and attention['answer'] is not None:
            if not job or not item['session'] or not item['session']['id']:
                self.defer(item, 'deferred: session unavailable')
            else:
                self.launch(item, attention['answer'], resume=True)
            return
        if attention and attention['kind'] == 'merge' and attention['approved']:
            if item['session']['tool'] == 'codex':
                if job and item['session']['id']:
                    self.launch(item, 'The owner approves the merge.', resume=True)
                else:
                    self.defer(item, 'deferred: session unavailable')
                return
            if not job or not item['pr']:
                self.defer(item, 'deferred: PR metadata unavailable')
                return
            status, failing = self.github.checks(self.github_repo(item), item['pr'])
            self.log(item, 'approval checks: ' + status)
            if status == 'red':
                self.attention(item, 'escalation', 'failing check: ' + failing)
                return
            if status != 'green':
                return
            self.merge(item, job)
        if job and job['phase'] == 'merged' and item['session']['id']:
            self.launch(item, 'merged as ' + job['sha'], resume=True)

    def pr_checks(self, item, job):
        if job['phase'] != 'pr' or item['attention']:
            return
        # Recover PR number if creation succeeded but saving state did not.
        if item['pr'] is None:
            item['pr'] = (job['pr'] if job['tool'] == 'codex'
                          else self.github.open(self.github_repo(item), job['request']))
        status, failing = self.github.checks(self.github_repo(item), item['pr'])
        self.log(item, 'checks: ' + status)
        if status == 'red':
            self.attention(item, 'escalation', 'failing check: ' + failing)
        elif status == 'green':
            if item['stop_before_merge']:
                self.attention(item, 'merge', f'Approve PR #{item["pr"]}')
            elif job['tool'] == 'codex':
                if item['session'] and item['session']['id']:
                    self.launch(item, f'CI is green on PR #{item["pr"]}; merge it and continue.', resume=True)
                else:
                    self.defer(item, 'deferred: session unavailable')
            else:
                self.merge(item, job)

    def run(self):
        with Path(str(self.path) + '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.git.pull(self.path)
            orders_changed = self.orders.collect(self)
            self.data = state.load(self.path)
            if not self.data["slices"]:
                if orders_changed:
                    self.git.commit(self.path)
                return  # Nothing to mutate or commit in an empty scheduler.
            state_before = json.dumps(self.data, ensure_ascii=False, separators=(',', ':'))
            self.instant = self.clock()
            self.at = self.instant.isoformat()
            self.notices = []
            self.jobs = {}
            for path in sorted(self.runs.glob('*/job.json')):
                job = json.loads(path.read_text())
                previous = self.jobs.get(job['id'])
                if previous is None or previous['started_ns'] < job['started_ns']:
                    self.jobs[job['id']] = job
            for item in self.data['slices']:
                if item['state'] == 'accepted':
                    # An accepted slice's finished process must not hold a slot.
                    job = self.jobs.get(item['id'])
                    if job and job['phase'] == 'running':
                        # In memory only: the accepted slice's files stay as they are.
                        if self.processes.poll(job)[0]:
                            job['phase'] = 'collected'
                    continue
                try:
                    job = self.jobs.get(item['id'])
                    if job:
                        phase_before = job['phase']
                        if (phase_before in ('merged', 'node-step')
                                and not any(e['event'] == 'merged: ' + job['sha'] for e in item['log'])):
                            self.log(item, 'merged: ' + job['sha'], True)
                            item['attention'] = None
                            if phase_before == 'node-step':
                                self.attention(item, 'node-step', job['request']['node_steps'])
                        marker = 'collected turn: ' + Path(job['run']).name
                        if (job['phase'] in ('ended', 'collected', 'pr', 'usage-limit-wait')
                                and not any(e['event'] == marker for e in item['log'])):
                            item['session'] = {'tool': job['tool'], 'id': job['session'], 'folder': job['repo']}
                            item['state'] = 'issued'
                            self.apply_final(item, job)
                        else:
                            self.collect(item, job)
                        if phase_before == 'pr':
                            self.pr_checks(item, job)
                except Exception:
                    self.slice_failure(item, 'collect/deliver')
            for item in self.data['slices']:
                if item['state'] != 'accepted':
                    try:
                        self.deliver(item)
                    except Exception:
                        self.slice_failure(item, 'delivery')
            accepted = {s['id'] for s in self.data['slices'] if s['state'] == 'accepted'}
            for item in self.data['slices']:
                if (item['state'] == 'ready' and not item['paused'] and item['slot']
                        and datetime.fromisoformat(item['slot']) <= self.instant
                        and all(dep in accepted for dep in item['depends_on'])):
                    if item['brief'] is None:
                        self.attention(item, 'escalation', 'missing brief')
                        continue
                    brief = Path(item['brief'])
                    if not brief.is_absolute():
                        brief = self.path.parent / brief
                    try:
                        with brief.open(encoding='utf-8', newline='') as stream:
                            prompt = stream.read()
                        lines = prompt.splitlines(keepends=True)
                        if lines and lines[0].rstrip('\r\n') == '---':
                            closing = next((i for i in range(1, len(lines))
                                            if lines[i].rstrip('\r\n') == '---'), None)
                            if closing is not None:
                                prompt = ''.join(lines[closing + 1:])
                        self.launch(item, prompt)
                    except Exception:
                        self.slice_failure(item, 'start')
            changed = json.dumps(self.data, ensure_ascii=False, separators=(',', ':')) != state_before
            if changed or self.notices:
                state.save(self.path, self.data)
            if self.notices:
                outbox = Path(str(self.path) + '.outbox.jsonl')
                with outbox.open('a') as stream:
                    for notice in self.notices:
                        stream.write(json.dumps(notice, ensure_ascii=False) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
            if orders_changed or changed or self.notices:
                self.git.commit(self.path)
            busy = set()
            for item in self.data['slices']:
                job = self.jobs.get(item['id'])
                is_busy = (bool(job and job['phase'] == 'running')
                           or item['state'] in ('issued', 'escalated')
                           or bool(item['attention'] and item['attention'].get('answer') is None))
                if is_busy:
                    busy.add(self.repo(item))
            for folder in sorted({self.repo(item) for item in self.data['slices']}):
                if folder not in busy and folder.is_dir() and (folder / '.git').exists():
                    try:
                        self.git.tidy(folder, now=self.instant)
                    except Exception as error:
                        print(f'{folder.name}: tidy failed: {error}', file=sys.stderr)
