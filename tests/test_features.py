"""Feature persistence against isolated Postgres 17 schemas and synthetic text."""
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
from threading import Barrier

import pytest

from cplane.cli import main
from cplane.features import STAGES, TEXT_LIMIT
from cplane.state import StateError
from cplane.stores import PostgresStore
from test_stores import pg_store


def test_seed_projects_and_id_allocation(pg_store):
    pg_store.migrate()
    with pg_store.locked():
        projects = list(pg_store.connection.execute('SELECT key, name, repository FROM cplane_projects ORDER BY key'))
    assert [(r[0], r[1]) for r in projects] == [
        ('CTL', 'control-plane'), ('FAC', 'factory'), ('LAB', 'homelab-v2'),
        ('MED', 'med-ask'), ('NEW', 'No project yet'), ('STU', 'studio')]
    assert projects[4][2] is None
    barrier = Barrier(2)

    def add():
        store = PostgresStore(pg_store._url)
        barrier.wait(timeout=5)
        return [store.feature_add('FAC', 'Synthetic feature')['id'] for _ in range(5)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(add) for _ in range(2)]
        ids = [identifier for future in futures for identifier in future.result(timeout=15)]
    assert set(ids) == {f'FAC-F{i}' for i in range(1, 11)}
    assert [r['position'] for r in pg_store.feature_list()] == list(range(10))
    assert pg_store.feature_add('LAB', 'Independent counter')['id'] == 'LAB-F1'


def test_move_aliases_and_no_reuse(pg_store):
    store = pg_store
    original = store.feature_add('FAC', 'Synthetic')['id']
    store.feature_section(original, 'Problem', 'Some Markdown', actor='planner')
    revision = store.feature_history(original)[0]['id']
    moved = store.feature_move(original, 'LAB', actor='planner')
    assert moved['id'] == 'LAB-F1'
    assert store.feature_show(original) == moved
    back = store.feature_move(original, 'FAC')
    assert back['id'] == 'FAC-F2'
    assert back['aliases'] == ['FAC-F1', 'LAB-F1']
    assert store.feature_show('LAB-F1') == back
    assert store.feature_move('LAB-F1', 'FAC') == back  # same-project move is a no-op
    assert store.feature_add('LAB', 'Next')['id'] == 'LAB-F2'
    assert store.feature_history('LAB-F1')[0]['id'] == revision
    store.feature_stage(original, 'grilling')
    store.feature_section('LAB-F1', 'Problem', 'Changed')
    store.feature_revert(original, revision, actor='reviewer')
    assert store.feature_show('LAB-F1')['sections'][0]['text'] == 'Some Markdown'
    # A linked chat retains its feature. Explicitly remove this synthetic
    # record before the fixture's SQL-only feature deletion; there is no delete CLI.
    with pytest.raises(StateError):
        with store.mutation():
            store.connection.execute('DELETE FROM cplane_features WHERE id = %s', ('FAC-F2',))
    chat = store.chats(kind='feature')[0]
    with store.mutation():
        store.connection.execute('DELETE FROM cplane_session_messages WHERE session = %s', (chat['id'],))
        store.connection.execute('DELETE FROM cplane_sessions WHERE id = %s', (chat['id'],))
        store.connection.execute('DELETE FROM cplane_features WHERE id = %s', ('FAC-F2',))
    assert store.feature_add('FAC', 'After deletion')['id'] == 'FAC-F3'
    with pytest.raises(StateError, match='not found'):
        store.feature_show(original)


def test_sections_history_and_revert(pg_store):
    store = pg_store
    identifier = store.feature_add('NEW', 'Synthetic')['id']
    store.feature_section(identifier, 'Problem', '# Original\n', actor='alice')
    store.feature_section(identifier, 'Solution', '', actor='bob')
    store.feature_section(identifier, 'Problem', '# Original\n', actor='bob')
    before = store.feature_history(identifier)
    assert len(before) == 2
    assert before[0]['actor'] == 'alice' and before[0]['time']
    store.feature_section(identifier, 'Problem', 'Changed', actor='bob')
    store.feature_revert(identifier, before[0]['id'], actor='carol')
    history = store.feature_history(identifier)
    assert len(history) == 4
    assert history[:2] == before
    assert history[-1]['text'] == '# Original\n'
    assert history[-1]['actor'] == 'carol'
    assert len(store.feature_history(identifier, 'Problem')) == 3
    assert [(s['name'], s['position']) for s in store.feature_show(identifier)['sections']] == [('Problem', 0), ('Solution', 1)]
    store.feature_revert(identifier, before[0]['id'], actor='carol')
    assert len(store.feature_history(identifier)) == 5
    other = store.feature_add('NEW', 'Other')['id']
    with pytest.raises(StateError, match='revision not found'):
        store.feature_revert(other, before[0]['id'])


def test_unknown_stage(pg_store):
    identifier = pg_store.feature_add('FAC', 'First')['id']
    with pytest.raises(StateError, match='Unknown feature stage'):
        pg_store.feature_stage(identifier, 'invented')
    with pytest.raises(StateError, match='Unknown feature stage'):
        pg_store.feature_add('FAC', 'Invalid', stage='invented')


def test_bounds_and_atomic_failure(pg_store):
    identifier = pg_store.feature_add('FAC', 'Synthetic')['id']
    pg_store.feature_section(identifier, 'Long', 'x' * TEXT_LIMIT)
    with pytest.raises(StateError, match='16000 characters'):
        pg_store.feature_section(identifier, 'Long', 'x' * (TEXT_LIMIT + 1))
    with pytest.raises(StateError, match='Actor'):
        pg_store.feature_move(identifier, 'LAB', actor='')
    assert pg_store.feature_show(identifier)['id'] == identifier
    assert pg_store.feature_add('LAB', 'Rollback kept counter')['id'] == 'LAB-F1'
    with pytest.raises(StateError, match='Project not found'):
        pg_store.feature_add('BAD', 'Unknown')
    assert len(pg_store.feature_history(identifier)) == 1


def test_cli(pg_store, capsys, monkeypatch, tmp_path):
    assert main(['--actor', 'planner', 'feature', 'add', 'FAC', 'CLI synthetic']) == 0
    assert json.loads(capsys.readouterr().out)['id'] == 'FAC-F1'
    with pg_store.locked():
        assert pg_store.connection.execute('SELECT actor FROM cplane_feature_events').fetchone()[0] == 'planner'
    path = tmp_path / 'section.md'
    path.write_text('File Markdown\n')
    assert main(['feature', 'section', 'FAC-F1', 'Problem', '--file', str(path), '--actor', 'writer']) == 0
    capsys.readouterr()
    monkeypatch.setattr('sys.stdin', StringIO('Stdin Markdown\n'))
    assert main(['feature', 'section', 'FAC-F1', 'Problem']) == 0
    capsys.readouterr()
    assert main(['feature', 'history', 'FAC-F1', '--section', 'Problem']) == 0
    revisions = json.loads(capsys.readouterr().out)
    assert revisions[0]['actor'] == 'writer'
    assert main(['feature', 'revert', 'FAC-F1', str(revisions[0]['id'])]) == 0
    capsys.readouterr()
    assert main(['feature', 'move', 'FAC-F1', 'LAB']) == 0
    capsys.readouterr()
    assert main(['feature', 'stage', 'FAC-F1', 'grilling']) == 0
    capsys.readouterr()
    assert main(['feature', 'show', 'FAC-F1', '--json']) == 0
    feature = json.loads(capsys.readouterr().out)
    assert feature['id'] == 'LAB-F1'
    assert feature['sections'][0]['text'] == 'File Markdown\n'
    assert main(['feature', 'list', '--project', 'LAB', '--stage', 'grilling', '--json']) == 0
    assert json.loads(capsys.readouterr().out) == [feature]
    assert main(['feature', 'show', 'FAC-F1']) == 0
    assert 'File Markdown' in capsys.readouterr().out
    assert main(['feature', 'list']) == 0
    assert 'LAB-F1 [grilling] CLI synthetic' in capsys.readouterr().out
    assert main(['feature', 'show', 'FAC-F999']) == 1
    assert 'Feature not found' in capsys.readouterr().err


@pytest.mark.parametrize('arguments', [
    ['add', 'FAC', 'Title'], ['list'], ['show', 'FAC-F1'], ['stage', 'FAC-F1', 'ready'],
    ['move', 'FAC-F1', 'LAB'], ['section', 'FAC-F1', 'Problem'],
    ['history', 'FAC-F1'], ['revert', 'FAC-F1', '1'],
])
def test_file_store_refused(arguments, monkeypatch, capsys):
    monkeypatch.delenv('CPLANE_DATABASE_URL', raising=False)
    assert main(['feature', *arguments]) == 1
    assert 'feature commands require Postgres' in capsys.readouterr().err


def test_title_cli_preserves_identity_aliases_and_audits(pg_store, capsys):
    from cplane.cli import main
    item = pg_store.feature_add('FAC', 'Old name')
    moved = pg_store.feature_move(item['id'], 'LAB')
    assert main(['feature', 'title', item['id'], 'New name', '--actor', 'owner']) == 0
    capsys.readouterr()
    changed = pg_store.feature_show(moved['id'])
    assert changed['title'] == 'New name'
    assert changed['id'] == moved['id'] and changed['aliases'] == moved['aliases']
    event = pg_store.feature_history(item['id'])[-1]
    assert event['actor'] == 'owner' and 'Old name' in event['event'] and 'New name' in event['event']
    for title in ('', '   ', 'x' * 121):
        assert main(['feature', 'title', item['id'], title]) == 1
        capsys.readouterr()
        assert pg_store.feature_show(item['id']) == changed
    assert pg_store.feature_title(item['id'], 'x' * 120, actor='chat:7')['title'] == 'x' * 120
    assert pg_store.feature_history(item['id'])[-1]['actor'] == 'chat:7'


@pytest.mark.parametrize('stage', ['shortlist', 'grilling', 'ready', 'next', 'parked', 'done'])
def test_close_correction_bypasses_no_other_moves(pg_store, stage, capsys):
    from cplane.cli import main
    item = pg_store.feature_add('NEW', 'Already finished', stage=stage)
    before_chats = len(pg_store.chats())
    assert main(['feature', 'close', item['id'], '--reason', 'Completed outside the pipeline', '--actor', 'owner']) == 0
    capsys.readouterr()
    result = pg_store.feature_show(item['id'])
    assert result['stage'] == 'done' and result['parked_from'] is None
    assert result['review_passed'] is None
    assert len(pg_store.chats()) == before_chats
    assert pg_store.claim_session_turn() is None
    for chat in pg_store.chats(kind='feature'):
        assert chat['archived']
    event = pg_store.feature_history(item['id'])[-1]
    assert event['actor'] == 'owner'
    assert f'stage {stage} to done: correction: Completed outside the pipeline' == event['event']


@pytest.mark.parametrize('stage', ['building', 'testing'])
def test_close_rejects_active_stages(pg_store, stage):
    item = pg_store.feature_add('NEW', 'Active', stage=stage)
    before = pg_store.feature_history(item['id'])
    with pytest.raises(StateError, match='Building or Testing'):
        pg_store.feature_close(item['id'], 'Finished')
    assert pg_store.feature_show(item['id'])['stage'] == stage
    assert pg_store.feature_history(item['id']) == before


def test_close_requires_owner_and_nonempty_reason(pg_store):
    item = pg_store.feature_add('NEW', 'Finished')
    for actor in ('runner', 'chat:7'):
        with pytest.raises(StateError, match='actor owner'):
            pg_store.feature_close(item['id'], 'Finished', actor=actor)
    for reason in ('', '  '):
        with pytest.raises(StateError, match='Reason'):
            pg_store.feature_close(item['id'], reason)
    assert pg_store.feature_show(item['id'])['stage'] == 'shortlist'
