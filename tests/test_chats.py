"""Chat records and atomic lifecycle, with synthetic Postgres 17 data only."""
from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import Mock

import pytest

from cplane.cli import main
from cplane.sessions import turn_command
from cplane.state import StateError
from cplane.stores import PostgresStore
from factory_ui import create_app
from test_stores import pg_store


def feature_chat(store, title='Feature', project='NEW'):
    feature = store.feature_add(project, title)
    store.feature_section(feature['id'], 'Problem', '# Synthetic problem')
    store.feature_stage(feature['id'], 'grilling', actor='chat:1')
    return feature['id'], store.chats(kind='feature')[-1]


def test_migration_carries_sessions_and_bootstraps_empty_database(pg_store):
    store = pg_store
    assert len(store.chats(kind='orchestrator')) == 1
    assert store.chats(kind='orchestrator')[0]['area'] == 'homelab'
    with store.mutation():
        store.connection.execute('DELETE FROM cplane_sessions')
        store.connection.execute('DROP TABLE cplane_chat_settings')
        store.connection.execute('DROP INDEX cplane_chat_latest_reply')
        store.connection.execute('ALTER TABLE cplane_sessions DROP COLUMN kind, DROP COLUMN project, '
                                 'DROP COLUMN feature, DROP COLUMN archived, DROP COLUMN last_read_at')
        store.connection.execute('ALTER TABLE cplane_session_messages DROP COLUMN automatic')
        store.connection.execute("DELETE FROM cplane_migrations WHERE name = '009_chats.sql'")
        factory = store.connection.execute(
            "INSERT INTO cplane_sessions (area,title,tool,model,cli_session_id,repositories) "
            "VALUES ('factory','Old code','claude','synthetic','saved','[\"owner/repo\"]') RETURNING id").fetchone()[0]
        lab = store.connection.execute(
            "INSERT INTO cplane_sessions (area,title,tool,model) "
            "VALUES ('homelab','Old planning','codex','synthetic') RETURNING id").fetchone()[0]
        other = store.connection.execute(
            "INSERT INTO cplane_sessions (area,title,tool,model) "
            "VALUES ('homelab','Other planning','claude','synthetic') RETURNING id").fetchone()[0]
        store.connection.execute(
            "INSERT INTO cplane_session_messages(session,role,text,status) VALUES (%s,'owner','old message','queued')", (factory,))
    store.migrate()
    store.migrate()
    chats = {c['id']: c for c in store.chats()}
    assert len(chats) == 3
    assert chats[lab]['kind'] == 'orchestrator'
    assert chats[other]['kind'] == chats[factory]['kind'] == 'legacy'
    assert chats[factory]['cli_session_id'] == 'saved'
    assert chats[factory]['repositories'] == ['owner/repo']
    assert store.session_messages('factory', factory)[0]['text'] == 'old message'
    assert store.claim_session_turn()['session']['cli_session_id'] == 'saved'
    with pytest.raises(StateError):
        with store.mutation():
            store.connection.execute(
                "INSERT INTO cplane_sessions(area,title,tool,model,kind) VALUES ('homelab','Duplicate','codex','synthetic','orchestrator')")


def test_feature_event_atomic_creation_order_and_reentry(pg_store, tmp_path):
    identifier, chat = feature_chat(pg_store)
    assert (chat['kind'], chat['project'], chat['feature'], chat['area']) == ('feature', 'NEW', identifier, 'factory')
    message = pg_store.session_messages('factory', chat['id'])[0]
    assert message['role'] == 'system' and message['automatic'] and message['status'] == 'queued'
    for text in (identifier, 'Feature', 'NEW', 'Problem', '# Synthetic problem', 'Run the grill'):
        assert text in message['text']
    pg_store.session_messages('factory', chat['id'], 'owner first')
    turn = pg_store.claim_session_turn()
    assert turn['role'] == 'owner' and turn['text'] == 'owner first'
    pg_store.finish_session_turn(turn, 'reply', 'synthetic-resume')
    turn = pg_store.claim_session_turn()
    assert turn['role'] == 'system'
    assert turn_command(turn, tmp_path, [], tmp_path)[-1] == 'Workshop event: ' + message['text']
    assert turn['session']['cli_session_id'] == 'synthetic-resume'
    pg_store.finish_session_turn(turn, 'grill reply', 'synthetic-resume')
    pg_store.feature_stage(identifier, 'shortlist')
    pg_store.feature_stage(identifier, 'grilling')
    assert len(pg_store.chats(kind='feature')) == 1
    assert len(pg_store.session_messages('factory', chat['id'])) == 4
    # Existing aliases continue to identify the same chat after a project move.
    moved = pg_store.feature_move(identifier, 'FAC')
    chat = pg_store.chats(kind='feature')[0]
    assert chat['project'] == 'FAC' and chat['feature'] == moved['id']


def test_chat_creation_failure_rolls_back_stage_and_event(pg_store, monkeypatch):
    identifier = pg_store.feature_add('NEW', 'Rollback')['id']
    before = pg_store.feature_show(identifier)
    monkeypatch.setattr(pg_store, '_create_chat', Mock(side_effect=StateError('synthetic failure')))
    with pytest.raises(StateError, match='synthetic failure'):
        pg_store.feature_stage(identifier, 'grilling')
    assert pg_store.feature_show(identifier) == before
    assert pg_store.chats(kind='feature') == []
    with pg_store.locked():
        assert pg_store.connection.execute('SELECT count(*) FROM cplane_feature_events').fetchone()[0] == 1


def test_archive_waiting_read_unread_and_reopen(pg_store):
    identifier, chat = feature_chat(pg_store)
    sid = chat['id']
    assert not chat['waiting']
    turn = pg_store.claim_session_turn()
    pg_store.finish_session_turn(turn, 'Question?', 'synthetic')
    assert pg_store.chats(kind='feature')[0]['waiting']
    assert not pg_store.chat_open(sid)['chat']['waiting']
    assert pg_store.chat_read(sid, unread=True)['waiting']
    assert not pg_store.chat_read(sid)['waiting']
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_features SET stage = 'testing', review_passed = now() WHERE id = %s", (identifier,))
    pg_store.feature_stage(identifier, 'done')
    archived = pg_store.chats(kind='feature', archived=True)[0]
    assert archived['id'] == sid
    pg_store.system_message(sid, 'An archived event')
    assert pg_store.claim_session_turn() is None
    assert len(pg_store.chat_open(sid)['messages']) == 3
    assert pg_store.chats(kind='feature')[0]['archived']
    pg_store.session_messages('factory', sid, 'Reopen')
    assert not pg_store.chats(kind='feature')[0]['archived']
    assert pg_store.claim_session_turn()['text'] == 'Reopen'


def test_project_unique_defaults_and_configuration(pg_store):
    pg_store.project_add('XYZ', 'Synthetic project', repository='owner/repo')
    pg_store.chat_defaults('project', chat_tool='claude', chat_model='synthetic-a')
    with ThreadPoolExecutor(2) as pool:
        def create(_):
            try:
                return PostgresStore(pg_store._url).create_project_chat('XYZ')['id']
            except StateError:
                return None
        ids = list(pool.map(create, range(2)))
    assert len([sid for sid in ids if sid]) == 1
    chat = pg_store.chats(kind='project')[0]
    assert chat['repositories'] == ['owner/repo']
    assert chat['tool'] == 'claude' and chat['model'] == 'synthetic-a'
    pg_store.chat_defaults('project', chat_model='synthetic-b')
    assert pg_store.chats(kind='project')[0]['model'] == 'synthetic-a'
    assert pg_store.chat_configure(chat['id'], model='synthetic-c')['model'] == 'synthetic-c'
    for kwargs in (dict(tool='shell'), dict(model='--bad'), dict(model=''), dict(model=['bad'])):
        with pytest.raises(StateError):
            pg_store.chat_configure(chat['id'], **kwargs)
    pg_store.session_messages('factory', chat['id'], 'Run')
    pg_store.claim_session_turn()
    with pytest.raises(StateError, match='running'):
        pg_store.chat_configure(chat['id'], model='synthetic-d')
    assert pg_store.chats(kind='project')[0]['model'] == 'synthetic-c'


def test_routes_guard_defaults_and_cli(pg_store, capsys, monkeypatch):
    client = create_app(pg_store).test_client()
    headers = {'X-Factory-UI': '1'}
    pg_store.project_add('XYZ', 'Synthetic', repository='owner/repo')
    assert client.post('/api/chats/project', json={'project': 'XYZ'}).status_code == 403
    response = client.post('/api/chats/project', json={'project': 'XYZ'}, headers=headers)
    assert response.status_code == 201
    sid = response.json['id']
    assert 'cli_session_id' not in response.json
    assert client.post('/api/chats/project', json={'project': 'XYZ'}, headers=headers).status_code == 400
    assert client.get('/api/chats?kind=project&project=XYZ&archived=false').json[0]['id'] == sid
    assert client.get('/api/chats?archived=no').status_code == 400
    for suffix in ('open', 'read', 'unread'):
        assert client.post(f'/api/chats/{sid}/{suffix}').status_code == 403
        assert client.post(f'/api/chats/{sid}/{suffix}', headers=headers).status_code == 200
    assert client.patch(f'/api/chats/{sid}', json={'model': 'synthetic'}).status_code == 403
    assert client.patch(f'/api/chats/{sid}', json={'model': 'synthetic'}, headers=headers).json['model'] == 'synthetic'
    assert client.patch(f'/api/chats/{sid}', json={'repositories': []}, headers=headers).status_code == 400
    assert client.patch('/api/chats/defaults/feature', json={'chat_tool': 'claude', 'chat_model': 'synthetic'}, headers=headers).status_code == 200
    assert main(['chat', 'list', '--kind', 'project']) == 0
    assert json.loads(capsys.readouterr().out)[0]['id'] == sid
    for command in ('open', 'read', 'unread'):
        assert main(['chat', command, str(sid)]) == 0
        assert 'cli_session_id' not in capsys.readouterr().out
    assert main(['chat', 'configure', str(sid), '--model', 'synthetic-cli']) == 0
    assert json.loads(capsys.readouterr().out)['model'] == 'synthetic-cli'
    assert main(['chat', 'defaults', 'project', '--model', 'synthetic-default']) == 0
    assert json.loads(capsys.readouterr().out)['project']['chat_model'] == 'synthetic-default'
    assert main(['chat', 'project', 'NEW']) == 0
    assert json.loads(capsys.readouterr().out)['project'] == 'NEW'
    monkeypatch.delenv('CPLANE_DATABASE_URL')
    assert main(['chat', 'list']) == 1


def test_queue_prioritizes_owner_globally_and_serializes_shared_repository(pg_store):
    pg_store.project_add('XYZ', 'Synthetic', repository='owner/shared')
    chat = pg_store.create_project_chat('XYZ')
    feature, feature_chat_row = feature_chat(pg_store, project='XYZ')
    pg_store.session_messages('factory', chat['id'], 'Owner first')
    owner = pg_store.claim_session_turn()
    assert owner['session']['id'] == chat['id']
    assert pg_store.claim_session_turn() is None
    unrelated = pg_store.create_session('factory', 'Other', 'codex', 'synthetic', ['owner/other'])
    pg_store.session_messages('factory', unrelated, 'Independent')
    second = pg_store.claim_session_turn()
    assert second['session']['id'] == unrelated
    pg_store.finish_session_turn(owner, 'Done', 'synthetic')
    event = pg_store.claim_session_turn()
    assert event['session']['id'] == feature_chat_row['id']
    assert event['role'] == 'system'


def test_concurrent_feature_stage_creates_only_one_chat(pg_store):
    identifier = pg_store.feature_add('NEW', 'Concurrent')['id']
    def move(_):
        try:
            PostgresStore(pg_store._url).feature_stage(identifier, 'grilling')
            return True
        except StateError:
            return False
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(move, range(2))) == [False, True]
    assert len(pg_store.chats(kind='feature')) == 1
    chat = pg_store.chats(kind='feature')[0]
    assert len(pg_store.session_messages('factory', chat['id'])) == 1
