"""Synthetic judge requests, recovery, and calibration through a fake run API."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from cplane import cli, eval_judge, evals, run_platform, skills, state
from cplane.eval_execution import Context
from test_eval_runner import (Runs, block, cases, create, execution, finish_slice,
                              pg_store, saved, step)  # noqa: F401


def enable_judge(store):
    with store.mutation():
        store.connection.execute("UPDATE cplane_eval_cases SET grade='tests_and_judge'")


def start_judge(store, runner, api):
    enable_judge(store)
    run = create(store)
    step(store, runner)
    finish_slice(store, runner, api)
    api.finish('check', check=1)
    step(store, runner)
    return run


@pytest.mark.parametrize('status,body', [('failed', 'Judge failed'), ('question', 'Need help'),
                                        ('done', 'No verdict'), ('done', block({'verdict': 'pass', 'reason': 'Bad'}))])
def test_judge_failure_retains_test_grade(pg_store, execution, status, body):
    runner, api, github = execution
    run = start_judge(pg_store, runner, api)
    api.finish('review', body, status=status)
    step(pg_store, runner)
    attempt = saved(pg_store, run)
    assert attempt['state'] == 'done'
    assert attempt['result']['tests'] == 'fail' and attempt['result']['judge'] is None
    assert attempt['result']['judge_error']
    assert attempt['verdicts'] == [] and len(attempt['runs']) == 4
    github.delete_eval_branch.assert_called_once()


def test_oversized_inputs_skip_judge(pg_store, execution):
    runner, api, github = execution
    enable_judge(pg_store)
    github.eval_diff.return_value = 'diff --git a/large.py b/large.py\n@@ -0,0 +1 @@\n+' + 'é' * 100_000 + '\n'
    run = create(pg_store)
    step(pg_store, runner)
    finish_slice(pg_store, runner, api)
    api.finish('check', check=0)
    step(pg_store, runner)
    attempt = saved(pg_store, run)
    assert len(api.requests) == 3
    assert attempt['state'] == 'done'
    assert attempt['result'] == dict(tests='pass', exit_code=0, review='pass', judge=None, judge_error='inputs too large')
    assert Path(attempt['output_ref']).read_text() == github.eval_diff.return_value


def test_judge_recovery_replays_verdict_and_preserves_prompt(pg_store, execution, tmp_path, monkeypatch):
    runner, api, github = execution
    run = start_judge(pg_store, runner, api)
    request = copy.deepcopy(list(api.requests.values())[-1])
    digest = eval_judge.prompt()[1]
    root = tmp_path / 'new-skills'
    root.mkdir()
    (root / 'judge.md').write_text((skills.ROOT / 'judge.md').read_text() + '\nChanged prompt\n')
    monkeypatch.setattr(skills, 'ROOT', root)
    api.finish('review', block(dict(verdict='mergeable', reason='Good')))
    # Save the filesystem completion, then roll back all database changes.
    with pytest.raises(RuntimeError), pg_store.mutation():
        runner.collect(pg_store)
        raise RuntimeError('synthetic rollback')
    assert saved(pg_store, run)['state'] == 'running'
    runner.parent.jobs = {}
    step(pg_store, Context(runner.parent))
    attempt = saved(pg_store, run)
    assert attempt['state'] == 'done' and attempt['result']['judge'] == 'mergeable'
    assert attempt['verdicts'][0]['prompt_hash'] == digest
    assert list(api.requests.values())[-1] == request
    assert len(attempt['runs']) == 4


def test_lost_judge_submission_and_usage_wait(pg_store, execution):
    runner, api, github = execution
    enable_judge(pg_store)
    run = create(pg_store)
    step(pg_store, runner)
    finish_slice(pg_store, runner, api)
    api.finish('check', check=0)
    api.lost = True
    step(pg_store, runner)
    assert len(api.requests) == 4
    identity = list(api.requests)[-1]
    api.records[identity].update(status='waiting', status_reason='usage_limit')
    runner.parent.jobs = {}
    runner = Context(runner.parent)
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'running'
    github.delete_eval_branch.assert_not_called()
    api.finish('review', block(dict(verdict='mergeable', reason='Good')))
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'done' and len(api.requests) == 4


def diff(path, count, content='value'):
    return (f'diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1,{count} @@\n'
            + ''.join('+' + content + '\n' for _ in range(count)))


def test_hidden_test_content_never_reaches_judge(pg_store, execution):
    runner, api, github = execution
    hidden = diff('tests/hidden.py', 3, 'SECRET HIDDEN TEST')
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_eval_cases SET grade='tests_and_judge', reference_diff=%s",
                                    (diff('small.py', 2) + hidden,))
    github.eval_diff.return_value = diff('small.py', 1) + hidden
    run = create(pg_store)
    step(pg_store, runner)
    finish_slice(pg_store, runner, api)
    api.finish('check', check=0)
    step(pg_store, runner)
    judge = list(api.requests.values())[-1]
    assert len(judge['assets']) == 3
    assert 'SECRET HIDDEN TEST' not in json.dumps(api.requests)
    assert 'hidden.py' not in json.dumps(judge)
    assert judge['base_commit'] == 'a' * 40 and 'overlay' not in judge['work']


def automatic(api, monkeypatch, verdict_for=lambda body: 'mergeable'):
    submit = api.submit
    def complete(body):
        identity = submit(body)
        api.records[identity] = dict(status='done', resumable=False,
                                    final_message=dict(kind='handover', body=block(dict(
                                        verdict=verdict_for(body), reason='Synthetic assessment'))),
                                    metrics=dict(tokens=dict(fresh=10, cached=2, output=3), minutes=0.5, usd=0.01))
        return identity
    monkeypatch.setattr(api, 'submit', complete)
    monkeypatch.setattr(run_platform, 'Client', lambda: api)


def test_cli_rejudge_once_per_current_prompt(pg_store, execution, monkeypatch, tmp_path, capsys):
    runner, api, github = execution
    run = create(pg_store)
    step(pg_store, runner)
    finish_slice(pg_store, runner, api)
    api.finish('check', check=0)
    step(pg_store, runner)
    attempt_id = saved(pg_store, run)['id']
    automatic(api, monkeypatch)
    assert cli.main(['eval', 'judge', str(attempt_id)]) == 0
    assert json.loads(capsys.readouterr().out)['judge'] == 'mergeable'
    attempt = saved(pg_store, run)
    assert len(attempt['verdicts']) == 1 and len(attempt['runs']) == 4
    assert attempt['metrics']['input_tokens'] == 36
    assert cli.main(['eval', 'judge', str(attempt_id)]) == 1
    assert 'already exists' in capsys.readouterr().err and len(api.requests) == 4
    root = tmp_path / 'changed-skills'
    root.mkdir()
    (root / 'judge.md').write_text((skills.ROOT / 'judge.md').read_text() + '\nNew instructions\n')
    monkeypatch.setattr(skills, 'ROOT', root)
    assert cli.main(['eval', 'judge', str(attempt_id)]) == 0
    assert len(saved(pg_store, run)['verdicts']) == 2
    assert saved(pg_store, run)['metrics']['input_tokens'] == 48
    github.eval_diff.assert_called_once()


@pytest.mark.parametrize('kind,state_value', [('slice', 'running'), ('review', 'done'), ('ticket', 'done')])
def test_rejudge_refuses_unfinished_and_non_slice(pg_store, execution, kind, state_value):
    runner, api, github = execution
    run = create(pg_store)
    with pg_store.mutation():
        if kind != 'slice':
            pg_store.connection.execute('UPDATE cplane_eval_cases SET kind=%s, level=NULL', (kind,))
        pg_store.connection.execute('UPDATE cplane_eval_attempts SET state=%s', (state_value,))
    with pytest.raises(state.StateError):
        eval_judge.judge_attempt(pg_store, run['attempts'][0]['id'], client=api)
    assert not api.requests


def calibration_set(store, folder):
    folder.mkdir()
    reference = diff('small.py', 1) + diff('large.py', 4) + diff('tests/hidden.py', 10, 'PRIVATE TEST')
    for n in range(11):
        branch = f'case{n}'
        source = dict(kind='slice', level='standard', repository='example/calibration', pr=n+1,
                      base_commit='a'*40, branch=branch, title='Synthetic', change='Implement the task',
                      tag_kind='fix', language='python', hidden_paths=['tests/hidden.py'], grade='judge')
        (folder / f'{n}.json').write_text(json.dumps(source))
        (folder / f'{branch}.patch').write_text(reference if n < 10 else diff('tests/only.py', 2))
    evals.import_folder(store, folder)
    return evals.set_create(store, 'calibration', title='Calibration', filters={})


@pytest.mark.parametrize('passing,exit_code', [(9, 0), (8, 1)])
def test_judge_test_threshold_and_inputs(pg_store, tmp_path, monkeypatch, capsys, passing, exit_code):
    calibration_set(pg_store, tmp_path / 'calibration')
    api = Runs()
    def grade(body):
        label = body['request_id'].split('-')[-1]
        good = (len(api.requests) - 1) // 2 < passing
        return 'mergeable' if (label == 'reference') == good else 'not_mergeable'
    automatic(api, monkeypatch, grade)
    assert cli.main(['eval', 'judge-test', 'calibration:1']) == exit_code
    report = json.loads(capsys.readouterr().out)
    assert report['skipped'] == 1
    assert report['reference'] == report['removed'] == dict(passed=passing, total=10, rate=passing/10)
    assert len(api.requests) == 20
    for request in api.requests.values():
        assets = {a['name']: a['text'] for a in request['assets']}
        assert request['eval']['executor'] == eval_judge.EXECUTOR
        assert 'PRIVATE TEST' not in json.dumps(request)
        assert 'large.py' in assets['reference.patch']
        assert ('large.py' in assets['attempt.patch']) == request['request_id'].endswith('reference')
        assert 'small.py' in assets['attempt.patch']
    with pg_store.locked():
        assert pg_store.connection.execute('SELECT count(*) FROM cplane_eval_verdicts').fetchone()[0] == 0
        assert pg_store.connection.execute('SELECT count(*) FROM cplane_eval_attempt_runs').fetchone()[0] == 0


def test_removed_part_quoted_rename_binary_and_ties():
    renamed = ('diff --git "a/old name.py" "b/new name.py"\nsimilarity index 100%\n'
               'rename from old name.py\nrename to new name.py\n')
    case = dict(reference_diff=renamed + diff('z.py', 2) + diff('a.py', 2) + diff('tests/test_z.py', 20))
    patch, path = eval_judge.removed_part(case)
    assert path == 'a.py' and 'diff --git a/a.py' not in patch
    assert renamed in patch and 'tests/test_z.py' in patch
    assert eval_judge.removed_part(dict(reference_diff=renamed))[1] == 'new name.py'
    assert eval_judge.removed_part(dict(reference_diff='diff --git a/a.bin b/a.bin\nBinary files differ\n'))[0] == ''


@pytest.mark.parametrize('hidden', ['tests/test_hidden.py', 'tests'])
def test_hidden_renames_are_removed(hidden):
    patch = ('diff --git a/tests/test_hidden.py b/public.py\nsimilarity index 100%\n'
             'rename from tests/test_hidden.py\nrename to public.py\n')
    assert eval_judge.visible_diff(dict(hidden_paths=[hidden]), patch) == ''


def test_asset_limit_is_in_bytes_and_inclusive():
    case = dict(id='x', task='', reference_diff='', repository='example/public', base_commit='a'*40)
    case['task'] = 'é' * 100_000
    request, digest = eval_judge.request(case, '', request_id='x', set_id='s')
    assert len(request['assets']) == 3
    assert digest == hashlib.sha256((skills.ROOT / 'judge.md').read_bytes()).hexdigest()
    case['task'] += 'a'
    with pytest.raises(state.StateError, match='inputs too large'):
        eval_judge.request(case, '', request_id='x', set_id='s')


def test_tickets_path_is_judged_after_check(pg_store, execution):
    runner, api, github = execution
    enable_judge(pg_store)
    run = create(pg_store, 'tickets')
    step(pg_store, runner)
    api.finish('cut', block(dict(tickets=[dict(title='Work', files=['small.py'], change='Implement', check='check')],
                                 test_files=['tests/new.py'], node_steps=None)))
    step(pg_store, runner)
    api.finish('ticket', 'Done')
    step(pg_store, runner)
    api.finish('review', block(dict(verdict='pass', title='Good', body='Reviewed')))
    step(pg_store, runner)
    api.finish('check', check=0)
    step(pg_store, runner)
    assert [r['role'] for r in api.requests.values()] == ['cut', 'ticket', 'review', 'check', 'review']
    api.finish('review', block(dict(verdict='mergeable', reason='Complete')))
    step(pg_store, runner)
    assert saved(pg_store, run)['result']['judge'] == 'mergeable'
    assert len(saved(pg_store, run)['verdicts']) == 1


def test_judge_test_all_skipped_fails(pg_store, tmp_path, monkeypatch, capsys):
    calibration_set(pg_store, tmp_path / 'calibration')
    with pg_store.mutation():
        pg_store.connection.execute('UPDATE cplane_eval_cases SET reference_diff=%s', (diff('tests/only.py', 1),))
    api = Runs()
    automatic(api, monkeypatch)
    assert cli.main(['eval', 'judge-test', 'calibration']) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['skipped'] == 11 and not api.requests
    assert report['reference'] == report['removed'] == dict(passed=0, total=0, rate=0)


def test_cancel_judge_waits_for_running_turn(pg_store, execution):
    runner, api, github = execution
    run = start_judge(pg_store, runner, api)
    evals.run_cancel(pg_store, run['id'])
    api.cancel_pending = True
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'running'
    github.delete_eval_branch.assert_not_called()
    api.cancel_pending = False
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'failed'
    assert saved(pg_store, run)['result'] == dict(error='Eval run cancelled')
    assert saved(pg_store, run)['verdicts'] == []


def test_rejudge_failed_run_can_retry(pg_store, execution, monkeypatch):
    runner, api, github = execution
    run = create(pg_store)
    step(pg_store, runner)
    finish_slice(pg_store, runner, api)
    api.finish('check', check=0)
    step(pg_store, runner)
    attempt_id = saved(pg_store, run)['id']
    automatic(api, monkeypatch)
    submit = api.submit
    def fail(body):
        identity = submit(body)
        api.records[identity].update(status='failed', final_message=dict(kind='escalation', body='Judge failed'))
        return identity
    monkeypatch.setattr(api, 'submit', fail)
    answer = eval_judge.judge_attempt(pg_store, attempt_id, client=api)
    assert answer == dict(judge=None, judge_error='Judge failed')
    assert saved(pg_store, run)['metrics']['input_tokens'] == 36
    monkeypatch.setattr(api, 'submit', submit)
    assert eval_judge.judge_attempt(pg_store, attempt_id, client=api)['judge'] == 'mergeable'
    assert saved(pg_store, run)['metrics']['input_tokens'] == 48
    assert len(api.requests) == 5 and len(saved(pg_store, run)['verdicts']) == 1


def test_rejudge_recovers_lost_submission(pg_store, execution, monkeypatch):
    runner, api, github = execution
    run = create(pg_store)
    step(pg_store, runner)
    finish_slice(pg_store, runner, api)
    api.finish('check', check=0)
    step(pg_store, runner)
    attempt_id = saved(pg_store, run)['id']
    automatic(api, monkeypatch)
    api.lost = True
    with pytest.raises(run_platform.Unavailable):
        eval_judge.judge_attempt(pg_store, attempt_id, client=api)
    assert len(api.requests) == 4
    assert eval_judge.judge_attempt(pg_store, attempt_id, client=api)['judge'] == 'mergeable'
    assert saved(pg_store, run)['metrics']['input_tokens'] == 36
    assert len(api.requests) == 4 and len(saved(pg_store, run)['runs']) == 4
