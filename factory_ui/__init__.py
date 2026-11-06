"""Read-only web view of Factory state."""
import os
import re
from pathlib import Path

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
    return {
        'id': item['id'], 'title': clean(item['title']), 'state': item['state'],
        'repo': clean(item['repo']), 'feature': clean(item['feature']),
        'paused': item['paused'], 'slot': item['slot'], 'depends_on': item['depends_on'],
        'executor': {key: clean(value) for key, value in item['executor'].items()}, 'pr': item['pr'],
        'attention': None if attention is None else {
            'kind': attention['kind'], 'body': clean(attention['body']),
            'since': attention['since'], 'answer': clean(attention['answer']),
            'approved': attention['approved'],
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
            return jsonify(error='Required request header missing'), 403

    def slices():
        backend = app.config['STORE'] or PostgresStore(os.environ.get('CPLANE_DATABASE_URL'))
        return backend.load()['slices']

    @app.get('/api/slices')
    def list_slices():
        try:
            return jsonify([view(item) for item in slices()])
        except Exception:
            return jsonify(error='State unavailable'), 503

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
