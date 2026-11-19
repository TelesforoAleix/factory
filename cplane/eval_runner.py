"""Schedule evals as isolated runner jobs, then retain and grade delivered work."""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import time

from . import cut, evals, run_platform, state
from .runner import Runner


def _finish(store, attempt, status, *, metrics=None, result=None, output_ref=None):
    from psycopg.types.json import Jsonb

    store.connection.execute(
        'UPDATE cplane_eval_attempts SET state=%s, metrics=%s, result=%s, output_ref=%s WHERE id=%s',
        (status, Jsonb(metrics or {}), Jsonb(result) if result is not None else None, output_ref, attempt))


def _end_runs(store):
    store.connection.execute("UPDATE cplane_eval_runs r SET state='done' WHERE state='running' AND NOT EXISTS "
                             "(SELECT 1 FROM cplane_eval_attempts a WHERE a.eval_run=r.id "
                             "AND a.state IN ('planned','running'))")


def metrics(job):
    """Sum each run's accounting, including its internal retry attempts."""
    rows = []
    for entry in job['requests'].values():
        record = entry.get('record') or {}
        for attempt in record.get('attempts') or [record]:
            counters = dict(attempt.get('metrics') or {})
            if (entry.get('request') or {}).get('role') == 'check':
                # A sealed command has no executor and consumes no model usage.
                counters['tokens'] = dict(fresh=0, cached=0, output=0)
                counters['usd'] = 0
            if counters.get('minutes') is None:
                try:
                    duration = (datetime.fromisoformat(attempt['ended_at']) -
                                datetime.fromisoformat(attempt['started_at'])).total_seconds()
                    counters['minutes'] = max(0, duration) / 60
                except (KeyError, TypeError, ValueError):
                    pass
            rows.append(counters)
    result = {}
    def number(value):
        return type(value) in (int, float) and 0 <= value < float('inf')
    counters = {
        'input_tokens': lambda m: (m.get('tokens') or {}).get('fresh', 0) + (m.get('tokens') or {}).get('cached', 0)
            if number((m.get('tokens') or {}).get('fresh')) and number((m.get('tokens') or {}).get('cached')) else None,
        'output_tokens': lambda m: (m.get('tokens') or {}).get('output'),
        'cost_usd': lambda m: m.get('usd'),
        'wall_seconds': lambda m: m['minutes'] * 60 if number(m.get('minutes')) else None,
    }
    for name, counter in counters.items():
        values = [counter(row) for row in rows]
        if values and all(number(v) for v in values):
            result[name] = sum(values)
    return result


def _complete(runner, store, job):
    # Cancel resumable predecessors and queued successors before removing their
    # branch. A running turn retains the reservation until cancellation succeeds.
    for purpose, entry in job['requests'].items():
        if purpose != 'judge':
            runner.cancel_entry(job, entry)
    for entry in job['requests'].values():
        if entry.get('run_id'):
            runner.send_request(job, entry)  # Recover links after a rollback.
    if any(not entry.get('cancelled') for purpose, entry in job['requests'].items() if purpose != 'judge'):
        return
    completion = job['completion']
    if 'output_ref' not in completion:
        output_ref = None
        if job.get('tip'):
            patch = (runner.github.eval_diff(job['repository'], job['base'], job['tip'])
                     if job['tip'] != job['base'] else '')
            target = Path(job['run']) / 'attempt.patch'
            temporary = target.with_suffix('.tmp')
            with temporary.open('wb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(patch.encode('utf-8', errors='surrogateescape'))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
            output_ref = str(target)
        completion.update(output_ref=output_ref, metrics=metrics(job))
        runner.save_job(job)
    if (completion['status'] == 'done' and job['case']['kind'] == 'slice'
            and job['case'].get('grade') in ('tests_and_judge', 'judge')):
        from .eval_judge import advance
        if not advance(runner, store, job):
            return
    if 'judge' in job['requests']:
        entry = job['requests']['judge']
        runner.cancel_entry(job, entry)
        if not entry.get('cancelled'):
            return
    completion['metrics'] = metrics(job)
    runner.github.delete_eval_branch(job['repository'], job['branch'])
    job['phase'] = 'eval-ended'
    runner.save_job(job)
    _finish(store, job['eval_attempt'], **completion)


def _launch(runner, job):
    item, case = job['item'], job['case']
    if job['component']:
        entry = runner.new_request(item, job, 'ticket-1', 'ticket', job['brief'] + runner.ticket_assignment(),
                                   allowed_files=case['allowed_files'], pinned_paths=case['pinned_paths'],
                                   check_command=case['check_command'])
        runner.send_request(job, entry)
    else:
        runner.launch_work(item, job)


def collect(runner, store):
    """Recover durable jobs before slices and release completed reservations."""
    for path in runner.runs.parent.glob('*/*/job.json'):
        try:
            saved = json.loads(path.read_text())
            if not saved.get('eval_attempt'):
                continue
            previous = runner.jobs.get(saved['id'])
            if previous is None or previous.get('started_ns', 0) < saved['started_ns']:
                runner.jobs[saved['id']] = saved
        except (OSError, ValueError, KeyError, AttributeError):
            continue
    for job in runner.jobs.values():
        if job.get('eval_attempt'):
            store.connection.execute(
                "UPDATE cplane_eval_attempts SET state='running' WHERE id=%s AND state='planned'",
                (job['eval_attempt'],))
    attempts = evals._rows(store, 'SELECT a.*, r.state AS run_state FROM cplane_eval_attempts a '
                          'JOIN cplane_eval_runs r ON r.id=a.eval_run WHERE a.state=\'running\' ORDER BY a.id')
    for attempt in attempts:
        job = runner.jobs.get('eval:' + str(attempt['id']))
        if job is None or job.get('metadata_unavailable'):
            # Missing intent cannot safely be resubmitted. Reserve the repository
            # while the platform may still be executing its uncollected work.
            repo = evals._rows(store, 'SELECT repository FROM cplane_eval_cases WHERE id=%s', (attempt['case'],))[0]['repository']
            runner.jobs['eval:' + str(attempt['id'])] = dict(
                eval_attempt=attempt['id'], phase='running', metadata_unavailable=True,
                item=dict(id='eval:' + str(attempt['id']), repo=repo, state='issued', log=[]))
            continue
        try:
            for entry in job['requests'].values():
                if entry.get('run_id'):
                    runner.send_request(job, entry)
            if job['phase'] == 'eval-ended':
                if (job.get('judge_outcome') or {}).get('judge') is not None:
                    from .eval_judge import record_verdict
                    record_verdict(store, attempt['id'], job['requests']['judge']['prompt_hash'], job['judge_outcome'])
                _finish(store, attempt['id'], **job['completion'])
                continue
            if (attempt['run_state'] == 'cancelled' and job['phase'] == 'eval-finishing'
                    and 'judge' in job['requests']):
                job['completion'].update(status='failed', result={'error': 'Eval run cancelled'})
                runner.save_job(job)
            if attempt['run_state'] == 'cancelled' and job['phase'] != 'eval-finishing':
                runner.fail(job, 'Eval run cancelled')
            if job['phase'] != 'eval-finishing':
                if not job['requests']:
                    _launch(runner, job)
                Runner.collect(runner, job['item'], job)
                if job['phase'] == 'tickets':
                    runner.follow_tickets(job['item'], job)
            if job['phase'] == 'eval-finishing':
                _complete(runner, store, job)
        except run_platform.Unavailable as error:
            logging.getLogger(__name__).warning('%s', error)
        except (ValueError, KeyError, state.StateError) as error:
            # Invalid cutter/reviewer output fails only this attempt. App errors
            # must retry so a transient read cannot lose a delivered diff.
            from .runner import GitHubReadError
            if isinstance(error, GitHubReadError):
                logging.getLogger(__name__).warning('Eval App read unavailable')
            elif job['phase'] != 'eval-finishing':
                runner.fail(job, str(error))
            else:
                logging.getLogger(__name__).warning('Eval branch cleanup unavailable; retrying')
    _end_runs(store)


def start(runner, store):
    """Start one due attempt, under the runner's global scheduler lock."""
    due = evals._rows(store, "SELECT id FROM cplane_eval_runs WHERE state='planned' "
                     'AND (scheduled_for IS NULL OR scheduled_for <= %s) ORDER BY id LIMIT 1', (runner.instant,))
    if due:
        store.connection.execute("UPDATE cplane_eval_runs SET state='running' WHERE id=%s", (due[0]['id'],))
    _end_runs(store)
    if evals._rows(store, "SELECT id FROM cplane_eval_attempts WHERE state='running' LIMIT 1"):
        return
    attempts = evals._rows(store, 'SELECT a.*, r.configurations FROM cplane_eval_attempts a '
                           'JOIN cplane_eval_runs r ON r.id=a.eval_run '
                           "WHERE a.state='planned' AND r.state='running' ORDER BY a.id LIMIT 1")
    if not attempts:
        return
    attempt = attempts[0]
    case = evals._rows(store, 'SELECT * FROM cplane_eval_cases WHERE id=%s', (attempt['case'],))[0]
    config = next(c for c in attempt['configurations'] if c['id'] == attempt['configuration_id'])
    if 'roles' not in config:
        _finish(store, attempt['id'], 'failed', result={'error': 'Legacy inline configuration cannot start; create a named run'})
        _end_runs(store)
        return
    identifier = 'eval:' + str(attempt['id'])
    item = dict(id=identifier, repo=case['repository'], title=case['title'], state='ready', paused=False,
                attention=None, pr=None, log=[], depends_on=[], flow='tickets' if config['path'] == 'tickets' else 'cli')
    if runner.room(item):
        return
    folder = runner.runs / ('eval-' + str(attempt['id']))
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    brief = case['task']
    if config['path'] == 'tickets' and case['kind'] == 'slice':
        try:
            cut.sections(brief, identifier)
        except state.StateError:
            brief += '\n\n## Do not\nDo not open a PR or perform merge or node steps.\n'
    job = dict(id=identifier, eval_attempt=attempt['id'], eval_run=attempt['eval_run'],
               configuration=config, case=case, item=item, component=case['kind'] == 'ticket',
               attempt=1, run=str(folder), repository=case['repository'],
               branch=f"eval/{attempt['eval_run']}/{attempt['id']}",
               base=case['start_commit'] if case['kind'] == 'ticket' else case['base_commit'],
               brief=brief, level=case['level'] or 'standard', started_ns=time.time_ns(),
               requests={}, active='cut' if config['path'] == 'tickets' else 'slice', phase='running',
               skills=cut.skills_version())
    if job['component']:
        job['active'] = 'ticket-1'
    item['state'] = 'issued'
    runner.jobs[identifier] = job
    runner.save_job(job)
    store.connection.execute("UPDATE cplane_eval_attempts SET state='running' WHERE id=%s", (attempt['id'],))
    try:
        _launch(runner, job)
    except run_platform.Unavailable as error:
        logging.getLogger(__name__).warning('%s', error)
