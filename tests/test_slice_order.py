"""Slice placement uses synthetic state and isolated Postgres schemas."""
import copy
import json

import pytest

from cplane.cli import main
from cplane.state import StateError
from cplane.stores import PostgresStore
from factory_ui import create_app
from test_stores import pg_store
from test_runner import setup as runner_setup
from test_pipeline import runner_board


def group(store, template, states=('ready', 'planned', 'researching')):
    feature = store.feature_add('FAC', 'Slice ordering', stage='building')['id']
    items = [dict(copy.deepcopy(template), id=f'test/{i}', feature_id=feature, state=state)
             for i, state in enumerate(states)]
    store.save(dict(version=1, slices=items))
    return feature, items


def ids(store, feature):
    return next(f['slices'] for f in store.feature_board()['features'] if f['id'] == feature)


def test_persistence_cli_api_actor(pg_store, slice_data, capsys):
    feature, items = group(pg_store, slice_data)
    assert main(['slice', 'place', 'test/2', '--before', 'test/0', '--actor', 'chat:9']) == 0
    assert json.loads(capsys.readouterr().out) == ['test/2', 'test/0', 'test/1']
    reopened = PostgresStore(pg_store._url)
    assert [s['id'] for s in ids(reopened, feature)] == ['test/2', 'test/0', 'test/1']
    # Ordinary state saves do not erase the order.
    pg_store.save(pg_store.load())
    assert ids(pg_store, feature)[0]['log'][-1]['actor'] == 'chat:9'
    client = create_app(pg_store).test_client()
    url = '/api/slices/test/1/place'
    assert client.post(url, json={'before':'test/2'}).status_code == 403
    assert client.post(url, json={'before':'test/2'}, headers={'X-Factory-UI':'1'}).status_code == 200
    assert ids(pg_store, feature)[0]['log'][-1]['actor'] == 'owner'
    with pg_store.locked():
        assert pg_store.connection.execute('SELECT actor FROM cplane_feature_events ORDER BY id DESC LIMIT 1').fetchone()[0] == 'owner'


@pytest.mark.parametrize('fixed', ['issued', 'awaiting handover', 'in review', 'accepted', 'escalated'])
def test_fixed_rows_cannot_move_or_be_crossed(pg_store, slice_data, fixed):
    feature, _ = group(pg_store, slice_data, ('ready', fixed, 'ready'))
    for identifier, anchor in [('test/1','test/0'), ('test/2','test/0'), ('test/0','test/2')]:
        before = pg_store.snapshot()
        with pytest.raises(StateError):
            pg_store.slice_place(identifier, before=anchor)
        assert pg_store.snapshot() == before
    assert [s['id'] for s in ids(pg_store, feature)] == ['test/0', 'test/1', 'test/2']


def test_dependencies_feature_boundary_and_reset(pg_store, slice_data):
    feature, items = group(pg_store, slice_data)
    items[2]['depends_on'] = ['test/0']
    pg_store.save(dict(version=1, slices=items))
    before = pg_store.snapshot()
    with pytest.raises(StateError, match='dependencies'):
        pg_store.slice_place('test/2', before='test/0')
    with pytest.raises(StateError, match='dependencies'):
        pg_store.slice_place('test/0', after='test/2')
    assert pg_store.snapshot() == before
    other = pg_store.feature_add('LAB', 'Other')['id']
    items[1]['feature_id'] = other
    items[0]['log'] = [dict(at='2026-10-16T10:00:00+00:00', actor='tester', event='state: issued')]
    pg_store.save(dict(version=1, slices=items))
    with pytest.raises(StateError, match='another feature'):
        pg_store.slice_place('test/2', before='test/1')
    with pytest.raises(StateError, match='already started'):
        pg_store.slice_place('test/0', after='test/2')


def test_runner_uses_slice_order_preserves_feature_priority_and_eligibility(pg_store, runner_setup, slice_data):
    r, processes, _ = runner_setup
    features = runner_board(pg_store, r, slice_data, [('building', {}), ('building', {})])
    data = pg_store.load()
    second = dict(copy.deepcopy(data['slices'][0]), id='synthetic/second')
    blocked = dict(copy.deepcopy(second), id='synthetic/blocked', paused=True)
    data['slices'].extend([second, blocked])
    pg_store.save(data)
    pg_store.slice_place(second['id'], before='synthetic/0')
    pg_store.slice_place(blocked['id'], before=second['id'])
    r.run()
    assert [job['id'] for job in processes.started] == [second['id'], 'synthetic/1']
    assert next(s for s in pg_store.load()['slices'] if s['id'] == blocked['id'])['state'] == 'ready'


def test_place_after_fixed_and_atomic_failure(pg_store, slice_data, monkeypatch):
    feature, _ = group(pg_store, slice_data, ('accepted', 'ready', 'ready'))
    pg_store.slice_place('test/2', after='test/0')
    assert [s['id'] for s in ids(pg_store, feature)] == ['test/0', 'test/2', 'test/1']
    before = pg_store.snapshot()
    with monkeypatch.context() as patch:
        def fail(*args):
            raise StateError('synthetic save failure')
        patch.setattr(pg_store, 'save', fail)
        with pytest.raises(StateError, match='synthetic save failure'):
            pg_store.slice_place('test/1', after='test/0')
    assert pg_store.snapshot() == before
    assert [s['id'] for s in ids(pg_store, feature)] == ['test/0', 'test/2', 'test/1']
    client = create_app(pg_store).test_client()
    result = client.post('/api/slices/test/1/place', json={'before':'test/0'}, headers={'X-Factory-UI':'1'})
    assert result.status_code == 400 and 'stay in place' in result.json['error']
    assert pg_store.snapshot() == before


@pytest.mark.parametrize('fields,expected', [
    ({'paused':True}, True),
    ({'session':{'tool':'codex','id':'synthetic','folder':'/tmp/synthetic'}}, False),
    ({'log':[dict(at='2026-10-16T10:00:00+00:00', actor='tester', event='started')]}, False),
    ({'log':[dict(at='2026-10-16T10:00:00+00:00', actor='tester', event='place test/issued before test/0')]}, True),
])
def test_movable_uses_issuance_evidence(slice_data, fields, expected):
    from cplane.features import slice_movable
    assert slice_movable(dict(slice_data, **fields)) is expected


def test_allowed_files_database_projection_and_board_eligibility(pg_store, slice_data, monkeypatch):
    from cplane.runner import Runner
    monkeypatch.setattr(Runner, 'choose', lambda *args: ('codex', 'synthetic'))
    feature, items = group(pg_store, slice_data, ('escalated', 'ready'))
    items[0].update(allowed_files=['first/**'], attention=dict(
        kind='question', body='Decision', since='2026-11-01T00:00:00Z', answer=None, approved=False))
    items[1]['allowed_files'] = ['second/**']
    pg_store.save(dict(version=1, slices=items))
    with pg_store.locked():
        assert list(pg_store.connection.execute(
            'SELECT allowed_files FROM cplane_slices ORDER BY position')) == [(['first/**'],), (['second/**'],)]
    pg_store.save(pg_store.load())
    response = create_app(pg_store).test_client().get('/api/pipeline/' + feature)
    assert response.status_code == 200
    projected = response.get_json()['slices']
    assert projected[0]['eligibility']['status'] == 'waiting for a decision'
    assert projected[1]['eligibility'] == dict(status='ready')
    assert 'allowed_files' not in projected[0]  # File scopes need not leak to the board.
    items[1].pop('allowed_files')
    pg_store.save(dict(version=1, slices=items))
    with pg_store.locked():
        assert pg_store.connection.execute(
            "SELECT allowed_files FROM cplane_slices WHERE id = 'test/1'").fetchone()[0] is None


def test_pipeline_uses_merged_installed_dependencies(pg_store, slice_data, monkeypatch):
    feature, items = group(pg_store, slice_data, ('in review', 'ready'))
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', slice_data['repo'])
    items[0]['log'] = [dict(at='2026-11-01T00:00:00Z', actor='runner', event='merged: abc')]
    items[1].update(depends_on=[items[0]['id']], slot=None)
    pg_store.save(dict(version=1, slices=items))
    pg_store.pipeline_step('2026-11-01T00:00:01Z')
    assert pg_store.load()['slices'][1]['slot'] is None
    items = pg_store.load()['slices']
    items[0]['log'].append(dict(at='2026-11-01T00:00:02Z', actor='runner', event='Installed abc'))
    pg_store.save(dict(version=1, slices=items))
    pg_store.pipeline_step('2026-11-01T00:00:03Z')
    assert pg_store.load()['slices'][1]['slot'] == '2026-11-01T00:00:03Z'


def test_feature_add_slice_keeps_scope_without_logging_content(pg_store, monkeypatch):
    monkeypatch.setattr(type(pg_store), 'model_choice', lambda self, tool, model, effort: model)
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_projects SET repository = 'example/repo' WHERE key = 'FAC'")
    feature = pg_store.feature_add('FAC', 'Scope', stage='grilling')['id']
    item = pg_store.feature_add_slice(feature, 'Scoped work',
                                    '# Synthetic task\n\n## Fixed decisions\nKeep the contract.\n',
                                    'synthetic', 'high', allowed_files=['src/**'], actor='chat:1')
    assert item['allowed_files'] == ['src/**']
    assert pg_store.load()['slices'][0]['allowed_files'] == ['src/**']
    assert all('src/**' not in entry['event'] for entry in item['log'])
