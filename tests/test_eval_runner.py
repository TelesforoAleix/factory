"""Real runner job methods with a fake run API and synthetic Postgres cases."""
# ruff: noqa: F811 - shared fixtures
import copy
import hashlib
from datetime import UTC, datetime
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from cplane import eval_runner, evals, run_platform, state
from cplane.eval_execution import Context
from cplane.runner import GitHub, GitHubReadError, Runner
from test_evals import cases, named  # noqa: F401
from test_stores import pg_store  # noqa: F401

NOW = datetime(2026, 11, 18, tzinfo=UTC)


def block(value):
    return '```json\n' + json.dumps(value) + '\n```'


class Runs:
    def __init__(self):
        self.requests = {}
        self.records = {}
        self.cancel_pending = False
        self.lost = False
        self.messages = []

    def submit(self, body):
        identity = body['request_id']
        if identity not in self.requests:
            self.requests[identity] = copy.deepcopy(body)
            self.records[identity] = dict(status='queued', resumable=False)
        assert self.requests[identity] == body
        if self.lost:
            self.lost = False
            raise run_platform.Unavailable('Lost response')
        return identity

    def get(self, identity):
        return copy.deepcopy(self.records[identity])

    def find(self, request_id):
        return request_id if request_id in self.records else None

    def cancel(self, identity):
        if self.cancel_pending:
            raise run_platform.NotResumable('Still running')
        self.records[identity].update(status='cancelled', resumable=False)
        return self.get(identity)

    def message(self, identity, body):
        self.messages.append((identity, body))
        self.records[identity].update(status='done')
        return self.get(identity)

    def finish(self, role, body='', *, status='done', check=None, kind='handover', index=-1):
        identity = [k for k, v in self.requests.items() if v['role'] == role][index]
        record = dict(status=status, resumable=False, final_message=dict(kind=kind, body=body),
                      metrics=dict(tokens=dict(fresh=10, cached=2, output=3), minutes=0.5, usd=0.01))
        if role == 'check':
            record['metrics'] = dict(minutes=0.5)
        if check is not None:
            record['check'] = dict(exit_code=check, tail='synthetic output')
        self.records[identity] = record
        return identity


@pytest.fixture
def execution(pg_store, cases, tmp_path):
    evals.import_folder(pg_store, cases[0])
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_eval_cases SET kind='slice', level='strong', "
                                    "grade='tests_and_judge', merge_commit=%s, hidden_paths=ARRAY['tests/hidden.py']",
                                    ('c' * 40,))
    evals.set_create(pg_store, 's', title='Synthetic set', filters={'size': 'S'})
    api, github = Runs(), Mock(spec=GitHub)
    github.branch_tip.return_value = 'b' * 40
    github.eval_diff.return_value = 'diff --git a/small.py b/small.py\n+synthetic\n'
    parent = Runner(tmp_path / 'state', runs=tmp_path / 'runs', run_client=api, github=github)
    parent.instant, parent.at = NOW, NOW.isoformat()
    parent.jobs, parent.data = {}, {'slices': []}
    return Context(parent), api, github


def create(store, path='slice', *, repeats=1):
    return evals.run_create(store, title='Pipeline', sets=['s'], configurations=[named(store, path, path)], repeats=repeats)


def step(store, runner, *, start=True):
    with store.mutation():
        runner.collect(store)
        if start:
            runner.start(store)


def saved(store, run):
    return evals.run_show(store, run['id'])['attempts'][0]


def finish_slice(store, runner, api):
    job = next(j for j in runner.jobs.values() if j.get('eval_attempt'))
    api.finish('slice', block(dict(branch=job['branch'], title='Synthetic', body='Synthetic change', node_steps='Ignored')))
    step(store, runner)
    api.finish('review', block(dict(verdict='pass', title='Reviewed', body='Good')))
    step(store, runner)


@pytest.mark.parametrize('exit_code', [0, 1])
def test_slice_pipeline_links_metrics_diff_and_deletion(pg_store, execution, exit_code):
    runner, api, github = execution
    run = create(pg_store)
    before = pg_store.snapshot()
    step(pg_store, runner)
    request, = api.requests.values()
    attempt = run['attempts'][0]['id']
    assert request['branch'] == f"eval/{run['id']}/{attempt}"
    assert request['base_commit'] == 'a' * 40 and request['level'] == 'strong'
    assert request['eval'] == dict(set=f"run{run['id']}", case='case' + hashlib.sha256(run['attempts'][0]['case'].encode()).hexdigest()[:32], executor=run['configurations'][0]['roles']['executor'])
    assert request['work']['goal'].startswith('Synthetic task')
    finish_slice(pg_store, runner, api)
    assert [r['role'] for r in api.requests.values()] == ['slice', 'review', 'check']
    review, check = list(api.requests.values())[1:]
    assert review['eval']['executor'] == run['configurations'][0]['roles']['reviewer']
    assert review['base_commit'] == check['base_commit'] == 'b' * 40
    assert review['work']['history'] == 'full'
    assert check['role'] == 'check' and check['mode'] == 'write' and 'branch' not in check
    assert 'executor' not in check['eval']
    assert check['work']['overlay'] == dict(commit='c' * 40, paths=['tests/hidden.py'])
    assert check['work']['check_command'] == 'uv run pytest tests/test_small.py'
    assert 'hidden.py' not in json.dumps(list(api.requests.values())[:2])
    assert check['after'] == []
    api.finish('check', check=exit_code)
    step(pg_store, runner)
    attempt = saved(pg_store, run)
    assert attempt['state'] == 'done'
    assert attempt['result'] == dict(tests='pass' if exit_code == 0 else 'fail', exit_code=exit_code, review='pass')
    assert attempt['metrics'] == dict(input_tokens=24, output_tokens=6, wall_seconds=90, cost_usd=0.02)
    output = Path(attempt['output_ref'])
    assert output.read_text() == github.eval_diff.return_value
    assert output.stat().st_mode & 0o777 == 0o600
    links = attempt['runs']
    assert [r['position'] for r in links] == [1, 2, 3]
    assert [r['role'] for r in links] == ['slice', 'review', 'check']
    assert [r['run_id'] for r in links] == list(api.requests)
    github.eval_diff.assert_called_once_with('example/public', 'a' * 40, 'b' * 40)
    github.delete_eval_branch.assert_called_once_with('example/public', request['branch'])
    github.open.assert_not_called()
    github.merge.assert_not_called()
    assert not runner.notices and not api.messages
    assert pg_store.snapshot() == before
    assert runner.data == {'slices': []}
    assert evals.run_show(pg_store, run['id'])['state'] == 'done'
    with pg_store.locked():
        assert pg_store.connection.execute('SELECT count(*) FROM cplane_run_records').fetchone()[0] == 0


def test_saved_check_retries_without_predecessor(pg_store, execution):
    runner, api, _ = execution
    run = create(pg_store)
    step(pg_store, runner)
    finish_slice(pg_store, runner, api)
    job = next(iter(runner.jobs.values()))
    entry = job['requests']['check']
    request_id = entry['request']['request_id']
    api.requests.pop(request_id)
    api.records.pop(request_id)
    entry['run_id'] = None
    review = next(e for e in job['requests'].values() if e['request']['role'] == 'review')
    entry['request']['after'] = [review['request']['request_id']]
    runner.parent.save_job(job)  # Simulate an intent saved by the previous version.
    runner.parent.jobs = {}
    step(pg_store, Context(runner.parent))
    check = api.requests[request_id]
    assert check['request_id'] == request_id and check['after'] == []
    assert 'branch' not in check
    assert check['work']['overlay'] == dict(commit='c' * 40, paths=['tests/hidden.py'])
    assert saved(pg_store, run)['state'] == 'running'


def test_empty_slice_fails_immediately_without_branch_read(pg_store, execution):
    runner, api, github = execution
    run = create(pg_store)
    step(pg_store, runner)
    identity = api.finish('slice', 'No changes needed')
    api.records[identity]['commits'] = []
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'failed'
    assert saved(pg_store, run)['result'] == {'error': 'No changes needed'}
    github.branch_tip.assert_not_called()
    github.eval_diff.assert_not_called()
    assert [request['role'] for request in api.requests.values()] == ['slice']


def test_tickets_pipeline_uses_ordered_runner_tickets(pg_store, execution):
    runner, api, github = execution
    run = create(pg_store, 'tickets')
    step(pg_store, runner)
    api.finish('cut', block(dict(tickets=[dict(title=f'Ticket {n}', files=[f'file{n}.py'], change=f'Implement {n}', check=f'check-{n}')
                                         for n in (1, 2)], test_files=['tests/new.py'], node_steps='Ignored')))
    step(pg_store, runner)
    requests = list(api.requests.values())
    assert [r['role'] for r in requests] == ['cut', 'ticket', 'ticket']
    assert requests[1]['after'] == [requests[0]['request_id']]
    assert requests[2]['after'] == [requests[1]['request_id']]
    assert len({r['branch'] for r in requests}) == 1
    assert requests[1]['base_commit'] == requests[2]['base_commit'] == 'b' * 40
    assert requests[1]['work']['allowed_files'] == ['file1.py']
    assert requests[2]['work']['check_command'] == 'check-2'
    assert requests[1]['work']['pinned_paths'] == ['tests/new.py']
    assert 'review your diff' in requests[1]['work']['goal']
    for r in requests:
        key = {'cut':'cutter', 'ticket':'ticket'}[r['role']]
        assert r['eval']['executor'] == run['configurations'][0]['roles'][key]
    api.finish('ticket', 'Completed', index=0)
    step(pg_store, runner)
    assert len(api.requests) == 3
    api.finish('ticket', 'Completed', index=1)
    step(pg_store, runner)
    api.finish('review', block(dict(verdict='pass', title='Good', body='Reviewed')))
    step(pg_store, runner)
    api.finish('check', check=0)
    step(pg_store, runner)
    assert [r['role'] for r in saved(pg_store, run)['runs']] == ['cut', 'ticket', 'ticket', 'review', 'check']
    assert saved(pg_store, run)['metrics']['input_tokens'] == 48
    github.open.assert_not_called()
    assert not api.messages and not runner.notices


def test_judge_grade_skips_check(pg_store, execution):
    runner, api, github = execution
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_eval_cases SET grade='judge', merge_commit=NULL, hidden_paths=NULL, check_command=NULL")
    run = create(pg_store)
    step(pg_store, runner)
    finish_slice(pg_store, runner, api)
    assert [r['role'] for r in api.requests.values()] == ['slice', 'review']
    assert saved(pg_store, run)['result'] == dict(tests=None, exit_code=None, review='pass')
    github.delete_eval_branch.assert_called_once()


@pytest.mark.parametrize('exit_code', [0, 1])
def test_ticket_component_uses_own_check(pg_store, execution, exit_code):
    runner, api, github = execution
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_eval_cases SET kind='ticket', level=NULL, start_commit=%s, "
                                    "pinned_paths=ARRAY['tests/pinned.py']", ('d' * 40,))
    run = create(pg_store, 'tickets')
    step(pg_store, runner)
    request, = api.requests.values()
    assert request['role'] == 'ticket' and request['base_commit'] == 'd' * 40
    assert request['work']['allowed_files'] == ['small.py']
    assert request['work']['pinned_paths'] == ['tests/pinned.py']
    api.finish('ticket', 'Completed', check=exit_code)
    step(pg_store, runner)
    attempt = saved(pg_store, run)
    assert attempt['state'] == 'done' and attempt['result']['tests'] == ('pass' if exit_code == 0 else 'fail')
    assert len(attempt['runs']) == 1
    github.eval_diff.assert_called_once_with('example/public', 'd' * 40, 'b' * 40)


@pytest.mark.parametrize('role,status', [('slice','question'), ('slice','escalated'), ('cut','question'), ('review','question')])
def test_questions_fail_without_slice_attention(pg_store, execution, role, status):
    runner, api, github = execution
    run = create(pg_store, 'tickets' if role == 'cut' else 'slice')
    step(pg_store, runner)
    if role == 'review':
        job = next(iter(runner.jobs.values()))
        api.finish('slice', block(dict(branch=job['branch'], title='Change', body='Work', node_steps=None)))
        step(pg_store, runner)
    api.finish(role, 'Need a decision', status=status, kind='question' if status == 'question' else 'escalation')
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'failed'
    assert saved(pg_store, run)['result'] == {'error': 'Need a decision'}
    assert len(saved(pg_store, run)['runs']) == (2 if role == 'review' else 1)
    github.delete_eval_branch.assert_called_once()
    github.open.assert_not_called()
    assert not runner.notices


def test_recovery_lost_submit_and_transaction_rollback(pg_store, execution):
    runner, api, github = execution
    run = create(pg_store)
    api.lost = True
    step(pg_store, runner)
    assert len(api.requests) == 1
    # Simulate the surrounding scheduler transaction rolling back its DB writes.
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_eval_attempts SET state='planned'")
        pg_store.connection.execute('DELETE FROM cplane_eval_attempt_runs')
    runner.parent.jobs = {}
    runner = Context(runner.parent)
    step(pg_store, runner)
    assert len(api.requests) == 1
    assert saved(pg_store, run)['state'] == 'running'
    assert len(saved(pg_store, run)['runs']) == 1
    persisted = json.loads(next(runner.runs.glob('*/job.json')).read_text())
    assert all(entry['request']['eval']['executor'] for entry in persisted['requests'].values())
    finish_slice(pg_store, runner, api)
    api.finish('check', check=0)
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'done'


def test_usage_wait_keeps_reservation_and_no_fallback(pg_store, execution):
    runner, api, _ = execution
    run = create(pg_store, repeats=2)
    step(pg_store, runner)
    record = next(iter(api.records.values()))
    record.update(status='waiting', status_reason='usage_limit', resume_at='2099-01-01')
    for _ in range(3):
        step(pg_store, runner)
    assert len(api.requests) == 1 and not api.messages
    assert saved(pg_store, run)['state'] == 'running'
    item = dict(id='real/one', repo='example/public', state='ready')
    assert runner.parent.room(item)
    finish_slice(pg_store, runner, api)
    api.finish('check', check=0)
    step(pg_store, runner)
    assert len(api.requests) == 4  # The second attempt now owns the place.


def test_real_work_reserves_room_before_eval(pg_store, execution):
    runner, api, _ = execution
    create(pg_store)
    runner.parent.data['slices'].append(dict(id='real/one', repo='example/public', state='issued', log=[]))
    step(pg_store, runner)
    assert api.requests == {}


def test_cleanup_retries_without_losing_patch(pg_store, execution):
    runner, api, github = execution
    run = create(pg_store)
    step(pg_store, runner)
    finish_slice(pg_store, runner, api)
    api.finish('check', check=0)
    github.delete_eval_branch.side_effect = GitHubReadError('Unavailable')
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'running'
    github.delete_eval_branch.side_effect = None
    runner.parent.jobs = {}
    step(pg_store, Context(runner.parent))
    assert saved(pg_store, run)['state'] == 'done'
    github.eval_diff.assert_called_once()


def test_cancel_waits_for_running_turn_before_branch_deletion(pg_store, execution):
    runner, api, github = execution
    run = create(pg_store)
    step(pg_store, runner)
    api.cancel_pending = True
    evals.run_cancel(pg_store, run['id'])
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'running'
    github.delete_eval_branch.assert_not_called()
    api.cancel_pending = False
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'failed'
    assert saved(pg_store, run)['result'] == {'error':'Eval run cancelled'}
    github.delete_eval_branch.assert_called_once()


def test_metrics_sum_internal_attempts_and_leave_unknown_absent():
    rows = [dict(metrics=dict(tokens=dict(fresh=1,cached=2,output=3),minutes=1,usd=0.5)),
            dict(metrics=dict(tokens=dict(fresh=4,cached=5,output=6),minutes=2,usd=0.75))]
    job = dict(requests={'one':dict(record=dict(attempts=rows))})
    assert eval_runner.metrics(job) == dict(input_tokens=12,output_tokens=9,wall_seconds=180,cost_usd=1.25)
    rows[1]['metrics'].pop('usd')
    assert 'cost_usd' not in eval_runner.metrics(job)


def test_app_deletes_only_attempt_branch_and_absence_is_idempotent():
    github = GitHub()
    github.call = Mock(side_effect=[json.dumps([{'ref':'refs/heads/eval/1/2'}]), '', '[]'])
    github.delete_eval_branch('example/public', 'eval/1/2')
    github.delete_eval_branch('example/public', 'eval/1/2')
    assert github.call.call_count == 3
    assert github.call.call_args_list[1].args == ('example/public','api','--method','DELETE','repos/example/public/git/refs/heads/eval/1/2')
    for branch in ('main','slice/one','eval/pr53-t1','eval/1/2/extra'):
        with pytest.raises(state.StateError):
            github.delete_eval_branch('example/public',branch)


def test_fix_review_is_recorded_then_graded_without_repairs(pg_store, execution):
    runner, api, github = execution
    run = create(pg_store)
    step(pg_store, runner)
    job = next(iter(runner.jobs.values()))
    api.finish('slice', block(dict(branch=job['branch'],title='Change',body='Work',node_steps=None)))
    step(pg_store, runner)
    api.finish('review', block(dict(verdict='fix', tickets=[dict(title='Fix', files=['small.py'],change='Fix it',check='check')],test_files=['tests/new.py'])))
    step(pg_store, runner)
    api.finish('check', check=1)
    step(pg_store, runner)
    assert [r['role'] for r in api.requests.values()] == ['slice','review','check']
    assert saved(pg_store, run)['result'] == dict(tests='fail', exit_code=1, review='fix')
    github.open.assert_not_called()


@pytest.mark.parametrize('failure', ['handover', 'setup'])
def test_incomplete_outputs_fail_without_slice_mutations(pg_store, execution, failure):
    runner, api, github = execution
    run = create(pg_store)
    before = pg_store.snapshot()
    step(pg_store, runner)
    if failure == 'handover':
        api.finish('slice', 'Done, but no PR request')
        step(pg_store, runner)
    else:
        finish_slice(pg_store, runner, api)
        api.finish('check', 'Check setup failed', status='failed')
        step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'failed'
    assert saved(pg_store, run)['result'].get('error')
    assert 'tests' not in saved(pg_store, run)['result']
    assert pg_store.snapshot() == before
    github.open.assert_not_called()
    assert not runner.notices


def test_empty_initial_intent_recovers_and_marks_first_request(pg_store, execution, monkeypatch):
    runner, api, _ = execution
    run = create(pg_store)
    with monkeypatch.context() as patch:
        patch.setattr(eval_runner, '_launch', lambda *a: None)
        step(pg_store, runner)
    assert not api.requests
    runner.parent.jobs = {}
    step(pg_store, Context(runner.parent))
    assert len(api.requests) == 1
    assert next(iter(api.requests.values()))['eval']['executor'] == run['configurations'][0]['roles']['executor']


def test_ticket_component_can_use_pi_and_records_failed_check(pg_store, execution, monkeypatch):
    runner, api, github = execution
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_eval_cases SET kind='ticket', level=NULL, start_commit=%s", ('d' * 40,))
    monkeypatch.setattr(GitHub, 'is_public', lambda self, repo: True)
    config = evals.config_add(pg_store, 'pi-ticket', path='tickets', roles={
        'cutter': {'harness':'codex','model':'synthetic','effort':'medium'},
        'ticket': {'configuration':'pi/base'}, 'reviewer': {'harness':'claude','model':'synthetic'}})
    run = evals.run_create(pg_store,title='Component',sets=['s'],configurations=[config['id']],repeats=1)
    step(pg_store, runner)
    request, = api.requests.values()
    assert request['eval']['executor'] == {'configuration':'pi/base'}
    api.finish('ticket','Check failed',status='failed',check=1)
    step(pg_store, runner)
    attempt = saved(pg_store, run)
    assert attempt['state'] == 'done' and attempt['result']['tests'] == 'fail'
    assert Path(attempt['output_ref']).read_text() == ''
    assert len(attempt['runs']) == 1
    github.delete_eval_branch.assert_called_once()


def test_diff_read_retries_before_branch_deletion(pg_store, execution):
    runner, api, github = execution
    run = create(pg_store)
    step(pg_store, runner)
    finish_slice(pg_store, runner, api)
    api.finish('check',check=0)
    github.eval_diff.side_effect = GitHubReadError('Unavailable')
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'running'
    github.delete_eval_branch.assert_not_called()
    github.eval_diff.side_effect = None
    def deleted(*args):
        assert next(runner.runs.glob('*/attempt.patch')).read_text() == github.eval_diff.return_value
    github.delete_eval_branch.side_effect = deleted
    step(pg_store, runner)
    assert saved(pg_store, run)['state'] == 'done'


def test_sealed_check_adds_time_without_harness_usage():
    metrics = dict(tokens=dict(fresh=1,cached=2,output=3),minutes=1,usd=0.5)
    job = dict(requests={
        'slice':dict(request=dict(role='slice'),record=dict(metrics=metrics)),
        'check':dict(request=dict(role='check'),record=dict(started_at='2026-11-18T12:00:00Z',ended_at='2026-11-18T12:00:10Z'))})
    assert eval_runner.metrics(job) == dict(input_tokens=3,output_tokens=3,wall_seconds=70,cost_usd=0.5)


def test_missing_job_retains_repository_reservation(pg_store, execution):
    runner, api, _ = execution
    run = create(pg_store)
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_eval_attempts SET state='running'")
        pg_store.connection.execute("UPDATE cplane_eval_runs SET state='running'")
    step(pg_store, runner)
    assert not api.requests
    assert saved(pg_store, run)['state'] == 'running'
    assert runner.parent.room(dict(id='real/one',repo='example/public',state='ready'))
