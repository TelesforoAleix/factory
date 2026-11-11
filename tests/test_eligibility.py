"""Eligibility uses synthetic slices and disposable run metadata only."""
import copy
import json

import pytest

from cplane import state
from cplane.cli import main
from cplane.eligibility import eligibility, overlaps, patterns_overlap, satisfied


def data(*items, **context):
    return dict(version=1, slices=list(items), _eligibility=context)


def event(text):
    return dict(at='2026-11-01T00:00:00Z', actor='test', event=text)


def test_dependency_requires_latest_merge_then_matching_later_install(slice_data, monkeypatch):
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', slice_data['repo'])
    dependency = dict(copy.deepcopy(slice_data), id='test/dependency', state='awaiting handover')
    item = dict(slice_data, depends_on=[dependency['id']])
    snapshot = data(item, dependency, jobs={dependency['id']: dict(phase='ended')})
    for entries in ([], ['Installed abc', 'merged: abc'], ['merged: abc'],
                    ['merged: abc', 'Installed xyz'],
                    ['merged: abc', 'Installed abc', 'merged: def']):
        dependency['log'] = [event(e) for e in entries]
        assert eligibility(item, snapshot) == dict(status='blocked', ids=[dependency['id']])
    dependency['log'] = [event('merged: def'), event('Installed def. Node steps are done. End with kind handover.')]
    assert satisfied(dependency)
    # The completed dependency can still own overlapping files pending review.
    dependency['allowed_files'] = ['other/**']
    item['allowed_files'] = ['src/**']
    assert eligibility(item, snapshot)['status'] == 'ready'
    dependency['state'] = 'accepted'
    dependency['log'] = []
    assert eligibility(item, snapshot)['status'] == 'ready'


def test_non_installable_merge_satisfies_dependency(slice_data, monkeypatch):
    monkeypatch.delenv('CPLANE_INSTALL_REPOS', raising=False)
    assert satisfied(dict(slice_data, log=[event('merged: abc')]))
    assert not satisfied(dict(slice_data, log=[event('merged: ')]))
    item = dict(slice_data, depends_on=['test/missing'])
    assert eligibility(item, data(item)) == dict(status='blocked', ids=['test/missing'])


@pytest.mark.parametrize('left,right,expected', [
    ('src/*.py', 'src/main.py', True), ('src/main.py', 'src/*.py', True),
    ('src/*.py', 'src/test_*', True), ('a*/z', 'ab/*', True),
    ('src/**', 'docs/**', False), ('a[0-3]', 'a[4-9]', False),
    ('a[!0-3]', 'a[2-5]', True), ('a?', 'a', False),
    ('[[]', '[', True), ('a**b', 'a*b', True), ('[!a]', '[a]', False),
    ('a[', 'a[', True), ('a[]x]', 'ax', True), ('', '*', True),
])
def test_glob_overlap_is_symmetric(left, right, expected):
    assert patterns_overlap(left, right) is expected
    assert patterns_overlap(right, left) is expected


@pytest.mark.parametrize('scope', [None, [], ['**']])
def test_missing_or_empty_scope_is_repository_wide(slice_data, scope):
    other = dict(slice_data, allowed_files=scope)
    assert overlaps(slice_data, other)
    assert not overlaps(slice_data, dict(other, repo='another/repo'))
    assert overlaps(dict(slice_data, allowed_files=['docs/**']), other)


@pytest.mark.parametrize('status,blocked', [
    ('issued', True), ('awaiting handover', True), ('escalated', True),
    ('planned', False), ('ready', False), ('in review', False), ('accepted', False),
])
def test_only_specified_states_hold_files(slice_data, status, blocked):
    other = dict(slice_data, id='test/other', state=status,
                 attention=dict(kind='question', body='Question', since='2026-11-01T00:00:00Z',
                                answer=None, approved=False))
    result = eligibility(slice_data, data(slice_data, other, jobs={other['id']: dict(phase='ended')}))
    assert result == (dict(status='resource busy', reason='overlapping files', ids=[other['id']])
                      if blocked else dict(status='ready'))


@pytest.mark.parametrize('kind,status,who', [
    ('question', 'waiting for a decision', 'planner'),
    ('escalation', 'waiting for a decision', 'planner'),
    ('merge', 'waiting for a test or approval', 'owner'),
    ('node-step', 'waiting for a test or approval', 'planner'),
    ('owner-check', 'waiting for a test or approval', 'planner'),
])
def test_attention_reason_and_recipient(slice_data, monkeypatch, kind, status, who):
    monkeypatch.delenv('CPLANE_INSTALL_REPOS', raising=False)
    attention = dict(kind=kind, body='Synthetic attention', since='2026-11-01T00:00:00Z',
                     answer=None, approved=False)
    item = dict(slice_data, attention=attention)
    assert eligibility(item, data(item)) == {'status': status, 'for': who}
    attention['for'] = 'owner'
    assert eligibility(item, data(item))['for'] == 'owner'
    if kind == 'merge':
        attention['approved'] = True
    else:
        attention['answer'] = 'Done'
    assert eligibility(item, data(item))['status'] == 'ready'


def test_install_attention_belongs_to_owner(slice_data, monkeypatch):
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', slice_data['repo'])
    attention = dict(kind='node-step', body='Install', answer=None, approved=False)
    item = dict(slice_data, attention=attention)
    assert eligibility(item, data(item))['for'] == 'owner'
    attention.update(kind='escalation', body='Install failed')
    assert eligibility(item, data(item))['for'] == 'owner'


def test_failed_paused_and_lifecycle_explanations(slice_data):
    item = dict(slice_data, state='escalated')
    assert eligibility(item, data(item)) == dict(status='failed')
    item = dict(slice_data, paused=True)
    assert eligibility(item, data(item)) == dict(status='waiting for a test or approval', reason='paused')
    item = dict(slice_data, state='in review')
    assert eligibility(item, data(item))['status'] == 'waiting for a test or approval'


def test_resource_limits_and_ended_attention(slice_data):
    other = dict(slice_data, id='test/other', state='issued', allowed_files=['other/**'],
                 attention=dict(kind='question', answer=None))
    item = dict(slice_data, allowed_files=['src/**'])
    job = dict(phase='running', repository=item['repo'])
    assert eligibility(item, data(item, other, jobs={other['id']: job})) == dict(
        status='resource busy', reason='repository busy', ids=[other['id']])
    assert eligibility(item, data(item, other, jobs={other['id']: job},
                                 limits=dict(executors=1, repository_runs=1)))['reason'] == 'executor limit'
    job['phase'] = 'ended'
    assert eligibility(item, data(item, other, jobs={other['id']: job})) == dict(status='ready')
    assert eligibility(item, data(item, other)) == dict(status='ready')
    assert eligibility(item, data(item, providers={item['id']: False})) == dict(
        status='resource busy', reason='provider away')
    other['attention'] = None
    assert eligibility(item, data(item, other))['reason'] == 'repository busy'


def test_allowed_files_cli_atomic_rules_and_why(make_state, capsys, monkeypatch):
    from cplane import runner
    monkeypatch.setattr(runner, 'codex_usage', lambda: 0)
    # Runner's default reader is bound at definition time; use an explicit fake.
    monkeypatch.setattr(runner.Runner, 'choose', lambda *args: ('codex', 'synthetic'))
    path = make_state()
    args = ['--state', str(path), '--actor', 'planner']
    assert main([*args, 'edit', 'voice/W1', '--allowed-files', 'src/**', '*.toml']) == 0
    item = state.load(path)['slices'][0]
    assert item['allowed_files'] == ['src/**', '*.toml']
    assert item['log'][-1]['actor'] == 'planner'
    assert 'src/**' not in item['log'][-1]['event']
    assert main([*args, 'why', item['id']]) == 0
    assert json.loads(capsys.readouterr().out) == dict(status='ready')
    before = path.read_bytes()
    assert main([*args, 'edit', item['id'], '--allowed-files', '']) == 1
    assert path.read_bytes() == before
    assert main([*args, 'state', item['id'], 'issued', '--session', 'codex:synthetic:/tmp/test']) == 0
    before = path.read_bytes()
    assert main([*args, 'edit', item['id'], '--allowed-files', 'docs/**']) == 1
    assert path.read_bytes() == before
    assert main([*args, 'why', 'test/missing']) == 1


def test_allowed_files_add(make_state):
    path = make_state([])
    assert main(['--state', str(path), 'add', '--id', 'test/new', '--repo', 'owner/repo',
                 '--feature', 'Feature', '--title', 'Scope', '--allowed-files', 'docs/**']) == 0
    assert state.load(path)['slices'][0]['allowed_files'] == ['docs/**']


def test_live_and_answered_sessions_explain_current_run(slice_data):
    item = dict(slice_data, state='issued', session=dict(tool='codex', id='synthetic', folder='/tmp/synthetic'))
    job = dict(phase='running', repository=item['repo'])
    snapshot = data(item, jobs={item['id']: job})
    assert eligibility(item, snapshot) == dict(status='resource busy', reason='repository busy', ids=[item['id']])
    job['phase'] = 'ended'
    item['attention'] = dict(kind='question', answer='Continue', approved=False)
    assert eligibility(item, snapshot) == dict(status='ready')
    item['state'] = 'escalated'
    assert eligibility(item, snapshot) == dict(status='ready')
    item.update(state='issued', attention=None)
    assert eligibility(item, snapshot)['status'] == 'waiting for a test or approval'
    job['phase'] = 'merged'
    assert eligibility(item, snapshot) == dict(status='ready')
