import copy
from datetime import datetime
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from cplane.cli import main
from cplane.state import load


STATES = ('planned', 'researching', 'ready', 'issued', 'awaiting handover', 'in review', 'accepted', 'escalated')
# Explicit contract, independent of the implementation's transition table.
ALLOWED = {
    ('planned', 'researching'), ('planned', 'ready'),
    ('researching', 'planned'), ('researching', 'ready'),
    ('ready', 'planned'), ('ready', 'issued'),
    ('issued', 'in review'), ('issued', 'escalated'), ('issued', 'awaiting handover'),
    ('awaiting handover', 'in review'), ('awaiting handover', 'escalated'),
    ('awaiting handover', 'awaiting handover'), ('escalated', 'issued'),
    ('in review', 'accepted'), ('in review', 'issued'),
}
ADD = ['add', '--id', 'new/W2', '--repo', 'example/repo', '--feature', 'feature', '--title', 'Title']


def invoke(path, *args):
    return main(['--state', str(path), *args])


def notice_path(path):
    return path.with_name(path.name + '.outbox.jsonl')


def test_add_defaults_and_log(make_state):
    path = make_state([])
    assert invoke(path, *ADD) == 0
    item = load(path)['slices'][0]
    assert item == dict(id='new/W2', repo='example/repo', feature='feature', title='Title',
                       state='planned', brief=None, executor={'tool': 'codex', 'model': 'gpt-6.1-terra', 'effort': 'medium'},
                       stop_before_merge=False, depends_on=[], slot=None, paused=False,
                       session=None, pr=None, attention=None, log=item['log'])
    assert len(item['log']) == 1
    assert item['log'][0]['actor'] == 'owner'
    assert item['log'][0]['event'] == 'add'
    assert datetime.fromisoformat(item['log'][0]['at']).utcoffset() is not None
    assert not notice_path(path).exists()


def test_add_all_options(make_state):
    path = make_state()
    assert invoke(path, *ADD, '--brief', 'brief.md', '--tool', 'claude', '--model', 'opus',
                  '--stop-before-merge', '--depends-on', 'voice/W1', 'absent/W0', '--actor', 'planner') == 0
    item = load(path)['slices'][1]
    assert item['brief'] == 'brief.md'
    assert item['executor'] == {'tool': 'claude', 'model': 'opus', 'effort': 'medium'}
    assert item['stop_before_merge']
    assert item['depends_on'] == ['voice/W1', 'absent/W0']
    assert item['log'][0]['actor'] == 'planner'


@pytest.mark.parametrize('options', [[], ['--id', 'bad'], ['--depends-on', 'bad'],
                                   ['--depends-on', 'voice/W1', 'voice/W1']])
def test_add_refused_without_writes(make_state, capsys, options):
    path = make_state()
    args = ADD.copy()
    args[2] = 'voice/W1' if not options else 'new/W2'
    before = path.read_bytes()
    assert invoke(path, *args, *options) == 1
    assert path.read_bytes() == before
    assert not notice_path(path).exists()
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_concurrent_duplicate_add_is_serialized(make_state):
    path = make_state([])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: invoke(path, *ADD), range(2)))
    assert sorted(results) == [0, 1]
    assert len(load(path)['slices']) == 1
    assert len(load(path)['slices'][0]['log']) == 1


EDIT_OPTIONS = [(['--repo', 'other/repo'], 'repo', 'other/repo'),
                (['--feature', 'new'], 'feature', 'new'),
                (['--title', 'new'], 'title', 'new'),
                (['--brief', 'new.md'], 'brief', 'new.md'),
                (['--tool', 'claude'], 'executor', {'tool': 'claude', 'model': 'example-model'}),
                (['--model', 'new'], 'executor', {'tool': 'codex', 'model': 'new'}),
                (['--no-stop-before-merge'], 'stop_before_merge', False),
                (['--stop-before-merge'], 'stop_before_merge', True),
                (['--depends-on', 'absent/W0'], 'depends_on', ['absent/W0']),
                (['--depends-on'], 'depends_on', []),
                (['--id', 'new/W2'], 'id', 'new/W2')]


@pytest.mark.parametrize('options,field,value', EDIT_OPTIONS)
@pytest.mark.parametrize('status', STATES)
def test_edit_fields_and_active_restrictions(make_state, slice_data, capsys, options, field, value, status):
    slice_data['state'] = status
    slice_data['depends_on'] = ['old/W0']
    path = make_state()
    before = path.read_bytes()
    refused = status in ('issued', 'awaiting handover') and field not in ('title', 'depends_on')
    assert invoke(path, 'edit', 'voice/W1', *options, '--actor', 'planner') == (1 if refused else 0)
    if refused:
        assert path.read_bytes() == before
        assert 'only --title and --depends-on' in capsys.readouterr().err
    else:
        item = load(path)['slices'][0]
        expected = copy.deepcopy(slice_data)
        expected[field] = value
        expected['log'] = item['log']
        assert item == expected
        assert item['log'][-1]['actor'] == 'planner'
        assert item['log'][-1]['event'] == 'edit'


@pytest.mark.parametrize('source', STATES)
@pytest.mark.parametrize('target', STATES)
def test_transition_matrix(make_state, slice_data, capsys, source, target):
    slice_data['state'] = source
    slice_data['slot'] = '2026-10-19T03:00:00+02:00'
    path = make_state()
    before = path.read_bytes()
    args = ['state', 'voice/W1', target, '--actor', 'planner']
    if (source, target) == ('ready', 'issued'):
        args += ['--session', 'claude:external-id:/tmp/folder:with-colon']
    assert invoke(path, *args) == (0 if (source, target) in ALLOWED else 1)
    if (source, target) not in ALLOWED:
        assert path.read_bytes() == before
        assert 'transition is not allowed' in capsys.readouterr().err
    else:
        item = load(path)['slices'][0]
        assert item['state'] == target
        assert item['log'][-1] == dict(at=item['log'][-1]['at'], actor='planner', event=f'state: {target}')
        assert item['slot'] == (None if target == 'planned' else slice_data['slot'])
        if (source, target) == ('ready', 'issued'):
            assert item['session'] == dict(tool='claude', id='external-id', folder='/tmp/folder:with-colon')
        else:
            assert item['session'] is None
    assert not notice_path(path).exists()


@pytest.mark.parametrize('source', STATES)
def test_forced_reset(make_state, slice_data, source):
    slice_data['state'] = source
    slice_data['slot'] = '2026-10-19T03:00:00+02:00'
    path = make_state()
    assert invoke(path, 'state', 'voice/W1', 'planned', '--force', '--reason', 'Replan this slice', '--actor', 'planner') == 0
    item = load(path)['slices'][0]
    assert item['state'] == 'planned'
    assert item['slot'] is None
    assert item['log'][-1]['event'] == 'state: planned (forced: Replan this slice)'
    assert item['log'][-1]['actor'] == 'planner'


@pytest.mark.parametrize('source', ['planned', 'researching'])
def test_ready_needs_brief(make_state, slice_data, capsys, source):
    slice_data.update(state=source, brief=None)
    path = make_state()
    before = path.read_bytes()
    assert invoke(path, 'state', 'voice/W1', 'ready') == 1
    assert path.read_bytes() == before
    assert 'needs a brief' in capsys.readouterr().err


@pytest.mark.parametrize('target,options', [
    ('issued', []), ('issued', ['--session', 'codex:id']),
    ('issued', ['--session', 'other:id:/tmp']), ('issued', ['--session', 'codex::/tmp']),
    ('issued', ['--session', 'codex:id:']), ('planned', ['--session', 'codex:id:/tmp']),
    ('planned', ['--force']), ('planned', ['--force', '--reason', '  ']),
    ('issued', ['--force', '--reason', 'reset']), ('planned', ['--reason', 'reset']),
    ('invented', []),
])
def test_invalid_state_options(make_state, capsys, target, options):
    path = make_state()
    before = path.read_bytes()
    assert invoke(path, 'state', 'voice/W1', target, *options) == 1
    assert path.read_bytes() == before
    assert len(capsys.readouterr().err.splitlines()) == 1


@pytest.mark.parametrize('kind', ['question', 'escalation', 'merge', 'node-step', 'owner-check'])
def test_attention_set_clear_and_notice(make_state, kind):
    path = make_state()
    assert invoke(path, 'attention', 'voice/W1', '--kind', kind, '--body', 'Please review\nnext step', '--actor', 'planner') == 0
    item = load(path)['slices'][0]
    assert item['state'] == 'ready'
    assert item['attention'] == dict(kind=kind, body='Please review\nnext step', since=item['log'][-1]['at'], answer=None, approved=False)
    assert item['log'][-1]['actor'] == 'planner'
    notice = json.loads(notice_path(path).read_text())
    assert notice == dict(at=item['log'][-1]['at'], id='voice/W1', event='attention',
                          text=f'Needs attention: voice/W1 ({kind}): Please review\nnext step')
    for _ in range(2):
        assert invoke(path, 'attention', 'voice/W1', '--clear') == 0
        assert load(path)['slices'][0]['attention'] is None
    assert len(notice_path(path).read_text().splitlines()) == 1


@pytest.mark.parametrize('options', [[], ['--kind', 'question'], ['--body', 'text'],
                                   ['--clear', '--kind', 'question'], ['--clear', '--body', 'text']])
def test_invalid_attention(make_state, capsys, options):
    path = make_state()
    before = path.read_bytes()
    assert invoke(path, 'attention', 'voice/W1', *options) == 1
    assert path.read_bytes() == before
    assert not notice_path(path).exists()
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_show_complete_read_only(make_state, capsys):
    path = make_state()
    before = path.read_bytes()
    assert invoke(path, 'show', 'voice/W1', '--json') == 0
    assert json.loads(capsys.readouterr().out) == load(path)['slices'][0]
    assert invoke(path, 'show', 'voice/W1') == 0
    output = capsys.readouterr().out
    assert 'voice/W1' in output and 'First slice' in output and 'executor:' in output
    assert path.read_bytes() == before
    assert not path.with_name(path.name + '.lock').exists()


@pytest.mark.parametrize('command,options', [('show', ['--json']), ('edit', ['--title', 'new']),
                                          ('state', ['planned']), ('attention', ['--clear'])])
def test_unknown_id(make_state, capsys, command, options):
    path = make_state()
    before = path.read_bytes()
    assert invoke(path, command, 'missing/W0', *options) == 1
    assert path.read_bytes() == before
    assert capsys.readouterr().err == 'cplane: unknown slice: missing/W0\n'


def test_edit_rename_duplicate_refused(make_state, slice_data):
    other = dict(copy.deepcopy(slice_data), id='other/W0')
    path = make_state([slice_data, other])
    before = path.read_bytes()
    assert invoke(path, 'edit', 'voice/W1', '--id', 'other/W0') == 1
    assert path.read_bytes() == before


@pytest.mark.parametrize('args', [
    ['add', '--id', 'new/W2'],
    [*ADD, '--tool', 'invalid'],
    ['edit', 'voice/W1', '--tool', 'invalid'],
    ['attention', 'voice/W1', '--kind', 'invalid', '--body', 'text'],
])
def test_invalid_cli_options(make_state, capsys, args):
    path = make_state()
    before = path.read_bytes()
    with pytest.raises(SystemExit) as error:
        invoke(path, *args)
    assert error.value.code == 2
    assert len(capsys.readouterr().err.splitlines()) == 1
    assert path.read_bytes() == before


def test_mixed_active_edit_refused_atomically(make_state, slice_data):
    slice_data['state'] = 'issued'
    path = make_state()
    before = path.read_bytes()
    assert invoke(path, 'edit', 'voice/W1', '--title', 'new', '--repo', 'other/repo') == 1
    assert path.read_bytes() == before


def test_repeated_dependency_options_and_codex_session(make_state, slice_data):
    path = make_state()
    assert invoke(path, 'edit', 'voice/W1', '--depends-on', 'first/W0', '--depends-on', 'second/W0') == 0
    assert load(path)['slices'][0]['depends_on'] == ['first/W0', 'second/W0']
    assert invoke(path, 'state', 'voice/W1', 'issued', '--session', 'codex:external:/tmp/folder') == 0
    assert load(path)['slices'][0]['session'] == dict(tool='codex', id='external', folder='/tmp/folder')


def test_ready_brief_can_be_set_through_edit(make_state, slice_data):
    slice_data.update(state='planned', brief=None)
    path = make_state()
    assert invoke(path, 'edit', 'voice/W1', '--brief', 'briefs/new.md') == 0
    assert invoke(path, 'state', 'voice/W1', 'ready') == 0
    assert load(path)['slices'][0]['state'] == 'ready'


@pytest.mark.parametrize('kind', [None, 'question', 'escalation', 'node-step', 'owner-check'])
def test_review_requires_merge_attention(make_state, slice_data, capsys, kind):
    from conftest import attention
    slice_data['attention'] = attention(kind) if kind else None
    path = make_state()
    before = path.read_bytes()
    assert invoke(path, 'review', 'voice/W1', 'Reviewed') == 1
    assert 'no merge attention to review' in capsys.readouterr().err
    assert path.read_bytes() == before
    assert not notice_path(path).exists()


def test_review_records_actor_timestamp_and_first_line_notice(make_state, slice_data):
    from conftest import attention
    slice_data['attention'] = attention('merge')
    path = make_state()
    verdict = 'Ready to merge\nChecked tests and diff'
    assert invoke(path, 'review', 'voice/W1', verdict, '--actor', 'orchestrator') == 0
    item = load(path)['slices'][0]
    at = item['log'][-1]['at']
    assert item['attention'] == dict(slice_data['attention'], review={
        'verdict': verdict, 'at': at, 'actor': 'orchestrator'})
    assert item['log'][-1] == dict(at=at, actor='orchestrator', event='review')
    assert datetime.fromisoformat(at).utcoffset() is not None
    assert json.loads(notice_path(path).read_text()) == dict(
        at=at, id='voice/W1', event='review', text='Reviewed voice/W1: Ready to merge')
    # Replacing attention must remove the review and require a fresh one.
    assert invoke(path, 'attention', 'voice/W1', '--kind', 'merge', '--body', 'New PR') == 0
    assert 'review' not in load(path)['slices'][0]['attention']


def test_flow_add_edit_and_issued_guard(make_state):
    from cplane import cli, state
    path = make_state()
    prefix = ['--state', str(path), '--actor', 'planner']
    assert cli.main(prefix + ['edit', 'voice/W1', '--flow', 'tickets']) == 0
    assert state.load(path)['slices'][0]['flow'] == 'tickets'
    assert cli.main(prefix + ['edit', 'voice/W1', '--flow', 'cli']) == 0
    assert state.load(path)['slices'][0]['flow'] == 'cli'
    assert cli.main(prefix + ['add', '--id', 'voice/W2', '--repo', 'owner/repo', '--feature', 'f',
                              '--title', 'Second', '--tool', 'codex', '--flow', 'tickets']) == 0
    assert state.load(path)['slices'][1]['flow'] == 'tickets'
    data = state.load(path)
    data['slices'][0]['state'] = 'issued'
    state.save(path, data)
    assert cli.main(prefix + ['edit', 'voice/W1', '--flow', 'tickets']) == 1
    assert state.load(path)['slices'][0]['flow'] == 'cli'


@pytest.mark.parametrize('source', STATES + ('dropped',))
@pytest.mark.parametrize('paused', [False, True])
def test_dropped_transitions(make_state, slice_data, source, paused):
    slice_data.update(state=source, paused=paused)
    path = make_state()
    before = path.read_bytes()
    allowed = source not in ('accepted', 'dropped') and (paused or source not in ('issued', 'awaiting handover'))
    assert invoke(path, 'state', 'voice/W1', 'dropped', '--actor', 'planner') == (0 if allowed else 1)
    if allowed:
        item = load(path)['slices'][0]
        assert item['state'] == 'dropped'
        assert item['log'][-1]['event'] == 'state: dropped'
        assert item['log'][-1]['actor'] == 'planner'
    else:
        assert path.read_bytes() == before


def test_hand_install_recording(make_state, slice_data, monkeypatch):
    from cplane.eligibility import satisfied
    from cplane.installation import review_status
    from cplane.digest import build
    from datetime import timedelta, timezone
    sha = 'a' * 40
    slice_data['state'] = 'awaiting handover'
    slice_data['attention'] = dict(kind='node-step', body='install', since='2026-10-15T12:00:00+02:00', answer=None, approved=False)
    path = make_state()
    monkeypatch.delenv('CPLANE_INSTALL_REPOS', raising=False)
    assert invoke(path, 'installed', 'voice/W1', sha) == 1
    slice_data['log'] = [dict(at='2026-10-15T12:00:00+02:00', actor='runner', event='merged: ' + sha)]
    path = make_state()
    assert invoke(path, 'installed', 'voice/W1', 'b' * 40) == 1
    assert invoke(path, 'installed', 'voice/W1', sha, '--actor', 'planner') == 1
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', slice_data['repo'])
    assert invoke(path, 'installed', 'voice/W1', sha) == 1
    monkeypatch.delenv('CPLANE_INSTALL_REPOS')
    assert invoke(path, 'installed', 'voice/W1', sha, '--note', 'verified', '--actor', 'chat:123') == 0
    item = load(path)['slices'][0]
    install = next(e for e in item['log'] if e['event'].startswith('Installed '))
    assert install['event'] == f'Installed {sha}. By hand: verified'
    assert install['actor'] == 'chat:123'
    assert item['attention']['answer'] is None
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', item['repo'])
    assert satisfied(item)
    monkeypatch.delenv('CPLANE_INSTALL_REPOS')
    end = datetime.fromisoformat(install['at']).astimezone(timezone.utc) + timedelta(seconds=1)
    assert 'Installed: 1 (voice/W1)' in build({'slices': [item]}, [], end)
    assert invoke(path, 'answer', 'voice/W1', 'Done') == 0
    assert review_status(load(path)['slices'][0])['status'] == 'finished'


def test_dropped_refuses_live_executor_even_when_paused(make_state, slice_data, monkeypatch, tmp_path):
    from cplane.installation import runs_path
    slice_data.update(state='issued', paused=True)
    path = make_state()
    jobdir = runs_path(path) / 'turn'
    jobdir.mkdir(parents=True)
    (jobdir / 'job.json').write_text(json.dumps(dict(id='voice/W1', phase='running',
        run=str(jobdir), tool='codex', started_ns=0)))
    before = path.read_bytes()
    assert invoke(path, 'state', 'voice/W1', 'dropped') == 1
    assert path.read_bytes() == before


def test_dropped_skips_pending_runner_and_uses_minimal_bot_export(make_state, slice_data, monkeypatch, tmp_path):
    from unittest.mock import Mock
    from cplane.cli import pending
    from cplane.runner import BOT_ACCEPTED_FIELDS, Runner, export_bot
    slice_data.update(state='dropped', attention=dict(kind='question', body='?',
                      since='2026-10-15T12:00:00+02:00', answer=None, approved=False))
    path = make_state()
    assert all(not group for group in pending(load(path)).values())
    folder = tmp_path / 'export'
    folder.mkdir()
    monkeypatch.setenv('CPLANE_BOT_EXPORT', str(folder))
    monkeypatch.setattr('cplane.fence.trusted_directory', lambda folder: None)
    export_bot(path)
    exported = json.loads((folder / 'slices.json').read_text())['slices'][0]
    assert set(exported) == set(slice_data) & BOT_ACCEPTED_FIELDS
    runner = Runner(path, git=Mock(), orders=Mock(collect=Mock(return_value=False)))
    runner.deliver = Mock()
    runner.collect = Mock()
    runner.run()
    runner.deliver.assert_not_called()
    runner.collect.assert_not_called()


def test_dropped_cannot_be_forced_back_to_planned(make_state, slice_data):
    slice_data['state'] = 'dropped'
    path = make_state()
    before = path.read_bytes()
    assert invoke(path, 'state', 'voice/W1', 'planned', '--force', '--reason', 'reset') == 1
    assert path.read_bytes() == before


def test_hand_install_without_note(make_state, slice_data, monkeypatch):
    monkeypatch.delenv('CPLANE_INSTALL_REPOS', raising=False)
    sha = 'f' * 40
    slice_data['log'] = [{'at': '2026-10-15T12:00:00+02:00', 'actor': 'runner', 'event': 'merged: ' + sha}]
    path = make_state()
    assert invoke(path, 'installed', 'voice/W1', sha) == 0
    assert any(entry['event'] == f'Installed {sha}. By hand.' for entry in load(path)['slices'][0]['log'])
