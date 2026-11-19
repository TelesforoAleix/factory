"""Fixed platform judge, safe diff assets, and the judge's calibration command."""

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from . import evals, run_platform, run_records, skills
from .state import StateError

JUDGE = 'claude/opus'
EXECUTOR = {'harness': 'claude', 'model': 'opus'}
ASSET_LIMIT = 200_000


def prompt():
    raw = (skills.ROOT / 'judge.md').read_bytes()
    return raw.decode().split('\n', 1)[1], hashlib.sha256(raw).hexdigest()


def diff_parts(patch):
    """Keep whole file entries, including quoted paths, renames and binaries."""
    quoted = r'"(?:[^"\\]|\\.)*"'
    parts = []
    for block in re.split(r'(?m)(?=^diff --git )', patch):
        if not block:
            continue
        header = block.splitlines()[0]
        match = re.fullmatch(r'diff --git (' + quoted + r'|a/.*?) (' + quoted + r'|b/.*)', header)
        if match is None:
            raise StateError('Invalid judge diff paths')
        try:
            old, new = (ast.literal_eval('b' + p).decode('utf-8') if p.startswith('"') else p
                        for p in match.groups())
        except (ValueError, SyntaxError, UnicodeError):
            raise StateError('Invalid judge diff paths') from None
        if not old.startswith('a/') or not new.startswith('b/'):
            raise StateError('Invalid judge diff paths')
        changed, in_hunk = 0, False
        for line in block.splitlines()[1:]:
            if line.startswith('@@ '):
                in_hunk = True
            elif in_hunk and line.startswith(('+', '-')):
                changed += 1
        parts.append((old[2:], new[2:], block, changed))
    return parts


def test_file(path):
    path = Path(path)
    return (any(p.lower() in ('test', 'tests', '__tests__') for p in path.parts[:-1])
            or path.name.startswith('test_')
            or bool(re.search(r'_test\.[^.]+$|\.(?:test|spec)\.|Tests?\.swift$', path.name)))


def visible_diff(case, patch):
    hidden = set(case.get('hidden_paths') or [])
    return ''.join(block for old, new, block, _ in diff_parts(patch)
                   if not any(p == h or p.startswith(h.rstrip('/') + '/')
                              for p in (old, new) for h in hidden))


def removed_part(case):
    """Remove the largest non-test file by changed lines; break ties by path."""
    reference = visible_diff(case, case['reference_diff'])
    parts = diff_parts(reference)
    candidates = [p for p in parts if not test_file(p[0]) and not test_file(p[1])]
    if not candidates:
        return None
    removed = min(candidates, key=lambda p: (-p[3], p[1], p[0]))
    return ''.join(p[2] for p in parts if p is not removed), removed[1]


def request(case, patch, *, request_id, set_id, goal=None):
    goal, digest = (prompt() if goal is None else goal)
    assets = []
    for name, asset_type, text in (('task.md', 'text/markdown', case['task']),
                                   ('attempt.patch', 'text/x-diff', visible_diff(case, patch)),
                                   ('reference.patch', 'text/x-diff', visible_diff(case, case['reference_diff']))):
        assets.append(dict(name=name, type=asset_type, version='1', text=text,
                           sha256=hashlib.sha256(text.encode()).hexdigest()))
    if sum(len(a['text'].encode()) for a in assets) > ASSET_LIMIT or len(goal) > 200_000:
        raise StateError('inputs too large')
    return dict(contract=1, request_id=request_id, attribution={'slice': 'eval-judge'},
                repository=case['repository'], base_commit=case['base_commit'],
                mode='read', role='review', level=case.get('level') or 'standard',
                work=dict(goal=goal, allowed_files=None, pinned_paths=[], check_command=None),
                assets=assets, after=[], priority=0,
                eval=dict(set=set_id, case='case' + hashlib.sha256(case['id'].encode()).hexdigest()[:32],
                          executor=dict(EXECUTOR))), digest


def outcome(record):
    """Read the final fenced verdict, allowing reasoning before that block."""
    final = run_records.run_final(record) or {}
    status = record.get('status')
    if status in ('queued', 'running') or (status == 'waiting' and record.get('status_reason') == 'usage_limit'):
        return None
    if status != 'done':
        return dict(judge=None, judge_error=final.get('body') or str(record.get('status_reason') or status))
    blocks = re.findall(r'```(?:json)?[ \t]*\r?\n(.*?)\r?\n```', final.get('body') or '', re.DOTALL)
    try:
        answer = json.loads(blocks[-1]) if blocks else None
        if (not isinstance(answer, dict) or set(answer) != {'verdict', 'reason'}
                or answer['verdict'] not in ('mergeable', 'not_mergeable')
                or not isinstance(answer['reason'], str) or not answer['reason'].strip()):
            raise ValueError
    except (ValueError, TypeError):
        return dict(judge=None, judge_error='Judge run ended without a valid verdict')
    return dict(judge=answer['verdict'], reason=answer['reason'])


def record_verdict(store, attempt, digest, answer):
    # A saved completion can outlive a rolled back transaction. Replay the same
    # verdict, but do not turn recovery into a second grading operation.
    if not evals._rows(store, 'SELECT id FROM cplane_eval_verdicts WHERE attempt=%s AND judge=%s AND prompt_hash=%s',
                       (attempt, JUDGE, digest)):
        evals.verdict_add(store, attempt, judge=JUDGE, prompt_hash=digest,
                          verdict=answer['judge'], reason=answer['reason'])


def advance(runner, store, job):
    """Advance grading from the durable patch without changing slice execution."""
    result = job['completion']['result']
    if 'judge_outcome' not in job:
        if 'judge' not in job['requests']:
            try:
                output = job['completion'].get('output_ref')
                if not output:
                    raise StateError('Attempt has no stored diff')
                body, digest = request(job['case'], Path(output).read_bytes().decode(),
                                       request_id=runner.request_id(job['item'], job, 'judge'),
                                       set_id=f"run{job['eval_run']}")
                job['requests']['judge'] = dict(request=body, run_id=None, record=None, turn=0,
                                               prompt_hash=digest,
                                               context=[dict(kind='skill', name='judge', sha256=digest)])
                runner.save_job(job)
            except (OSError, UnicodeError, StateError) as error:
                job['judge_outcome'] = dict(judge=None, judge_error=str(error))
        if 'judge_outcome' not in job:
            entry = job['requests']['judge']
            runner.send_request(job, entry)
            entry['record'] = runner.client.get(entry['run_id'])
            answer = outcome(entry['record'])
            runner.save_job(job)
            if answer is None:
                return False
            job['judge_outcome'] = answer
        runner.save_job(job)
    answer = job['judge_outcome']
    if answer['judge'] is not None:
        record_verdict(store, job['eval_attempt'], job['requests']['judge']['prompt_hash'], answer)
    result.update({k: v for k, v in answer.items() if k != 'reason'})
    runner.save_job(job)
    return True


def wait(client, identity):
    while True:
        record = client.get(identity)
        answer = outcome(record)
        if answer is not None:
            return answer, record
        time.sleep(1)


def judge_attempt(store, attempt_id, *, client=None):
    """Judge a finished attempt. Persist submission intent next to its patch."""
    import fcntl
    from psycopg.types.json import Jsonb
    from .eval_runner import metrics
    from .executors import atomic_json

    goal = prompt()
    with store.locked():
        rows = evals._rows(store, 'SELECT * FROM cplane_eval_attempts WHERE id=%s', (attempt_id,))
        if not rows or rows[0]['state'] not in ('done', 'failed'):
            raise StateError('Judge requires a finished attempt')
        attempt = rows[0]
        case = evals._rows(store, 'SELECT * FROM cplane_eval_cases WHERE id=%s', (attempt['case'],))[0]
    if case['kind'] != 'slice':
        raise StateError('Judge requires a slice case')
    if not attempt['output_ref']:
        raise StateError('Attempt has no stored diff')
    target = Path(attempt['output_ref']).parent / ('judge-' + goal[1] + '.json')
    with (target.parent / 'judge.lock').open('a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        with store.locked():
            if evals._rows(store, 'SELECT id FROM cplane_eval_verdicts WHERE attempt=%s AND judge=%s AND prompt_hash=%s',
                           (attempt_id, JUDGE, goal[1])):
                raise StateError('Verdict already exists for this judge and prompt hash')
        entry = json.loads(target.read_text()) if target.exists() else None
        if entry is None or entry.get('completed'):
            try:
                body, digest = request(case, Path(attempt['output_ref']).read_bytes().decode(),
                                       request_id='eval-judge-' + uuid.uuid4().hex,
                                       set_id=f"run{attempt['eval_run']}", goal=goal)
            except (OSError, UnicodeError) as error:
                raise StateError('Attempt diff unavailable') from error
            except StateError as error:
                if str(error) != 'inputs too large':
                    raise
                answer = dict(judge=None, judge_error='inputs too large')
                with store.mutation():
                    result = {**(attempt['result'] or {}), **answer}
                    store.connection.execute('UPDATE cplane_eval_attempts SET result=%s WHERE id=%s', (Jsonb(result), attempt_id))
                return answer
            entry = dict(request=body, run_id=None, prompt_hash=digest)
            atomic_json(target, entry)
        client = client or run_platform.Client()
        if entry['run_id'] is None:
            entry['run_id'] = client.submit(entry['request'])
            atomic_json(target, entry)
        with store.mutation():
            store.connection.execute(
                'INSERT INTO cplane_eval_attempt_runs (attempt, position, role, purpose, run_id) '
                "SELECT %s, COALESCE(MAX(position),0)+1, 'review', %s, %s FROM cplane_eval_attempt_runs WHERE attempt=%s "
                'ON CONFLICT DO NOTHING', (attempt_id, 'judge-' + goal[1], entry['run_id'], attempt_id))
        answer, record = wait(client, entry['run_id'])
        with store.locked():
            links = evals.attempt_run_list(store, attempt_id)
        # API reads may take time; do not hold the scheduler's database lock.
        records = {link['run_id']: dict(request={'role': link['role']},
                                        record=client.get(link['run_id'])) for link in links}
        with store.mutation():
            if answer['judge'] is not None:
                evals.verdict_add(store, attempt_id, judge=JUDGE, prompt_hash=goal[1],
                                  verdict=answer['judge'], reason=answer['reason'])
            current = evals._rows(store, 'SELECT result FROM cplane_eval_attempts WHERE id=%s', (attempt_id,))[0]
            result = dict(current['result'] or {})
            result.pop('judge_error', None)
            result.update({k: v for k, v in answer.items() if k != 'reason'})
            # Recompute from the ledger so retrying a failed grade cannot count
            # the same run twice. All earlier pipeline runs remain linked.
            total = metrics(dict(requests=records))
            store.connection.execute('UPDATE cplane_eval_attempts SET result=%s, metrics=%s WHERE id=%s',
                                     (Jsonb(result), Jsonb(total), attempt_id))
        entry['completed'] = True
        atomic_json(target, entry)
        return answer


def judge_test(store, selector, *, client=None):
    identifier, separator, version = selector.rpartition(':')
    if not separator:
        identifier, version = selector, None
    else:
        try:
            version = int(version)
        except ValueError:
            raise StateError('Set version must be an integer') from None
    selected = evals.set_show(store, identifier, version)
    with store.locked():
        cases = [c for c in evals._rows(store, 'SELECT * FROM cplane_eval_cases ORDER BY id')
                 if c['id'] in selected['members'] and c['kind'] == 'slice' and c['reference_diff']]
    report = dict(set=identifier, version=selected['version'], skipped=0, cases=[])
    goal = prompt()
    pending = []
    client = client or run_platform.Client()
    invocation = uuid.uuid4().hex
    for index, case in enumerate(cases):
        removed = removed_part(case)
        if removed is None:
            report['skipped'] += 1
            report['cases'].append(dict(case=case['id'], skipped='no non-test file'))
            continue
        row = dict(case=case['id'], removed_file=removed[1])
        report['cases'].append(row)
        for label, patch in (('reference', case['reference_diff']), ('removed', removed[0])):
            try:
                body, _ = request(case, patch, request_id=f'judge-test-{invocation}-{index}-{label}',
                                  set_id='judge-test', goal=goal)
            except StateError as error:
                row[label] = dict(judge=None, judge_error=str(error))
                continue
            pending.append((row, label, client.submit(body)))
    for row, label, identity in pending:
        row[label], _ = wait(client, identity)
    graded = [r for r in report['cases'] if 'skipped' not in r]
    for label, expected in (('reference', 'mergeable'), ('removed', 'not_mergeable')):
        passed = sum(r[label]['judge'] == expected for r in graded)
        report[label] = dict(passed=passed, total=len(graded), rate=passed / len(graded) if graded else 0)
    report['passed'] = all(report[k]['rate'] >= 0.9 for k in ('reference', 'removed'))
    return report
