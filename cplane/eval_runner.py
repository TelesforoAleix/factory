"""Runner-only eval execution. No delivery, grading, or slice run records."""
import json
import os
from pathlib import Path
import re
import time
import uuid

from . import evals, fence, run_records
from .executors import read_output

LEAD = ('Make the change in this working tree; do not branch, commit, push or open a PR; '
        'stop when the change is done.\n\n')
TIMEOUT = 30 * 60


def _finish(store, attempt, status, *, metrics=None, error=None, output_ref=None):
    from psycopg.types.json import Jsonb
    store.connection.execute(
        'UPDATE cplane_eval_attempts SET state=%s, metrics=%s, result=%s, output_ref=%s WHERE id=%s',
        (status, Jsonb(metrics or {}), Jsonb({'error': error}) if error else None, output_ref, attempt))


def _end_runs(store):
    store.connection.execute("UPDATE cplane_eval_runs r SET state='done' WHERE state='running' AND NOT EXISTS "
                             "(SELECT 1 FROM cplane_eval_attempts a WHERE a.eval_run=r.id "
                             "AND a.state IN ('planned','running'))")


def _reset(runner, tool, message):
    from .runner import codex_limits
    now = runner.instant.timestamp()
    if tool == 'codex':
        windows = [w['resets_at'] for w in (codex_limits() or [])
                   if isinstance(w.get('used_percent'), (int, float)) and w['used_percent'] >= 99
                   and isinstance(w.get('resets_at'), (int, float)) and w['resets_at'] > now]
        if windows:
            return max(windows)
    else:
        report = runner.claude_reader() or {}
        reset = report.get('rate_limits', {}).get('five_hour', {}).get('resets_at')
        if isinstance(reset, (int, float)) and reset > now:
            return reset
    return runner.limit_reset(message) or now + 3600


def _limit(tool, output):
    from .runner import usage_limit_message
    if tool == 'codex':
        return usage_limit_message(output)
    reply = json.loads(output)
    if isinstance(reply, dict) and reply.get('is_error'):
        message = reply.get('result', '')
        if isinstance(message, str) and re.search(r'usage limit|hit your limit|rate.limit', message, re.I):
            return message
    return None


def _wall(job):
    return {'wall_seconds': max(0, time.time() - job['started_ns'] / 1e9)}


def collect(runner, store):
    """Collect before slices so finished attempts release their shared place."""
    # Eval capacity is global, even if a pass uses another state-file identity.
    for path in runner.runs.parent.glob('*/*/job.json'):
        try:
            saved = json.loads(read_output(path))
            if not saved.get('eval_attempt'):
                continue
            previous = runner.jobs.get(saved['id'])
            if previous is None or previous.get('started_ns', 0) < saved['started_ns']:
                runner.jobs[saved['id']] = saved
        except (OSError, ValueError, KeyError, AttributeError):
            continue
    # Recover a launch whose surrounding scheduler transaction rolled back.
    for saved in runner.jobs.values():
        if saved.get('eval_attempt') and saved['phase'] in ('running', 'eval-ended'):
            store.connection.execute(
                "UPDATE cplane_eval_attempts SET state='running' WHERE id=%s AND state='planned'",
                (saved['eval_attempt'],))
    for attempt in evals._rows(store, 'SELECT a.*, c.repository FROM cplane_eval_attempts a '
                              'JOIN cplane_eval_cases c ON c.id=a."case" '
                              "WHERE a.state='running' ORDER BY a.id"):
        job = runner.jobs.get('eval:' + str(attempt['id']))
        if job is None or job.get('metadata_unavailable'):
            # Without a confirmed end, another runner may still own this process.
            # Reserve its place and repository until its metadata is available.
            runner.jobs['eval:' + str(attempt['id'])] = dict(
                phase='running', repository=attempt['repository'], metadata_unavailable=True)
            continue
        if job['phase'] == 'usage-limit-wait':
            _finish(store, attempt['id'], 'planned')
            copy = Path(job['repo'])
            if copy.exists():
                fence.remove(copy, 'work')
            continue
        if job['phase'] == 'running':
            done, _, _, _ = runner.processes.poll(job)
            expired = time.time() - job['started_ns'] / 1e9 >= TIMEOUT
            if not done and not expired:
                continue
            if not (Path(job['run']) / 'exit.json').exists():
                try:
                    runner.processes.stop(job)
                except Exception:
                    # An unconfirmed stop still owns the sole attempt and its slot.
                    continue
            metrics = _wall(job)
            try:
                if expired and (not done or not (Path(job['run']) / 'exit.json').exists()):
                    raise TimeoutError
                folder = Path(job['run'])
                exit_info = json.loads(read_output(folder / 'exit.json'))
                if exit_info.get('timeout'):
                    raise TimeoutError
                output = read_output(folder / ('turn.jsonl' if job['tool'] == 'codex' else 'claude.json'))
                message = _limit(job['tool'], output)
                if message:
                    job.update(phase='usage-limit-wait', reset_at=_reset(runner, job['tool'], message))
                    runner.save_job(job)
                    _finish(store, attempt['id'], 'planned')
                    fence.remove(Path(job['repo']), 'work')
                    continue
                if exit_info.get('code') in (125, 126, 127) or 'code' not in exit_info:
                    raise OSError
                counters = run_records.usage(job['tool'], output)
                metrics = {k: counters[k] for k in ('input_tokens', 'output_tokens') if counters[k] is not None}
                metrics['wall_seconds'] = max(0, exit_info['at'] - job['started_ns'] / 1e9)
                patch = runner.fence.eval_diff(job)
                target = folder / 'attempt.patch'
                with target.open('w', encoding='utf-8', errors='surrogateescape') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(patch)
                    stream.flush()
                    os.fsync(stream.fileno())
                job.update(phase='eval-ended', completion=dict(status='done', metrics=metrics, output_ref=str(target)))
            except TimeoutError:
                job.update(phase='eval-ended', completion=dict(status='failed', error='Attempt timed out',
                                                            metrics=metrics))
            except Exception:
                job.update(phase='eval-ended', completion=dict(status='failed', error='Attempt output unavailable',
                                                            metrics=metrics))
            runner.save_job(job)
        if job['phase'] == 'eval-ended':
            # Save terminal intent before removing the copy or committing the DB.
            copy = Path(job['repo'])
            if copy.exists():
                fence.remove(copy, 'work')
            _finish(store, attempt['id'], **job['completion'])
    _end_runs(store)


def start(runner, store):
    """Called after slice starts under the runner's global Postgres lock."""
    due = evals._rows(store, "SELECT id FROM cplane_eval_runs WHERE state='planned' "
                     'AND (scheduled_for IS NULL OR scheduled_for <= %s) ORDER BY id LIMIT 1', (runner.instant,))
    if due:
        store.connection.execute("UPDATE cplane_eval_runs SET state='running' WHERE id=%s", (due[0]['id'],))
    _end_runs(store)
    if evals._rows(store, "SELECT id FROM cplane_eval_attempts WHERE state='running' LIMIT 1"):
        return
    if any(j['phase'] == 'usage-limit-wait' and j['reset_at'] > runner.instant.timestamp()
           for j in runner.jobs.values()):
        return
    attempts = evals._rows(store, 'SELECT a.*, c.repository, c.base_commit, c.task, r.configurations '
                           'FROM cplane_eval_attempts a JOIN cplane_eval_runs r ON r.id=a.eval_run '
                           'JOIN cplane_eval_cases c ON c.id=a."case" '
                           "WHERE a.state='planned' AND r.state='running' ORDER BY a.id LIMIT 1")
    if not attempts:
        return
    attempt = attempts[0]
    # Use the same eligibility calculation as slices, including absent live jobs.
    item = dict(id='eval:' + str(attempt['id']), repo=attempt['repository'], state='ready')
    if runner.room(item):
        return
    config = next(c for c in attempt['configurations'] if c['id'] == attempt['configuration_id'])
    if config['harness'] not in ('codex', 'claude'):
        _finish(store, attempt['id'], 'failed', error='Attempt harness unavailable')
        _end_runs(store)
        return
    tool, model = config['harness'], config['model']
    # The provider's normal availability gate applies to attempts as well.
    if not available(runner, tool):
        return
    folder = runner.runs / uuid.uuid4().hex
    job = None
    metadata = None
    started = time.time()
    try:
        runner.runs.mkdir(parents=True, mode=0o700, exist_ok=True)
        fence.trusted_directory(runner.runs)
        folder.mkdir(mode=0o700)
        metadata = runner.fence.prepare_eval(attempt['repository'], attempt['base_commit'], uuid.uuid4().hex)
        job = dict(id=item['id'], eval_attempt=attempt['id'], run=str(folder), tool=tool, model=model,
                   effort=config.get('effort', 'medium'), prompt=LEAD + attempt['task'],
                   started_ns=time.time_ns(), phase='running', session='', resume=None, fence=True,
                   timeout_seconds=TIMEOUT, container_id='eval-' + folder.name, cleanup_turn=time.time_ns(), **metadata)
        runner.save_job(job)
        store.connection.execute("UPDATE cplane_eval_attempts SET state='running' WHERE id=%s", (attempt['id'],))
        runner.jobs[job['id']] = job
        job['pid'] = runner.processes.start(job)
    except Exception:
        if job:
            job.update(phase='eval-ended', completion=dict(status='failed', error='Attempt could not start',
                                                            metrics={'wall_seconds': max(0, time.time() - started)}))
            runner.save_job(job)
        if metadata:
            fence.remove(Path(metadata['repo']), 'work')
        _finish(store, attempt['id'], 'failed', error='Attempt could not start',
                metrics={'wall_seconds': max(0, time.time() - started)})
        _end_runs(store)
        return
    # A persistence failure after Popen must retain the live job's reservation.
    runner.save_job(job)


def available(runner, tool):
    if tool == 'codex':
        value = runner.codex_reader()
        return isinstance(value, (int, float)) and 0 <= value < 99
    report = runner.claude_reader() or {}
    try:
        window = report['rate_limits']['five_hour']
        if window.get('resets_at') is not None and window['resets_at'] <= runner.instant.timestamp():
            return True
        return (0 <= runner.instant.timestamp() - report['at'] < 3600
                and 0 <= window['used_percentage'] < 90)
    except (KeyError, TypeError):
        return False
