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
