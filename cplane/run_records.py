"""Best-effort turn accounting; diagnostics never include executor or prompt text."""
from datetime import datetime, timezone
import json
import time
from pathlib import Path
import subprocess
import sys

from .features import TEXT_LIMIT
from .text_bounds import cut
from .state import StateError

TOKEN_FIELDS = ('input_tokens', 'cached_tokens', 'cache_write_tokens', 'output_tokens', 'reasoning_tokens')
FIELDS = ('kind', 'project', 'feature_id', 'slice_id', 'session_id', 'tool', 'model', 'effort',
          *TOKEN_FIELDS, 'seconds', 'started_at', 'outcome', 'starting_commit', 'prompt',
          'prompt_truncated', 'skill_version', 'eval_candidate')


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
    if not hasattr(store, 'run_record_add'):
        return
    try:
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
            prompt = values.get('prompt')
            values.update(project=project, feature_id=feature_id,
                          prompt=cut(prompt, TEXT_LIMIT) if prompt is not None else None,
                          prompt_truncated=prompt is not None and len(prompt) > TEXT_LIMIT,
                          eval_candidate=False)
            self.connection.execute(
                'INSERT INTO cplane_run_records (turn_key, ' + ', '.join(FIELDS) + ') VALUES (' +
                ', '.join(['%s'] * (len(FIELDS) + 1)) + ') ON CONFLICT (turn_key) DO NOTHING',
                (turn_key, *(values.get(field) for field in FIELDS)))

    def run_record_list(self, *, slice_id=None, project=None):
        # Exclude the prompt in SQL too: summary callers never receive private text.
        columns = ('id', *(field for field in FIELDS if field != 'prompt'))
        with self.locked():
            rows = self.connection.execute('SELECT ' + ', '.join(columns) +
                ' FROM cplane_run_records WHERE (%s::text IS NULL OR slice_id = %s) '
                'AND (%s::text IS NULL OR project = %s) ORDER BY id', (slice_id, slice_id, project, project))
            return [self._run_record_dict(columns, row) for row in rows]

    @staticmethod
    def _run_record_dict(columns, row):
        return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in zip(columns, row)}

    def run_record_show(self, identifier):
        with self.locked():
            row = self.connection.execute('SELECT id, ' + ', '.join(FIELDS) +
                ' FROM cplane_run_records WHERE id = %s', (identifier,)).fetchone()
            if row is None:
                raise StateError('Run record not found')
            return self._run_record_dict(('id', *FIELDS), row)

    def run_record_mark(self, identifier, *, clear=False):
        with self.mutation():
            if not self.connection.execute('UPDATE cplane_run_records SET eval_candidate = %s WHERE id = %s RETURNING id',
                                           (not clear, identifier)).fetchone():
                raise StateError('Run record not found')

    def run_record_total(self, slice_id):
        with self.locked():
            columns = (*TOKEN_FIELDS, 'seconds')
            row = self.connection.execute('SELECT count(*), ' + ', '.join(f'sum({field})' for field in columns) +
                ' FROM cplane_run_records WHERE slice_id = %s', (slice_id,)).fetchone()
            # PostgreSQL SUM(bigint) returns numeric/Decimal. Keep token sums
            # as arbitrary-precision Python integers for JSON, preserving NULL.
            totals = {field: int(value) if field in TOKEN_FIELDS and value is not None else value
                      for field, value in zip(columns, row[1:])}
            return dict(turns=row[0], **totals)


def slice_record(store, item, job):
    end = job.get('ended_at')
    started = job.get('started_ns')
    record(store, turn_key='slice:' + job['run'], repository=item['repo'], feature=item.get('feature'),
           log=Path(job['run']) / ('turn.jsonl' if job['tool'] == 'codex' else 'claude.json'),
           kind='slice', slice_id=item['id'], session_id=job.get('session') or None,
           tool=job['tool'], model=job.get('model'), effort=job.get('effort'),
           prompt=job.get('prompt'), starting_commit=job.get('starting_commit'), skill_version=job.get('skills'),
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
               prompt=turn.get('text'), starting_commit=session.get('_starting_commit'), skill_version=None,
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
