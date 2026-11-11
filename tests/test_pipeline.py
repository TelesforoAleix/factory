"""Pipeline rules using synthetic features and an isolated Postgres 17 schema."""
import copy
import json

import pytest

from cplane.cli import main
from cplane.features import STAGES
from cplane.state import StateError
from test_stores import pg_store
from test_runner import setup as runner_setup, NOW


# Independent specification: every pair, including forbidden jumps and no-ops.
ALLOWED = {
    ('shortlist', 'grilling'): {'owner', 'chat:7'},
    ('grilling', 'ready'): {'chat:7'},
    ('ready', 'next'): {'owner', 'chat:7'},
    ('next', 'building'): {'runner'},
    ('building', 'testing'): {'runner'},
    ('testing', 'done'): {'owner', 'chat:7'},
    ('testing', 'building'): {'chat:7', 'runner'},
    ('next', 'ready'): {'owner', 'chat:7'},
    ('ready', 'grilling'): {'owner', 'chat:7'},
    ('grilling', 'shortlist'): {'owner', 'chat:7'},
    ('building', 'next'): {'owner', 'chat:7'},
    ('building', 'ready'): {'owner', 'chat:7'},
}


def linked(store, slice_data, identifier, **fields):
    item = copy.deepcopy(slice_data)
    item.update(feature_id=identifier, **fields)
    store.save(dict(version=1, slices=[item]))


@pytest.mark.parametrize('actor', ['owner', 'chat:7', 'runner', 'planner', 'chat:', 'chat'])
def test_move_table(pg_store, slice_data, actor):
    for source in STAGES:
        for target in STAGES:
            item = pg_store.feature_add('FAC', f'{source} to {target}', stage=source)
            identifier = item['id']
            pg_store.feature_mark(identifier, 'design')
            pg_store.feature_mark(identifier, 'review')
            linked(pg_store, slice_data, identifier)
            if source == 'parked':
                with pg_store.mutation():
                    pg_store.connection.execute("UPDATE cplane_features SET parked_from = 'testing' WHERE id = %s", (identifier,))
                allowed = target == 'testing' and actor in ('owner', 'chat:7')
            elif target == 'parked':
                allowed = actor in ('owner', 'chat:7')
            else:
                allowed = actor in ALLOWED.get((source, target), set())
            before = pg_store.feature_show(identifier)
            if allowed:
                result = pg_store.feature_stage(identifier, target, actor=actor)
                assert result['stage'] == target
                assert result['parked_from'] == (source if target == 'parked' else None)
            else:
                with pytest.raises(StateError):
                    pg_store.feature_stage(identifier, target, actor=actor)
                assert pg_store.feature_show(identifier) == before


def test_marks_and_entry_conditions(pg_store, slice_data):
    store = pg_store
    identifier = store.feature_add('FAC', 'Gates', stage='grilling')['id']
    with pytest.raises(StateError, match='No agreed design yet'):
        store.feature_stage(identifier, 'ready', actor='chat:1')
    marked = store.feature_mark(identifier, 'design', actor='chat:1')
    assert marked['design_agreed'] and marked['review_passed'] is None
    with pytest.raises(StateError, match='No linked slice yet'):
        store.feature_stage(identifier, 'ready', actor='chat:1')
    # Free text does not count as a link.
    free = copy.deepcopy(slice_data)
    free['feature'] = identifier
    store.save(dict(version=1, slices=[free]))
    with pytest.raises(StateError, match='No linked slice yet'):
        store.feature_stage(identifier, 'ready', actor='chat:1')
    linked(store, slice_data, identifier)
    store.feature_stage(identifier, 'ready', actor='chat:1')
    store.feature_stage(identifier, 'next')
    store.feature_stage(identifier, 'building', actor='runner')
    store.feature_stage(identifier, 'testing', actor='runner')
    with pytest.raises(StateError, match='Review has not passed yet'):
        store.feature_stage(identifier, 'done')
    store.feature_mark(identifier, 'review')
    store.feature_mark(identifier, 'review', clear=True)
    with pytest.raises(StateError, match='Review has not passed yet'):
        store.feature_stage(identifier, 'done')
    store.feature_mark(identifier, 'review')
    store.feature_stage(identifier, 'done')
    store.feature_stage(identifier, 'parked')
    store.feature_mark(identifier, 'review', clear=True)
    with pytest.raises(StateError, match='Review has not passed yet'):
        store.feature_stage(identifier, 'done', actor='chat:1')
    store.feature_mark(identifier, 'review')
    store.feature_stage(identifier, 'done')
    with store.locked():
        events = list(store.connection.execute('SELECT event, actor FROM cplane_feature_events WHERE event LIKE %s ORDER BY id', ('mark %',)))
    assert events[0] == ('mark design', 'chat:1')
    assert ('mark review clear', 'owner') in events


@pytest.mark.parametrize('slice_state', ['issued', 'awaiting handover', 'planned', 'accepted'])
@pytest.mark.parametrize('paused', [False, True])
@pytest.mark.parametrize('target', ['next', 'ready', 'parked'])
def test_running_gate(pg_store, slice_data, slice_state, paused, target):
    identifier = pg_store.feature_add('FAC', 'Running gate', stage='building')['id']
    pg_store.feature_mark(identifier, 'design')
    # Old IDs remain links after a project move.
    pg_store.feature_move(identifier, 'LAB')
    linked(pg_store, slice_data, identifier, state=slice_state, paused=paused)
    assert pg_store.feature_stage(identifier, target, actor='chat:1')['stage'] == target
    result = pg_store.load()['slices'][0]
    assert result['paused'] == (paused or slice_state in ('issued', 'awaiting handover'))
    if not paused and slice_state in ('issued', 'awaiting handover'):
        assert result['log'][-1]['actor'] == 'runner'
        assert result['log'][-1]['event'].startswith('pipeline pause:')


def test_parked_return_and_ready_gate(pg_store, slice_data):
    identifier = pg_store.feature_add('FAC', 'Return', stage='ready')['id']
    pg_store.feature_stage(identifier, 'parked')
    with pytest.raises(StateError, match='stage this feature left'):
        pg_store.feature_stage(identifier, 'shortlist')
    with pytest.raises(StateError, match='No agreed design yet'):
        pg_store.feature_stage(identifier, 'ready')
    pg_store.feature_mark(identifier, 'design')
    with pytest.raises(StateError, match='No linked slice yet'):
        pg_store.feature_stage(identifier, 'ready')
    linked(pg_store, slice_data, identifier)
    assert pg_store.feature_stage(identifier, 'ready')['parked_from'] is None
    fresh = pg_store.feature_add('FAC', 'No return stage', stage='parked')
    assert fresh['parked_from'] == 'shortlist'
    assert pg_store.feature_stage(fresh['id'], 'shortlist')['stage'] == 'shortlist'


def test_global_order_and_placing(pg_store):
    store = pg_store
    a = store.feature_add('FAC', 'A')['id']
    b = store.feature_add('LAB', 'B')['id']
    c = store.feature_add('FAC', 'C')['id']

    def order(expected):
        items = store.feature_list(stage='shortlist')
        assert [f['id'] for f in items] == expected
        assert [f['position'] for f in items] == list(range(len(expected)))

    order([a, b, c])
    store.feature_place(c, top=True)
    order([c, a, b])
    store.feature_place(c, bottom=True)
    order([a, b, c])
    store.feature_place(c, before=b)
    order([a, c, b])
    store.feature_place(a, after=b)
    order([c, b, a])
    moved = store.feature_move(b, 'NEW')
    assert moved['position'] == 1
    store.feature_place(b, top=True)  # alias
    order([moved['id'], c, a])
    other = store.feature_add('FAC', 'Other stage', stage='grilling')['id']
    before = store.feature_list()
    for kwargs in ({}, {'top': True, 'bottom': True}, {'before': other}, {'after': a}, {'top': True, 'actor': ''}):
        with pytest.raises(StateError):
            store.feature_place(a, **kwargs)
        assert store.feature_list() == before
    store.feature_stage(a, 'grilling')
    assert [f['id'] for f in store.feature_list(stage='grilling')] == [other, a]


def test_return_to_building_is_top(pg_store):
    a = pg_store.feature_add('FAC', 'Already building', stage='building')['id']
    b = pg_store.feature_add('LAB', 'Return from testing', stage='testing')['id']
    pg_store.feature_stage(b, 'building', actor='runner')
    assert [f['id'] for f in pg_store.feature_list(stage='building')] == [b, a]
    pg_store.feature_stage(a, 'parked')
    pg_store.feature_stage(a, 'building')
    assert [f['id'] for f in pg_store.feature_list(stage='building')] == [a, b]
    c = pg_store.feature_add('FAC', 'New build', stage='next')['id']
    pg_store.feature_stage(c, 'building', actor='runner')
    assert [f['id'] for f in pg_store.feature_list(stage='building')] == [a, b, c]


def test_limits_and_cli(pg_store, capsys):
    assert main(['limit', 'show']) == 0
    assert json.loads(capsys.readouterr().out) == dict(building_limit=3, waiting_limit=3, chat_auto_turns=5, executors=2, repository_runs=1)
    assert main(['limit', 'set', 'building_limit', '5']) == 0
    assert json.loads(capsys.readouterr().out)['building_limit'] == 5
    for value in (0, -1, 1.5, True, '3'):
        with pytest.raises(StateError, match='whole number'):
            pg_store.limit_set('waiting_limit', value)
    with pytest.raises(StateError, match='Unknown limit'):
        pg_store.limit_set('other', 3)
    assert pg_store.limit_show() == dict(building_limit=5, waiting_limit=3, chat_auto_turns=5, executors=2, repository_runs=1)
    identifier = pg_store.feature_add('FAC', 'CLI')['id']
    assert main(['feature', 'mark', identifier, 'design', '--actor', 'chat:8']) == 0
    assert json.loads(capsys.readouterr().out)['design_agreed']
    assert main(['feature', 'mark', identifier, 'design', '--clear']) == 0
    assert json.loads(capsys.readouterr().out)['design_agreed'] is None
    assert main(['feature', 'place', identifier, '--top']) == 0
    capsys.readouterr()
    assert main(['feature', 'stage', identifier, 'grilling', '--actor', 'chat:8']) == 0
    assert json.loads(capsys.readouterr().out)['stage'] == 'grilling'


def test_slice_link_commands(pg_store, slice_data, capsys):
    from conftest import seed_model_choices
    seed_model_choices(pg_store)
    identifier = pg_store.feature_add('FAC', 'Link')['id']
    moved = pg_store.feature_move(identifier, 'LAB')['id']
    args = ['--actor', 'chat:9', 'add', '--id', 'synthetic/1', '--repo', 'repo', '--feature', 'Free text', '--title', 'Slice', '--model', 'test']
    assert main([*args, '--feature-id', identifier]) == 0
    item = pg_store.load()['slices'][0]
    assert item['feature_id'] == identifier and item['feature'] == 'Free text'
    assert item['log'][-1]['actor'] == 'chat:9'
    assert main(['edit', 'synthetic/1', '--feature-id', moved]) == 0
    before = pg_store.snapshot()
    assert main(['edit', 'synthetic/1', '--feature-id', 'FAC-F999']) == 1
    assert 'Feature not found' in capsys.readouterr().err
    assert pg_store.snapshot() == before
    assert main([*args, '--id', 'synthetic/2', '--feature-id', 'missing']) == 1
    assert pg_store.snapshot() == before
    linked(pg_store, slice_data, identifier, state='issued')
    assert main(['edit', slice_data['id'], '--feature-id', moved]) == 1
    assert 'only --title and --depends-on' in capsys.readouterr().err


def test_backward_ready_has_only_the_listed_conditions(pg_store):
    for source in ('next', 'building'):
        identifier = pg_store.feature_add('FAC', source, stage=source)['id']
        assert pg_store.feature_stage(identifier, 'ready')['stage'] == 'ready'


def test_migration_preserves_old_relative_order(pg_store):
    a = pg_store.feature_add('FAC', 'First')['id']
    b = pg_store.feature_add('LAB', 'Other project')['id']
    c = pg_store.feature_add('FAC', 'Second')['id']
    with pg_store.mutation():
        pg_store.connection.execute('ALTER TABLE cplane_features DROP CONSTRAINT cplane_features_stage_position_key')
        pg_store.connection.execute('ALTER TABLE cplane_features ADD UNIQUE (project, stage, position)')
        pg_store.connection.execute('UPDATE cplane_features SET position = 0 WHERE id = %s', (b,))
        pg_store.connection.execute('ALTER TABLE cplane_features DROP COLUMN design_agreed, DROP COLUMN review_passed')
        pg_store.connection.execute('DROP TABLE cplane_settings')
        pg_store.connection.execute("DELETE FROM cplane_migrations WHERE name = '007_pipeline.sql'")
    pg_store.migrate()
    pg_store.migrate()
    items = pg_store.feature_list(stage='shortlist')
    assert [f['id'] for f in items] == [a, c, b]
    assert [f['position'] for f in items] == [0, 1, 2]
    assert all(f['design_agreed'] is None and f['review_passed'] is None for f in items)
    # The database enforces global stage uniqueness, even across projects.
    with pytest.raises(StateError, match='Postgres operation failed'):
        with pg_store.mutation():
            pg_store.connection.execute('UPDATE cplane_features SET position = 0 WHERE id = %s', (b,))
    assert [f['position'] for f in pg_store.feature_list(stage='shortlist')] == [0, 1, 2]


@pytest.mark.parametrize('arguments', [
    ['feature', 'place', 'FAC-F1', '--top'],
    ['feature', 'mark', 'FAC-F1', 'design'],
    ['limit', 'show'], ['limit', 'set', 'waiting_limit', '1'],
])
def test_new_commands_require_database(arguments, monkeypatch, capsys):
    monkeypatch.delenv('CPLANE_DATABASE_URL', raising=False)
    assert main(arguments) == 1
    assert 'require Postgres' in capsys.readouterr().err


def test_import_still_bypasses_move_gates(pg_store):
    from cplane.backlog import COLUMNS
    header = '| ' + ' | '.join(COLUMNS) + ' |\n'
    separator = '|' + '|'.join(['---'] * 9) + '|\n'
    rows = [
        ['Build', '', '', 'factory', 'now', '', '', '', ''],
        ['Ready', '', '', 'homelab-v2', 'next', '', '', 'ready', ''],
        ['Done', '', '', 'factory', 'done', '', '', '', ''],
    ]
    text = header + separator + ''.join('| ' + ' | '.join(row) + ' |\n' for row in rows)
    pg_store.feature_import_backlog(text, actor='importer')
    items = pg_store.feature_list()
    assert {f['stage'] for f in items} == {'building', 'ready', 'done'}
    assert all(f['design_agreed'] is None and f['review_passed'] is None for f in items)


def test_optional_link_file_roundtrip(make_state, slice_data, monkeypatch, tmp_path):
    from cplane.stores import FileStore
    monkeypatch.delenv('CPLANE_DATABASE_URL', raising=False)
    path = make_state()
    original = FileStore(path).load()
    assert 'feature_id' not in original['slices'][0]
    slice_data['feature_id'] = 'FAC-F1'
    path = make_state([slice_data])
    destination = tmp_path / 'export.json'
    assert main(['--state', str(path), 'export', str(destination)]) == 0
    exported = FileStore(destination).load()
    assert exported['version'] == 1
    assert exported['slices'][0]['feature_id'] == 'FAC-F1'


def test_board_reads_alias_links_and_owner_moves(pg_store, slice_data):
    from factory_ui import create_app
    item = pg_store.feature_add('FAC', 'Synthetic', stage='building')
    linked(pg_store, slice_data, item['id'], state='issued', paused=False)
    moved = pg_store.feature_move(item['id'], 'LAB')
    client = create_app(pg_store).test_client()
    board = client.get('/api/pipeline')
    assert board.status_code == 200
    feature = board.json['features'][0]
    assert feature['id'] == moved['id']
    assert feature['slice_count'] == 1 and feature['slice_counts']['issued'] == 1
    assert 'slices' not in feature and 'moves' not in feature
    detail = client.get('/api/pipeline/' + item['id']).json
    assert detail['id'] == moved['id']
    assert detail['slices'][0]['id'] == slice_data['id']
    assert 'parked' in detail['moves'] and 'ready' in detail['moves']
    assert detail['stage_since'] is not None


def runner_board(store, runner, slice_data, specs):
    """Features and slices are synthetic; executors and Git are fakes."""
    items = []
    features = []
    for index, (stage, fields) in enumerate(specs):
        feature = store.feature_add('FAC', f'Feature {index}', stage=stage)['id']
        features.append(feature)
        if fields is None:
            continue
        item = copy.deepcopy(slice_data)
        item.update(id=f'synthetic/{index}', feature_id=feature, state='ready', slot=None,
                    repo=f'repo{index}')
        item.update(fields)
        items.append(item)
        (runner.repos / item['repo']).mkdir(exist_ok=True)
    store.save(dict(version=1, slices=items))
    return features


def waiting_attention(answer=None):
    return dict(kind='question', body='Synthetic question', since=NOW.isoformat(),
                answer=answer, approved=False)


@pytest.mark.parametrize('waiting_limit,answer,expected', [(1, None, 'next'), (2, None, 'building'),
                                                          (2, 'Answered', 'next')])
def test_runner_pipeline_limits(pg_store, runner_setup, slice_data, waiting_limit, answer, expected):
    r, p, _ = runner_setup
    pg_store.limit_set('building_limit', 1)
    pg_store.limit_set('waiting_limit', waiting_limit)
    features = runner_board(pg_store, r, slice_data, [
        ('building', None),  # Imported rows consume neither limit.
        ('building', dict(state='planned', attention=waiting_attention(answer))),
        ('next', None),  # Skip an empty Next row, preserving its stage.
        ('next', {}), ('next', {})])
    r.run()
    assert pg_store.feature_show(features[2])['stage'] == 'next'
    assert pg_store.feature_show(features[3])['stage'] == expected
    assert pg_store.feature_show(features[4])['stage'] == 'next'
    assert len(p.started) == (expected == 'building')


def test_runner_pipeline_dependencies_waiting_and_order(pg_store, runner_setup, slice_data):
    r, p, _ = runner_setup
    features = runner_board(pg_store, r, slice_data, [('building', {}), ('testing', {}), ('next', {})])
    pg_store.feature_stage(features[1], 'building', actor='chat:1')
    data = pg_store.load()
    # Store order differs from feature order; the returned feature starts first.
    stopped = copy.deepcopy(data['slices'][1])
    stopped.update(id='synthetic/stopped', state='planned', attention=waiting_attention())
    data['slices'].append(stopped)
    blocked = copy.deepcopy(data['slices'][0])
    blocked.update(id='synthetic/blocked', depends_on=[stopped['id']])
    data['slices'].append(blocked)
    data['slices'][0]['depends_on'] = ['synthetic/accepted']
    accepted = copy.deepcopy(data['slices'][0])
    accepted.update(id='synthetic/accepted', state='accepted', feature_id=features[0], depends_on=[])
    data['slices'].append(accepted)
    pg_store.save(data)
    r.run()
    assert [job['id'] for job in p.started] == ['synthetic/1', 'synthetic/0']
    results = {s['id']: s for s in pg_store.load()['slices']}
    assert results['synthetic/blocked']['slot'] is None
    assert results['synthetic/2']['state'] == 'ready'
    assert 'executor limit' in results['synthetic/2']['log'][-1]['event']
    with pg_store.locked():
        assert pg_store.connection.execute(
            "SELECT count(*) FROM cplane_feature_events WHERE actor = 'runner' AND event LIKE 'start:%%'").fetchone()[0] == 3


def test_runner_pipeline_testing_and_empty_board(pg_store, runner_setup, slice_data):
    r, p, _ = runner_setup
    features = runner_board(pg_store, r, slice_data, [('building', dict(state='accepted')),
                                                        ('building', None)])
    r.run()
    assert pg_store.feature_show(features[0])['stage'] == 'testing'
    assert pg_store.feature_show(features[1])['stage'] == 'building'
    assert pg_store.load()['slices'][0]['log'][-1]['actor'] == 'runner'
    assert not p.started
    pg_store.save(dict(version=1, slices=[]))
    before = pg_store.feature_list()
    r.run()
    assert pg_store.feature_list() == before


@pytest.mark.parametrize('target', ['parked', 'next', 'ready'])
def test_runner_pipeline_pause_return(pg_store, runner_setup, slice_data, target):
    r, p, _ = runner_setup
    feature = runner_board(pg_store, r, slice_data, [('building', dict(state='issued'))])[0]
    data = pg_store.load()
    manual = copy.deepcopy(data['slices'][0])
    manual.update(id='synthetic/manual', paused=True)
    data['slices'].append(manual)
    pg_store.save(data)
    pg_store.feature_stage(feature, target, actor='owner')
    assert all(s['paused'] for s in pg_store.load()['slices'])
    if target == 'parked':
        r.run()
        assert all(s['paused'] for s in pg_store.load()['slices'])
        pg_store.feature_stage(feature, 'building')
    elif target == 'ready':
        r.run()
        assert all(s['paused'] for s in pg_store.load()['slices'])
        pg_store.feature_stage(feature, 'next')
    r.run()
    assert [s['paused'] for s in pg_store.load()['slices']] == [False, True]
    assert not p.started  # An existing issued session is not started afresh.
    assert pg_store.load()['slices'][0]['log'][-1]['event'].startswith('pipeline resume:')


def test_runner_pipeline_manual_pause_takes_ownership(pg_store, runner_setup, slice_data):
    from cplane import state
    from cplane.cli import change_for
    r, _, _ = runner_setup
    feature = runner_board(pg_store, r, slice_data, [('building', dict(state='issued'))])[0]
    pg_store.feature_stage(feature, 'parked')
    state.update(r.path, 'synthetic/0', 'pause', 'owner', change_for('pause'))
    pg_store.feature_stage(feature, 'building')
    r.run()
    assert pg_store.load()['slices'][0]['paused']


@pytest.mark.parametrize('sql_failure', [False, True])
def test_runner_pipeline_failure_isolated(pg_store, runner_setup, slice_data, monkeypatch, capsys, sql_failure):
    from cplane.features import FeatureStore
    r, p, _ = runner_setup
    feature = runner_board(pg_store, r, slice_data, [('next', {})])[0]
    data = pg_store.load()
    data['slices'][0]['slot'] = NOW.isoformat()
    pg_store.save(data)
    original = FeatureStore.pipeline_step

    def broken(store, at):
        with store.mutation():
            original(store, at)
            if sql_failure:
                store.connection.execute('SELECT synthetic_missing_function()')
            raise RuntimeError('private diagnostics\nsecond line')

    monkeypatch.setattr(FeatureStore, 'pipeline_step', broken)
    r.run()
    assert capsys.readouterr().err == 'pipeline step failed\n'
    assert pg_store.feature_show(feature)['stage'] == 'next'
    assert len(p.started) == 1  # Existing slot still executes after rollback.


def test_pipeline_deferred_slots_stop_on_park(pg_store, runner_setup, slice_data):
    r, p, _ = runner_setup
    features = runner_board(pg_store, r, slice_data, [('building', {}), ('building', {}), ('building', {})])
    r.run()
    assert len(p.started) == 2
    deferred = pg_store.load()['slices'][2]
    assert deferred['slot'] is not None and deferred['state'] == 'ready'
    pg_store.feature_stage(features[2], 'parked')
    assert pg_store.load()['slices'][2]['slot'] is None
    # Release capacity without any real executor or external repository.
    p.finish()
    r.run()
    assert len(p.started) == 2
    pg_store.feature_stage(features[2], 'building')
    r.run()
    assert len(p.started) == 3 and p.started[-1]['id'] == 'synthetic/2'


def test_pipeline_park_blocks_answer_delivery_until_return(pg_store, runner_setup, slice_data):
    from cplane import state
    from cplane.cli import change_for
    r, p, _ = runner_setup
    feature = runner_board(pg_store, r, slice_data, [('building', {})])[0]
    r.run()
    p.finish(kind='question', body='Synthetic question')
    r.run()
    pg_store.feature_stage(feature, 'parked')
    state.update(r.path, 'synthetic/0', 'answer', 'owner', change_for('answer', 'Synthetic answer'))
    r.run()
    assert len(p.started) == 1
    pg_store.feature_stage(feature, 'building')
    r.run()
    assert len(p.started) == 2
    assert p.started[-1]['resume'] == 'session-1'


def test_pipeline_keeps_repository_limit(pg_store, runner_setup, slice_data):
    r, p, _ = runner_setup
    runner_board(pg_store, r, slice_data, [('building', {}), ('building', {})])
    data = pg_store.load()
    data['slices'][1]['repo'] = data['slices'][0]['repo']
    pg_store.save(data)
    r.run()
    assert len(p.started) == 1
    assert 'repository busy' in pg_store.load()['slices'][1]['log'][-1]['event']


def test_pipeline_once_with_active_store_under_lock(pg_store, runner_setup, slice_data, monkeypatch):
    from cplane import state
    from cplane.features import FeatureStore
    r, _, _ = runner_setup
    runner_board(pg_store, r, slice_data, [('building', None)])
    calls = []
    original = FeatureStore.pipeline_step

    def checked(store, at):
        assert state.store(r.path) is store
        assert store.connection is not None
        calls.append(at)
        return original(store, at)

    monkeypatch.setattr(FeatureStore, 'pipeline_step', checked)
    r.run()
    assert calls == [NOW.isoformat()]


def test_other_parking_gates_unchanged(pg_store, slice_data):
    identifier = pg_store.feature_add('FAC', 'Still gated', stage='testing')['id']
    linked(pg_store, slice_data, identifier, state='issued')
    with pytest.raises(StateError, match='still running unpaused'):
        pg_store.feature_stage(identifier, 'parked')
    assert not pg_store.load()['slices'][0]['paused']


def test_pipeline_park_blocks_pr_progress_until_return(pg_store, runner_setup, slice_data):
    r, p, github = runner_setup
    feature = runner_board(pg_store, r, slice_data, [('building', {})])[0]
    r.run()
    p.finish(kind='waiting', body='Waiting on CI')
    # An existing PR follows the normal unfenced Codex route.
    data = pg_store.load()
    data['slices'][0]['pr'] = 12
    pg_store.save(data)
    r.run()
    pg_store.feature_stage(feature, 'parked')
    github.checks.return_value = ('green', '')
    r.run()
    assert len(p.started) == 1
    github.merge.assert_not_called()
    pg_store.feature_stage(feature, 'building')
    r.run()
    assert pg_store.load()['slices'][0]['attention']['kind'] == 'merge'
