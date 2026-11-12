"""Persisted model choices; only explicit refreshes execute a model program."""
import json
import os
import re
import shutil
import subprocess
import uuid

from .roles import EFFORTS, TOOLS
from . import fence
from .state import StateError

ALIASES = ('fable', 'opus', 'sonnet', 'haiku')
CLAUDE_EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max']
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}')
FAILURE = 'Model update failed; previous list kept.'


def catalog(tool, run):
    """Validate all output before opening the replacement transaction."""
    if tool == 'codex':
        payload = json.loads(run(['codex', 'debug', 'models']))
        rows = []
        for model in payload['models']:
            if model['visibility'] != 'list':
                continue
            efforts = [level['effort'] for level in model['supported_reasoning_levels']]
            rows.append(dict(model=model['slug'], label=model['slug'], efforts=efforts))
    else:
        rows = []
        for alias in ALIASES:
            payload = json.loads(run(['claude', '-p', '--model', alias, '--effort', 'low',
                                      '--output-format', 'json', '--', 'Reply only: OK']))
            if payload.get('is_error'):
                continue
            ids = list(payload.get('modelUsage') or {})
            if not ids:
                continue
            if len(ids) != 1:
                raise ValueError('ambiguous model')
            rows.append(dict(model=ids[0], label=alias, efforts=list(CLAUDE_EFFORTS)))
    if not rows or len({r['label'] for r in rows}) != len(rows):
        raise ValueError('empty or duplicate catalog')
    for row in rows:
        if (not isinstance(row['model'], str) or not IDENTIFIER.fullmatch(row['model'])
                or not row['efforts'] or any(e not in EFFORTS for e in row['efforts'])
                or len(set(row['efforts'])) != len(row['efforts'])):
            raise ValueError('invalid catalog')
    return rows


def cleanup_runs(commands):
    """Attempt every stop before allowing deletion of the probe workspace."""
    failure = None
    for command in commands:
        try:
            subprocess.run([*fence.fence_command(), *command], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           env=fence.host_environment())
        except (OSError, subprocess.SubprocessError) as error:
            failure = failure or error
    if failure is not None:
        raise failure


def refresh_catalog(tool):
    """Use the chat execution boundary, user, login mounts and host environment."""
    from . import sessions
    from .fence import WORK_ROOT, trusted_directory, host_environment
    trusted_directory(WORK_ROOT)
    trusted_directory(sessions.RUNS)
    token = uuid.uuid4().hex
    folder = WORK_ROOT / ('models-' + token)
    run_root = sessions.RUNS / ('models-' + token)
    folder.mkdir(mode=0o700)
    fence.own(folder, 'work')
    run_root.mkdir(mode=0o700)
    turn_id = (1 << 128) + int(token, 16)  # Disjoint from Postgres bigint chat IDs.
    started = []
    try:
        def run(command):
            output = run_root / str(uuid.uuid4())
            output.mkdir(mode=0o700)
            run_id = f'models-{token}-{output.name}'
            options = (['--run-id', run_id] if fence.socket_enabled()
                       else ['--session-turn', str(turn_id)])
            started.append(run_id)
            result = subprocess.run(
                [*fence.fence_command(), 'run', '--tool', tool, '--repo', str(folder),
                 '--run', str(output), *options, '--', *command],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=1260, env=host_environment())
            if result.returncode:
                raise ValueError('program failed')
            return result.stdout
        return catalog(tool, run)
    finally:
        # The wrapper cleans up normal turns and its own timeout. Also cover an
        # interrupted/killed wrapper before touching an agent-owned workspace.
        cleanups = ([['stop', run_id] for run_id in started] if fence.socket_enabled()
                    else [['session-cleanup', str(turn_id)]])
        cleanup_runs(cleanups)
        fence.remove(folder, 'work')
        shutil.rmtree(run_root)


def recover_catalog_runs():
    from . import sessions
    from .fence import WORK_ROOT, trusted_directory
    trusted_directory(sessions.RUNS)
    trusted_directory(WORK_ROOT)
    for run_root in sessions.RUNS.glob('models-*'):
        token = run_root.name.removeprefix('models-')
        if not re.fullmatch('[0-9a-f]{32}', token):
            continue
        turn_id = (1 << 128) + int(token, 16)
        cleanups = ([['stop', f'models-{token}-{output.name}']
                     for output in sorted(run_root.iterdir())
                     if output.is_dir() and not output.is_symlink()] if fence.socket_enabled()
                    else [['session-cleanup', str(turn_id)]])
        cleanup_runs(cleanups)
        folder = WORK_ROOT / run_root.name
        if folder.exists():
            fence.remove(folder, 'work')
        shutil.rmtree(run_root)


class ModelStore:
    def model_list(self):
        with self.locked():
            return [dict(tool=r[0], model=r[1], label=r[2], efforts=r[3], refreshed_at=r[4].isoformat())
                    for r in self.connection.execute(
                        'SELECT tool, model, label, efforts, refreshed_at FROM cplane_models ORDER BY tool, label')]

    def model_choice(self, tool, model, effort):
        if tool not in TOOLS or not isinstance(model, str) or effort not in EFFORTS:
            raise StateError('Invalid tool, model or effort')
        choices = [r for r in self.model_list() if r['tool'] == tool
                   and model in (r['model'], r['label']) and effort in r['efforts']]
        if not choices:
            raise StateError('Choose a model and effort from the stored list')
        return choices[0]['model']

    def model_in_list(self, tool, model, effort):
        return any(r['tool'] == tool and model in (r['model'], r['label']) and effort in r['efforts']
                   for r in self.model_list())

    def models_update(self, tool):
        if tool not in TOOLS:
            raise StateError('Unknown model tool')
        try:
            rows = refresh_catalog(tool)
            from psycopg.types.json import Jsonb
            with self.mutation():
                self.connection.execute('DELETE FROM cplane_models WHERE tool = %s', (tool,))
                for row in rows:
                    self.connection.execute(
                        'INSERT INTO cplane_models (tool, model, label, efforts) VALUES (%s, %s, %s, %s)',
                        (tool, row['model'], row['label'], Jsonb(row['efforts'])))
            result = dict(status='completed', tool=tool)
            if tool == 'claude':
                skipped = [alias for alias in ALIASES if alias not in {r['label'] for r in rows}]
                if skipped:
                    result.update(skipped=skipped, reason='Skipped aliases: ' + ', '.join(skipped) + '.')
            return result
        except Exception:
            # Never persist or return subprocess output, arguments or credentials.
            return dict(status='failed', tool=tool, reason=FAILURE)

    def models_request(self, tool):
        if tool not in TOOLS:
            raise StateError('Unknown model tool')
        with self.mutation():
            row = self.connection.execute(
                "SELECT id, status FROM cplane_model_updates WHERE tool = %s AND status IN ('queued','running')",
                (tool,)).fetchone()
            if row is None:
                row = self.connection.execute(
                    'INSERT INTO cplane_model_updates (tool) VALUES (%s) RETURNING id, status', (tool,)).fetchone()
            return dict(id=row[0], tool=tool, status=row[1])

    def models_status(self):
        with self.locked():
            updates = [dict(id=r[0], tool=r[1], status=r[2], reason=r[3]) for r in self.connection.execute(
                'SELECT DISTINCT ON (tool) id, tool, status, reason FROM cplane_model_updates ORDER BY tool, id DESC')]
            return dict(models=self.model_list(), updates=updates)

    def models_recover(self):
        with self.mutation():
            self.connection.execute(
                "UPDATE cplane_model_updates SET status = 'failed', reason = %s WHERE status = 'running'", (FAILURE,))

    def models_process_one(self):
        with self.mutation():
            row = self.connection.execute(
                "SELECT id, tool FROM cplane_model_updates WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
            if row is None:
                return False
            self.connection.execute("UPDATE cplane_model_updates SET status = 'running' WHERE id = %s", (row[0],))
        result = self.models_update(row[1])
        with self.mutation():
            self.connection.execute('UPDATE cplane_model_updates SET status = %s, reason = %s WHERE id = %s',
                                    (result['status'], result.get('reason'), row[0]))
        return True
