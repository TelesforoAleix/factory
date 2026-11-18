from cplane import evals
from cplane.state import StateError
from factory_ui import create_app


def test_eval_endpoints(monkeypatch):
    store = object()
    client = create_app(store).test_client()
    sets = [{'id': 'set', 'version': 1, 'title': 'Set'}]
    detail = dict(sets[0], members=['case'], tag_filter={})
    attempt = dict(id=1, state='done', configuration_id='c', metrics={'wall_seconds': 3}, verdicts=[])
    run = dict(id=1, configurations=[dict(id='c', harness='pi', model='m')], attempts=[attempt], set_versions=[{'set':'set','version':1}])
    monkeypatch.setattr(evals, 'config_list', lambda s: [{'id':'named','path':'slice','roles':{}}])
    assert client.get('/api/evals/configurations').json[0]['id'] == 'named'
    monkeypatch.setattr(evals, 'set_list', lambda s: sets)
    monkeypatch.setattr(evals, 'set_show', lambda s, i, v=None: detail.copy())
    monkeypatch.setattr(evals, 'case_list', lambda s: [dict(id='case', title='Case')])
    monkeypatch.setattr(evals, 'run_list', lambda s: [run])
    monkeypatch.setattr(evals, 'run_show', lambda s, i: run.copy())
    assert client.get('/api/evals/sets').json[0]['case_count'] == 1
    assert client.get('/api/evals/sets/set?version=1').json['cases'][0]['id'] == 'case'
    assert client.get('/api/evals/runs').json[0]['done'] == 1
    assert client.get('/api/evals/runs/1').json['sets'][0]['version'] == 1
    assert client.get('/api/evals/estimate').json == [dict(harness='pi', model='m', metrics={'wall_seconds':3})]
    monkeypatch.setattr(evals, 'run_list', lambda s: [])
    assert client.get('/api/evals/estimate').json == []
    payload = dict(title='Run', sets=['set'], configurations=['c'], repeats=1)
    assert client.post('/api/evals/runs', json=payload).status_code == 403
    def create(s, **kwargs):
        assert kwargs['actor'] == 'owner'
        raise StateError('bad configuration')
    monkeypatch.setattr(evals, 'run_create', create)
    response = client.post('/api/evals/runs', json=payload, headers={'X-Factory-UI':'1'})
    assert response.status_code == 400 and response.json['error'] == 'bad configuration'
    monkeypatch.setattr(evals, 'run_create', lambda s, **kw: {'id': 7})
    assert client.post('/api/evals/runs', json=payload, headers={'X-Factory-UI':'1'}).json == {'id': 7}


def test_inline_configurations_refused_by_route(monkeypatch):
    client = create_app(object()).test_client()
    called = []
    monkeypatch.setattr(evals, 'run_create', lambda *a, **kw: called.append(kw))
    response = client.post('/api/evals/runs', json=dict(title='Bad', sets=['s'],
        configurations=[dict(id='legacy')], repeats=1), headers={'X-Factory-UI':'1'})
    assert response.status_code == 400 and called == []
