"""One locked scheduling pass. Adapters keep external effects fakeable."""
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import traceback
import uuid

from . import run_records
from . import state
from .orders import Collector
from .executors import Processes, atomic_json, FENCE_PARAGRAPH
from . import fence
from . import cut as cutter
from . import review as reviewer
from .text_bounds import ATTENTION_LIMIT, LOG_LIMIT, cut, cut_line
from .times import now
from .eligibility import eligibility

BOT_EVENTS = frozenset({'question', 'escalation', 'merge', 'owner-check', 'stuck', 'chat-paused', 'testing-review'})
BOT_ACCEPTED_FIELDS = frozenset({'id', 'repo', 'title', 'state', 'pr', 'feature', 'paused', 'attention'})


def stuck_since(item, instant):
    """Return the start and reason of a current stalled interval, if any."""
    if item['state'] != 'issued' or not item['log']:
        return None
    entries = item['log']
    last = datetime.fromisoformat(entries[-1]['at'])
    candidates = []
    if instant - last >= timedelta(minutes=20):
        candidates.append((last, 'no new log activity'))
    pending = None
    for entry in reversed(entries):
        event = entry['event']
        if event in ('checks: pending', 'approval checks: pending'):
            pending = datetime.fromisoformat(entry['at'])
        elif event.startswith(('checks: ', 'approval checks: ')):
            break
    if pending is not None and instant - pending > timedelta(minutes=10):
        candidates.append((pending, 'checks pending'))
    return min(candidates) if candidates else None


def export_bot(path):
    directory = os.environ.get('CPLANE_BOT_EXPORT')
    if not directory:
        return
    try:
        folder = Path(directory)
        if not folder.is_absolute():
            raise ValueError('export directory must be absolute')
        fence.trusted_directory(folder)
        with state.locked(path) as backend:
            data, notices = backend.load(), backend.notices()
            data['slices'] = [{key: value for key, value in item.items()
                               if (key in BOT_ACCEPTED_FIELDS if item['state'] == 'accepted'
                                   else key != 'log')}
                              for item in data['slices']]
            payload = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
            outbox = ''.join(json.dumps(notice, ensure_ascii=False) + '\n'
                             for _, notice in notices if notice.get('event') in BOT_EVENTS)
            outbox_path = folder / 'slices.json.outbox.jsonl'
            if outbox_path.exists() and not outbox.startswith(outbox_path.read_text(encoding='utf-8')):
                raise ValueError('notice history changed')
            gid = folder.stat().st_gid
            for destination, content in ((outbox_path, outbox), (folder / 'slices.json', payload)):
                name = None
                try:
                    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=folder,
                                                     prefix='.cplane-bot-', delete=False) as stream:
                        name = stream.name
                        os.fchown(stream.fileno(), -1, gid)
                        os.fchmod(stream.fileno(), 0o640)
                        stream.write(content)
                    os.replace(name, destination)
                finally:
                    if name is not None and os.path.exists(name):
                        os.unlink(name)
    except Exception:
        print('cplane: bot export failed', file=sys.stderr)


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
    root = fence.LOGIN_ROOT / 'codex/sessions'
    paths = Path(folder or root).rglob('*.jsonl')
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
        default = fence.LOGIN_ROOT / 'claude/usage-now.json'
        return json.loads(Path(path or default).read_text())
    except (OSError, ValueError):
        return None


class Git:
    def tidy(self, path, *, now=None):
        return

    def pull(self, path):
        if (path.parent / '.git').exists():
            fence.trusted_directory(path.parent)
            result = subprocess.run(['git', '-C', str(path.parent),
                                     '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                                     'pull', '--ff-only'], capture_output=True, text=True,
                                    env=fence.host_environment())
            if result.returncode:
                raise state.StateError('briefs fast-forward pull failed')

    def commit(self, path):
        state.commit_state(path, Path(str(path) + '.outbox.jsonl'), 'run', 'pass')

    def branch(self, path):
        raise state.StateError('host branch read refused in fenced mode')
class BlockedPR(state.StateError):
    pass


class GitHubReadError(state.StateError):
    pass


class GitHub:
    successful_reads = 0

    def repository(self, path):
        raise state.StateError('host origin read refused in fenced mode')

    def call(self, repo, *args):
        options = {'env': fence.github_environment([repo]), 'cwd': '/'}
        command = ['gh', *args] if args and args[0] == 'api' else ['gh', *args, '-R', repo]
        read = args[:2] in (('pr', 'view'), ('pr', 'list')) or args[:1] == ('api',)
        attempts = 3 if read else 1
        for attempt in range(attempts):
            result = subprocess.run(command, text=True, capture_output=True, **options)
            if not result.returncode:
                if read:
                    self.successful_reads += 1
                return result.stdout.strip()
            if attempt + 1 < attempts:
                time.sleep(5)
        if read:
            raise GitHubReadError('gh operation failed')
        raise state.StateError('gh operation failed')

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

    def checks(self, repo, number, expected=None):
        if expected:
            info = json.loads(self.call(repo, 'pr', 'view', str(number), '--json', 'headRefOid'))
            if info['headRefOid'] != expected:
                raise state.StateError('PR head differs from delivered bundle')
            info = json.loads(self.call(repo, 'api', f'repos/{repo}/actions/runs?head_sha={expected}&per_page=100'))
            runs = info['workflow_runs']
            jobs = []
            for run in runs:
                info = json.loads(self.call(repo, 'api', f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100"))
                jobs.extend(info['jobs'])
            passed = {job['name'] for job in jobs
                      if job['status'] == 'completed' and job['conclusion'] == 'success'}
            pending = not runs or not passed or any(run['status'] != 'completed' for run in runs)
            for job in jobs:
                if job['status'] != 'completed':
                    pending = True
                    continue
                conclusion = job['conclusion']
                if conclusion == 'cancelled' and job['name'] in passed:
                    continue
                if conclusion in ('failure', 'cancelled', 'timed_out', 'action_required', 'startup_failure'):
                    return 'red', job['name']
                if conclusion not in ('success', 'neutral', 'skipped'):
                    pending = True
            return ('pending' if pending else 'green'), ''
        info = json.loads(self.call(repo, 'pr', 'view', str(number), '--json', 'statusCheckRollup,headRefOid'))
        self.check_sha = info.get('headRefOid')
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

    def merge(self, repo, number, expected=None):
        fields = 'state,mergeCommit,title,headRefOid' if expected else 'state,mergeCommit,title'
        info = json.loads(self.call(repo, 'pr', 'view', str(number), '--json', fields))
        if expected and info['headRefOid'] != expected:
            raise state.StateError('PR head differs from delivered bundle')
        if info['state'] != 'MERGED':
            if re.match(r'(?:\[blocked\]|blocked:)', info['title'], re.I):
                raise BlockedPR('PR titled as blocked; not merged')
            self.call(repo, 'pr', 'merge', str(number), '--squash',
                      *(['--match-head-commit', expected] if expected else []))
            info = json.loads(self.call(repo, 'pr', 'view', str(number), '--json', 'state,mergeCommit'))
        return info['mergeCommit']['oid']


class Runner:
    def __init__(self, path, *, processes=None, github=None, git=None, clock=now,
                 codex_reader=codex_usage, claude_reader=claude_usage, runs=None, repos=None, orders=None):
        self.path = Path(path).expanduser().resolve()
        self.fence = fence.Fence()
        self.orders = orders or Collector()
        self.processes = processes or Processes()
        self.github = github or GitHub()
        self.git = git or Git()
        self.clock = clock
        self.codex_reader, self.claude_reader = codex_reader, claude_reader
        default_runs = '/srv/factory/runs'
        base = Path(runs or os.environ.get('CPLANE_RUNS', default_runs)).expanduser().resolve()
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
        run_records.owner_wait(self, item, close=True)
        body = cut(body, ATTENTION_LIMIT)
        item['attention'] = {'kind': kind, 'body': body, 'since': self.at, 'answer': None, 'approved': False}
        if kind == 'escalation':
            item['state'] = 'escalated'
        run_records.owner_wait(self, item)
        first_line = body.partition('\n')[0]
        self.log(item, f'{kind}: {first_line}', True)

    def slice_failure(self, item, stage):
        if isinstance(sys.exception(), fence.deny.Denied):
            self.attention(item, 'escalation', str(sys.exception()))
            return
        lines = traceback.format_exc().strip().splitlines()
        summary = f'{stage} failed: {lines[-1] if lines else "unknown error"}'
        self.attention(item, 'escalation', summary + ('\n' + '\n'.join(lines[-8:]) if lines else ''))

    def github_repo(self, item):
        return item['repo']

    def open_pr(self, repo, request):
        # All runner PR sends, including review and recovery, use the same gate
        # and per-pass visibility cache as bundle delivery.
        self.fence.check_request(repo, request)
        return self.github.open(repo, request)

    def save_job(self, job):
        atomic_json(Path(job['run']) / 'job.json', job)

    def execution(self, item):
        if state.postgres():
            return state.store(self.path).slice_executor(item)
        from .roles import DEFAULT_LEVELS
        return {**DEFAULT_LEVELS['standard'], **item['executor']}

    def choose(self, item, resume=False):
        execution = self.execution(item)
        model = execution['model']
        if resume:
            tool = item['session']['tool']
            model = self.jobs[item['id']]['model']
        else:
            tool = execution['tool']
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
                    return 'claude', model
            except (KeyError, TypeError):
                pass
        return None

    def eligibility_data(self, *, resources_only=False):
        limits = state.store(self.path).limit_show() if state.postgres() else dict(executors=2, repository_runs=1)
        return {**self.data, '_eligibility': dict(jobs=self.jobs, limits=limits,
                                                resources_only=resources_only,
                                                available=None if resources_only else lambda item: self.choose(item) is not None)}

    def room(self, item):
        result = eligibility(item, self.eligibility_data(resources_only=True))
        if result['status'] != 'resource busy':
            return None
        reason = result['reason']
        ids = ', '.join(result.get('ids', []))
        detail = f' (running: {ids})' if reason == 'executor limit' else f' ({ids})' if ids else ''
        return f'deferred: {reason}{detail}'

    def repo(self, item):
        name = item['repo'].split('/')[-1]
        if name in ('', '.', '..') or '\\' in name:
            raise state.StateError('invalid repository name')
        return (self.repos / name).resolve()

    def launch(self, item, prompt, resume=False, review=False):
        reason = self.room(item)
        if reason:
            self.defer(item, reason)
            return False
        choice = self.choose(item, resume)
        if choice is None:
            self.defer(item, 'deferred: capacity unavailable')
            return False
        tool, model = choice
        effort = self.execution(item)['effort']
        previous = self.jobs.get(item['id'])
        if resume and previous and bool(previous.get('fence')) != True:
            raise state.StateError('resume mode differs from saved job; needs attention')
        metadata = {}
        self.runs.mkdir(parents=True, mode=0o700, exist_ok=True)
        fence.trusted_directory(self.runs)
        metadata = (self.fence.resume(previous, item['session']['id']) if resume else
                    reviewer.prepare(self.fence, previous, uuid.uuid4().hex) if review else
                    self.fence.prepare(item['repo'], 'slice/' + item['id'].replace('/', '-'), uuid.uuid4().hex))
        folder = Path(metadata['repo'])
        run = self.runs / uuid.uuid4().hex
        run.mkdir(parents=True, mode=0o700)
        review = review or bool(resume and previous and previous.get('review') and not previous.get('sha'))
        cut_turn = item.get('flow', 'cli') == 'tickets' and not review and not (previous and previous.get('sha'))
        brief = previous.get('brief', '') if (resume or review) and previous else prompt
        skills = cutter.skills_version()
        if (cut_turn or review) and not resume:
            from .skills import instructions
            prompt = instructions('slice-review' if review else 'cut') + brief
        prompt += (f'\n\nRunner assignment: use branch {metadata["branch"]}. '
                   f'This assigned branch overrides any branch named in the brief. '
                   f'The pinned base commit is {metadata["base"]}.' + (
                       '\nCommit the tests on the assigned branch. End with kind "waiting", '
                       'ending the reply with the fenced JSON plan described above. '
                       'The runner delivers the commit and submits the tickets.'
                       if cut_turn else ('\nReview only; change nothing. End waiting with schema/review.schema.json.'
                                         if review else FENCE_PARAGRAPH)))
        job = {'id': item['id'], 'repo': str(folder), 'run': str(run), 'tool': tool,
               'model': model, 'effort': effort, 'prompt': prompt, 'started_ns': time.time_ns(),
               'session': item['session']['id'] if resume else '',
               'resume': item['session']['id'] if resume else None, 'phase': 'running'}
        job['skills'] = skills
        job['starting_commit'] = (metadata.get('base') if not resume else
                                  None)
        job.update(metadata, fence=True)
        if item.get('flow', 'cli') == 'tickets' or item.get('brief_id'):
            job.update(brief=brief, skills=skills)
        if review:
            job.update(review=True, repair=bool(previous.get('repair')))
        if resume and previous:
            for key in ('tip', 'repair', 'queue_slice'):
                if key in previous:
                    job[key] = previous[key]
        if resume and previous and previous.get('sha'):
            job['sha'] = previous['sha']
        run_records.owner_wait(self, item, close=True)
        run_records.launch_metadata(self, item, job)
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
        if session and (not isinstance(session, str) or not re.fullmatch(r'[A-Za-z0-9-]+', session)):
            raise state.StateError('fenced turn returned an invalid session; needs attention')
        if job.get('resume') and session and session != job['resume']:
            raise state.StateError('fenced resume returned a different session; needs attention')
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
        job['ended_at'] = run_records.end_time(job)
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
        if state.postgres():
            try:
                run_records.slice_record(state.store(self.path), item, job)
            except Exception:
                print('cplane: run recording failed', file=sys.stderr)
        final = job.get('final')
        if (isinstance(final, dict) and isinstance(final.get('kind'), str)
                and isinstance(final.get('body'), str)):
            item['final'] = {'kind': final['kind'], 'body': cut(final['body'], ATTENTION_LIMIT), 'at': self.at}
        if final and not job.get('session'):
            raise state.StateError('fenced turn has no session to resume; needs attention')
        cut_message = (usage_limit_message(job.get('tail', ''))
                       if job['tool'] == 'codex' and not final else None)
        if job['tool'] == 'codex' and job.get('pr'):
            item['pr'] = job['pr']
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
        elif job.get('review') and not job.get('sha') and final['kind'] == 'handover':
            self.attention(item, 'escalation', 'invalid review: expected waiting with review JSON')
        elif final['kind'] == 'handover':
            item['state'], item['attention'] = 'in review', None
            self.log(item, 'finished', True)
        elif final['kind'] in ('question', 'escalation'):
            self.attention(item, final['kind'], final['body'])
        elif job.get('sha'):
            # A post-merge turn only collects replies; it can never publish again.
            node_steps = final['body'].strip()
            match = re.match(r'\s*```(?:json)?\s*\n(.*?)\n```', final['body'], re.S)
            try:
                if match or node_steps.startswith('{'):
                    request = json.loads(match[1] if match else node_steps)
                    if not isinstance(request, dict) or 'node_steps' not in request:
                        raise ValueError('expected node_steps')
                    node_steps = request['node_steps']
                    if node_steps is not None and not isinstance(node_steps, str):
                        raise ValueError('invalid node_steps')
                    node_steps = (node_steps or '').strip()
            except ValueError as error:
                self.attention(item, 'escalation', 'invalid post-merge request: ' + str(error))
            else:
                if node_steps:
                    job['phase'] = 'node-step'
                    self.attention(item, 'node-step', node_steps)
                else:
                    item['state'], item['attention'] = 'in review', None
                    self.log(item, 'finished', True)
        elif job.get('review') and final['kind'] == 'waiting':
            self.apply_review(item, job, final['body'])
        elif item.get('flow', 'cli') == 'tickets' and final['kind'] == 'waiting':
            try:
                blocks = list(re.finditer(r'^```(?:json)?[ \t]*\r?\n(.*?)\r?\n```[ \t]*$',
                                          final['body'], re.S | re.M))
                if not blocks:
                    raise state.StateError('invalid plan: expected fenced JSON')
                try:
                    plan = json.loads(blocks[-1][1])
                except ValueError:
                    raise state.StateError('invalid plan: expected fenced JSON') from None
                cutter.validate_plan(plan)
                # Validate brief rules before publishing anything.
                cutter.sections(job['brief'], item['id'])
            except state.StateError:
                # Record the rejected turn alongside its escalation in state, so
                # an answer can resume it without replaying the same final.
                self.log(item, 'collected turn: ' + Path(job['run']).name)
                raise
            if item['attention'] and item['attention']['answer'] is not None:
                item['attention'] = None
            tickets = cutter.status(item['id'])
            if tickets:
                # Workers may already have advanced the branch; only follow it.
                self.follow_tickets(item, job, tickets)
            else:
                job['tip'] = job.get('tip') or self.fence.publish(job, {'branch': job['branch']})
                job['task_file'] = cutter.build_task_file(item['id'], item['repo'], job['branch'],
                                                         job['tip'], plan, job['brief'])
                job['phase'] = 'cut-ready'
                self.save_job(job)
                self.submit_tickets(item, job)
        elif (final['kind'] == 'waiting' or job['tool'] == 'claude') and re.match(r'\s*```', final['body']):
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
                self.attention(item, 'escalation', 'invalid fenced PR request: ' + str(error))
            else:
                job['tip'] = self.fence.publish(job, request)
                job['request'], job['phase'] = request, 'pr'
                self.save_job(job)
                item['pr'] = self.open_pr(self.github_repo(item), request)
                self.log(item, f'opened PR: {item["pr"]}', True)
        else:
            self.attention(item, 'node-step', final['body'])
        if job['phase'] == 'ended':
            job['phase'] = 'collected'
        self.log(item, 'collected turn: ' + Path(job['run']).name)
        self.save_job(job)
        if item['state'] == 'in review' and final['kind'] == 'handover' and state.postgres():
            state.store(self.path).chat_handover(item, final['body'])

    def apply_review(self, item, job, body):
        match = re.match(r'\s*```(?:json)?[ \t]*\n(.*?)\n```', body, re.S)
        try:
            answer = json.loads(match[1]) if match else None
        except ValueError:
            raise state.StateError('invalid review: expected fenced JSON') from None
        run_records.review_record(self, job, answer)
        if answer['verdict'] == 'pass':
            job['request'] = dict(branch=job['branch'], title=answer['title'],
                                  body=answer['body'], node_steps=None)
            job['phase'] = 'pr'
            self.save_job(job)
            item['pr'] = self.open_pr(self.github_repo(item), job['request'])
            self.log(item, f'opened PR: {item["pr"]}', True)
        elif job.get('repair'):
            self.ticket_attention(item, 'escalation', 'slice review still needs fixes after repair:\n' + json.dumps(answer))
        else:
            # Save the repair plan before any queue effect; subsequent passes use
            # the same submission-intent protocol as the initial cut.
            queue_slice = item['id'] + '/repair'
            job.update(repair=True, queue_slice=queue_slice,
                       task_file=cutter.build_task_file(queue_slice, item['repo'], job['branch'],
                                                        job['tip'], {key: answer[key] for key in ('tickets', 'test_files')},
                                                        job['brief']), phase='cut-ready')
            self.save_job(job)
            self.submit_tickets(item, job)

    def ticket_attention(self, item, kind, body):
        body = cut(body, ATTENTION_LIMIT)
        existing = item['attention']
        if not existing or existing['kind'] != kind or existing['body'] != body:
            self.attention(item, kind, body)

    def follow_tickets(self, item, job, tickets):
        job['phase'] = 'tickets'
        self.save_job(job)
        failed = next((t for t in tickets if t['status'] in ('failed', 'escalated')), None)
        if failed:
            self.ticket_attention(item, 'escalation', f"ticket {failed['id']} ({failed['title']}): {failed['status']}: {failed['reason'] or ''}")
        elif tickets and all(t['status'] == 'done' for t in tickets):
            # Continue runs stopped by the former tickets-done placeholder.
            attention = item['attention']
            if attention and attention['kind'] == 'node-step' and attention['body'] == 'tickets done':
                item['attention'] = None
            job['phase'] = 'review-ready'
            self.save_job(job)
        elif not tickets:
            self.ticket_attention(item, 'escalation', 'tickets missing from queue; needs attention')

    def submit_tickets(self, item, job):
        tickets = cutter.status(job.get('queue_slice', item['id']))
        if tickets:
            self.follow_tickets(item, job, tickets)
            return
        if job['phase'] != 'cut-ready':
            self.ticket_attention(item, 'escalation', 'ticket submission failed or interrupted; will not retry')
            return
        # Durable before the external call: even a crash or invalid reply cannot retry.
        job['phase'] = 'submitting'
        self.save_job(job)
        try:
            ids = cutter.submit(job['task_file'])
        except Exception:
            job['phase'] = 'submit-failed'
            self.save_job(job)
            raise
        job['phase'], job['ticket_ids'] = 'tickets', ids
        self.save_job(job)
        self.log(item, f"cut-submit: skills {job['skills']}")
        self.log(item, f'Submitted {len(ids)} tickets: ' + json.dumps(ids), True)

    def merge(self, item, job):
        if reviewer.changes_workflows(self.fence, job):
            approval = item['attention']
            if not (approval and approval['kind'] == 'merge' and approval['approved']):
                self.attention(item, 'merge', f'Approve PR #{item["pr"]}: workflow changes')
                return
        options = {'expected': job['tip']}
        try:
            sha = self.github.merge(self.github_repo(item), item['pr'], **options)
        except BlockedPR as error:
            self.attention(item, 'escalation', str(error))
            return
        run_records.owner_wait(self, item, job, close=True)
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
        run_records.owner_wait(self, item, job)
        attention = item['attention']
        if job and job['phase'] == 'review-ready':
            if attention and attention['answer'] is not None:
                item['attention'] = attention = None
            if not attention and not item['paused']:
                self.launch(item, job['brief'], review=True)
            return
        if item['paused']:
            return
        if job and job['phase'] in ('cut-ready', 'submitting', 'submit-failed', 'tickets'):
            return
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
            if not job or not item['pr']:
                self.defer(item, 'deferred: PR metadata unavailable')
                return
            options = {'expected': job['tip']}
            status, failing = self.github.checks(self.github_repo(item), item['pr'], **options)
            run_records.ci_record(self, item, job, status, failing)
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
        if job['phase'] != 'pr' or item['attention'] or item['paused']:
            return
        # Recover PR number if creation succeeded but saving state did not.
        if item['pr'] is None:
            item['pr'] = self.open_pr(self.github_repo(item), job['request'])
        options = {'expected': job['tip']}
        status, failing = self.github.checks(self.github_repo(item), item['pr'], **options)
        run_records.ci_record(self, item, job, status, failing)
        self.log(item, 'checks: ' + status)
        if status == 'red':
            self.attention(item, 'escalation', 'failing check: ' + failing)
        elif status == 'green':
            if item['stop_before_merge']:
                self.attention(item, 'merge', f'Approve PR #{item["pr"]}')
            else:
                self.merge(item, job)

    def run(self):
        self._run_pass()
        export_bot(self.path)

    def _run_pass(self):
        self.fence.begin_pass()
        with state.locked(self.path):
            self.git.pull(self.path)
            orders_changed = self.orders.collect(self)
            pipeline_order = []
            self.instant = self.clock()
            self.at = self.instant.isoformat()
            if state.postgres():
                try:
                    pipeline_order = state.store(self.path).pipeline_step(self.at)
                except Exception:
                    print('pipeline step failed', file=sys.stderr)
            self.data = state.load(self.path)
            if state.postgres():
                state.store(self.path).route_chat_events()
                self.data = state.load(self.path)
            if not self.data["slices"]:
                if orders_changed:
                    self.git.commit(self.path)
                return  # Nothing to mutate or commit in an empty scheduler.
            state_before = json.dumps(self.data, ensure_ascii=False, separators=(',', ':'))
            self.notices = []
            self.jobs = {}
            for path in sorted(self.runs.glob('*/job.json')):
                job = json.loads(path.read_text())
                previous = self.jobs.get(job['id'])
                if previous is None or previous['started_ns'] < job['started_ns']:
                    self.jobs[job['id']] = job
            read_failures, read_successes = set(), set()
            for item in self.data['slices']:
                read_start = self.github.successful_reads if isinstance(self.github, GitHub) else 0
                run_records.owner_wait(self, item)
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
                        if bool(job.get('fence')) != True:
                            raise state.StateError('run mode differs from saved job; needs attention')
                        phase_before = job['phase']
                        if phase_before in ('cut-ready', 'submitting', 'submit-failed', 'tickets', 'review-ready'):
                            if item['state'] == 'ready':
                                item['state'] = 'issued'
                            item['session'] = {'tool': job['tool'], 'id': job['session'], 'folder': job['repo']}
                            if phase_before == 'tickets':
                                self.follow_tickets(item, job, cutter.status(job.get('queue_slice', item['id'])))
                            elif phase_before != 'review-ready' and (phase_before != 'cut-ready' or (not item['attention'] and not item['paused'])):
                                self.submit_tickets(item, job)
                            continue
                        if (phase_before in ('merged', 'node-step')
                                and not any(e['event'] == 'merged: ' + job['sha'] for e in item['log'])):
                            self.log(item, 'merged: ' + job['sha'], True)
                            item['attention'] = None
                            if phase_before == 'node-step':
                                self.attention(item, 'node-step', job['request']['node_steps'])
                        marker = 'collected turn: ' + Path(job['run']).name
                        if ((job['phase'] in ('ended', 'collected', 'pr', 'usage-limit-wait')
                             or (job['phase'] == 'node-step' and job.get('sha')
                                 and (job.get('final') or {}).get('kind') == 'waiting'))
                                and not any(e['event'] == marker for e in item['log'])):
                            item['session'] = {'tool': job['tool'], 'id': job['session'], 'folder': job['repo']}
                            item['state'] = 'issued'
                            self.apply_final(item, job)
                        else:
                            self.collect(item, job)
                        if phase_before == 'pr':
                            self.pr_checks(item, job)
                except GitHubReadError:
                    read_failures.add(item['id'])
                except Exception:
                    self.slice_failure(item, 'collect/deliver')
                finally:
                    if isinstance(self.github, GitHub) and self.github.successful_reads > read_start:
                        read_successes.add(item['id'])
            from . import installation
            installation.process(self)
            for item in self.data['slices']:
                read_start = self.github.successful_reads if isinstance(self.github, GitHub) else 0
                if item['state'] != 'accepted' and item['id'] not in read_failures:
                    try:
                        self.deliver(item)
                    except GitHubReadError:
                        read_failures.add(item['id'])
                    except Exception:
                        self.slice_failure(item, 'delivery')
                    finally:
                        if isinstance(self.github, GitHub) and self.github.successful_reads > read_start:
                            read_successes.add(item['id'])
                job = self.jobs.get(item['id'])
                if job and item['id'] in read_failures:
                    job.setdefault('github_read_failure_since', self.at)
                    job.pop('github_read_failures', None)
                    self.save_job(job)
                    self.log(item, 'checks: pending')
                    if self.instant - datetime.fromisoformat(job['github_read_failure_since']) >= timedelta(seconds=1500):
                        self.attention(item, 'escalation', 'GitHub reads failed continuously for 25 minutes')
                elif job and item['id'] in read_successes and (job.get('github_read_failure_since')
                                                              or job.get('github_read_failures')):
                    job.pop('github_read_failure_since', None)
                    job.pop('github_read_failures', None)
                    self.save_job(job)
            by_id = {s['id']: s for s in self.data['slices']}
            start_order = [by_id[key] for key in pipeline_order]
            start_order.extend(s for s in self.data['slices'] if s['id'] not in pipeline_order)
            if state.postgres():
                start_order = state.store(self.path).ordered_slices(start_order)
            for item in start_order:
                if (item['state'] == 'ready' and not item['paused'] and item['slot']
                        and datetime.fromisoformat(item['slot']) <= self.instant):
                    result = eligibility(item, self.eligibility_data())
                    if result['status'] != 'ready':
                        if result['status'] == 'resource busy':
                            self.defer(item, 'deferred: capacity unavailable'
                                       if result['reason'] == 'provider away' else self.room(item))
                        continue
                    if item.get('brief_id'):
                        try:
                            prompt = state.store(self.path).stored_brief(item['brief_id'])
                            self.launch(item, prompt)
                        except Exception:
                            self.slice_failure(item, 'start')
                        continue
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
            previous_notices = state.store(self.path).notices()
            seen = {(notice.get('id'), notice.get('since'), notice.get('reason'))
                    for _, notice in previous_notices if notice.get('event') == 'stuck'}
            for item in self.data['slices']:
                stalled = stuck_since(item, self.instant)
                if stalled:
                    since, reason = stalled
                    key = (item['id'], since.isoformat(), reason)
                    if key not in seen:
                        self.notices.append(dict(at=self.at, id=item['id'], event='stuck',
                                                 text=f'Stuck: {reason}', since=key[1], reason=reason))
            changed = json.dumps(self.data, ensure_ascii=False, separators=(',', ':')) != state_before
            if changed or self.notices:
                if state.postgres():
                    backend = state.store(self.path)
                    backend.save(self.data)
                    backend.route_chat_events()
                    backend.append_notices(self.notices)
                else:
                    state.save(self.path, self.data, self.notices)
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
