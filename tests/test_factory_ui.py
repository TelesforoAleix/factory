from factory_ui import create_app


class Store:
    def slice_policy(self, identifier):
        return None

    def slice_executor(self, item):
        return item['executor']

    def load(self):
        return {'slices': [{
            'id': 'demo/one', 'title': 'Example', 'state': 'ready', 'repo': 'owner/repo',
            'feature': 'Example', 'paused': False, 'slot': None, 'depends_on': [],
            'executor': {'tool': 'codex', 'model': 'test'}, 'pr': None,
            'brief': '/private/brief', 'session': {'folder': '/private/session'},
            'attention': {'kind': 'question', 'body': '<script>alert(1)</script> /private/file',
                          'since': '2026-01-01T00:00:00Z', 'answer': None, 'approved': False},
            'log': [{'at': '2026-01-01T00:00:00Z', 'actor': 'planner', 'event': 'read /private/log'}],
        }]}


def test_slice_views_omit_private_fields_and_redact_paths():
    client = create_app(Store()).test_client()
    response = client.get('/api/slices')
    assert response.status_code == 200
    assert b'/private/' not in response.data
    item = response.get_json()[0]
    assert 'brief' not in item and 'session' not in item
    assert item['final'] is None
    assert '<script>' in item['attention']['body']
    assert client.get('/api/slices/demo/one').get_json() == {**item, 'level': None}
    assert client.get('/api/slices/demo/missing').status_code == 404


def test_mutation_guard_applies_to_future_routes():
    app = create_app(Store())
    app.add_url_rule('/future', view_func=lambda: 'ok', methods=['POST', 'PATCH', 'DELETE'])
    client = app.test_client()
    for method in ('post', 'patch', 'delete'):
        assert getattr(client, method)('/future').status_code == 403
        assert getattr(client, method)('/future', headers={'X-Factory-UI': '1'}).status_code == 200


def test_store_errors_do_not_expose_details():
    class Broken:
        def load(self):
            raise ValueError('postgresql://secret /private/file')
    response = create_app(Broken()).test_client().get('/api/slices')
    assert response.status_code == 503
    assert response.get_json() == {'error': 'State unavailable'}


def test_owner_actions_use_cli_rules_and_locked_store(tmp_path):
    from cplane import planner, state
    from cplane.stores import FileStore

    item = planner.new_slice('demo/one')
    item.update(repo='owner/repo', feature='demo', title='Demo', brief='brief.md',
                state='ready', stop_before_merge=True, pr=42)
    item['attention'] = {'kind': 'merge', 'body': 'Review PR', 'since': '2026-01-01T00:00:00+00:00',
                         'answer': None, 'approved': False}
    path = tmp_path / 'state.json'
    path.touch()
    state._file_save(path, {'version': 1, 'slices': [item]})
    store = FileStore(path)
    client = create_app(store).test_client()
    headers = {'X-Factory-UI': '1'}
    url = '/api/actions/'
    assert client.post(url + 'pause/demo/one', json={}).status_code == 403
    assert client.post(url + 'approve/demo/one', headers=headers, json={'pr': 42, 'confirmed': True}).status_code == 400
    assert client.post(url + 'answer/demo/one', headers=headers, json={'value': 'answer'}).status_code == 400
    assert client.post(url + 'review/demo/one', headers=headers, json={'value': 'Looks good'}).status_code == 200
    assert client.post(url + 'approve/demo/one', headers=headers, json={'pr': 43, 'confirmed': True}).status_code == 400
    assert client.post(url + 'approve/demo/one', headers=headers, json={'pr': 42, 'confirmed': True}).status_code == 200
    for action in ('start', 'pause', 'resume'):
        assert client.post(url + action + '/demo/one', headers=headers, json={}).status_code == 200
    saved = store.load()['slices'][0]
    assert saved['attention']['approved'] and not saved['paused'] and saved['slot']
    assert all(entry['actor'] == 'owner' for entry in saved['log'])
    assert len(store.notices()) == 3
    assert client.get('/api/pending').get_json()['scheduled'][0]['id'] == 'demo/one'


def test_answer_and_start_refusal(tmp_path):
    from cplane import planner, state
    from cplane.stores import FileStore
    item = planner.new_slice('demo/two')
    item.update(repo='owner/repo', feature='demo', title='Demo')
    item['attention'] = {'kind': 'question', 'body': 'What next?',
                         'since': '2026-01-01T00:00:00+00:00', 'answer': None, 'approved': False}
    path = tmp_path / 'state.json'
    path.touch()
    state._file_save(path, {'version': 1, 'slices': [item]})
    store = FileStore(path)
    client = create_app(store).test_client()
    headers = {'X-Factory-UI': '1'}
    assert client.post('/api/actions/start/demo/two', json={}, headers=headers).status_code == 400
    assert client.post('/api/actions/answer/demo/two', json={'value': 'Proceed'}, headers=headers).status_code == 200
    assert store.load()['slices'][0]['attention']['answer'] == 'Proceed'
    assert store.notices()[0][1]['event'] == 'answer'


def test_final_message_is_cleaned_in_detail_api():
    class FinalStore(Store):
        def load(self):
            data = super().load()
            data['slices'][0]['final'] = {
                'kind': 'handover', 'body': '<script>text</script> /private/file https://example.com/secret',
                'at': '2026-01-01T00:00:00Z',
            }
            return data
    final = create_app(FinalStore()).test_client().get('/api/slices/demo/one').get_json()['final']
    assert final == {'kind': 'handover', 'body': '<script>text<[path]> [path] [redacted]',
                     'at': '2026-01-01T00:00:00Z'}


def test_pipeline_api_guard_reads_and_refusals():
    from cplane.state import StateError

    class BoardStore:
        def __init__(self):
            self.calls = []
        def feature_board(self, identifier=None):
            if identifier == 'missing': raise StateError('Feature not found')
            return {'projects': [{'key': 'FAC', 'name': 'Factory'}], 'features': [{
                'id': 'FAC-F1', 'project': 'FAC', 'aliases': ['OLD-F1'], 'title': 'Title /private/path',
                'sections': [{'name': 'Overview', 'text': 'Read /private/file'}],
                'slices': [], 'backlog': {'private': 'secret'}}]}
        def feature_stage(self, identifier, stage, *, actor):
            self.calls.append((identifier, stage, actor))
            raise StateError('No agreed design yet')
        def feature_place(self, identifier, *, actor, **placement):
            self.calls.append((identifier, placement, actor))
    store = BoardStore()
    client = create_app(store).test_client()
    item = client.get('/api/pipeline/OLD-F1').get_json()
    assert item['id'] == 'FAC-F1' and 'backlog' not in item
    assert '/private/' not in str(item)
    assert client.get('/api/pipeline/missing').status_code == 404
    url = '/api/pipeline/FAC-F1/'
    assert client.post(url + 'move', json={'stage': 'ready'}).status_code == 403
    headers = {'X-Factory-UI': '1'}
    response = client.post(url + 'move', json={'stage': 'ready'}, headers=headers)
    assert response.status_code == 400 and response.json['error'] == 'No agreed design yet'
    assert client.post(url + 'place', json={'before': 'FAC-F2'}, headers=headers).status_code == 200
    assert store.calls == [('FAC-F1', 'ready', 'owner'), ('FAC-F1', {'before': 'FAC-F2'}, 'owner')]
    assert client.post(url + 'place', json={'top': False}, headers=headers).status_code == 400


def test_chat_usage_is_scoped_and_omits_private_fields():
    class ChatStore:
        def chat_show(self, chat_id):
            return {'area': 'factory'}

        def session_messages(self, area, chat_id):
            return [dict(id=10, role='assistant', automatic=False, status='done',
                         time='2026-01-01T12:01:00+00:00'),
                    dict(id=11, role='assistant', automatic=True, status='done',
                         time='2026-01-01T12:01:01+00:00'),
                    dict(id=12, role='assistant', automatic=False, status='done',
                         time='2026-01-01T12:03:00+00:00')]

        def run_record_list(self):
            def row(session, started, tokens):
                return dict(kind='chat', session_id=session, started_at=started,
                            turn_tokens={'input_tokens': tokens}, seconds=5, prompt='private')
            return [row('7', '2026-01-01T12:00:00+00:00', 10),
                    row('8', '2026-01-01T12:00:00+00:00', 99),
                    row('7', '2026-01-01T12:02:00+00:00', 20)]

    response = create_app(ChatStore()).test_client().get('/api/chats/7/usage')
    assert response.status_code == 200
    assert response.json == {'10': {'tokens': {'input_tokens': 10}, 'seconds': 5},
                             '12': {'tokens': {'input_tokens': 20}, 'seconds': 5}}
    assert b'private' not in response.data


def test_home_projection_orders_attention_and_discards_stale_stuck(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from cplane import planner
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=30)).isoformat()
    item = planner.new_slice('demo/one')
    item.update(title='One', repo='owner/repo', feature='Feature', feature_id='FAC-F1', state='issued', pr=7)
    item['log'] = [dict(at=old, actor='runner', event='issued')]
    item['attention'] = dict(kind='merge', body='Approve', since=old, answer=None, approved=False,
                             review=dict(verdict='Looks good', actor='planner', at=old))
    feature = dict(id='FAC-F1', aliases=[], title='Feature', project='FAC', stage='building',
                   sections=[], slices=[item])
    class HomeStore:
        def load(self): return dict(slices=[item])
        def locked(self):
            from contextlib import nullcontext
            return nullcontext()
        def feature_cards(self): return dict(projects=[dict(key='FAC', name='Factory', active=False)], features=[{k:v for k,v in feature.items() if k not in ('slices', 'sections')} | dict(extra=None, waiting=True)])
        def notices(self): return [(1, dict(event='stuck', id=item['id'], since=old, reason='no new log activity', at=old))]
        def chats(self, **kwargs): return []
        def limit_show(self): return dict(waiting_limit=1, building_limit=2)
    client = create_app(HomeStore()).test_client()
    result = client.get('/api/home').get_json()
    assert [a['kind'] for a in result['attention']] == ['approval', 'limit']
    assert result['attention'][0]['verdict'] == 'Looks good'
    assert result['running'][0]['feature'] == 'FAC-F1'
    item['log'].append(dict(at=now.isoformat(), actor='runner', event='progress'))
    assert [a['kind'] for a in client.get('/api/home').get_json()['attention']] == ['approval', 'limit']
    item['attention'] = dict(kind='node-step', body='Install', since=old, answer=None, approved=False)
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', 'owner/repo')
    assert client.get('/api/home').get_json()['attention'][0]['installable'] is True
    from cplane.installation import request_change
    data = dict(slices=[item])
    request_change('chat:12')(item, data, now.isoformat())
    card = client.get('/api/home').get_json()['attention'][0]
    assert card['kind'] == 'install'
    assert card['label'] == 'proposed by chat'
    assert card['installing'] is False
    request_change('owner')(item, data, now.isoformat())
    card = client.get('/api/home').get_json()['attention'][0]
    assert card['label'] is None
    assert card['installing'] is True

    monkeypatch.setenv('CPLANE_INSTALL_REPOS', 'other/repo')
    assert client.get('/api/home').get_json()['attention'][0]['installable'] is False


def test_home_chat_decisions_follow_read_and_latest_pause():
    from factory_ui.home import home_data

    chat = dict(id=1, kind='feature', feature='FAC-F1', project='FAC', title='Chat',
                waiting=False, auto_paused=True, last_read_at=None)
    notices = [dict(event='owner-check', chat=1, at='2026-01-01T00:00:00Z', text='Check'),
               dict(event='chat-paused', chat=1, at='2026-01-01T00:01:00Z', text='Paused')]

    class HomeStore:
        def load(self): return dict(slices=[])
        def chats(self, **kwargs): return [chat]
        def notices(self): return list(enumerate(notices))
        def limit_show(self): return dict(waiting_limit=1)

    def cards():
        return home_data(HomeStore(), dict(features=[], projects=[]), lambda value: value, None)['attention']

    assert [card['text'] for card in cards()] == ['Check', 'Paused']
    # Postgres returns UTC timestamps, while notices use Copenhagen local time.
    # Lexicographic ordering puts this later read before both notices.
    notices[0]['at'] = '2026-01-01T01:00:00+01:00'
    notices[1]['at'] = '2026-01-01T01:01:00+01:00'
    chat['last_read_at'] = '2026-01-01T00:02:00.123456+00:00'
    assert cards() == []
    chat['last_read_at'] = '2026-01-01T00:01:00+00:00'
    assert cards() == []
    chat['last_read_at'] = '2026-01-01T00:02:00Z'
    assert cards() == []
    assert chat['auto_paused'] is True
    notices.append(dict(event='chat-paused', chat=1, at='2026-01-01T01:03:00+01:00', text='Paused again'))
    assert [card['text'] for card in cards()] == ['Paused again']
    chat['last_read_at'] = None
    assert [card['text'] for card in cards()] == ['Check', 'Paused again']
    chat['auto_paused'] = False
    assert [card['text'] for card in cards()] == ['Check']


def test_chat_responses_include_project_name_and_fallback():
    class ChatStore:
        def library_projects(self):
            return [dict(key='FAC', name='Factory')]

        def chats(self, **kwargs):
            return [dict(id=1, project='FAC'), dict(id=2, project='UNKNOWN')]

        def chat_show(self, chat_id):
            return dict(id=chat_id, project='FAC')

        def chat_open(self, chat_id):
            return dict(chat=self.chat_show(chat_id), messages=[])

    client = create_app(ChatStore()).test_client()
    rows = client.get('/api/chats').get_json()
    assert [row['project_name'] for row in rows] == ['Factory', 'UNKNOWN']
    assert client.get('/api/chats/1').get_json()['project_name'] == 'Factory'
    assert client.post('/api/chats/1/open', headers={'X-Factory-UI': '1'}).get_json()['chat']['project_name'] == 'Factory'


def test_inbox_owner_route_guard_and_dispatch():
    from unittest.mock import Mock
    store = Mock()
    store.inbox_show.return_value = {'label': None}
    store.inbox_route.return_value = {'route': 'Idea'}
    store.inbox_reject.return_value = {'route': 'Rejected'}
    client = create_app(store).test_client()
    path = '/api/inbox/42/route'
    assert client.post(path, json={'route': 'Idea'}).status_code == 403
    headers = {'X-Factory-UI': '1'}
    assert client.post(path, json={'route': 'Idea'}, headers=headers).json['route'] == 'Idea'
    store.inbox_route.assert_called_once_with(42, 'idea', 1, project=None, actor='owner')
    assert client.post(path, json={'route': 'Rejected', 'reason': 'No'}, headers=headers).json['route'] == 'Rejected'
    store.inbox_reject.assert_called_once_with(42, 'No', actor='owner')
    assert client.post(path, json={'route': 'chat', 'chat': 'secretary'}, headers=headers).status_code == 400


def test_slice_level_changes_only_before_issue_and_preserves_overrides():
    from contextlib import nullcontext
    class PolicyStore(Store):
        def __init__(self):
            self.state = 'planned'
            self.policy = {'level': 'light', 'overrides': {'model': 'custom'}}
        def locked(self):
            return nullcontext()
        def load(self):
            data = super().load()
            data['slices'][0]['state'] = self.state
            return data
        def slice_policy(self, identifier):
            return self.policy
        def slice_level(self, identifier, level, overrides):
            self.policy = {'level': level, 'overrides': overrides}
    store = PolicyStore()
    client = create_app(store).test_client()
    headers = {'X-Factory-UI': '1'}
    for status in ('planned', 'ready'):
        store.state = status
        assert client.post('/api/slices/demo/one/level', headers=headers, json={'level': 'strong'}).status_code == 200
        assert store.policy == {'level': 'strong', 'overrides': {'model': 'custom'}}
    store.policy = None
    assert client.post('/api/slices/demo/one/level', headers=headers, json={'level': 'light'}).status_code == 200
    assert store.policy['overrides'] == {}
    store.state = 'issued'
    assert client.post('/api/slices/demo/one/level', headers=headers, json={'level': 'standard'}).status_code == 400
    assert client.post('/api/slices/demo/one/level', headers=headers, json={'level': 'bad'}).status_code == 400
