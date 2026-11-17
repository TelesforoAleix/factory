"""The same store contract on synthetic files and an isolated CI database schema."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
from threading import Event
from unittest.mock import Mock
import uuid

import pytest

from cplane import state
from cplane.cli import change_for, main
from cplane.runner import Git, Runner
from cplane.stores import PostgresStore


def test_store_requires_database_url(synthetic_store, monkeypatch, tmp_path):
    monkeypatch.delenv('CPLANE_DATABASE_URL', raising=False)
    with pytest.raises(state.StateError, match='Postgres connection failed'):
        synthetic_store(tmp_path / 'state.json')


def test_store_selects_postgres(synthetic_store, monkeypatch, tmp_path):
    factory = Mock(return_value=object())
    monkeypatch.setenv('CPLANE_DATABASE_URL', 'postgresql://synthetic')
    monkeypatch.setattr('cplane.stores.PostgresStore', factory)
    assert synthetic_store(tmp_path / 'state.json') is factory.return_value
    factory.assert_called_once_with('postgresql://synthetic')


@pytest.fixture
def pg_store(monkeypatch, request):
    url = os.environ.get('CPLANE_TEST_DATABASE_URL') or os.environ.get('HOMELAB_TEST_DATABASE_URL')
    if not url:
        if os.environ.get('CI'):
            pytest.fail('CI must set CPLANE_TEST_DATABASE_URL')
        pytest.skip('no disposable Postgres test URL configured')
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    # Never drop shared tables: every test owns a fresh schema, even in CI.
    name = 'test_' + uuid.uuid4().hex
    try:
        connection = psycopg.connect(url, autocommit=True)
    except (psycopg.Error, ValueError):
        pytest.fail('cannot connect to disposable Postgres test database', pytrace=False)
    with connection:
        assert connection.info.server_version // 10000 == 17
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
        try:
            test_url = make_conninfo(url, options=f'-c search_path={name}')
            monkeypatch.setenv('CPLANE_DATABASE_URL', test_url)
            backend = PostgresStore(test_url)
            backend.migrate()
            request.node.user_properties.append(("postgres17", True))
            yield backend
        finally:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))


@pytest.fixture
def backend(request, make_state, monkeypatch):
    path = make_state()
    pg = request.getfixturevalue('pg_store')
    pg.import_file(path)
    path.unlink()
    return path, pg


def test_load_and_update(backend, slice_data):
    path, store = backend
    assert store.load() == {'version': 1, 'slices': [slice_data]}
    state.update(path, 'voice/W1', 'start', 'tester', change_for('start'), commit=True)
    item = state.load(path)['slices'][0]
    assert item['slot']
    assert item['log'][-1]['actor'] == 'tester'
    marker, notice = store.notices()[0]
    assert marker > 0 and notice['event'] == 'start'
    assert notice['at'] == item['log'][-1]['at']
    assert store.notices(after=marker) == []
    if isinstance(store, PostgresStore):
        assert not path.exists()
        assert not Path(str(path) + '.lock').exists()
        assert not Path(str(path) + '.outbox.jsonl').exists()


@pytest.mark.parametrize('failure', ['invalid', 'exception'])
def test_failed_change_leaves_nothing(backend, failure):
    path, store = backend
    before = store.snapshot()

    def change(item, data, at):
        item['paused'] = 'invalid' if failure == 'invalid' else True
        if failure == 'exception':
            raise ValueError('synthetic failure')
        return 'notice', None

    with pytest.raises((ValueError, state.StateError)):
        state.update(path, 'voice/W1', 'test', 'tester', change)
    assert store.snapshot() == before


def test_two_writers(backend):
    path, store = backend
    entered, attempted = Event(), Event()
    release = Event()

    def first(item, data, at):
        entered.set()
        assert release.wait(10)
        item['paused'] = True
        return 'paused', None

    def second():
        attempted.set()
        state.update(path, 'voice/W1', 'slot', 'second', change_for('slot', '2026-10-19T03:00:00+02:00'))

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(state.update, path, 'voice/W1', 'pause', 'first', first)
        assert entered.wait(10)
        b = pool.submit(second)
        assert attempted.wait(10)
        try:
            with pytest.raises(TimeoutError):
                b.result(timeout=0.1)
        finally:
            release.set()
        a.result(timeout=10)
        b.result(timeout=10)
    item = store.load()['slices'][0]
    assert item['paused'] and item['slot']
    assert [entry['actor'] for entry in item['log']] == ['first', 'second']
    assert [notice['event'] for _, notice in store.notices()] == ['pause', 'slot']


def test_runner_pass_excludes_writers(backend, tmp_path):
    path, store = backend
    entered, attempted, release = Event(), Event(), Event()

    class Orders:
        def collect(self, runner):
            entered.set()
            assert release.wait(10)
            state.update_locked(path, 'voice/W1', 'start', 'order', change_for('start'))
            return True

    runner = Runner(path, runs=tmp_path / 'runs',
                    git=Mock(), orders=Orders(), )

    def writer():
        attempted.set()
        state.update(path, 'voice/W1', 'pause', 'planner', change_for('pause'))

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(runner.run)
        assert entered.wait(10)
        b = pool.submit(writer)
        assert attempted.wait(10)
        try:
            with pytest.raises(TimeoutError):
                b.result(timeout=0.1)
        finally:
            release.set()
        a.result(timeout=10)
        b.result(timeout=10)
    item = store.load()['slices'][0]
    assert item['paused'] and item['slot']
    assert item['log'][-1]['actor'] == 'planner'


def test_migrate_twice_and_roundtrip(pg_store, make_state, slice_data, tmp_path, capsys):
    assert main(['migrate']) == main(['migrate']) == 0
    other = copy.deepcopy(slice_data)
    other.update(id='voice/W2', title='Unicode æøå')
    source = make_state([other, slice_data])
    notices = [{'at': '2026-10-19T03:00:00+02:00', 'id': 'voice/W1', 'event': 'start', 'text': 'Synthetic æ'}]
    Path(str(source) + '.outbox.jsonl').write_text(''.join(json.dumps(n) + '\n' for n in notices))
    assert main(['import', str(source)]) == 0
    target = tmp_path / 'export.json'
    assert main(['export', str(target)]) == 0
    assert json.loads(target.read_text()) == json.loads(source.read_text())
    assert [json.loads(line) for line in Path(str(target) + '.outbox.jsonl').read_text().splitlines()] == notices
    assert main(['import', str(source)]) == 1
    assert 'empty database' in capsys.readouterr().err
    assert pg_store.load() == json.loads(source.read_text())


def test_notice_failure_rolls_back_change(pg_store, make_state, monkeypatch):
    path = make_state()
    pg_store.import_file(path)
    before = pg_store.snapshot()
    original = PostgresStore.append_notices

    def fail(self, notices):
        original(self, notices)
        raise RuntimeError('after notice insert')

    monkeypatch.setattr(PostgresStore, 'append_notices', fail)
    with pytest.raises(RuntimeError):
        state.update(path, 'voice/W1', 'start', 'tester', change_for('start'))
    assert pg_store.snapshot() == before


def test_uncommitted_notice_and_change_are_invisible(pg_store, make_state):
    import psycopg
    path = make_state()
    pg_store.import_file(path)
    with state.locked(path):
        state.update_locked(path, 'voice/W1', 'start', 'tester', change_for('start'))
        with psycopg.connect(os.environ['CPLANE_DATABASE_URL']) as observer:
            assert observer.execute('SELECT document FROM cplane_slices').fetchone()[0]['slot'] is None
            assert observer.execute('SELECT count(*) FROM cplane_notices').fetchone()[0] == 0
    assert pg_store.load()['slices'][0]['slot']
    assert len(pg_store.notices()) == 1


def test_failed_order_savepoint_preserves_pass(pg_store, make_state):
    path = make_state()
    pg_store.import_file(path)
    with state.locked(path):
        def fail(item, data, at):
            item['paused'] = True
            raise ValueError('synthetic failed order')
        with pytest.raises(ValueError):
            state.update_locked(path, 'voice/W1', 'pause', 'order', fail)
        state.update_locked(path, 'voice/W1', 'start', 'order', change_for('start'))
    assert not pg_store.load()['slices'][0]['paused']
    assert len(pg_store.notices()) == 1


def test_postgres_git_does_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv('CPLANE_DATABASE_URL', 'secret-url')
    monkeypatch.setattr('cplane.runner.subprocess.run', Mock(side_effect=AssertionError('git invoked')))
    Git().pull(tmp_path / 'missing.json')
    Git().commit(tmp_path / 'missing.json')
    assert not list(tmp_path.iterdir())


def test_file_mode_does_not_need_libpq(make_state, monkeypatch):
    monkeypatch.delenv('CPLANE_DATABASE_URL', raising=False)
    assert state.load(make_state())['version'] == 1


def test_transfer_requires_database(monkeypatch, capsys):
    monkeypatch.delenv('CPLANE_DATABASE_URL', raising=False)
    assert main(['migrate']) == main(['import', 'synthetic.json']) == 1
    assert 'requires CPLANE_DATABASE_URL' in capsys.readouterr().err


def test_database_errors_never_expose_url(pg_store, monkeypatch, capsys):
    secret = 'postgresql://private-user:private-password@private-host/private-database'
    import psycopg
    def fail(*args, **kwargs):
        raise psycopg.OperationalError('connection failed: ' + secret)
    monkeypatch.setattr(psycopg, 'connect', fail)
    monkeypatch.setenv('CPLANE_DATABASE_URL', secret)
    assert main(['pending']) == 1
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == 'cplane: Postgres connection failed\n'


def test_import_invalid_source_is_atomic(pg_store, make_state):
    source = make_state()
    source.write_text('{"version": 2, "slices": []}')
    with pytest.raises(state.StateError):
        pg_store.import_file(source)
    assert pg_store.load() == {'version': 1, 'slices': []}
    assert pg_store.notices() == []
    assert not Path(str(source) + '.lock').exists()


def test_import_refuses_notices_only_database(pg_store, make_state):
    pg_store.append_notices([{'event': 'synthetic'}])
    with pytest.raises(state.StateError, match='empty database'):
        pg_store.import_file(make_state())
    assert pg_store.load() == {'version': 1, 'slices': []}
    assert len(pg_store.notices()) == 1


def test_runner_failure_rolls_back_pass(pg_store, make_state, tmp_path):
    path = make_state()
    pg_store.import_file(path)
    before = pg_store.snapshot()
    class Orders:
        def collect(self, runner):
            state.update_locked(path, 'voice/W1', 'start', 'order', change_for('start'))
            raise RuntimeError('synthetic pass failure')
    runner = Runner(path, runs=tmp_path / 'runs', orders=Orders(), git=Mock())
    with pytest.raises(RuntimeError):
        runner.run()
    assert pg_store.snapshot() == before


def test_export_path(backend, tmp_path):
    path, store = backend
    state.update(path, 'voice/W1', 'start', 'tester', change_for('start'))
    destination = tmp_path / 'export.json'
    assert main(['--state', str(path), 'export', str(destination)]) == 0
    assert json.loads(destination.read_text()) == store.load()
    assert [json.loads(line) for line in Path(str(destination) + '.outbox.jsonl').read_text().splitlines()] == [n for _, n in store.notices()]


def test_export_stdout_without_notices(backend, capsys):
    path, store = backend
    assert main(['--state', str(path), 'export']) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == store.load()
    assert captured.err == ''


@pytest.mark.parametrize('drop', [False, True])
def test_collector_uses_store(backend, tmp_path, monkeypatch, drop):
    from cplane.orders import Collector
    from test_orders import Client, order
    path, store = backend
    queued = order(store.load()['slices'][0], 'start')
    if drop:
        queued['expect']['paused'] = True
    client = Client([queued])
    monkeypatch.setenv('CPLANE_ORDERS_URL', 'http://synthetic.invalid')
    runner = Runner(path, runs=tmp_path / 'runs',
                    orders=Collector(client=client), git=Mock())
    runner.run()
    assert client.acks[0][1]['outcome'] == ('dropped' if drop else 'done')
    assert store.notices()[0][1]['event'] == ('dropped' if drop else 'start')
    if isinstance(store, PostgresStore):
        assert not path.exists()
        assert not Path(str(path) + '.lock').exists()
        assert not Path(str(path) + '.outbox.jsonl').exists()


def test_empty_url_selects_database_and_refuses_defaults(monkeypatch, capsys):
    monkeypatch.setenv('CPLANE_DATABASE_URL', '')
    assert state.postgres()
    assert main(['pending']) == 1
    assert capsys.readouterr().err == 'cplane: Postgres connection failed\n'


def test_export_stdout_refuses_notices(backend, capsys):
    path, store = backend
    state.update(path, 'voice/W1', 'start', 'tester', change_for('start'))
    before = store.snapshot()
    assert main(['--state', str(path), 'export']) == 1
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == ('cplane: export contains notices; provide PATH with '
                            'cplane export PATH to write state and its outbox\n')
    assert store.snapshot() == before


def test_runner_uses_stored_brief_and_same_run_on_answer(pg_store, tmp_path):
    from conftest import seed_model_choices
    from datetime import datetime, timezone
    from test_run_api_runner import FakeRuns, BASE, TIP
    from cplane.workshop import Workshop
    seed_model_choices(pg_store)
    store = pg_store
    with store.mutation():
        store.connection.execute("UPDATE cplane_projects SET repository = 'example/repo' WHERE key = 'FAC'")
    feature = store.feature_add('FAC', 'Synthetic', stage='grilling')['id']
    chat = store.chats(kind='feature')[0]
    brief = '---\nkeep: stored frontmatter\n---\n## Do not\r\nChange this.  \r\n'
    created = Workshop(store, chat['id'], Mock()).call('add_slice', dict(feature=feature, title='Task', brief=brief, model='example-model', effort='high'))
    store.feature_mark(feature, 'design', actor=f"chat:{chat['id']}")
    store.feature_stage(feature, 'ready', actor=f"chat:{chat['id']}")
    store.feature_stage(feature, 'next', actor=f"chat:{chat['id']}")
    api, gh = FakeRuns(), Mock()
    gh.default_tip.return_value = BASE
    gh.branch_tip.return_value = TIP
    runner = Runner(tmp_path / 'missing-briefs-clone' / 'slices.json', run_client=api, github=gh, git=Mock(),
                    clock=lambda: datetime(2026, 11, 8, tzinfo=timezone.utc), runs=tmp_path / 'runs')
    runner.run()
    assert len(api.requests) == 1
    request = next(iter(api.requests.values()))
    assert request['work']['goal'].startswith(brief)
    key = next(iter(api.records))
    assert store.load()['slices'][0]['state'] == 'issued'
    runner.run()
    assert len(api.requests) == 1
    api.finish(key, 'question', 'question', 'Which local detail?')
    runner.run()
    assert main(['answer', created['id'], 'Use the agreed value']) == 0
    runner.run()
    assert len(api.requests) == 1 and len(api.messages) == 1
    assert next(iter(api.messages.values()))['text'] == 'Use the agreed value'
    assert store.stored_brief(created['brief_id']) == brief
