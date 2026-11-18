# ruff: noqa: F811 - shared synthetic runner fixture
"""Ticket completion, retry, review-tip and old-ledger regressions."""
import copy
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cplane import state
from cplane.cli import main
from cplane.executors import atomic_json
from cplane.roles import slice_runs
from factory_ui import create_app
from conftest import SyntheticStore
from test_run_api_runner import (  # noqa: F401
    BASE, NOW, PLAN, TIP, block, current, edit, item, pr_reply, setup,
)


def test_ticket_goals_end_with_assignment_without_changing_saved_tasks(setup):
    r, api, _ = setup
    edit(r, lambda s: s.update(flow='tickets'))
    r.run()
    api.finish(current(r), body=block(dict(PLAN, node_steps=None)))
    r.run()
    tasks = r.jobs['voice/W1']['task_file']['tasks']
    tickets = [req for req in api.requests.values() if req['role'] == 'ticket']
    for task, ticket in zip(tasks, tickets, strict=True):
        assert ticket['work']['goal'] == task['goal'] + r.ticket_assignment()
        assert ticket['work']['goal'].endswith(
            'Before you finish, review your diff against this ticket and its check, '
            'and correct anything that does not match. Do not commit or push; '
            'the platform runs the check, commits and pushes.'
        )
        assert 'Commit all of your work' not in ticket['work']['goal']
        assert 'Ticket assignment:' not in task['goal']


@pytest.mark.parametrize('flow', ['cli', 'tickets'])
@pytest.mark.parametrize('status', ['failed', 'escalated'])
def test_escalated_ready_start_retires_attempt_even_when_resumable(setup, flow, status):
    r, api, gh = setup
    edit(r, lambda s: s.update(flow=flow))
    r.run()
    old = copy.deepcopy(r.jobs['voice/W1'])
    original = current(r)
    api.finish(original, status=status, resumable=status == 'escalated')
    r.run()
    assert item(r)['state'] == 'escalated'
    preserved = {key: item(r)[key] for key in ('id', 'brief', 'flow')}
    assert main(['--state', str(r.path), '--actor', 'planner', 'state', 'voice/W1', 'ready']) == 0
    with patch('cplane.state.now', return_value=NOW):
        assert main(['--state', str(r.path), '--actor', 'planner', 'start', 'voice/W1']) == 0
    gh.default_tip.return_value = 'd' * 40
    r.run()
    fresh = r.jobs['voice/W1']
    assert fresh['attempt'] == old['attempt'] + 1
    assert fresh['branch'] == old['branch']
    assert fresh['level'] == old['level']
    assert {key: item(r)[key] for key in preserved} == preserved
    assert fresh['base'] == 'd' * 40
    assert api.requests[current(r)]['base_commit'] == 'd' * 40
    assert current(r) != original
    assert item(r)['attention'] is None
    retired = json.loads((Path(old['run']) / 'job.json').read_text())
    assert all(entry['cancelled'] for entry in retired['requests'].values())
    if status == 'escalated':
        assert original in api.cancels
    assert not api.messages


def test_restart_retries_running_old_chain_cancellation(setup):
    r, api, gh = setup
    edit(r, lambda s: s.update(flow='tickets'))
    r.run()
    cut = current(r)
    api.finish(cut, body=block(dict(PLAN, node_steps=None)))
    r.run()
    tickets = [key for key, req in api.requests.items() if req['role'] == 'ticket']
    api.finish(tickets[0], status='escalated')
    api.records[tickets[1]]['status'] = 'running'
    r.run()
    assert main(['--state', str(r.path), 'state', 'voice/W1', 'ready', '--actor', 'planner']) == 0
    r.run()
    assert r.jobs['voice/W1']['attempt'] == 1
    assert item(r)['state'] == 'ready' and item(r)['attention'] is None
    assert api.cancels.count(tickets[1]) >= 1
    api.finish(tickets[1], status='question', kind='question')
    gh.default_tip.return_value = 'd' * 40
    r.run()
    assert r.jobs['voice/W1']['attempt'] == 2
    assert api.records[tickets[1]]['status'] == 'cancelled'
    assert api.records[cut]['status'] == 'cancelled'
    assert api.requests[current(r)]['base_commit'] == 'd' * 40


@pytest.mark.parametrize('old_status', ['running', 'done', 'waiting'])
def test_new_slice_tip_supersedes_review_and_waits_for_new_verdict(setup, old_status):
    r, api, gh = setup
    r.run()
    api.finish(current(r), body=pr_reply())
    r.run()
    old_review = r.jobs['voice/W1']['requests']['review-1']['run_id']
    if old_status in ('done', 'waiting'):
        api.finish(old_review, status=old_status, body=block(dict(verdict='fix', **PLAN)))
        r.run()
        assert r.jobs['voice/W1']['review_verdict'] == 'fix'
    else:
        api.records[old_review]['status'] = 'running'
    gh.branch_tip.return_value = 'd' * 40
    gh.merge_info.return_value = {'state': 'OPEN', 'headRefOid': 'd' * 40}
    gh.checks.return_value = ('green', '')
    r.run()
    fresh = r.jobs['voice/W1']
    assert fresh['pr_review'] == 'review-2'
    assert fresh['review_tip'] == 'd' * 40
    assert fresh['requests']['review-1']['request']['base_commit'] == TIP
    assert fresh['requests']['review-2']['request']['base_commit'] == 'd' * 40
    assert fresh['review_requested_at'] == NOW.timestamp()
    assert any('review: superseded review-1 on ' + TIP in log['event'] for log in item(r)['log'])
    assert 'review_verdict' not in fresh
    assert not any(log['event'] == 'review: missing' for log in item(r)['log'])
    assert old_review in api.cancels
    gh.merge.assert_not_called()
    # A late final from the superseded run cannot become the new verdict.
    if old_status == 'running':
        api.finish(old_review, body=block(dict(verdict='fix', **PLAN)))
    r.run()
    gh.merge.assert_not_called()
    api.finish(fresh['requests']['review-2']['run_id'],
               body=block(dict(verdict='pass', title='Reviewed tip', body='Passed')))
    r.run()
    gh.merge.assert_called_once_with('example/repo', 12, expected='d' * 40)
    assert r.jobs['voice/W1']['review_verdict'] == 'pass'


@pytest.mark.parametrize('review_done', [False, True])
def test_behind_update_keeps_review_of_original_slice_tip(setup, review_done):
    r, api, gh = setup
    r.run()
    api.finish(current(r), body=pr_reply())
    r.run()
    review = r.jobs['voice/W1']['requests']['review-1']['run_id']
    if review_done:
        api.finish(review, body=block(dict(verdict='fix', **PLAN)))
    gh.merge_info.return_value = {'state': 'OPEN', 'headRefOid': TIP,
                                 'mergeStateStatus': 'BEHIND', 'mergeable': 'MERGEABLE'}
    gh.update_branch.return_value = 'd' * 40
    r.run()
    assert r.jobs['voice/W1']['tip'] == 'd' * 40
    gh.branch_tip.return_value = 'd' * 40
    gh.merge_info.return_value = {'state': 'OPEN', 'headRefOid': 'd' * 40}
    gh.checks.return_value = ('green', '')
    if not review_done:
        r.run()
        gh.merge.assert_not_called()
        api.finish(review, body=block(dict(verdict='pass', title='Review', body='Passed')))
    r.run()
    job = r.jobs['voice/W1']
    assert job['review_tip'] == TIP
    assert job['review_number'] == 1
    assert not any('superseded' in log['event'] for log in item(r)['log'])
    gh.merge.assert_called_once_with('example/repo', 12, expected='d' * 40)


@pytest.mark.parametrize('flow', ['cli', 'tickets'])
@pytest.mark.parametrize('review_status', ['failed', 'cancelled', 'running', 'question', 'escalated'])
def test_failed_or_expired_review_does_not_hold_merge(setup, flow, review_status):
    r, api, gh = setup
    edit(r, lambda s: s.update(flow=flow))
    r.run()
    api.finish(current(r), body=pr_reply() if flow == 'cli' else block(dict(PLAN, node_steps=None)))
    r.run()
    if flow == 'tickets':
        for key, req in list(api.requests.items()):
            if req['role'] == 'ticket':
                api.finish(key)
        r.run()
    job = r.jobs['voice/W1']
    review = job['requests'][job['pr_review']]['run_id']
    api.finish(review, status=review_status, kind='question' if review_status == 'question' else 'handover')
    r.run()
    r.clock = lambda: NOW + timedelta(minutes=21)
    gh.checks.return_value = ('green', '')
    r.run()
    assert r.jobs['voice/W1']['review_verdict'] == 'missing'
    gh.merge.assert_called_once()
    assert not any('repair-ticket' in key for key in api.requests)


def test_job_files_do_not_supply_slice_runs(setup, monkeypatch, capsys):
    r, api, _ = setup
    monkeypatch.setenv('CPLANE_RUNS', str(r.runs.parent))
    r.run()
    api.records[current(r)]['executor'] = {'harness': 'codex', 'model': 'synthetic'}
    api.finish(current(r), body=pr_reply())
    r.run()
    assert slice_runs(item(r)) == []
    assert main(['--state', str(r.path), 'show', 'voice/W1', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['runs'] == []
    store = SyntheticStore(r.path)
    store.slice_policy = lambda identifier: None
    assert create_app(store).test_client().get('/api/slices/voice/W1').get_json()['runs'] == []


FIXTURES = Path(__file__).parent / 'fixtures' / 'ticket_completion'


@pytest.mark.parametrize('fixture', sorted(FIXTURES.glob('*.json')), ids=lambda p: p.stem)
def test_old_job_and_slice_fixtures_survive_two_passes_unchanged(setup, fixture):
    r, api, gh = setup
    folder = r.runs / fixture.stem
    folder.mkdir(parents=True)
    data = json.loads(fixture.read_text().replace('@RUN@', str(folder)))
    job, saved_item = data['job'], data['slice']
    state.save(r.path, {'version': 1, 'slices': [saved_item]})
    atomic_json(folder / 'job.json', job)
    for entry in job.get('requests', {}).values():
        api.requests[entry['run_id']] = copy.deepcopy(entry['request'])
        api.records[entry['run_id']] = copy.deepcopy(entry['record'])
    before_state = r.path.read_bytes()
    before_job = (folder / 'job.json').read_bytes()
    for _ in range(2):
        r.run()
        assert r.path.read_bytes() == before_state
        assert (folder / 'job.json').read_bytes() == before_job
    assert not api.cancels and not api.messages and not api.calls
    gh.open.assert_not_called()
    gh.merge.assert_not_called()


def test_saved_ticket_request_keeps_its_original_goal_on_submission_retry(setup):
    r, api, _ = setup
    folder = r.runs / 'old-ticket'
    folder.mkdir(parents=True)
    data = json.loads((FIXTURES / 'platform-ticket.json').read_text().replace('@RUN@', str(folder)))
    saved_item, job = data['slice'], data['job']
    saved_item['paused'] = False
    job['phase'] = 'cut-ready'
    state.save(r.path, {'version': 1, 'slices': [saved_item]})
    atomic_json(folder / 'job.json', job)
    original = copy.deepcopy(job['requests']['ticket-1']['request'])
    for entry in job['requests'].values():
        api.requests[entry['run_id']] = copy.deepcopy(entry['request'])
        api.records[entry['run_id']] = copy.deepcopy(entry['record'])
    r.run()
    r.run()
    assert r.jobs['voice/W1']['requests']['ticket-1']['request'] == original
    assert api.requests['old-ticket-1'] == original
    assert item(r)['attention'] is None
    assert r.jobs['voice/W1']['phase'] == 'tickets'
    assert not api.calls


def test_legacy_review_ready_and_repair_round_can_finish(setup):
    r, api, gh = setup
    edit(r, lambda s: s.update(flow='tickets'))
    r.run()
    api.finish(current(r), body=block(dict(PLAN, node_steps=None)))
    r.run()
    for key, req in list(api.requests.items()):
        if req['role'] == 'ticket':
            api.finish(key)
    # Recreate the saved boundary produced by the previous runner version.
    job = r.jobs['voice/W1']
    job['phase'] = 'review-ready'
    r.save_job(job)
    r.run()
    assert r.jobs['voice/W1']['active'] == 'review-1'
    api.finish(current(r), body=block(dict(verdict='fix', **PLAN)))
    r.run()
    repairs = [key for key in api.requests if 'repair-ticket' in key]
    assert len(repairs) == 2
    # Reloading this saved repair round uses its old path too.
    for key in repairs:
        api.finish(key)
    r.run()
    assert r.jobs['voice/W1']['active'] == 'review-2'
    api.finish(current(r), body=block(dict(verdict='pass', title='Complete', body='Passed')))
    gh.checks.return_value = ('green', '')
    r.run()
    gh.merge.assert_called_once()
    assert r.jobs['voice/W1'].get('pr_review') is None
    assert len(api.requests) == 7


def test_restart_intent_does_not_retire_new_attempt_after_lost_state_save(setup, monkeypatch):
    r, api, _ = setup
    r.run()
    api.finish(current(r), status='escalated')
    r.run()
    assert main(['--state', str(r.path), 'state', 'voice/W1', 'ready', '--actor', 'planner']) == 0
    with monkeypatch.context() as m:
        m.setattr(state, 'save', Mock(side_effect=OSError('interrupted state save')))
        with pytest.raises(OSError):
            r.run()
    fresh = current(r)
    assert r.jobs['voice/W1']['attempt'] == 2
    r.run()
    assert r.jobs['voice/W1']['attempt'] == 2
    assert current(r) == fresh
    assert fresh not in api.cancels
    assert item(r)['state'] == 'issued'
