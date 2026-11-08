"""Synthetic Library API, atomic comment delivery and additive migration."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from cplane.state import StateError
from cplane.stores import PostgresStore
from test_stores import pg_store
from test_documents import published, client_for

HEADERS = {'X-Factory-UI': '1'}
SELECTOR = dict(type='TextQuoteSelector', exact='searchable', prefix='A ', suffix=' document.')


def draft(store, path='folder/plan.md', text='Why?'):
    return store.document_comments(path, dict(text=text, selector=SELECTOR))


def test_tree_filter_search_and_default_receiver(published, pg_store):
    root = published[1].destination
    (root / 'factory').mkdir()
    (root / 'factory/plan.md').write_text('# Factory plan\nsearchable')
    client = client_for(published, pg_store)
    assert {d['path'] for d in client.get('/api/library?project=FAC').json['documents']} == {'backlog.md', 'factory/plan.md'}
    assert [d['path'] for d in client.get('/api/library?project=FAC&q=searchable').json['documents']] == ['factory/plan.md']
    assert client.get('/api/library?project=BAD').status_code == 400
    orchestrator = pg_store.chats(kind='orchestrator')[0]
    assert client.get('/api/library/documents/factory/plan.md').json['receiver']['id'] == orchestrator['id']
    project = pg_store.create_project_chat('FAC')
    assert client.get('/api/library/documents/factory/plan.md').json['receiver']['id'] == project['id']
    assert client.get('/api/library/documents/backlog.md').json['receiver']['id'] == orchestrator['id']
    assert 'cli_session_id' not in client.get('/api/library/documents/backlog.md').json['receiver']


def test_comment_api_batch_and_grill(published, pg_store):
    client = client_for(published, pg_store)
    url = '/api/library/comments/folder/plan.md'
    assert client.post(url, json={}).status_code == 403
    assert client.post(url, json={}, headers=HEADERS).status_code == 400
    for text in ['First?', 'Second?']:
        assert client.post(url, json=dict(text=text, selector=SELECTOR), headers=HEADERS).status_code == 200
    assert client.get(url).json[0]['selector'] == SELECTOR
    chat = pg_store.create_project_chat('FAC')
    result = client.post('/api/library/send/folder/plan.md', json={'chat':chat['id']}, headers=HEADERS)
    assert result.status_code == 200
    assert all(c['sent_at'] and c['chat'] == chat['id'] for c in result.json['comments'])
    messages = pg_store.session_messages('factory', chat['id'])
    assert len(messages) == 1
    assert all(s in messages[0]['text'] for s in ['folder/plan.md', 'searchable', 'First?', 'Second?'])
    assert client.post('/api/library/send/folder/plan.md', json={'chat':chat['id']}, headers=HEADERS).status_code == 400
    result = client.post('/api/library/grill/folder/plan.md', json={}, headers=HEADERS)
    assert result.status_code == 200
    message = pg_store.session_messages('homelab', result.json['chat'])[-1]['text']
    assert 'grilling skill' in message and 'planning/folder/plan.md' in message
    assert 'A searchable document.' not in message
    assert client.post('/api/library/grill/../secret.md', json={}, headers=HEADERS).status_code == 404


def test_send_rollback_and_duplicate_serialization(pg_store, monkeypatch):
    draft(pg_store)
    chat = pg_store.chats(kind='orchestrator')[0]
    original = pg_store.session_messages
    monkeypatch.setattr(pg_store, 'session_messages', Mock(side_effect=StateError('queue failed')))
    with pytest.raises(StateError, match='queue failed'):
        pg_store.library_send('folder/plan.md')
    assert pg_store.document_comments('folder/plan.md')[0]['sent_at'] is None
    monkeypatch.setattr(pg_store, 'session_messages', original)
    def send():
        try:
            return PostgresStore(pg_store._url).library_send('folder/plan.md')
        except StateError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: send(), range(2)))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert len(original('homelab', chat['id'])) == 1


def test_archived_receiver_and_invalid_selector_refused(pg_store):
    draft(pg_store)
    chat = pg_store.create_project_chat('FAC')
    with pg_store.mutation():
        pg_store.connection.execute('UPDATE cplane_sessions SET archived = true WHERE id = %s', (chat['id'],))
    with pytest.raises(StateError, match='non-archived'):
        pg_store.library_send('folder/plan.md', chat['id'])
    with pytest.raises(StateError):
        pg_store.library_send('folder/plan.md', True)
    for selector in [None, {}, {**SELECTOR, 'type':'XPathSelector'}, {**SELECTOR, 'prefix':'x'*257}]:
        with pytest.raises(StateError):
            pg_store.document_comments('folder/plan.md', dict(text='hello', selector=selector))
    assert not pg_store.document_comments('folder/plan.md')[0]['sent_at']


def test_note_migration_keeps_text_time_and_legacy_history(pg_store):
    # Recreate the exact pre-013 boundary in this test's disposable schema.
    with pg_store.mutation():
        pg_store.connection.execute('DROP TABLE cplane_document_comments')
        pg_store.connection.execute("DELETE FROM cplane_migrations WHERE name = '013_library.sql'")
        pg_store.connection.execute("INSERT INTO cplane_document_notes(document,text,time) VALUES ('backlog.md','Original note','2026-01-02T03:04:05Z')")
    sid = pg_store.create_session('homelab', 'Old grill', 'codex', 'test', ['owner/repo'])
    pg_store.session_messages('homelab', sid, 'Keep this message')
    pg_store.migrate()
    pg_store.migrate()
    comments = pg_store.document_comments('backlog.md')
    assert len(comments) == 1
    assert comments[0]['text'] == 'Original note' and comments[0]['selector'] is None
    assert comments[0]['sent_at'] == comments[0]['time'] == '2026-01-02T03:04:05+00:00'
    assert comments[0]['imported'] and comments[0]['chat'] is None
    assert pg_store.chat_show(sid)['archived']
    assert pg_store.session_messages('homelab', sid)[0]['text'] == 'Keep this message'
    assert pg_store.document_notes('backlog.md')[0]['text'] == 'Original note'


def test_skills_text_and_project_switch(published, pg_store):
    client = client_for(published, pg_store)
    result = client.get('/api/skills/grilling')
    assert result.status_code == 200 and 'Grill one question' in result.json['markdown']
    assert 'FAC' in result.json['projects']
    assert client.post('/api/skills/grilling', json={'project':'FAC','enabled':False}, headers=HEADERS).status_code == 200
    assert 'FAC' not in client.get('/api/skills/grilling').json['projects']
    assert client.post('/api/skills/grilling', json={'project':'FAC','enabled':'false'}, headers=HEADERS).status_code == 400
    assert client.post('/api/skills/../secret', json={}, headers=HEADERS).status_code == 405


@pytest.mark.parametrize(('old','new'), [('/home-lab','/library'),('/home-lab/documents/folder/plan.md','/library/documents/folder/plan.md'),('/home-lab/backlog','/library/documents/backlog.md'),('/home-lab/grills','/library'),('/home-lab/sessions?session=3','/chats/3')])
def test_old_addresses_redirect(published, old, new):
    response = client_for(published).get(old)
    assert response.status_code == 302 and response.location == new


def test_batch_limit_refuses_unsendable_draft_without_changing_existing(pg_store):
    draft(pg_store, text='x' * 15900)
    before = pg_store.document_comments('folder/plan.md')
    with pytest.raises(StateError, match='send existing drafts first'):
        draft(pg_store, text='x' * 16000)
    assert pg_store.document_comments('folder/plan.md') == before
    result = pg_store.library_send('folder/plan.md')
    assert result['comments'][0]['sent_at']
    draft(pg_store, text='Now the next batch')
    assert len([c for c in pg_store.document_comments('folder/plan.md') if not c['sent_at']]) == 1


def test_documents_remain_readable_without_a_usable_default_chat(published, pg_store):
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_sessions SET archived = true WHERE kind = 'orchestrator'")
    response = client_for(published, pg_store).get('/api/library/documents/backlog.md')
    assert response.status_code == 200
    assert response.json['markdown'] and response.json['receiver'] is None
