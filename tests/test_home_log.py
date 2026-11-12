from datetime import datetime, timedelta, timezone

from cplane.planner import new_slice
from factory_ui.home import home_data
from test_stores import pg_store


def test_home_log_projection():
    now = datetime.now(timezone.utc)
    item = new_slice('repo/S')
    events = ['state: ready', 'started', 'finished', 'merged: abc', 'install requested: id',
              'install started: id', 'install finished: id', 'Installed abc. By hand',
              'escalation: Install failed: error', 'rollback started', 'answer',
              'pause', 'resume', 'review', 'edit', 'escalation: unrelated']
    item['log'] = [dict(at=(now - timedelta(minutes=i + 1)).isoformat(), actor='chat:orchestrator', event=e)
                   for i, e in enumerate(events)]
    item['log'].append(dict(at=(now - timedelta(hours=25)).isoformat(), actor='owner', event='state: planned'))
    class Connection:
        def execute(self, query):
            if 'cplane_feature_events' in query:
                return [('FAC-F1', now - timedelta(seconds=30), 'owner', 'stage next to building')]
            return []
    class Store:
        connection = Connection()
        def load(self): return dict(slices=[item])
        def chats(self, **kwargs): return []
        def notices(self): return []
        def limit_show(self): return dict(waiting_limit=3)
    data = home_data(Store(), dict(features=[], projects=[]), lambda x: x, None)['log']
    assert not data['truncated']
    assert [m['event'] for m in data['moves']] == ['stage next to building'] + events[:11]
    assert data['moves'][0]['kind'] == 'feature' and data['moves'][0]['id'] == 'FAC-F1'
    assert data['moves'][1]['kind'] == 'slice' and data['moves'][1]['id'] == 'repo/S'
    assert data['moves'][1]['actor'] == 'chat:orchestrator'
    item['log'] = [dict(at=(now - timedelta(seconds=i)).isoformat(), actor='owner', event='state: ' + 'x' * 100) for i in range(201)]
    data = home_data(Store(), dict(features=[], projects=[]), lambda x: x.replace('x', 'y'), None)['log']
    assert data['truncated'] and len(data['moves']) == 200
    assert len(data['moves'][0]['event']) == 80 and 'x' not in data['moves'][0]['event']
    assert [m['at'] for m in data['moves']] == sorted((m['at'] for m in data['moves']), reverse=True)


def test_home_log_feature_events_postgres(pg_store):
    from factory_ui import create_app

    identifier = pg_store.feature_add('FAC', 'Synthetic')['id']
    pg_store.feature_stage(identifier, 'grilling', actor='owner')
    response = create_app(pg_store).test_client().get('/api/home')
    assert response.status_code == 200
    moves = response.get_json()['log']['moves']
    assert any(m['id'] == identifier and m['kind'] == 'feature' and m['event'] == 'stage shortlist to grilling' for m in moves)
    assert not any(m['id'] == identifier and m['event'].startswith('add ') for m in moves)
