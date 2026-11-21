"""One scheduling explanation for the runner, planners and Workshop.

The optional ``_eligibility`` snapshot is transient: jobs, limits and provider
availability are observations, never part of the version 1 state document.
"""
import json
import os
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

from .attention import recipient
from .installation import installable, runs_path


def satisfied(item):
    if item['state'] == 'dropped':
        return False
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


def merged_since_start(item):
    for entry in reversed(item['log']):
        event = entry['event']
        if event.startswith('merged: ') and event.removeprefix('merged: ').strip():
            return True
        if event == 'started':
            return False
    return False


def eligibility(item, data):
    """Return a JSON explanation: status, with reason/ids/for where relevant."""
    if item['state'] == 'dropped':
        return {'status': 'dropped'}
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
            return {'status': 'failed'}
        if item['paused']:
            return {'status': 'waiting for a test or approval', 'reason': 'paused'}
        records = [entry.get('record') or {} for entry in (job or {}).get('requests', {}).values()]
        waiting = next((record for record in records if record.get('status') == 'waiting' and record.get('status_reason') == 'usage_limit'), None)
        if waiting:
            return {'status': 'waiting for a test or approval', 'reason': 'usage_limit', 'resume_at': waiting.get('resume_at')}
        if (job and job['phase'] == 'running') or (
                not job and item['state'] in ('issued', 'awaiting handover')):
            return {'status': 'resource busy', 'reason': 'repository busy', 'ids': [item['id']]}
        if item['state'] != 'ready' and not resumable:
            status = ('waiting for a decision' if item['state'] in ('planned', 'researching')
                      else 'waiting for a test or approval')
            return {'status': status, 'reason': item['state']}
        if not resumable:
            by_id = {s['id']: s for s in data['slices']}
            blocked = [dep for dep in item['depends_on']
                       if dep not in by_id or not satisfied(by_id[dep])]
            if blocked:
                return {'status': 'blocked', 'ids': blocked}
            if item.get('contract_step'):
                from .contract_drain import drain
                check = drain(item, data)
                if not check['passed']:
                    return {'status': 'blocked', 'reason': 'drain', 'detail': check['reason']}
    conflicting = [s['id'] for s in data['slices'] if s['id'] != item['id']
                   and s['state'] in ('issued', 'awaiting handover', 'escalated')
                   and not merged_since_start(s) and overlaps(item, s)]
    if conflicting:
        return {'status': 'resource busy', 'reason': 'overlapping files', 'ids': conflicting}
    return {'status': 'ready'}


def observed(data, path=None, *, limits=None):
    """Attach a read-only snapshot for UI/CLI; absence of a job is conservative."""
    path = Path(path or os.environ.get('CPLANE_STATE') or 'slices.json')
    jobs = {}
    for file in runs_path(path).glob('*/job.json'):
        try:
            job = json.loads(file.read_text())
            if job['id'] not in jobs or jobs[job['id']].get('started_ns', 0) < job.get('started_ns', 0):
                jobs[job['id']] = job
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return {**data, '_eligibility': {'jobs': jobs, 'state_path': path}}
