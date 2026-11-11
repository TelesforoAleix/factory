import pytest
from cplane.attention import recipient


@pytest.mark.parametrize(('kind', 'body', 'repo', 'expected'), [
    ('escalation', 'failing check: test', 'other/repo', 'planner'),
    ('escalation', 'missing brief', 'other/repo', 'planner'),
    ('node-step', 'Manual work', 'other/repo', 'planner'),
    ('merge', 'Approve', 'other/repo', 'owner'),
    ('node-step', 'Install', 'owner/repo', 'owner'),
    ('escalation', 'Install failed', 'other/repo', 'owner'),
])
def test_recipient(monkeypatch, kind, body, repo, expected):
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', 'owner/repo')
    item = {'repo': repo, 'attention': {'kind': kind, 'body': body}}
    assert recipient(item) == expected
    item['attention']['for'] = 'planner' if expected == 'owner' else 'owner'
    assert recipient(item) != expected


def test_cli_recipient_update_is_atomic_and_preserves_attention(make_state, slice_data, capsys):
    import json
    from cplane.cli import main
    from cplane import state
    item = dict(slice_data)
    item['attention'] = dict(kind='escalation', body='missing brief', since='2026-01-01T00:00:00+00:00', answer=None, approved=False)
    path = make_state([item])
    def invoke(*args):
        return main(['--state', str(path), 'attention', item['id'], *args])
    assert invoke('--for', 'owner', '--actor', 'planner') == 0
    saved = state.load(path)['slices'][0]
    assert saved['attention'] == {**item['attention'], 'for': 'owner'}
    assert saved['log'][-1]['actor'] == 'planner'
    notice = json.loads(path.with_name(path.name + '.outbox.jsonl').read_text())
    assert 'missing brief' not in str(notice)
    assert 'missing brief' not in str(saved['log'])
    before = path.read_bytes()
    assert invoke('--for', 'planner', '--body', 'new') == 1
    assert path.read_bytes() == before
    assert invoke('--for', 'planner') == 0
    assert state.load(path)['slices'][0]['attention']['for'] == 'planner'
    capsys.readouterr()


def test_cli_recipient_requires_open_attention(make_state, slice_data):
    from cplane.cli import main
    for attention in (None, dict(kind='question', body='x', since='2026-01-01T00:00:00+00:00', answer='done', approved=False),
                      dict(kind='merge', body='x', since='2026-01-01T00:00:00+00:00', answer=None, approved=True)):
        item = dict(slice_data, attention=attention)
        path = make_state([item])
        before = path.read_bytes()
        assert main(['--state', str(path), 'attention', item['id'], '--for', 'owner']) == 1
        assert path.read_bytes() == before


def test_cli_hands_planner_item_to_home(make_state, slice_data):
    from cplane import state
    from cplane.cli import main
    from factory_ui.home import home_data
    item = dict(slice_data, feature_id='F1', state='in review', attention=dict(
        kind='escalation', body='missing brief', since='2026-01-01T00:00:00+00:00', answer=None, approved=False))
    path = make_state([item])
    class Store:
        def load(self): return state.load(path)
        def chats(self, **kwargs): return []
        def notices(self): return []
        def limit_show(self): return {'waiting_limit': 2}
    board = {'features': [dict(id='F1', project='P', stage='building')], 'projects': []}
    def home(): return home_data(Store(), board, lambda x: x, None)
    assert home()['attention'] == []
    assert home()['orchestrator_count'] == 1
    assert main(['--state', str(path), 'attention', item['id'], '--for', 'owner', '--actor', 'planner']) == 0
    result = home()
    assert [card['id'] for card in result['attention']] == [item['id']]
    assert result['orchestrator_count'] == 0
