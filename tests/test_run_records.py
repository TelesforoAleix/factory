"""Synthetic provider logs and disposable Postgres accounting; no executor calls."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from cplane import run_records, sessions, state
from cplane.cli import main, parser
from cplane.features import TEXT_LIMIT
from test_stores import pg_store
from test_runner import setup


def codex_log():
    report = dict(input_tokens=10, cached_input_tokens=4, cache_write_input_tokens=2,
                  output_tokens=6, reasoning_output_tokens=3)
    return '\n'.join(json.dumps(dict(type='turn.completed', usage=report)) for _ in range(2))


def test_codex_sums_each_turn_and_preserves_missing():
    result = run_records.usage('codex', codex_log())
    assert result == dict(input_tokens=20, cached_tokens=8, cache_write_tokens=4,
                          output_tokens=12, reasoning_tokens=6)
    partial = codex_log() + '\n' + json.dumps(dict(usage=dict(input_tokens=5)))
    assert run_records.usage('codex', partial) == dict(input_tokens=25, cached_tokens=None,
        cache_write_tokens=None, output_tokens=None, reasoning_tokens=None)


def test_claude_maps_usage_missing_is_null():
    result = run_records.usage('claude', json.dumps(dict(usage=dict(
        input_tokens=12, cache_read_input_tokens=7, cache_creation_input_tokens=3, output_tokens=0))))
    assert result == dict(input_tokens=12, cached_tokens=7, cache_write_tokens=3,
                          output_tokens=0, reasoning_tokens=None)
    assert all(v is None for v in run_records.usage('codex', '{}').values())


def test_unreadable_log_still_records_unknown_usage(tmp_path, capsys):
    store = Mock()
    run_records.record(store, turn_key='synthetic', tool='codex', log=tmp_path / 'missing', prompt='PRIVATE')
    assert store.run_record_add.call_args.kwargs['input_tokens'] is None
    assert capsys.readouterr().err == 'cplane: run usage unreadable\n'
    store.run_record_add.side_effect = RuntimeError('PRIVATE')
    run_records.record(store, turn_key='synthetic', tool='codex', output='{}', prompt='PRIVATE')
    assert capsys.readouterr().err == 'cplane: run recording failed\n'


def add_record(store, key='slice:fixture', **overrides):
    values = dict(kind='slice', repository='example/factory', feature='free text', slice_id='factory/B4b',
                  tool='codex', model='synthetic', prompt='PRIVATE prompt',
                  started_at=datetime(2026, 11, 7, tzinfo=timezone.utc), seconds=1.5)
    values.update(overrides)
    run_records.record(store, turn_key=key, output=codex_log(), **values)


def test_postgres_dedup_totals_nulls_and_prompt_bound(pg_store):
    feature = pg_store.feature_add('FAC', 'Synthetic')['id']
    add_record(pg_store, prompt='X' * (TEXT_LIMIT + 1), feature=feature)
    add_record(pg_store)  # Same CLI turn collected a second time.
    pg_store.run_record_add('slice:second', kind='slice', slice_id='factory/B4b', tool='claude',
                           input_tokens=5, output_tokens=None, seconds=2)
    rows = pg_store.run_record_list(slice_id='factory/B4b')
    assert len(rows) == 2 and 'prompt' not in rows[0]
    assert rows[0]['project'] == 'FAC' and rows[0]['feature_id'] == feature
    detail = pg_store.run_record_show(rows[0]['id'])
    assert len(detail['prompt']) <= TEXT_LIMIT and detail['prompt_truncated'] is True
    assert detail['starting_commit'] is None and detail['skill_version'] is None
    assert pg_store.run_record_show(rows[1]['id'])['output_tokens'] is None
    total = pg_store.run_record_total('factory/B4b')
    assert all(type(total[field]) is int for field in run_records.TOKEN_FIELDS)
    assert total == dict(turns=2, input_tokens=25, cached_tokens=8, cache_write_tokens=4,
                         output_tokens=12, reasoning_tokens=6, seconds=3.5)
    assert pg_store.run_record_total('unknown')['input_tokens'] is None
    assert len(pg_store.run_record_list(project='FAC')) == 1


def test_session_turn_tokens_and_filtered_totals(pg_store, capsys):
    def add(key, session, tool, slice_id, **tokens):
        pg_store.run_record_add(key, kind='slice', session_id=session, tool=tool,
                                slice_id=slice_id, **tokens)

    add('a', 'one', 'codex', 'other', input_tokens=100, output_tokens=10, cached_tokens=5)
    add('b', 'one', 'codex', 'target', input_tokens=150, output_tokens=12, cached_tokens=None)
    add('c', 'two', 'codex', 'target', input_tokens=70, output_tokens=8)
    add('d', 'one', 'codex', 'target', input_tokens=20, output_tokens=15, cached_tokens=9)
    add('e', 'one', 'claude', 'target', input_tokens=30, output_tokens=4)
    add('f', None, 'codex', 'target', input_tokens=11)
    add('g', None, 'codex', 'target', input_tokens=13)

    assert main(['run', 'list', '--slice', 'target', '--json']) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row['input_tokens'] for row in rows] == [150, 70, 20, 30, 11, 13]
    assert [row['turn_tokens']['input_tokens'] for row in rows] == [50, 70, 20, 30, 11, 13]
    assert [row['turn_tokens']['output_tokens'] for row in rows] == [2, 8, 3, 4, None, None]
    assert rows[0]['turn_tokens']['cached_tokens'] is None
    assert rows[2]['turn_tokens']['cached_tokens'] is None
    assert pg_store.run_record_total('target') == dict(
        turns=6, input_tokens=194, cached_tokens=None, cache_write_tokens=None,
        output_tokens=17, reasoning_tokens=None, seconds=None)


def test_failed_insert_does_not_abort_scheduler_transaction(pg_store, capsys):
    with state.locked(Path('synthetic.json')) as store:
        # Reuse the active connection, as production does. A second store would
        # wait for the advisory lock held by this transaction.
        assert state.store(None) is store
        # Force a real database CHECK error inside the recorder savepoint.
        add_record(store, kind='invalid')
        assert store.load() == dict(version=1, slices=[])
        add_record(store)
    assert len(pg_store.run_record_list()) == 1
    assert capsys.readouterr().err == 'cplane: run recording failed\n'


def test_commands_and_prompt_privacy(pg_store, capsys):
    add_record(pg_store)
    assert main(['run', 'list', '--json']) == 0
    rows = json.loads(capsys.readouterr().out)
    assert 'prompt' not in rows[0]
    identifier = str(rows[0]['id'])
    assert main(['run', 'show', identifier]) == 0
    assert json.loads(capsys.readouterr().out)['prompt'] == 'PRIVATE prompt'
    assert main(['run', 'mark', identifier]) == 0
    assert pg_store.run_record_show(int(identifier))['eval_candidate'] is True
    assert main(['run', 'mark', identifier, '--clear']) == 0
    assert pg_store.run_record_show(int(identifier))['eval_candidate'] is False
    assert main(['run', 'total', '--slice', 'factory/B4b']) == 0
    assert json.loads(capsys.readouterr().out)['turns'] == 1
    assert main(['run', 'show', '99999']) == 1
    assert 'not found' in capsys.readouterr().err


def test_file_store_skip_and_clear_command_error(monkeypatch, tmp_path, capsys):
    from cplane.stores import FileStore
    monkeypatch.delenv('CPLANE_DATABASE_URL', raising=False)
    run_records.record(FileStore(tmp_path / 'unused'), turn_key='x', log=tmp_path / 'absent')
    assert capsys.readouterr().err == ''
    assert main(['run', 'list']) == 1
    assert 'require Postgres' in capsys.readouterr().err
    assert parser().parse_args(['run']).run_command is None


def test_runner_records_before_applying_final_and_failure_is_harmless(setup, monkeypatch, capsys):
    runner, processes, _ = setup
    runner.run()
    job = next(iter(runner.jobs.values()))
    Path(job['run'], 'turn.jsonl').write_text(codex_log())
    store = Mock()
    store.run_record_add.side_effect = RuntimeError('PRIVATE database diagnostic')
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(state, 'store', lambda _: store)
    processes.finish()
    item = runner.data['slices'][0]
    runner.collect(item, job)
    assert item['state'] == 'in review'
    assert job['phase'] == 'collected'
    values = store.run_record_add.call_args.kwargs
    assert values['skill_version'] == job['skills'] and job['skills']
    assert values['input_tokens'] == 20 and 'prompt' not in values
    assert values['slice_id'] == item['id'] and values['seconds'] >= 0
    assert capsys.readouterr().err == 'cplane: run recording failed\n'


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('code', [0, 124])
def test_chat_one_record_per_owner_message(tmp_path, monkeypatch, tool, code, capsys):
    output = (codex_log() + '\n' + json.dumps(dict(type='thread.started', thread_id='resume-id')) + '\n' +
              json.dumps(dict(type='item.completed', item=dict(type='agent_message', text='reply')))
              if tool == 'codex' else json.dumps(dict(session_id='resume-id', result='reply', usage=dict(input_tokens=8))))
    store = Mock()
    store.run_record_add.side_effect = RuntimeError('PRIVATE')
    turn = dict(id=7, text='exact owner message', session=dict(id=2, repositories=[], tool=tool,
                                                             model='synthetic', effort='medium', cli_session_id=None))
    monkeypatch.setattr(sessions, 'workspace', lambda _: (tmp_path, []))
    monkeypatch.setattr(sessions, 'trusted_directory', lambda _: None)
    monkeypatch.setattr(sessions, 'RUNS', tmp_path)
    monkeypatch.setattr(sessions.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, code, output, ''))
    sessions.execute_turn(turn, store)
    store.finish_session_turn.assert_called_once()
    store.run_record_add.assert_called_once()
    args = store.run_record_add.call_args
    assert args.args == ('chat:7',)
    assert args.kwargs['prompt'] == turn['text'] and args.kwargs['starting_commit'] is None
    assert args.kwargs['session_id'] == '2'
    assert args.kwargs['outcome'] == ('completed' if code == 0 else 'failed')
    assert capsys.readouterr().err == 'cplane: run recording failed\n'


def test_replay_commit_from_trusted_archive_and_local_git(tmp_path, monkeypatch):
    from cplane import fence
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
    repo = tmp_path / 'repo'
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'fixture.md').write_text('Synthetic fixture')
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c',
                    'user.email=test@example.test', 'commit', '-qm', 'fixture'], check=True)
    commit = run_records.starting_commit(repo)
    assert len(commit) == 40
    assert sessions.export_tree(repo, tmp_path / 'export', 'HEAD') == commit
    assert run_records.starting_commit(tmp_path / 'missing') is None


def test_interrupted_chat_has_null_timing_and_exact_message():
    store = Mock()
    turn = dict(id=9, text='Synthetic owner message', session=dict(id=2, tool='codex', model='synthetic'))
    run_records.chat_record(store, turn, dict(outcome='interrupted'))
    values = store.run_record_add.call_args.kwargs
    assert values['prompt'] == turn['text']
    assert values['outcome'] == 'interrupted'
    assert values['started_at'] is None and values['seconds'] is None
    assert values['input_tokens'] is None


def test_legacy_slice_call_leaves_outcomes_empty(pg_store, tmp_path):
    job = dict(run=str(tmp_path), tool='codex', model='synthetic', prompt='PRIVATE',
               final=dict(kind='waiting'))
    (tmp_path / 'turn.jsonl').write_text(codex_log())
    run_records.slice_record(pg_store, dict(id='factory/old', repo='example/factory'), job)
    row, = pg_store.run_record_list(slice_id='factory/old')
    assert all(row[field] is None for field in run_records.OUTCOME_FIELDS)
    assert pg_store.run_record_show(row['id'])['prompt'] is None


@pytest.mark.parametrize('tool,version', [('codex', 'codex-cli-exec 0.162.1\n'),
                                         ('claude', '2.1.318 (Claude Code)\n')])
@pytest.mark.parametrize('overrides', [{}, {'model': 'synthetic'}])
@pytest.mark.parametrize('fenced', [False, True])
def test_launch_captures_policy_hash_and_cli_version(setup, monkeypatch, tool, version, overrides, fenced):
    import hashlib
    runner, _, _ = setup
    runner.run()
    job = next(iter(runner.jobs.values()))
    job.update(tool=tool, effort='high', model='synthetic', fence=fenced)
    store = Mock()
    store.slice_policy.return_value = dict(level='strong', overrides=overrides)
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(state, 'store', lambda _: store)
    probe = Mock(return_value=subprocess.CompletedProcess([], 0, version, ''))
    monkeypatch.setattr(run_records.subprocess, 'run', probe)
    run_records.launch_metadata(runner, runner.data['slices'][0], job)
    assert job['level'] == 'strong'
    assert job['executor_source'] == ('override' if overrides else 'level')
    assert job['configuration'] == f"{tool} {version.split()[1] if tool == 'codex' else version.split()[0]} synthetic high"
    assert job['brief_hash'] == hashlib.sha256(job['prompt'].encode()).hexdigest()
    assert job['prompt'] not in str(probe.call_args)
    command = [tool, 'exec' if tool == 'codex' else '-p', '--version']
    if fenced:
        command = ['factory-cli', 'run', '--tool', tool, '--repo', job['repo'],
                   '--run', str(Path(job['run']) / 'version'), '--', *command]
    assert probe.call_args.args[0] == command
    store.slice_policy.return_value = None
    run_records.launch_metadata(runner, runner.data['slices'][0], job)
    assert job['level'] == 'standard' and job['executor_source'] == 'override'


@pytest.mark.parametrize('error', [FileNotFoundError('PRIVATE'), OSError('PRIVATE'),
                                   subprocess.TimeoutExpired('PRIVATE', 15)])
def test_unavailable_version_still_captures_launch_identity(setup, monkeypatch, capsys, error):
    runner, _, _ = setup
    runner.run()
    job = next(iter(runner.jobs.values()))
    store = Mock()
    store.slice_policy.return_value = dict(level='light', overrides={})
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(state, 'store', lambda _: store)
    monkeypatch.setattr(run_records.subprocess, 'run', Mock(side_effect=error))
    run_records.launch_metadata(runner, runner.data['slices'][0], job)
    assert job['level'] == 'light' and len(job['brief_hash']) == 64
    assert job.get('configuration') is None
    assert capsys.readouterr().err == ''


def test_ci_red_then_green_keeps_both_in_read_order(pg_store, setup, monkeypatch, capsys):
    from cplane.runner import GitHub
    runner, _, _ = setup
    # Launch using the synthetic file scheduler, then attach only accounting to PG.
    monkeypatch.setattr(state, 'postgres', lambda: False)
    runner.run()
    item = runner.data['slices'][0]
    job = runner.jobs[item['id']]
    Path(job['run'], 'turn.jsonl').write_text(codex_log())
    run_records.slice_record(pg_store, item, job)
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(state, 'store', lambda _: pg_store)
    github = GitHub()
    github.repository = Mock(return_value='example/factory')
    github.call = Mock(side_effect=[json.dumps(dict(headRefOid='a' * 40, statusCheckRollup=[
        dict(name='test', conclusion='FAILURE')])), json.dumps(dict(headRefOid='b' * 40,
        statusCheckRollup=[dict(name='test', conclusion='SUCCESS')]))])
    runner.github = github
    job['phase'] = 'pr'
    item.update(pr=12, attention=None, stop_before_merge=True)
    runner.pr_checks(item, job)
    assert item['attention']['kind'] == 'escalation'
    item['attention'] = None
    runner.pr_checks(item, job)
    assert item['attention']['kind'] == 'merge'
    assert main(['runs', 'show', item['id']]) == 0
    row, = json.loads(capsys.readouterr().out)
    assert row['ci_result'] == [dict(sha='a' * 40, status='red', failing_job='test'),
                                dict(sha='b' * 40, status='green', failing_job=None)]
    assert 'prompt' not in row


@pytest.mark.parametrize('verdict', ['pass', 'fix'])
def test_review_verdict_only_after_validation(pg_store, verdict):
    from cplane import review
    add_record(pg_store)
    job = dict(run='fixture')
    with pytest.raises(state.StateError):
        review.validate(dict(verdict='pass'), store=pg_store, job=job)
    assert pg_store.run_record_list()[0]['verdict'] is None
    answer = (dict(verdict='pass', title='PRIVATE', body='PRIVATE') if verdict == 'pass' else
              dict(verdict='fix', tickets=[dict(title='PRIVATE', files=['src.py'],
                                              change='PRIVATE', check='PRIVATE')],
                   test_files=['tests/test_src.py']))
    review.validate(answer, store=pg_store, job=job)
    assert pg_store.run_record_list()[0]['verdict'] == verdict
    assert 'PRIVATE' not in json.dumps(pg_store.run_record_list())


def test_owner_wait_accumulates_intervals_across_restart(setup, monkeypatch):
    from datetime import timedelta
    runner, _, _ = setup
    runner.run()
    item = runner.data['slices'][0]
    job = runner.jobs[item['id']]
    store = Mock()
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(state, 'store', lambda _: store)
    start = runner.instant
    for kind in ('merge', 'node-step', 'question', 'escalation'):
        item['attention'] = dict(kind=kind, since=runner.instant.isoformat())
        run_records.owner_wait(runner, item, job)
        runner.instant += timedelta(seconds=10)
        run_records.owner_wait(runner, item, job)
        # Restore precisely the durable job, as a fresh runner would.
        job = json.loads(Path(job['run'], 'job.json').read_text())
        run_records.owner_wait(runner, item, job, close=True)
        item['attention'] = None
        run_records.owner_wait(runner, item, job)
    assert job['owner_wait_seconds'] == 40
    item['attention'] = dict(kind='owner-check', since=start.isoformat())
    runner.instant += timedelta(seconds=100)
    run_records.owner_wait(runner, item, job)
    assert job['owner_wait_seconds'] == 40
    assert store.run_record_outcome.call_args.kwargs == dict(owner_wait_seconds=40)


def test_outcome_failure_is_private_and_harmless(capsys):
    store = Mock()
    store.run_record_outcome.side_effect = RuntimeError('PRIVATE')
    run_records.outcome(store, dict(run='synthetic'), verdict='fix')
    assert capsys.readouterr().err == 'cplane: run recording failed\n'


def test_owner_wait_uses_planner_clear_time(setup, monkeypatch):
    from datetime import timedelta
    runner, _, _ = setup
    runner.run()
    item = runner.data['slices'][0]
    job = runner.jobs[item['id']]
    store = Mock()
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(state, 'store', lambda _: store)
    start = runner.instant
    item['attention'] = dict(kind='question', since=start.isoformat())
    item['log'].append(dict(at=start.isoformat(), actor='planner', event='attention'))
    run_records.owner_wait(runner, item, job)
    item['attention'] = None
    item['log'].append(dict(at=(start + timedelta(seconds=5)).isoformat(),
                           actor='planner', event='attention'))
    runner.instant += timedelta(seconds=10)
    run_records.owner_wait(runner, item, job)
    assert job['owner_wait_seconds'] == 5


def test_outcome_sql_failure_preserves_scheduler_transaction(pg_store, capsys):
    add_record(pg_store)
    with state.locked(Path('synthetic.json')) as store:
        run_records.outcome(store, dict(run='fixture'), verdict='invalid')
        assert store.load() == dict(version=1, slices=[])
        run_records.outcome(store, dict(run='fixture'), verdict='pass')
    assert pg_store.run_record_list()[0]['verdict'] == 'pass'
    assert capsys.readouterr().err == 'cplane: run recording failed\n'


def test_failed_outcome_write_preserves_runner_attention(setup, monkeypatch, capsys):
    runner, _, _ = setup
    runner.run()
    item = runner.data['slices'][0]
    store = Mock()
    store.run_record_outcome.side_effect = RuntimeError('PRIVATE recording failure')
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(state, 'store', lambda _: store)
    runner.attention(item, 'escalation', 'Original runner error')
    assert item['state'] == 'escalated'
    assert item['attention']['body'] == 'Original runner error'
    assert item['log'][-1]['event'] == 'escalation: Original runner error'
    assert capsys.readouterr().err == 'cplane: run recording failed\n' * 2


def test_slice_link_existing_and_future_records(pg_store, make_state, slice_data, capsys):
    import copy
    other = copy.deepcopy(slice_data)
    other['id'] = 'voice/W0'
    path = make_state([slice_data, other])
    pg_store.import_file(path)
    add_record(pg_store, slice_id='voice/W1')
    assert main(['slice', 'link', 'voice/W1', '--corrects', 'voice/W0', '--actor', 'planner']) == 0
    first, = pg_store.run_record_list(slice_id='voice/W1')
    assert first['corrects_slice'] == 'voice/W0'
    add_record(pg_store, key='slice:future', slice_id='voice/W1')
    assert all(r['corrects_slice'] == 'voice/W0' for r in pg_store.run_record_list())
    item = pg_store.load()['slices'][0]
    assert item['log'][-1]['actor'] == 'planner'
    assert item['log'][-1]['event'] == 'slice link: corrects voice/W0'
    assert pg_store.notices()[-1][1]['event'] == 'slice link'
    before = pg_store.snapshot()
    assert main(['slice', 'link', 'voice/W1', '--corrects', 'voice/W1']) == 1
    assert main(['slice', 'link', 'voice/W1', '--corrects', 'missing']) == 1
    assert pg_store.snapshot() == before
    assert pg_store.run_record_show(first['id'])['corrects_slice'] == 'voice/W0'


@pytest.mark.parametrize('verdict', ['accepted', 'corrected'])
def test_planner_review_labels_all_slice_records_atomically(pg_store, make_state, verdict, capsys):
    path = make_state()
    pg_store.import_file(path)
    add_record(pg_store, slice_id='voice/W1', verdict='pass')
    add_record(pg_store, key='slice:next', slice_id='voice/W1', verdict='fix')
    assert main(['review', 'voice/W1', verdict, '--actor', 'planner']) == 1
    assert [r['verdict'] for r in pg_store.run_record_list()] == ['pass', 'fix']
    with pg_store.mutation():
        data = pg_store.load()
        data['slices'][0]['attention'] = dict(kind='merge', body='Synthetic',
            since='2026-11-07T00:00:00+00:00', answer=None, approved=False)
        pg_store.save(data)
    assert main(['review', 'voice/W1', verdict, '--actor', 'planner']) == 0
    assert all(r['verdict'] == verdict for r in pg_store.run_record_list())
    # A late old-style runner update must not erase the planner verdict.
    pg_store.run_record_outcome('slice:fixture', verdict='fix')
    first = pg_store.run_record_list()[0]
    assert pg_store.run_record_show(first['id'])['verdict'] == verdict
    assert pg_store.load()['slices'][0]['attention']['review']['verdict'] == verdict


def test_export_json_lines_filters_and_omits_prompt(pg_store, capsys):
    add_record(pg_store, key='slice:old', started_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    add_record(pg_store, key='slice:new', prompt='PRIVATE PROMPT', verdict='pass')
    add_record(pg_store, key='chat:new', kind='chat', prompt='PRIVATE CHAT')
    pg_store.slice_outcome('factory/B4b', verdict='corrected', corrects='factory/previous')
    task = dict(id='task-1', position=1, status='failed', reason='check failed',
                tokens=100, seconds=2.5, cost=0.03, title='PRIVATE TITLE', prompt='PRIVATE TASK')
    pg_store.task_record_poll('factory/B4b', [task])
    pg_store.task_record_poll('factory/B4b', [{**task, 'attempt': 2, 'status': 'running', 'reason': None}])
    pg_store.task_record_poll('factory/B4b', [{**task, 'attempt': 2, 'status': 'done', 'tokens': 120}])
    pg_store.task_record_poll('factory/old', [{**task, 'id': 'old-task'}])
    with pg_store.mutation():
        pg_store.connection.execute(
            "UPDATE cplane_task_runs SET started_at = '2026-11-07T00:00:00Z'")
        pg_store.connection.execute(
            "UPDATE cplane_task_runs SET started_at = '2026-11-06T23:59:59Z' WHERE task_id = 'old-task'")
    assert main(['runs', 'export', '--since', '2026-11-07']) == 0
    output = capsys.readouterr().out
    rows = [json.loads(line) for line in output.splitlines()]
    assert [r['kind'] for r in rows] == ['slice', 'task', 'task']
    assert 'PRIVATE' not in output
    assert all('prompt' not in r and 'title' not in r for r in rows)
    assert all(r['verdict'] == 'corrected' and r['corrects_slice'] == 'factory/previous' for r in rows)
    assert [(r['attempt'], r['status'], r['tokens']) for r in rows[1:]] == [(1, 'failed', 100), (2, 'done', 120)]
    assert rows[1]['seconds'] == 2.5 and rows[1]['cost'] == 0.03
    assert 'goal' not in rows[1] and 'check_command' not in rows[1]
    assert main(['runs', 'export', '--since', 'bad date']) == 1
    assert '--since must be an ISO date' in capsys.readouterr().err


def test_planner_accounting_failure_rolls_back_review(pg_store, make_state, monkeypatch):
    path = make_state()
    pg_store.import_file(path)
    with pg_store.mutation():
        data = pg_store.load()
        data['slices'][0]['attention'] = dict(kind='merge', body='Synthetic',
            since='2026-11-07T00:00:00+00:00', answer=None, approved=False)
        pg_store.save(data)
    before = pg_store.snapshot()
    # CLI creates a fresh store, so fail the class method.
    from cplane.stores import PostgresStore
    monkeypatch.setattr(PostgresStore, 'slice_outcome', Mock(side_effect=state.StateError('Synthetic failure')))
    assert main(['review', 'voice/W1', 'accepted']) == 1
    assert pg_store.snapshot() == before


def test_repair_tasks_keep_parent_and_distinct_attempt_identity(pg_store, make_state):
    pg_store.import_file(make_state())
    task = dict(id='same-id', position=1, status='done', reason=None)
    pg_store.task_record_poll('voice/W1', [task])
    pg_store.task_record_poll('voice/W1/repair', [task])
    pg_store.slice_outcome('voice/W1', verdict='corrected')
    rows = pg_store.run_record_export(datetime(1970, 1, 1, tzinfo=timezone.utc))
    assert len(rows) == 2
    assert {r['queue_slice'] for r in rows} == {'voice/W1', 'voice/W1/repair'}
    assert all(r['slice_id'] == 'voice/W1' and r['verdict'] == 'corrected' for r in rows)


def test_empty_export_and_optional_task_metrics(pg_store, capsys):
    assert main(['runs', 'export', '--since', '1970-01-01']) == 0
    assert capsys.readouterr().out == ''
    pg_store.task_record_poll('synthetic/slice', [dict(
        id=7, position=1, title='PRIVATE', status='queued', reason=None)])
    assert main(['runs', 'export', '--since', '1970-01-01']) == 0
    row = json.loads(capsys.readouterr().out)
    assert row['task_id'] == '7' and row['attempt'] == 1
    assert row['tokens'] is None and row['seconds'] is None and row['cost'] is None
