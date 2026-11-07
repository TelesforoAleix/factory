"""Pipeline rules using synthetic features and an isolated Postgres 17 schema."""
import copy
import json

import pytest

from cplane.cli import main
from cplane.features import STAGES
from cplane.state import StateError
from test_stores import pg_store


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
    if slice_state in ('issued', 'awaiting handover') and not paused:
        with pytest.raises(StateError, match='still running unpaused'):
            pg_store.feature_stage(identifier, target, actor='chat:1')
    else:
        assert pg_store.feature_stage(identifier, target, actor='chat:1')['stage'] == target


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
    fresh = pg_store.feature_add('FAC', 'No return stage', stage='parked')['id']
    with pytest.raises(StateError, match='stage this feature left'):
        pg_store.feature_stage(fresh, 'shortlist')


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
    assert json.loads(capsys.readouterr().out) == dict(building_limit=3, waiting_limit=3)
    assert main(['limit', 'set', 'building_limit', '5']) == 0
    assert json.loads(capsys.readouterr().out)['building_limit'] == 5
    for value in (0, -1, 1.5, True, '3'):
        with pytest.raises(StateError, match='whole number'):
            pg_store.limit_set('waiting_limit', value)
    with pytest.raises(StateError, match='Unknown limit'):
        pg_store.limit_set('other', 3)
    assert pg_store.limit_show() == dict(building_limit=5, waiting_limit=3)
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
