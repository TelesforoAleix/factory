"""Shared project visibility stays outside scheduling and preserves durable data."""
from concurrent.futures import ThreadPoolExecutor
import json
from unittest.mock import Mock

import pytest

from cplane.cli import main
from cplane.state import StateError
from cplane.stores import PostgresStore
from factory_ui import create_app
from test_stores import pg_store
from test_documents import published, client_for

HEADERS = {'X-Factory-UI': '1'}


def test_defaults_new_and_cli(pg_store, capsys):
    assert all(p['active'] for p in pg_store.library_projects())
    pg_store.project_add('SYN', 'Synthetic')
    assert pg_store.project_active('SYN')['active'] is True
    assert main(['project', 'active', 'SYN', 'off', '--actor', 'test-owner']) == 0
    assert json.loads(capsys.readouterr().out)['active'] is False
    assert main(['project', 'list']) == 0
    assert next(p for p in json.loads(capsys.readouterr().out) if p['key'] == 'SYN')['active'] is False
    with pg_store.locked():
        assert pg_store.connection.execute("SELECT actor, active FROM cplane_project_events WHERE project = 'SYN' ORDER BY id DESC LIMIT 1").fetchone() == ('test-owner', False)
    with pytest.raises(StateError, match='always active'):
        pg_store.project_active('NEW', False)
    assert pg_store.project_active('NEW', True)['active'] is True
    assert len(pg_store.chats(kind='project', project='NEW')) == 1
    with pytest.raises(StateError, match='Unknown project'):
        pg_store.project_active('BAD', True)
    with pytest.raises(StateError, match='boolean'):
        pg_store.project_active('FAC', 'false')


def test_activation_defaults_idempotence_and_serialization(pg_store):
    pg_store.chat_defaults('project', chat_tool='claude', chat_model='synthetic-model')
    pg_store.project_active('FAC', False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: PostgresStore(pg_store._url).project_active('FAC', True), range(2)))
    chats = pg_store.chats(kind='project', project='FAC')
    assert len(chats) == 1
    assert (chats[0]['tool'], chats[0]['model']) == ('claude', 'synthetic-model')
    pg_store.project_active('FAC', False)
    assert pg_store.chats(kind='project', project='FAC') == chats
    assert pg_store.project_active('FAC', True)['active'] is True
    assert pg_store.chats(kind='project', project='FAC') == chats


def test_activation_failure_rolls_back_flag_and_event(pg_store, monkeypatch):
    pg_store.project_active('FAC', False)
    monkeypatch.setattr(pg_store, 'create_project_chat', Mock(side_effect=StateError('synthetic failure')))
    with pytest.raises(StateError, match='synthetic failure'):
        pg_store.project_active('FAC', True)
    assert pg_store.project_active('FAC')['active'] is False
    with pg_store.locked():
        assert pg_store.connection.execute("SELECT count(*) FROM cplane_project_events WHERE project = 'FAC'").fetchone()[0] == 1


def test_project_api_guard_and_home_quick_chats(pg_store):
    client = create_app(pg_store).test_client()
    assert client.patch('/api/projects/FAC', json={'active':True}).status_code == 403
    for payload in ({'active':'false'}, {'key':'XYZ'}, {'active':False, 'name':'Rename'}):
        assert client.patch('/api/projects/FAC', json=payload, headers=HEADERS).status_code == 400
    assert client.patch('/api/projects/NEW', json={'active':False}, headers=HEADERS).status_code == 400
    for key in ('LAB', 'FAC'):
        assert client.patch('/api/projects/' + key, json={'active':True}, headers=HEADERS).status_code == 200
    quick = client.get('/api/home').json['quick_chats']
    assert [c['title'] for c in quick] == ['Development Orchestrator', 'factory', 'homelab-v2']
    pg_store.project_active('FAC', False)
    assert [c['title'] for c in client.get('/api/home').json['quick_chats']] == ['Development Orchestrator', 'homelab-v2']
    for url in ('/api/projects', '/api/home', '/api/pipeline'):
        data = client.get(url).json
        projects = data if isinstance(data, list) else data['projects']
        assert next(p for p in projects if p['key'] == 'FAC')['active'] is False
    assert len(pg_store.chats(kind='project', project='FAC')) == 1
    pg_store.project_active('NEW', True)
    assert client.get('/api/home').json['quick_chats'][-1]['title'] == 'No project yet'


def test_library_hides_only_inactive_repository_tree(published, pg_store):
    root = published[1].destination
    for folder in ('factory', 'homelab-v2', 'unowned'):
        (root / folder).mkdir()
        (root / folder / 'active-plan.md').write_text('# Plan\nSynthetic')
    client = client_for(published, pg_store)
    pg_store.project_active('FAC', False)
    paths = {d['path'] for d in client.get('/api/library').json['documents']}
    assert 'factory/active-plan.md' not in paths
    assert {'backlog.md', 'homelab-v2/active-plan.md', 'unowned/active-plan.md'} <= paths
    assert client.get('/api/library/documents/factory/active-plan.md').status_code == 200
    assert client.get('/api/library?project=FAC').json['documents'][0]['path'] == 'backlog.md'


def test_deactivation_keeps_features_queue_and_limits(pg_store):
    for stage in ('shortlist', 'parked', 'next', 'building', 'testing'):
        pg_store.feature_add('FAC', 'Synthetic ' + stage, stage=stage)
    before = pg_store.feature_board()['features']
    limits = pg_store.limit_show()
    pg_store.project_active('FAC', False)
    assert pg_store.feature_board()['features'] == before
    assert pg_store.limit_show() == limits


def test_migration_defaults_existing_projects_without_creating_chats(pg_store):
    chat = pg_store.create_project_chat('FAC')
    with pg_store.mutation():
        pg_store.connection.execute('ALTER TABLE cplane_projects DROP COLUMN active CASCADE')
        pg_store.connection.execute('ALTER TABLE cplane_project_events DROP COLUMN active')
        pg_store.connection.execute("DELETE FROM cplane_migrations WHERE name = '015_active_projects.sql'")
    pg_store.migrate()
    assert all(p['active'] is True for p in pg_store.library_projects())
    assert pg_store.chats(kind='project') == [chat]
    with pg_store.locked():
        nullable, default = pg_store.connection.execute(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'cplane_projects' AND column_name = 'active'").fetchone()
    assert (nullable, default) == ('NO', 'true')
