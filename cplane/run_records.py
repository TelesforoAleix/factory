"""Best-effort turn accounting; diagnostics never include executor or prompt text."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import hashlib
import os
import stat
import time
from pathlib import Path
import subprocess
import sys

from .features import TEXT_LIMIT
from .text_bounds import cut
from .state import StateError

TOKEN_FIELDS = ('input_tokens', 'cached_tokens', 'cache_write_tokens', 'output_tokens', 'reasoning_tokens')
OUTCOME_FIELDS = ('level', 'executor_source', 'configuration', 'brief_hash', 'ci_result',
                  'verdict', 'corrects_slice', 'owner_wait_seconds', 'change_class')
FIELDS = ('kind', 'project', 'feature_id', 'slice_id', 'session_id', 'tool', 'model', 'effort',
          *TOKEN_FIELDS, 'seconds', 'started_at', 'outcome', 'starting_commit', 'prompt',
          'prompt_truncated', 'skill_version', 'eval_candidate', *OUTCOME_FIELDS, 'context')


def _skill_digest(path, root=None):
    with ExitStack() as stack:
        parent = None
        if root is not None:
            parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, parent)
            parts = path.relative_to(root).parts
            if any(part in ('.', '..') for part in parts):
                raise ValueError('invalid skill path')
            for part in parts[:-1]:
                parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                stack.callback(os.close, parent)
            path = parts[-1]
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('skill must be a regular file')
            return hashlib.file_digest(stream, 'sha256').hexdigest()


def context(*, prompt_names=(), skill_files=(), skill_root=None):
    """Snapshot loaded instructions; one unreadable file never hides the others."""
    from . import prompts
    result = []
    for name in prompt_names:
        try:
            result.append(dict(kind='prompt', name=name, sha256=prompts.sha256(name)))
        except Exception:
            print('cplane: run context prompt unreadable', file=sys.stderr)
    for name, path in skill_files:
        try:
            # Installed files live in an agent workspace: never open a link or
            # block on a substituted FIFO, and hash bytes without text decoding.
            digest = _skill_digest(path, skill_root)
            result.append(dict(kind='skill', name=name, sha256=digest))
        except Exception:
            print('cplane: run context skill unreadable', file=sys.stderr)
    return sorted(result, key=lambda entry: (entry['kind'], entry['name']))


def chat_context(folder, session, prompt_names):
    try:
        directory = folder / '.claude' / 'skills'
        # Include the snapshot's expected files so a missing skill is diagnosed,
        # and discover installed files for legacy sessions as well.
        names = set(session.get('skill_names') or ())
        names.update(path.parent.name for path in directory.glob('*/SKILL.md'))
        files = [(name, directory / name / 'SKILL.md') for name in sorted(names)]
    except Exception:
        print('cplane: run context skills unreadable', file=sys.stderr)
        files = []
    return context(prompt_names=prompt_names, skill_files=files, skill_root=folder)


def save_context(run, entries):
    """Keep the pre-launch snapshot for interrupted chat recovery."""
    try:
        from .executors import atomic_json
        atomic_json(run / 'context.json', entries)
    except Exception:
        print('cplane: run context snapshot failed', file=sys.stderr)


def saved_context(run):
    try:
        from .executors import read_output
        entries = json.loads(read_output(run / 'context.json'))
        if not isinstance(entries, list):
            raise ValueError('context must be an array')
        return entries
    except Exception:
        print('cplane: run context snapshot unreadable', file=sys.stderr)
        return []


def usage(tool, output):
    """Sum per-turn reports, preserving unknown counters (including partial totals)."""
    names = (('input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens',
              'reasoning_output_tokens') if tool == 'codex' else
             ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens',
              'reasoning_output_tokens'))
    events = [json.loads(line) for line in output.splitlines() if line.strip()] if tool == 'codex' else [json.loads(output)]
    reports = [event['usage'] for event in events if isinstance(event, dict) and isinstance(event.get('usage'), dict)]
    result = {}
    for field, name in zip(TOKEN_FIELDS, names):
        values = [report.get(name) for report in reports]
        result[field] = (sum(values) if values and all(type(v) is int and v >= 0 for v in values) else None)
    return result


def starting_commit(repository):
    try:
        result = subprocess.run(['git', '-C', str(repository), '-c', 'core.hooksPath=/dev/null',
                                 '-c', 'core.fsmonitor=false', 'rev-parse', '--verify', 'HEAD^{commit}'],
                                capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def record(store, *, turn_key, repository=None, feature=None, output=None, log=None, **values):
    """Use a savepoint so a failed insert cannot poison the scheduler transaction."""
    try:
        if not hasattr(store, 'run_record_add'):
            return
        try:
            if log is not None:
                from .executors import read_output
                output = read_output(Path(log))
            counters = usage(values['tool'], output) if output is not None else dict.fromkeys(TOKEN_FIELDS)
        except Exception:
            print('cplane: run usage unreadable', file=sys.stderr)
            counters = dict.fromkeys(TOKEN_FIELDS)
        store.run_record_add(turn_key, repository=repository, feature=feature, **values, **counters)
    except Exception:
        print('cplane: run recording failed', file=sys.stderr)


class RunRecordStore:
    def slice_outcome(self, slice_id, *, verdict=None, corrects=None):
        """Called inside the planner's locked, validated state update."""
        if verdict is not None and verdict not in ('accepted', 'corrected'):
            raise StateError('Invalid planner verdict')
        with self.mutation():
            self.connection.execute(
                'INSERT INTO cplane_slice_outcomes (slice_id, verdict, corrects_slice) VALUES (%s, %s, %s) '
                'ON CONFLICT (slice_id) DO UPDATE SET '
                'verdict = COALESCE(EXCLUDED.verdict, cplane_slice_outcomes.verdict), '
                'corrects_slice = COALESCE(EXCLUDED.corrects_slice, cplane_slice_outcomes.corrects_slice)',
                (slice_id, verdict, corrects))
            if corrects is not None:
                self.connection.execute('UPDATE cplane_run_records SET corrects_slice = %s WHERE slice_id = %s',
                                        (corrects, slice_id))

    def slice_review(self, slice_id):
        with self.locked():
            row = self.connection.execute(
                'SELECT review_verdict, review_findings FROM cplane_slice_outcomes WHERE slice_id = %s',
                (slice_id,)).fetchone()
            return dict(zip(('review_verdict', 'review_findings'), row)) if row else {}

    def slice_review_record(self, slice_id, verdict, findings):
        from psycopg.types.json import Jsonb
        if verdict not in ('pass', 'fix', 'missing'):
            raise StateError('Invalid review verdict')
        with self.mutation():
            self.connection.execute(
                'INSERT INTO cplane_slice_outcomes (slice_id, review_verdict, review_findings) VALUES (%s, %s, %s) '
                'ON CONFLICT (slice_id) DO UPDATE SET review_verdict = EXCLUDED.review_verdict, '
                'review_findings = EXCLUDED.review_findings',
                (slice_id, verdict, Jsonb(findings)))

    def _slice_outcomes(self):
        return {row[0]: row[1:] for row in self.connection.execute(
            'SELECT slice_id, verdict, corrects_slice FROM cplane_slice_outcomes')}

    @staticmethod
    def _apply_slice_outcome(item, outcomes):
        verdict, corrects = outcomes.get(item['slice_id'], (None, None))
        if verdict is not None:
            item['verdict'] = verdict
        if corrects is not None:
            item['corrects_slice'] = corrects
        return item

    def task_record_poll(self, queue_slice, tickets):
        # Whitelist accounting only: never persist titles, goals, or prompts.
        with self.mutation():
            # The runner submits its single repair round as <slice>/repair.
            # Prefer an exact state ID so a real slice with that name still wins.
            parent = self.connection.execute(
                "SELECT id FROM cplane_slices WHERE id = %s OR id || '/repair' = %s "
                "ORDER BY (id = %s) DESC LIMIT 1", (queue_slice, queue_slice, queue_slice)).fetchone()
            slice_id = parent[0] if parent else queue_slice
            for ticket in tickets:
                self.connection.execute(
                    'INSERT INTO cplane_task_runs (slice_id, queue_slice, task_id, attempt, position, status, reason, tokens, seconds, cost) '
                    'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) '
                    'ON CONFLICT (queue_slice, task_id, attempt) DO UPDATE SET '
                    'position = EXCLUDED.position, status = EXCLUDED.status, reason = EXCLUDED.reason, '
                    'tokens = EXCLUDED.tokens, seconds = EXCLUDED.seconds, cost = EXCLUDED.cost, '
                    'updated_at = clock_timestamp()',
                    (slice_id, queue_slice, str(ticket['id']), ticket.get('attempt', 1), ticket['position'],
                     ticket['status'], cut(ticket['reason'], TEXT_LIMIT) if ticket['reason'] is not None else None,
                     ticket.get('tokens'), ticket.get('seconds'), ticket.get('cost')))

    def run_record_export(self, since):
        """One JSON-safe record per slice turn and task attempt; no content columns."""
        with self.locked():
            result = [row for row in self.run_record_list()
                      if row['kind'] == 'slice' and row['started_at'] is not None
                      and datetime.fromisoformat(row['started_at']) >= since]
            columns = ('id', 'slice_id', 'queue_slice', 'task_id', 'attempt', 'position', 'status', 'reason',
                       'tokens', 'seconds', 'cost', 'started_at', 'updated_at')
            rows = self.connection.execute('SELECT ' + ', '.join(columns) +
                                           ' FROM cplane_task_runs WHERE started_at >= %s ORDER BY id', (since,))
            outcomes = self._slice_outcomes()
            for row in rows:
                item = self._run_record_dict(columns, row)
                item.update(kind='task', verdict=None, corrects_slice=None)
                result.append(self._apply_slice_outcome(item, outcomes))
            return result

    def run_record_add(self, turn_key, *, repository=None, feature=None, **values):
        with self.mutation():
            project = None
            if repository:
                rows = list(self.connection.execute(
                    'SELECT key FROM cplane_projects WHERE repository = %s', (repository.split('/')[-1],)))
                if len(rows) == 1:
                    project = rows[0][0]
            feature_id = None
            if feature:
                row = self.connection.execute('SELECT id FROM cplane_feature_ids WHERE id = %s', (feature,)).fetchone()
                feature_id = row[0] if row else None
            if values.get('slice_id'):
                link = self.connection.execute(
                    'SELECT corrects_slice FROM cplane_slice_outcomes WHERE slice_id = %s',
                    (values['slice_id'],)).fetchone()
                if link and link[0] is not None:
                    values['corrects_slice'] = link[0]
            prompt = values.get('prompt')
            values.update(project=project, feature_id=feature_id,
                          prompt=cut(prompt, TEXT_LIMIT) if prompt is not None else None,
                          prompt_truncated=prompt is not None and len(prompt) > TEXT_LIMIT,
                          eval_candidate=False)
            from psycopg.types.json import Jsonb
            for field in ('ci_result', 'context'):
                if values.get(field) is not None:
                    values[field] = Jsonb(values[field])
            self.connection.execute(
                'INSERT INTO cplane_run_records (turn_key, ' + ', '.join(FIELDS) + ') VALUES (' +
                ', '.join(['%s'] * (len(FIELDS) + 1)) + ') ON CONFLICT (turn_key) DO NOTHING',
                (turn_key, *(values.get(field) for field in FIELDS)))

    def run_record_outcome(self, turn_key, *, ci=None, **values):
        if set(values) - set(OUTCOME_FIELDS):
            raise ValueError('unknown outcome field')
        from psycopg.types.json import Jsonb
        with self.mutation():
            assignments = [f'{field} = %s' for field in values]
            parameters = list(values.values())
            if ci is not None:
                assignments.append("ci_result = COALESCE(ci_result, '[]'::jsonb) || %s")
                parameters.append(Jsonb([ci]))
            if assignments:
                self.connection.execute('UPDATE cplane_run_records SET ' + ', '.join(assignments) +
                                        ' WHERE turn_key = %s', (*parameters, turn_key))

    def run_record_list(self, *, slice_id=None, project=None):
        # Calculate before filtering: a session's previous row may be outside
        # the requested slice or project. Never select private prompt text.
        columns = ('id', *(field for field in FIELDS if field != 'prompt'))
        with self.locked():
            outcomes = self._slice_outcomes()
            rows = self.connection.execute('SELECT ' + ', '.join(columns) +
                                           ' FROM cplane_run_records ORDER BY id')
            previous = {}
            result = []
            for row in rows:
                item = self._run_record_dict(columns, row)
                key = (item['tool'], item['session_id'])
                prior = previous.get(key) if item['session_id'] is not None else None
                tokens = {}
                for field in TOKEN_FIELDS:
                    value = item[field]
                    if item['tool'] == 'codex' and prior is not None:
                        old = prior[field]
                        value = (None if value is None or old is None else
                                 value - old if value >= old else value)
                    tokens[field] = value
                self._apply_slice_outcome(item, outcomes)
                item['turn_tokens'] = tokens
                if item['session_id'] is not None:
                    previous[key] = item
                if (slice_id is None or item['slice_id'] == slice_id) and (project is None or item['project'] == project):
                    result.append(item)
            return result

    @staticmethod
    def _run_record_dict(columns, row):
        return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in zip(columns, row)}

    def project_usage(self, project):
        """UTC calendar month; difference Codex cumulative counters before filtering."""
        fields = ('input_tokens', 'output_tokens', 'cached_tokens')
        counters = ', '.join(
            f"CASE WHEN tool = 'codex' AND session_id IS NOT NULL AND prior_id IS NOT NULL "
            f"THEN CASE WHEN {f} >= prior_{f} THEN {f} - prior_{f} "
            f"WHEN {f} < prior_{f} THEN {f} END ELSE {f} END AS {f}" for f in fields)
        lag = ', '.join(f'lag({f}) OVER session AS prior_{f}' for f in fields)
        with self.locked():
            rows = self.connection.execute(
                "WITH previous AS (SELECT id, tool, session_id, project, started_at, seconds, input_tokens, output_tokens, cached_tokens, lag(id) OVER session AS prior_id, " + lag +
                " FROM cplane_run_records WINDOW session AS (PARTITION BY tool, session_id ORDER BY id)), "
                "turns AS (SELECT project, started_at, seconds, " + counters + " FROM previous) "
                "SELECT period, count(t.project), sum(input_tokens), sum(output_tokens), sum(cached_tokens), sum(seconds) "
                "FROM (VALUES ('month'), ('all_time')) p(period) LEFT JOIN turns t ON t.project = %s "
                "AND (period = 'all_time' OR started_at >= date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' "
                "AND started_at < (date_trunc('month', now() AT TIME ZONE 'UTC') + interval '1 month') AT TIME ZONE 'UTC') "
                "GROUP BY period", (project,)).fetchall()
            return {period: dict(input_tokens=(int(i) if i is not None else None) if count else 0,
                                 output_tokens=(int(o) if o is not None else None) if count else 0,
                                 cached_tokens=(int(c) if c is not None else None) if count else 0,
                                 hours=seconds / 3600 if seconds is not None else (None if count else 0))
                    for period, count, i, o, c, seconds in rows}

    def run_record_show(self, identifier):
        with self.locked():
            row = self.connection.execute('SELECT id, ' + ', '.join(FIELDS) +
                ' FROM cplane_run_records WHERE id = %s', (identifier,)).fetchone()
            if row is None:
                raise StateError('Run record not found')
            return self._apply_slice_outcome(self._run_record_dict(('id', *FIELDS), row),
                                             self._slice_outcomes())

    def run_record_mark(self, identifier, *, clear=False):
        with self.mutation():
            if not self.connection.execute('UPDATE cplane_run_records SET eval_candidate = %s WHERE id = %s RETURNING id',
                                           (not clear, identifier)).fetchone():
                raise StateError('Run record not found')

    def run_record_total(self, slice_id):
        rows = self.run_record_list(slice_id=slice_id)
        totals = {}
        for field in (*TOKEN_FIELDS, 'seconds'):
            values = [(row['turn_tokens'][field] if field in TOKEN_FIELDS else row[field]) for row in rows]
            known = [value for value in values if value is not None]
            totals[field] = sum(known) if known else None
        return dict(turns=len(rows), **totals)



def slice_record(store, item, job):
    if job.get('requests'):
        entry = job['requests'][job['active']]
        return platform_record(store, item, job, entry)
    end = job.get('ended_at')
    started = job.get('started_ns')
    record(store, turn_key='slice:' + job['run'], repository=item['repo'], feature=item.get('feature'),
           log=Path(job['run']) / ('turn.jsonl' if job['tool'] == 'codex' else 'claude.json'),
           kind='slice', slice_id=item['id'], session_id=job.get('session') or None,
           tool=job['tool'], model=job.get('model'), effort=job.get('effort'),
           starting_commit=job.get('starting_commit'), skill_version=job.get('skills'),
           context=job.get('context', []),
           **{field: job.get(field) for field in OUTCOME_FIELDS},
           started_at=datetime.fromtimestamp(started / 1e9, timezone.utc) if started else None,
           seconds=max(0, end - started / 1e9) if end is not None and started else None,
           outcome=job.get('final', {}).get('kind') if job.get('final') else 'failed')



def chat_record(store, turn, accounting):
    try:
        session = turn['session']
        repositories = session.get('repositories', [])
        record(store, turn_key=f"chat:{turn['id']}", kind='chat',
               repository=repositories[0] if len(repositories) == 1 else None,
               session_id=str(session['id']) if session.get('id') is not None else None,
               tool=session['tool'], model=session.get('model'),
               effort='medium' if session['tool'] == 'codex' else None,
               prompt=turn.get('text'), starting_commit=session.get('_starting_commit'), skill_version=session.get('skill_version'),
               context=accounting.get('context', []),
               started_at=datetime.fromtimestamp(accounting['started'], timezone.utc) if accounting.get('started') else None,
               seconds=(max(0, accounting.get('ended', time.time()) - accounting['started'])
                        if accounting.get('started') else None),
               output=accounting.get('output'), outcome=accounting.get('outcome', 'failed'))
    except Exception:
        print('cplane: run recording failed', file=sys.stderr)


def end_time(job):
    try:
        from .executors import read_output
        value = json.loads(read_output(Path(job['run']) / 'exit.json'))['at']
        if type(value) in (int, float) and 0 <= value <= time.time():
            return value
    except Exception:
        pass
    return time.time()


def outcome(store, job, **values):
    """Outcome writes have the same best-effort/savepoint boundary as inserts."""
    try:
        if not hasattr(store, 'run_record_outcome'):
            return
        store.run_record_outcome(job.get('record_key', 'slice:' + job['run']), **values)
    except Exception:
        print('cplane: run recording failed', file=sys.stderr)





def review_record(runner, job, answer):
    from . import state, review
    store = None
    if state.postgres():
        try:
            store = state.store(runner.path)
        except Exception:
            print('cplane: run recording failed', file=sys.stderr)
    review.validate(answer, store=store, job=job)
    findings = ({key: answer[key] for key in ('title', 'body')}
                if answer['verdict'] == 'pass' else answer['tickets'])
    review_outcome(runner, {**job, 'review_verdict': answer['verdict'], 'review_findings': findings})


def review_outcome(runner, job, *, item=None):
    """Persist the review separately from the planner verdict, like other accounting."""
    from . import state
    if not state.postgres():
        return
    try:
        store = state.store(runner.path)
        review = job.get('pr_review')
        if item is not None and isinstance(review, dict) and review.get('ended_at') is not None:
            slice_record(store, item, review)
            if job['review_verdict'] in ('pass', 'fix'):
                outcome(store, review, verdict=job['review_verdict'])
        if isinstance(review, str) and job['review_verdict'] in ('pass', 'fix'):
            entry = job['requests'][review]
            record = entry.get('record') or {}
            attempts = record.get('attempts') or [{'number': entry['turn'] + 1}]
            key = 'slice:' + job['run'] + ':' + entry['request']['request_id'] + ':' + str(attempts[-1]['number'])
            outcome(store, {**job, 'record_key': key}, verdict=job['review_verdict'])
        store.slice_review_record(job['id'], job['review_verdict'], job.get('review_findings'))
    except Exception:  # noqa: BLE001 - accounting failures cannot change merge policy
        print('cplane: review recording failed', file=sys.stderr)



def ci_record(runner, item, job, status, failing):
    from . import state
    if state.postgres():
        try:
            sha = job.get('tip') or getattr(runner.github, 'check_sha', None)
            outcome(state.store(runner.path), job,
                    ci=dict(sha=sha if isinstance(sha, str) else None, status=status, failing_job=failing or None))
        except Exception:
            print('cplane: run recording failed', file=sys.stderr)


def class_record(runner, job, change_class):
    from . import state
    if state.postgres():
        try:
            outcome(state.store(runner.path), job, change_class=change_class)
        except Exception:
            print('cplane: run recording failed', file=sys.stderr)


def owner_wait(runner, item, job=None, *, close=False):
    """Attribute attention intervals to the turn that requested owner work.

    The local job keeps an interval cursor; absolute totals make repeated writes
    and runner restarts harmless. Only totals reach Postgres.
    """
    from . import state
    if not state.postgres():
        return
    try:
        job = job or runner.jobs.get(item['id'])
        if not job:
            return
        now = runner.instant.timestamp()
        active = job.get('_owner_attention')
        attention = item.get('attention')
        current = (attention['since'] if attention and attention['kind'] in
                   ('merge', 'node-step', 'question', 'escalation') else None)
        if active and (close or current != active):
            end = (datetime.fromisoformat(attention['since']).timestamp()
                   if attention and attention['since'] != active else now)
            if current is None:
                changes = [datetime.fromisoformat(entry['at']).timestamp() for entry in item['log']
                           if entry['event'] == 'attention' and entry['at'] > active]
                if changes:
                    end = min(end, min(changes))
            job['_owner_wait_closed'] = job.get('_owner_wait_closed', 0) + max(
                0, end - datetime.fromisoformat(active).timestamp())
            job.pop('_owner_attention', None)
        if current and not close:
            job['_owner_attention'] = current
        total = job.get('_owner_wait_closed', 0)
        if job.get('_owner_attention'):
            total += max(0, now - datetime.fromisoformat(job['_owner_attention']).timestamp())
        job['owner_wait_seconds'] = total
        outcome(state.store(runner.path), job, owner_wait_seconds=total)
        runner.save_job(job)
    except Exception:
        print('cplane: run recording failed', file=sys.stderr)


def platform_record(store, item, job, entry):
    """Account checked API attempts without reading local harness output."""
    try:
        saved = entry.get('record') or {}
        request = entry['request']
        if request['role'] == 'ticket':
            if not hasattr(store, 'task_record_poll'):
                return
            attempts = saved.get('attempts') or [{'number': 1, 'metrics': saved.get('metrics') or {}}]
            position = int(request['request_id'].rsplit('-', 1)[-1])
            status = saved['status']
            for attempt in attempts:
                metrics = attempt.get('metrics') or {}
                values = list((metrics.get('tokens') or {}).values())
                store.task_record_poll(item['id'] + ('/repair' if '-repair-ticket-' in request['request_id'] else ''), [{
                    'id': entry['run_id'], 'position': position, 'title': '', 'attempt': attempt['number'],
                    'status': status if status in ('queued', 'running', 'done', 'failed', 'escalated') else 'queued',
                    'reason': saved.get('status_reason'), 'tokens': sum(values) if values and all(v is not None for v in values) else None,
                    'seconds': metrics.get('minutes') * 60 if metrics.get('minutes') is not None else None,
                    'cost': metrics.get('usd')}])
            return
        executor = saved.get('executor') or {}
        harness = executor.get('harness') or executor.get('tool')
        if harness not in ('codex', 'claude'):
            return
        attempts = saved.get('attempts') or [{'number': entry['turn'] + 1, 'metrics': saved.get('metrics') or {}}]
        for attempt in attempts:
            key = 'slice:' + job['run'] + ':' + request['request_id'] + ':' + str(attempt['number'])
            metrics = attempt.get('metrics') or {}
            tokens = metrics.get('tokens') or {}
            fresh, cached = tokens.get('fresh'), tokens.get('cached')
            store.run_record_add(key, repository=item['repo'], feature=item.get('feature'), kind='slice',
                slice_id=item['id'], session_id=entry['run_id'] + ':' + str(attempt['number']), tool=harness, model=executor.get('model'),
                effort=executor.get('effort'), starting_commit=request['base_commit'], skill_version=job.get('skills'),
                level=request['level'], executor_source='level', configuration=attempt.get('configuration_hash') or saved.get('configuration_hash'),
                brief_hash=hashlib.sha256(request['work']['goal'].encode()).hexdigest(),
                started_at=attempt.get('started_at') or saved.get('started_at'),
                seconds=metrics.get('minutes') * 60 if metrics.get('minutes') is not None else None,
                input_tokens=fresh + cached if fresh is not None and cached is not None else None,
                cached_tokens=cached, output_tokens=tokens.get('output'), cache_write_tokens=None, reasoning_tokens=None,
                outcome=(saved.get('final_message') or {}).get('kind') or saved['status'],
                context=entry.get('context', []))
            if request['request_id'] == job['requests'][job['active']]['request']['request_id']:
                job['record_key'] = key
    except Exception:
        print('cplane: run recording failed', file=sys.stderr)
