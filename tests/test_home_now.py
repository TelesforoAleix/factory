from datetime import datetime, timezone

from cplane.planner import new_slice
from factory_ui.home import home_data
from test_stores import pg_store


def test_home_now_projection():
    at = '2026-01-01T00:00:00+00:00'
    def item(identifier, state, feature=None, reason=None):
        s = new_slice(identifier)
        s.update(title=identifier, state=state, feature_id=feature)
        s['log'] = [dict(at=at, actor='runner', event='started')]
        if reason:
            s['no_feature'] = reason
        return s
    slices = [item('run', 'issued', 'old'), item('drop', 'dropped', 'F1'),
              item('done', 'accepted', 'F1'), item('free', 'ready', reason='Maintenance'),
              item('free2', 'planned'), item('closed', 'dropped')]
    slices[0]['log'].append(dict(at=at, actor='owner', event='install requested: abc'))
    features = [dict(id='F2', title='Second', stage='building', project='P'),
                dict(id='F1', title='First', stage='building', project='P'),
                dict(id='N', title='Next', stage='next', project='P')]
    class Connection:
        def execute(self, query):
            return [(7, datetime.fromisoformat(at), None)]
    class Store:
        connection = Connection()
        def load(self): return dict(slices=slices)
        def chats(self, **kwargs): return [dict(id=7, kind='project', project='P', title='Planning', feature=None, waiting=False)]
        def notices(self): return []
        def feature_links(self): return {'old': 'F1', 'F1': 'F1'}
        def ordered_slices(self, entries): return list(reversed(entries))
        def limit_show(self): return dict(waiting_limit=3)
    result = home_data(Store(), dict(features=features, projects=[]), lambda x: x, None)
    assert [(r['kind'], r['id']) for r in result['running_now']] == [('slice', 'run'), ('install', 'run'), ('chat', 7)]
    assert all(r['since'] == at for r in result['running_now'])
    assert result['running'] == [dict(id='run', title='run', feature='F1', project='P', since=at)]
    assert [f['id'] for f in result['building']] == ['F2', 'F1']
    assert (result['building'][1]['done'], result['building'][1]['total']) == (2, 3)
    assert [s['id'] for s in result['building'][1]['slices']] == ['done', 'drop', 'run']
    assert [f['id'] for f in result['features'] if f['stage'] == 'next'] == ['N']
    assert [(s['id'], s['no_feature']) for s in result['unlinked']] == [('free2', None), ('free', 'Maintenance')]


def test_home_endpoint_with_running_chat_postgres(pg_store):
    from conftest import seed_model_choices
    from factory_ui import create_app

    seed_model_choices(pg_store)
    chat = pg_store.create_session('factory', 'Synthetic chat', 'codex', 'synthetic-model', [])
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_sessions SET state = 'running' WHERE id = %s", (chat,))
        pg_store.connection.execute(
            "INSERT INTO cplane_session_messages (session, role, text, status, time) VALUES (%s, 'owner', 'Test', 'running', '2026-01-01T00:00:00Z')", (chat,))
        pg_store.connection.execute(
            "INSERT INTO cplane_run_records (turn_key, kind, session_id, tool, started_at) VALUES ('test', 'chat', %s, 'codex', '2026-01-01T00:01:00Z')", (str(chat),))
    response = create_app(pg_store).test_client().get('/api/home')
    assert response.status_code == 200
    data = response.get_json()
    assert all(key in data for key in ('quick_chats', 'attention', 'projects', 'features', 'orchestrator_count', 'running', 'chats'))
    assert data['running'] == []
    assert data['running_now'] == [dict(kind='chat', id=chat, title='Synthetic chat', project=None, since='2026-01-01T00:01:00+00:00')]
