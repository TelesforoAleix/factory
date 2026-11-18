"""Workshop views over the eval catalogue; creation is the only mutation."""
from flask import jsonify, request
from cplane import evals
from cplane.state import StateError


def register_evals(app, backend):
    def respond(fn):
        try:
            return jsonify(fn())
        except (StateError, ValueError, TypeError) as error:
            return jsonify(error=str(error)), 400
        except Exception:
            return jsonify(error='Evals unavailable'), 503

    def set_detail(store, identifier, version=None):
        item = evals.set_show(store, identifier, version)
        members = set(item['members'])
        item['cases'] = [case for case in evals.case_list(store) if case['id'] in members]
        return item

    @app.get('/api/evals/sets')
    def sets():
        def read():
            store = backend()
            return [dict(item, case_count=len(evals.set_show(store, item['id'], item['version'])['members']))
                    for item in evals.set_list(store)]
        return respond(read)

    @app.get('/api/evals/sets/<identifier>')
    def show_set(identifier):
        def read():
            version = request.args.get('version')
            return set_detail(backend(), identifier, int(version) if version is not None else None)
        return respond(read)

    @app.get('/api/evals/configurations')
    def configurations():
        return respond(lambda: evals.config_list(backend()))

    @app.get('/api/evals/runs')
    def runs():
        def read():
            store = backend()
            result = []
            for run in reversed(evals.run_list(store)):
                attempts = evals.run_show(store, run['id'])['attempts']
                result.append(dict(run, done=sum(a['state'] == 'done' for a in attempts), total=len(attempts)))
            return result
        return respond(read)

    @app.get('/api/evals/runs/<int:identifier>')
    def show_run(identifier):
        def read():
            store = backend()
            run = evals.run_show(store, identifier)
            run['sets'] = [set_detail(store, ref['set'], ref['version']) for ref in run['set_versions']]
            return run
        return respond(read)

    @app.get('/api/evals/estimate')
    def history():
        def read():
            store = backend()
            result = []
            for run in evals.run_list(store):
                configs = {c['id']: c for c in run['configurations']}
                for attempt in evals.run_show(store, run['id'])['attempts']:
                    config = configs.get(attempt['configuration_id'])
                    if attempt['state'] == 'done' and config:
                        result.append(dict(configuration_id=config['id'], metrics=attempt.get('metrics') or {})
                                      if 'roles' in config else
                                      dict(harness=config['harness'], model=config['model'], metrics=attempt.get('metrics') or {}))
            return result
        return respond(read)

    @app.post('/api/evals/runs')
    def create():
        payload = request.get_json(silent=True)
        if (not isinstance(payload, dict) or not {'title', 'sets', 'configurations', 'repeats'} <= set(payload)
                or set(payload) - {'title', 'sets', 'configurations', 'repeats', 'scheduled_for'}):
            return jsonify(error='Invalid eval run'), 400
        if not isinstance(payload.get('sets'), list) or not all(isinstance(s, str) for s in payload['sets']) or not isinstance(payload.get('configurations'), list) or not all(isinstance(c, str) for c in payload['configurations']):
            return jsonify(error='Invalid eval run'), 400
        response = respond(lambda: evals.run_create(backend(), actor='owner', **payload))
        return response if isinstance(response, tuple) else (response, 201)
