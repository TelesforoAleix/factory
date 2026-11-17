# ruff: noqa: F811 - shared pytest fixtures
"""Synthetic eval execution: fake harnesses, disposable Postgres, offline Git."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from unittest.mock import Mock

import pytest

from cplane import eval_runner, evals, executors, fence, state
from cplane.cli import main
from cplane.runner import Runner
from cplane.eval_execution import Context
from test_evals import cases  # noqa: F401
from test_fenced_runner import delivery  # noqa: F401
from test_stores import pg_store  # noqa: F401

OUTPUTS = {
    'codex': '\n'.join([json.dumps(dict(type='thread.started', thread_id='synthetic')),
                        json.dumps(dict(type='turn.completed', usage=dict(input_tokens=123, output_tokens=45)))]),
    'claude': json.dumps(dict(type='result', is_error=False, result='done',
                              usage=dict(input_tokens=321, output_tokens=54))),
}


class FakeProcesses:
    def __init__(self):
        self.started = []
        self.finished = False
        self.output = None
        self.exit = None
        self.failure = False

    def start(self, job):
        if self.failure:
            raise OSError('synthetic secret /other/run/private')
        self.started.append(job.copy())
        return 999999999

    def poll(self, job):
        return self.finished, '', None, ''

    def stop(self, job):
        pass

    def finish(self, job):
        folder = Path(job['run'])
        name = 'turn.jsonl' if job['tool'] == 'codex' else 'claude.json'
        (folder / name).write_text(self.output if self.output is not None else OUTPUTS[job['tool']])
        executors.atomic_json(folder / 'exit.json', self.exit or dict(code=0, at=time.time()))
        self.finished = True


@pytest.fixture
def execution(pg_store, cases, tmp_path, monkeypatch):
    evals.import_folder(pg_store, cases[0])
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_eval_cases SET kind='review'")
    evals.set_create(pg_store, 'synthetic', title='S', filters={'size': 'S'})
    processes = FakeProcesses()
    runner = Context(Runner(tmp_path / 'state', git=Mock(), orders=Mock(), runs=tmp_path / 'runs'))
    runner.processes = processes
    runner.codex_reader = lambda: 0
    runner.claude_reader = lambda: dict(at=time.time() - 1, rate_limits=dict(five_hour=dict(used_percentage=0, resets_at=time.time() + 60)))
    runner.instant = datetime.now(timezone.utc)
    runner.jobs = {}
    runner.data = dict(version=1, slices=[])
    adapter = Mock()
    def prepare(repository, base, copy_id):
        copy = tmp_path / ('work-' + copy_id)
        copy.mkdir(mode=0o700)
        return dict(repo=str(copy), repository=repository, base=base)
    adapter.prepare_eval.side_effect = prepare
    adapter.eval_diff.return_value = 'diff --git a/new b/new\nnew content\n'
    runner.fence = adapter
    monkeypatch.setattr(fence, 'remove', lambda path, role: __import__('shutil').rmtree(path))
    return runner, processes, adapter


def create(store, *, at=None, tool='codex', effort=None, repeats=1):
    config = dict(id='synthetic', harness=tool, model='synthetic-model', route='subscription')
    if effort is not None:
        config['effort'] = effort
    return evals.run_create(store, title='Synthetic execution', sets=['synthetic'],
                            configurations=[config], repeats=repeats, scheduled_for=at)


def step(store, runner, *, start=True):
    with state.locked(runner.path):
        backend = state.store(runner.path)
        eval_runner.collect(runner, backend)
        if start:
            eval_runner.start(runner, backend)


@pytest.mark.parametrize('when,expected', [('now', True), ('equal', True), ('past', True), ('future', False), ('cancelled', False)])
def test_schedule(pg_store, execution, when, expected):
    runner, processes, _ = execution
    at = None if when in ('now', 'cancelled') else (runner.instant + timedelta(days=1 if when == 'future' else -1)).isoformat()
    if when == 'equal':
        at = runner.instant.isoformat()
    run = create(pg_store, at=at)
    if when == 'cancelled':
        evals.run_cancel(pg_store, run['id'])
    step(pg_store, runner)
    assert bool(processes.started) is expected
    assert evals.run_show(pg_store, run['id'])['state'] == ('running' if expected else 'cancelled' if when == 'cancelled' else 'planned')


@pytest.mark.parametrize('tool,effort', [('codex', 'low'), ('claude', 'high'), ('codex', None), ('claude', None)])
def test_attempt_prompt_configuration_diff_metrics_and_completion(pg_store, execution, tool, effort):
    runner, processes, adapter = execution
    run = create(pg_store, tool=tool, effort=effort)
    step(pg_store, runner)
    job, = processes.started
    assert job['prompt'] == eval_runner.LEAD + 'Synthetic task'
    assert job['model'] == 'synthetic-model' and job['effort'] == (effort or 'medium')
    assert job['timeout_seconds'] == 1800
    assert adapter.prepare_eval.call_args.args[:2] == ('example/public', 'a' * 40)
    args = executors.command(job)
    assert args[-2:] == ['--', job['prompt']]
    assert 'synthetic-model' in args
    assert (f'model_reasoning_effort="{effort or "medium"}"' in args if tool == 'codex'
            else args[args.index('--effort') + 1] == (effort or 'medium'))
    processes.finish(job)
    step(pg_store, runner)
    saved = evals.run_show(pg_store, run['id'])
    attempt, = saved['attempts']
    assert saved['state'] == 'done' and attempt['state'] == 'done'
    assert attempt['run_record'] is None and attempt['result'] is None
    assert Path(attempt['output_ref']).read_text() == adapter.eval_diff.return_value
    assert Path(attempt['output_ref']).stat().st_mode & 0o777 == 0o600
    assert Path(job['run']).stat().st_mode & 0o777 == 0o700
    assert not Path(job['repo']).exists()
    assert attempt['metrics']['input_tokens'] == (123 if tool == 'codex' else 321)
    assert attempt['metrics']['output_tokens'] == (45 if tool == 'codex' else 54)
    assert attempt['metrics']['wall_seconds'] >= 0
    assert set(attempt['metrics']) == {'wall_seconds', 'input_tokens', 'output_tokens'}


def test_one_attempt_id_order_and_cancel_running_finishes(pg_store, execution):
    runner, processes, _ = execution
    run = create(pg_store, repeats=3)
    create(pg_store)
    step(pg_store, runner)
    step(pg_store, runner)
    assert len(processes.started) == 1
    assert processes.started[0]['eval_attempt'] == run['attempts'][0]['id']
    processes.finish(processes.started[0])
    step(pg_store, runner)
    assert [j['eval_attempt'] for j in processes.started] == [a['id'] for a in run['attempts'][:2]]
    assert main(['eval', 'run', 'cancel', str(run['id'])]) == 0
    processes.finish(processes.started[-1])
    step(pg_store, runner, start=False)
    saved = evals.run_show(pg_store, run['id'])
    assert saved['state'] == 'cancelled'
    assert [a['state'] for a in saved['attempts']] == ['done', 'done', 'planned']


@pytest.mark.parametrize('failure', ['start', 'timeout', 'unreadable', 'launch-exit'])
def test_safe_failures(pg_store, execution, failure):
    runner, processes, _ = execution
    run = create(pg_store)
    processes.failure = failure == 'start'
    step(pg_store, runner)
    if failure != 'start':
        job, = processes.started
        if failure == 'timeout':
            processes.exit = dict(code=1, at=time.time(), timeout=True)
        elif failure == 'launch-exit':
            processes.exit = dict(code=125, at=time.time())
        processes.finish(job)
        if failure == 'unreadable':
            (Path(job['run']) / 'turn.jsonl').unlink()
        step(pg_store, runner)
    saved = evals.run_show(pg_store, run['id'])
    assert saved['state'] == 'done'
    attempt, = saved['attempts']
    assert attempt['state'] == 'failed' and attempt['output_ref'] is None
    assert set(attempt['result']) == {'error'}
    assert attempt['result']['error'] in ('Attempt could not start', 'Attempt timed out', 'Attempt output unavailable')
    assert 'secret' not in json.dumps(attempt) and '/other/run' not in json.dumps(attempt)


@pytest.mark.parametrize('tool', ['codex', 'claude'])
def test_usage_limit_replans_and_holds_until_reset(pg_store, execution, monkeypatch, tool):
    runner, processes, _ = execution
    monkeypatch.setattr('cplane.eval_execution.codex_limits', lambda: None)
    run = create(pg_store, tool=tool)
    step(pg_store, runner)
    processes.output = (json.dumps(dict(type='turn.failed', error=dict(message='usage limit; try again at 11:59 PM')))
                        if tool == 'codex' else json.dumps(dict(is_error=True, result='You have hit your limit')))
    processes.finish(processes.started[0])
    step(pg_store, runner)
    assert evals.run_show(pg_store, run['id'])['attempts'][0]['state'] == 'planned'
    assert len(processes.started) == 1
    reset = runner.jobs['eval:' + str(run['attempts'][0]['id'])]['reset_at']
    runner.instant = datetime.fromtimestamp(reset - 1, timezone.utc)
    step(pg_store, runner)
    assert len(processes.started) == 1
    runner.instant += timedelta(seconds=2)
    step(pg_store, runner)
    assert len(processes.started) == 2


@pytest.mark.parametrize('harness', ['other'])
def test_unavailable_harness_creates_nothing(pg_store, execution, harness):
    with pytest.raises(state.StateError, match=f'harness {harness} is not available yet'):
        create(pg_store, tool=harness)
    assert evals.run_list(pg_store) == []
    with pg_store.locked():
        assert pg_store.connection.execute('SELECT count(*) FROM cplane_eval_attempts').fetchone()[0] == 0


def test_shared_capacity_and_repository_lock(pg_store, execution, slice_data):
    runner, processes, _ = execution
    run = create(pg_store)
    runner.data['slices'] = [dict(slice_data, state='issued', repo='example/other')]
    runner.jobs = {'voice/W1': dict(phase='running', repository='example/other')}
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_settings SET value=1 WHERE name='executors'")
    step(pg_store, runner)
    assert not processes.started
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_settings SET value=2 WHERE name='executors'")
    step(pg_store, runner)
    assert len(processes.started) == 1
    assert runner.room(dict(id='another', repo='example/third', state='ready')).startswith('executor limit')
    assert evals.run_show(pg_store, run['id'])['attempts'][0]['state'] == 'running'


def test_empty_diff_and_unknown_tokens_are_success(pg_store, execution):
    runner, processes, adapter = execution
    run = create(pg_store)
    adapter.eval_diff.return_value = ''
    step(pg_store, runner)
    processes.output = '{}'
    processes.finish(processes.started[0])
    step(pg_store, runner)
    attempt, = evals.run_show(pg_store, run['id'])['attempts']
    assert attempt['state'] == 'done' and Path(attempt['output_ref']).read_text() == ''
    assert set(attempt['metrics']) == {'wall_seconds'}


def test_fresh_copy_pinned_base_and_safe_diff(delivery):
    d = delivery
    # Advance remote main: the case must still start at its older pinned commit.
    seed = d['root'] / 'advanced-main'
    d['g'](d['root'], 'clone', d['remote'], seed)
    (seed / 'README').write_text('new main\n')
    d['g'](seed, 'add', '.')
    d['g'](seed, 'commit', '-m', 'advance synthetic main')
    d['g'](seed, 'push', 'origin', 'main')
    before = d['g'](d['clean'], 'rev-parse', 'refs/heads/' + d['job']['branch'])
    job = d['adapter'].prepare_eval('example/repo', d['base'], 'a' * 32)
    work = Path(job['repo'])
    assert (work / '.git/HEAD').read_text() == d['base'] + '\n'
    assert work.stat().st_mode & 0o777 == 0o750
    assert (work / 'README').stat().st_mode & 0o040
    assert (work / 'README').read_text() == 'base\n'
    assert d['g'](d['clean'], 'rev-parse', 'refs/heads/' + d['job']['branch']) == before
    assert not d['g'](d['clean'], 'for-each-ref', 'refs/heads/factory-eval-')
    # Hostile agent Git config and hooks must never be loaded by host Git.
    (work / '.git/config').write_text('[core]\n fsmonitor = ' + str(d['marker']) + '\n')
    (work / 'README').write_text('changed\n')
    (work / 'untracked').write_text('new\n')
    (work / 'binary').write_bytes(b'\0binary')
    (work / 'link').symlink_to('/private/outside')
    (work / '.gitignore').write_text('ignored\n')
    (work / 'ignored').write_text('keep this too\n')
    job['run'] = str(d['folder'])
    patch = d['adapter'].eval_diff(job)
    assert all(name in patch for name in ('README', 'untracked', 'binary', 'link', 'ignored'))
    assert '+/private/outside' in patch and 'GIT binary patch' in patch
    assert '.git/config' not in patch
    assert not d['marker'].exists()
    assert any('fetch' in args for args, _ in d['calls'])
    assert not any('push' in args for args, _ in d['calls'])


@pytest.mark.parametrize('hostile', ['fifo', 'hardlink'])
def test_diff_rejects_special_files(delivery, hostile):
    d = delivery
    path = d['work'] / 'hostile'
    if hostile == 'fifo':
        os.mkfifo(path)
    else:
        path.hardlink_to(d['work'] / 'README')
    with pytest.raises(state.StateError, match='invalid eval output file'):
        d['adapter'].eval_diff(d['job'])


def test_eval_supervisor_timeout_stops_container(tmp_path, monkeypatch):
    job = dict(eval_attempt=1, tool='codex', model='synthetic', repo='/work/copy', run=str(tmp_path),
               prompt='synthetic', timeout_seconds=1800, container_id='eval-synthetic', cleanup_turn=123)
    executors.atomic_json(tmp_path / 'request.json', job)
    monkeypatch.setenv('CPLANE_FENCE_COMMAND', 'socket')
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        if 'run' in args:
            assert kwargs['timeout'] == 1800
            raise subprocess.TimeoutExpired(args, 1800)
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(subprocess, 'run', run)
    executors.supervise(tmp_path)
    assert calls[-1][0][-2:] == ['stop', 'eval-synthetic']
    assert json.loads((tmp_path / 'exit.json').read_text())['timeout'] is True


def test_platform_slice_does_not_reserve_local_eval_capacity(pg_store, execution, slice_data):
    runner, processes, _ = execution
    run = create(pg_store)
    runner.jobs = {'voice/W1': dict(phase='running', repository='example/other', requests={'slice': {}})}
    runner.data['slices'] = [dict(slice_data, state='issued', repo='example/other')]
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_settings SET value=1 WHERE name='executors'")
    step(pg_store, runner)
    assert len(processes.started) == 1
    assert evals.run_show(pg_store, run['id'])['attempts'][0]['state'] == 'running'


def test_same_repository_waits_for_slice(pg_store, execution, slice_data):
    runner, processes, _ = execution
    create(pg_store)
    runner.jobs = {'voice/W1': dict(phase='running', repository='example/public')}
    runner.data['slices'] = [dict(slice_data, state='issued', repo='example/public')]
    step(pg_store, runner)
    assert not processes.started


def test_restart_recovers_uncommitted_launch(pg_store, execution):
    runner, processes, _ = execution
    run = create(pg_store)
    step(pg_store, runner)
    # The local durable intent survives a rolled-back scheduler transaction.
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_eval_attempts SET state='planned'")
    step(pg_store, runner)
    assert len(processes.started) == 1
    assert evals.run_show(pg_store, run['id'])['attempts'][0]['state'] == 'running'
    processes.finish(processes.started[0])
    step(pg_store, runner)
    assert evals.run_show(pg_store, run['id'])['state'] == 'done'


def test_failed_timeout_cleanup_reserves_capacity(pg_store, execution, monkeypatch):
    runner, processes, _ = execution
    run = create(pg_store)
    step(pg_store, runner)
    job = runner.jobs['eval:' + str(run['attempts'][0]['id'])]
    job['started_ns'] = time.time_ns() - 1801 * 1_000_000_000
    monkeypatch.setattr(processes, 'stop', Mock(side_effect=OSError('synthetic cleanup failure')))
    step(pg_store, runner)
    assert evals.run_show(pg_store, run['id'])['attempts'][0]['state'] == 'running'
    assert len(processes.started) == 1
    assert Path(job['repo']).exists()


def test_attempt_reservation_is_global_across_runner_paths(pg_store, execution):
    runner, processes, adapter = execution
    run = create(pg_store)
    step(pg_store, runner)
    other = Context(Runner(runner.path.parent / 'other-state', runs=runner.runs.parent))
    other.processes, other.codex_reader = processes, lambda: 0
    other.jobs, other.data, other.instant = {}, runner.data, runner.instant
    other.fence = adapter
    step(pg_store, other)
    assert len(processes.started) == 1
    assert other.jobs['eval:' + str(run['attempts'][0]['id'])]['phase'] == 'running'
    # Even missing metadata cannot release capacity for a second live attempt.
    Path(processes.started[0]['run'], 'job.json').unlink()
    other.jobs = {}
    step(pg_store, other)
    assert len(processes.started) == 1
    assert other.jobs['eval:' + str(run['attempts'][0]['id'])]['metadata_unavailable']


def test_attempt_uses_start_commit_and_diffs_from_that_start(pg_store, execution):
    runner, processes, adapter = execution
    with pg_store.mutation():
        pg_store.connection.execute('UPDATE cplane_eval_cases SET start_commit=%s', ('b' * 40,))
    run = create(pg_store)
    step(pg_store, runner)
    job, = processes.started
    assert adapter.prepare_eval.call_args.args[:2] == ('example/public', 'b' * 40)
    assert job['base'] == 'b' * 40
    processes.finish(job)
    step(pg_store, runner)
    assert adapter.eval_diff.call_args.args[0]['base'] == 'b' * 40
    assert evals.run_show(pg_store, run['id'])['attempts'][0]['state'] == 'done'
