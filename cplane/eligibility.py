"""One scheduling explanation for the runner, planners and Workshop.

The optional ``_eligibility`` snapshot is transient: jobs, limits and provider
availability are observations, never part of the version 1 state document.
"""
from fnmatch import fnmatchcase
from functools import lru_cache
import json
import os
from pathlib import Path

from .attention import recipient
from .installation import installable, runs_path


def satisfied(item):
    if item['state'] == 'accepted':
        return True
    events = [entry['event'] for entry in item['log']]
    merged = next((i for i in reversed(range(len(events)))
                   if events[i].startswith('merged: ')), None)
    if merged is None:
        return False
    sha = events[merged].removeprefix('merged: ')
    return bool(sha) and (not installable(item) or any(
        event == 'Installed ' + sha or event.startswith('Installed ' + sha + '. ')
        for event in events[merged + 1:]))


def _tokens(pattern):
    tokens = []
    i = 0
    while i < len(pattern):
        end = i + 1
        if pattern[i] == '[':
            end += pattern[end:end + 1] == '!'
            end += pattern[end:end + 1] == ']'
            close = pattern.find(']', end)
            end = close + 1 if close >= 0 else i + 1
        tokens.append(pattern[i:end])
        i = end
    return tokens


@lru_cache(maxsize=4096)
def patterns_overlap(left, right):
    """Decide whether two fnmatch globs have any common matching string.

    Walk their product automaton. Literal characters and class range endpoints
    partition Unicode into equivalent character choices; adjacent code points
    provide witnesses for the remaining intervals, including negated classes.
    Stars match slashes, as in Python fnmatch (including **).
    """
    a, b = _tokens(left), _tokens(right)
    points = {0, 0x10ffff}
    for char in left + right:
        points.update(n for n in (ord(char) - 1, ord(char), ord(char) + 1)
                      if 0 <= n <= 0x10ffff)
    alphabet = [chr(n) for n in points]
    pending, seen = [(0, 0)], set()
    while pending:
        i, j = pending.pop()
        if (i, j) in seen:
            continue
        seen.add((i, j))
        if i == len(a) and j == len(b):
            return True
        if i < len(a) and a[i] == '*':
            pending.append((i + 1, j))
        if j < len(b) and b[j] == '*':
            pending.append((i, j + 1))
        if i < len(a) and j < len(b) and any(
                fnmatchcase(char, a[i]) and fnmatchcase(char, b[j]) for char in alphabet):
            pending.append((i if a[i] == '*' else i + 1,
                            j if b[j] == '*' else j + 1))
    return False


def overlaps(left, right):
    if left['repo'].casefold() != right['repo'].casefold():
        return False
    a, b = left.get('allowed_files'), right.get('allowed_files')
    # Missing, null and empty lists all retain the conservative legacy scope.
    return not a or not b or any(patterns_overlap(x, y) for x in a for y in b)


def eligibility(item, data):
    """Return a JSON explanation: status, with reason/ids/for where relevant."""
    context = data.get('_eligibility', {})
    resources_only = context.get('resources_only', False)
    if not resources_only:
        attention = item.get('attention')
        if attention and ((attention['kind'] == 'merge' and not attention['approved'])
                          or (attention['kind'] != 'merge' and attention['answer'] is None)):
            status = ('waiting for a test or approval' if attention['kind'] in
                      ('merge', 'node-step', 'owner-check') else 'waiting for a decision')
            return dict(status=status, **{'for': recipient(item, attention)})
        job = context.get('jobs', {}).get(item['id'])
        resumable = bool(job and item.get('session') and (
            (attention and attention['answer'] is not None)
            or (not attention and job['phase'] in ('merged', 'review-ready'))))
        if item['state'] == 'escalated' and not resumable:
            return dict(status='failed')
        if item['paused']:
            return dict(status='waiting for a test or approval', reason='paused')
        if (job and job['phase'] == 'running') or (
                not job and item['state'] in ('issued', 'awaiting handover')):
            return dict(status='resource busy', reason='repository busy', ids=[item['id']])
        if item['state'] != 'ready' and not resumable:
            status = ('waiting for a decision' if item['state'] in ('planned', 'researching')
                      else 'waiting for a test or approval')
            return dict(status=status, reason=item['state'])
        if not resumable:
            by_id = {s['id']: s for s in data['slices']}
            blocked = [dep for dep in item['depends_on']
                       if dep not in by_id or not satisfied(by_id[dep])]
            if blocked:
                return dict(status='blocked', ids=blocked)
    jobs = context.get('jobs', {})
    limits = context.get('limits', dict(executors=2, repository_runs=1))
    running = {key: job.get('repository', '') for key, job in jobs.items()
               if job['phase'] == 'running' and key != item['id']}
    # Attention is an ended turn's durable wait when its local job is absent.
    # A positively live job still holds capacity, even with open attention.
    for other in data['slices']:
        if (other['id'] != item['id'] and other['id'] not in jobs
                and other['state'] in ('issued', 'awaiting handover')
                and not other.get('attention')):
            running[other['id']] = other['repo']
    if len(running) >= limits['executors']:
        return dict(status='resource busy', reason='executor limit', ids=sorted(running))
    busy = [key for key, repo in running.items() if repo.casefold() == item['repo'].casefold()]
    if busy and limits['repository_runs'] == 1:
        return dict(status='resource busy', reason='repository busy', ids=sorted(busy))
    conflicting = [s['id'] for s in data['slices'] if s['id'] != item['id']
                   and s['state'] in ('issued', 'awaiting handover', 'escalated')
                   and overlaps(item, s)]
    if conflicting:
        return dict(status='resource busy', reason='overlapping files', ids=conflicting)
    available = context.get('available')
    if (context.get('providers', {}).get(item['id']) is False
            or (available is not None and not available(item))):
        return dict(status='resource busy', reason='provider away')
    return dict(status='ready')


def observed(data, path=None, *, limits=None):
    """Attach a read-only snapshot for UI/CLI; absence of a job is conservative."""
    from . import state
    from .runner import Runner
    path = Path(path or os.environ.get('CPLANE_STATE') or 'slices.json')
    jobs = {}
    for file in runs_path(path).glob('*/job.json'):
        try:
            job = json.loads(file.read_text())
            if job['id'] not in jobs or jobs[job['id']].get('started_ns', 0) < job.get('started_ns', 0):
                jobs[job['id']] = job
        except (OSError, ValueError, KeyError, TypeError):
            continue
    runner = Runner(path)
    from .times import now
    runner.instant, runner.jobs = now(), jobs
    providers = {item['id']: runner.choose(item) is not None for item in data['slices']}
    return {**data, '_eligibility': dict(jobs=jobs, limits=limits or dict(executors=2, repository_runs=1),
                                        providers=providers)}
