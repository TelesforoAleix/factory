"""Owner web view of Factory state."""
import os
import re
from pathlib import Path
from argparse import Namespace

from cplane import cli, planner, state

from flask import Flask, jsonify, request, send_from_directory
from cplane.stores import PostgresStore

DIST = Path(__file__).resolve().parent.parent / 'ui' / 'dist'


def clean(value):
    """Hide URLs and filesystem paths in free-form state text."""
    if value is None:
        return None
    value = re.sub(r'\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>"\']+', '[redacted]', value)
    return re.sub(r'(?<![\w/])(?:~?/|\.\.?/)[^\s<>"\']+', '[path]', value)


def view(item):
    attention = item['attention']
    final = item.get('final')
    return {
        'id': item['id'], 'title': clean(item['title']), 'state': item['state'],
        'repo': clean(item['repo']), 'feature': clean(item['feature']),
        'paused': item['paused'], 'slot': item['slot'], 'depends_on': item['depends_on'],
        'executor': {key: clean(value) for key, value in item['executor'].items()}, 'pr': item['pr'],
        'final': None if final is None else {
            'kind': clean(final['kind']), 'body': clean(final['body']), 'at': final['at'],
        },
        'attention': None if attention is None else {
            'kind': attention['kind'], 'body': clean(attention['body']),
            'since': attention['since'], 'answer': clean(attention['answer']),
            'approved': attention['approved'],
            'review': ({'verdict': clean(attention['review']['verdict']), 'actor': clean(attention['review']['actor']), 'at': attention['review']['at']} if attention.get('review') else None),
        },
        'log': [{'at': entry['at'], 'actor': clean(entry['actor']),
                 'event': clean(entry['event'])} for entry in item['log']],
    }


def create_app(store=None):
    app = Flask(__name__, static_folder=None)
    app.config['STORE'] = store

    @app.before_request
    def guard_mutations():
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('X-Factory-UI') != '1':
            return 'Required request header missing', 403

    def backend():
        return app.config['STORE'] or PostgresStore(os.environ.get('CPLANE_DATABASE_URL'))

    def slices():
        return backend().load()['slices']

    @app.get('/api/slices')
    def list_slices():
        try:
            return jsonify([view(item) for item in slices()])
        except Exception:
            return jsonify(error='State unavailable'), 503

    @app.get('/api/pending')
    def pending():
        try:
            return jsonify({key: [view(item) for item in items] for key, items in cli.pending({'slices': slices()}).items()})
        except Exception:
            return jsonify(error='State unavailable'), 503

    @app.post('/api/actions/<command>/<path:slice_id>')
    def action(command, slice_id):
        if command not in ('answer', 'review', 'approve', 'start', 'pause', 'resume'):
            return 'Unknown action', 404
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return 'Invalid request', 400
        value = payload.get('value')
        if command in ('answer', 'review') and (not isinstance(value, str) or not value.strip()):
            return 'Text is required', 400
        if command == 'approve' and (payload.get('confirmed') is not True or not isinstance(payload.get('pr'), int) or isinstance(payload.get('pr'), bool)):
            return 'Confirm the pull request before approval', 400
        change = (planner.change_for(Namespace(command='review', verdict=value, actor='owner'))
                  if command == 'review' else cli.change_for(command, value))
        def checked(item, data, at):
            if command == 'approve':
                if item['pr'] != payload['pr']:
                    raise state.StateError('Pull request changed; review it before approving')
                if item['attention'] and item['attention']['kind'] == 'merge' and 'review' not in item['attention']:
                    raise state.StateError('A recorded review is required before approval')
            return change(item, data, at)
        try:
            store = backend()
            with store.locked():
                # update_locked uses the supplied store for the complete transaction.
                token = state._ACTIVE.set(store)
                try:
                    warning = state.update_locked(Path('.'), slice_id, command, 'owner', checked)
                finally:
                    state._ACTIVE.reset(token)
            return f'{command.capitalize()} completed' + (f'\nwarning: {warning}' if warning else ''), 200
        except state.StateError as error:
            return clean(' '.join(str(error).splitlines())), 400
        except Exception:
            return 'State unavailable', 503

    @app.get('/api/slices/<path:slice_id>')
    def slice_detail(slice_id):
        try:
            item = next((item for item in slices() if item['id'] == slice_id), None)
            return (jsonify(view(item)) if item else (jsonify(error='Slice not found'), 404))
        except Exception:
            return jsonify(error='State unavailable'), 503

    @app.get('/')
    @app.get('/<path:path>')
    def frontend(path=''):
        if path == 'api' or path.startswith('api/'):
            return jsonify(error='Not found'), 404
        if path and (DIST / path).is_file():
            return send_from_directory(DIST, path)
        return send_from_directory(DIST, 'index.html')

    return app
