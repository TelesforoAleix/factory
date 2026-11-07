from factory_ui import create_app


class Store:
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
    assert client.get('/api/slices/demo/one').get_json() == item
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
        def feature_board(self):
            return {'projects': [{'key': 'FAC', 'name': 'Factory'}], 'features': [{
                'id': 'FAC-F1', 'aliases': ['OLD-F1'], 'title': 'Title /private/path',
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
