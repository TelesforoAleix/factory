"""Project pages and edits use synthetic data and isolated Postgres schemas."""
import copy
from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest

from cplane.cli import main
from cplane.state import StateError
from factory_ui import create_app
from test_stores import pg_store

HEADERS = {'X-Factory-UI': '1'}


def test_add_set_and_cli(pg_store, capsys):
    assert main(['project', 'add', 'SYN', 'Synthetic', '--actor', 'owner']) == 0
    project = json.loads(capsys.readouterr().out)
    assert project['active'] and project['key'] == 'SYN'
    assert len(pg_store.chats(kind='project', project='SYN')) == 1
    assert main(['project', 'set', 'SYN', '--name', 'Renamed', '--about', 'A few sentences.',
                 '--public-url', 'https://example.test', '--repository-url', 'https://example.test/repo',
                 '--actor', 'owner']) == 0
    project = json.loads(capsys.readouterr().out)
    assert project['name'] == 'Renamed' and project['about'] == 'A few sentences.'
    assert pg_store.project_set('SYN', public_url='')['public_url'] is None
    with pg_store.locked():
        events = pg_store.connection.execute(
            "SELECT actor, changes FROM cplane_project_events WHERE project = 'SYN' ORDER BY id").fetchall()
    assert all(actor == 'owner' for actor, _ in events)
    assert events[1][1]['name'] == 'Renamed' and events[-1][1] == {'public_url': None}
    with pytest.raises(StateError, match='taken'):
        pg_store.project_add('SYN', 'Duplicate')
    assert len(pg_store.chats(kind='project', project='SYN')) == 1
    with pytest.raises(StateError, match='owner'):
        pg_store.project_set('SYN', name='Planner edit', actor='chat:9')
    with pytest.raises(StateError):
        with pg_store.mutation():
            pg_store.connection.execute("UPDATE cplane_projects SET key = 'XYZ' WHERE key = 'SYN'")
    assert pg_store.project_show('SYN')['key'] == 'SYN'


@pytest.mark.parametrize('fields', [
    {'name':''}, {'name':' '}, {'name':'a'*61}, {'name':None}, {'about':'a'*601}, {'about':None},
    {'public_url':'http://example.test'}, {'public_url':'https://'}, {'public_url':123},
    {'repository_url':'javascript:alert(1)'}, {'repository_url':'https://example.test/ bad'},
    {'public_url':'https://user:password@example.test'}, {'repository_url':'https://[invalid'},
])
def test_field_validation_is_atomic(pg_store, fields):
    before = pg_store.project_show('FAC')
    with pytest.raises(StateError):
        pg_store.project_set('FAC', **fields)
    assert pg_store.project_show('FAC') == before
    with pg_store.locked():
        assert not pg_store.connection.execute('SELECT 1 FROM cplane_project_events').fetchone()
    with pytest.raises(StateError):
        pg_store.project_add('SYN', **{'name':'Synthetic', **fields})
    assert not pg_store.chats(project='SYN')


def test_lengths_and_add_failure_roll_back(pg_store, monkeypatch):
    pg_store.project_set('FAC', name='a'*60, about='b'*600, public_url=None)
    with pytest.raises(StateError):
        pg_store.project_add('bad', 'Bad')
    with monkeypatch.context() as patch:
        patch.setattr(pg_store, 'create_project_chat', Mock(side_effect=StateError('synthetic failure')))
        with pytest.raises(StateError, match='synthetic failure'):
            pg_store.project_add('SYN', 'Synthetic')
    assert not any(p['key'] == 'SYN' for p in pg_store.library_projects())
    assert not pg_store.chats(project='SYN')


def test_api_sections_scoping_and_guard(pg_store, slice_data):
    pg_store.project_active('FAC', True)
    fac = pg_store.feature_add('FAC', 'Building feature', stage='building')
    pg_store.feature_add('FAC', 'Testing feature', stage='testing')
    pg_store.feature_add('FAC', 'Queued feature', stage='next')
    other = pg_store.feature_add('LAB', 'Other project', stage='building')
    items = []
    for i, feature in enumerate((fac, other)):
        item = copy.deepcopy(slice_data)
        item.update(id=f'demo/S{i}', feature_id=feature['id'], state='issued',
                    attention=dict(kind='question', body='Which?', since='2026-11-09T12:00:00+00:00', answer=None, approved=False))
        items.append(item)
    pg_store.save(dict(version=1, slices=items))
    client = create_app(pg_store).test_client()
    data = client.get('/api/projects/FAC').json
    assert data['stages']['building'] == data['stages']['testing'] == data['stages']['next'] == 1
    assert len(data['features']) == 3
    assert [a['id'] for a in data['attention']] == ['demo/S0']
    assert [r['id'] for r in data['running']] == ['demo/S0']
    assert data['chats'][0]['kind'] == 'project'
    assert all(c.get('feature') != other['id'] for c in data['chats'])
    assert not any('cli_session_id' in c for c in data['chats'])
    pg_store.project_active('FAC', False)
    assert client.get('/api/projects/FAC').json['project']['active'] is False
    assert client.get('/api/projects/NEW').status_code == client.get('/api/projects/ZZZ').status_code == 404
    assert client.patch('/api/projects/FAC', json={'name':'Changed'}).status_code == 403
    assert client.post('/api/projects', json={'key':'SYN','name':'Synthetic'}).status_code == 403
    for fields in ({'key':'XYZ'}, {'actor':'planner'}, {'repository':'/tmp'}, {'name':None}, {'active':True,'about':'x'}):
        assert client.patch('/api/projects/FAC', json=fields, headers=HEADERS).status_code == 400
    assert client.patch('/api/projects/FAC', json={'name':'Changed'}, headers=HEADERS).json['name'] == 'Changed'
    assert client.post('/api/projects', json={'key':'SYN','name':'Synthetic'}, headers=HEADERS).status_code == 201
    assert client.post('/api/projects', json={'key':'SYN','name':'Again'}, headers=HEADERS).status_code == 400
    assert client.post('/api/projects', json={'key':None,'name':'Bad'}, headers=HEADERS).status_code == 400
    assert len(pg_store.chats(kind='project', project='SYN')) == 1


def test_usage_differences_before_project_and_month_filter(pg_store):
    # Codex counters accumulate across resumes, even if a prior run is in another project/month.
    with pg_store.mutation():
        for turn, project, tokens, seconds, started in (
            ('old', 'LAB', 100, 100, '2020-01-01T00:00:00Z'),
            ('month', 'FAC', 160, 3600, datetime.now(timezone.utc)),
            ('reset', 'FAC', 20, 1800, datetime.now(timezone.utc)),
            ('historic', 'FAC', 30, 7200, '2020-02-01T00:00:00Z'),
        ):
            pg_store.connection.execute(
                'INSERT INTO cplane_run_records (turn_key, kind, project, tool, session_id, input_tokens, '
                'output_tokens, cached_tokens, seconds, started_at) VALUES (%s, \'slice\', %s, \'codex\', \'synthetic\', %s, %s, %s, %s, %s)',
                (turn, project, tokens, tokens, tokens, seconds, started))
        pg_store.connection.execute(
            "INSERT INTO cplane_run_records (turn_key, kind, project, tool, seconds) VALUES ('unknown', 'chat', 'FAC', 'claude', NULL)")
    usage = create_app(pg_store).test_client().get('/api/projects/FAC').json['usage']
    assert usage['month'] == dict(input_tokens=80, output_tokens=80, cached_tokens=80, hours=1.5)
    assert usage['all_time'] == dict(input_tokens=90, output_tokens=90, cached_tokens=90, hours=3.5)
    assert pg_store.project_usage('ZZZ')['all_time'] == dict(input_tokens=0, output_tokens=0, cached_tokens=0, hours=0)
