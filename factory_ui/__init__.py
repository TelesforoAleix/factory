"""Owner web view of Factory state."""
import os
import re
from pathlib import Path
from argparse import Namespace

from cplane import cli, planner, state

from flask import Flask, jsonify, request, send_from_directory
from cplane.stores import PostgresStore
from .documents import Documents, DocumentNotFound

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
    app.config['DOCUMENT_ROOT'] = Path('/var/lib/factory/ui-docs')

    @app.before_request
    def guard_mutations():
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('X-Factory-UI') != '1':
            return 'Required request header missing', 403

    def backend():
        return app.config['STORE'] or PostgresStore(os.environ.get('CPLANE_DATABASE_URL'))

    def slices():
        return backend().load()['slices']

    def board_data():
        data = backend().feature_board()
        for item in data['features']:
            item['title'] = clean(item['title'])
            item['sections'] = [{**section, 'name': clean(section['name']), 'text': clean(section['text'])} for section in item['sections']]
            item['slices'] = [view(s) for s in item['slices']]
            item.pop('backlog', None)
        for project in data['projects']:
            project['name'] = clean(project['name'])
        return data

    @app.get('/api/skills')
    def list_skills():
        try:
            return jsonify(backend().skill_list())
        except Exception:
            return jsonify(error='Skills unavailable'), 503

    @app.get('/api/pipeline')
    def pipeline_board():
        try:
            return jsonify(board_data())
        except Exception:
            return jsonify(error='Pipeline unavailable'), 503

    @app.get('/api/pipeline/<identifier>')
    def pipeline_feature(identifier):
        try:
            item = next((f for f in board_data()['features'] if identifier == f['id'] or identifier in f['aliases']), None)
            return jsonify(item) if item else (jsonify(error='Feature not found'), 404)
        except Exception:
            return jsonify(error='Pipeline unavailable'), 503

    @app.post('/api/pipeline/<identifier>/<operation>')
    def pipeline_change(identifier, operation):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error='Invalid request'), 400
        try:
            if operation == 'move':
                target = payload.get('stage')
                if not isinstance(target, str):
                    return jsonify(error='Choose a stage'), 400
                backend().feature_stage(identifier, target, actor='owner')
            elif operation == 'place':
                if len(payload) != 1 or next(iter(payload), None) not in ('top', 'bottom', 'before', 'after'):
                    return jsonify(error='Choose exactly one placement'), 400
                key, value = next(iter(payload.items()))
                if (key in ('top', 'bottom') and value is not True) or (key in ('before', 'after') and not isinstance(value, str)):
                    return jsonify(error='Invalid placement'), 400
                backend().feature_place(identifier, actor='owner', **{key: value})
            else:
                return jsonify(error='Not found'), 404
            return jsonify(ok=True)
        except state.StateError as error:
            return jsonify(error=clean(' '.join(str(error).splitlines()))), 400
        except Exception:
            return jsonify(error='Pipeline unavailable'), 503

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

    @app.post('/api/slices/<path:slice_id>/install')
    def install_slice(slice_id):
        from cplane.installation import request_change
        try:
            store = backend()
            with store.locked():
                token = state._ACTIVE.set(store)
                try:
                    state.update_locked(Path('.'), slice_id, 'install', 'owner', request_change('owner'))
                finally:
                    state._ACTIVE.reset(token)
            return jsonify(status='requested'), 202
        except state.StateError as error:
            return jsonify(error=clean(str(error))), 400
        except Exception:
            return jsonify(error='State unavailable'), 503

    @app.get('/api/slices/<path:slice_id>')
    def slice_detail(slice_id):
        try:
            item = next((item for item in slices() if item['id'] == slice_id), None)
            return (jsonify(view(item)) if item else (jsonify(error='Slice not found'), 404))
        except Exception:
            return jsonify(error='State unavailable'), 503

    @app.route('/api/<area>/sessions', methods=['GET', 'POST'])
    def sessions(area):
        if area not in ('homelab', 'factory'):
            return jsonify(error='Not found'), 404
        try:
            store = backend()
            if request.method == 'GET':
                return jsonify([{k: v for k, v in item.items() if k != 'cli_session_id'}
                                for item in store.sessions(area)])
            from cplane.stores import validate_session
            fields = validate_session(request.get_json(silent=True), area)
            return jsonify(id=store.create_session(area, *fields)), 201
        except ValueError:
            return jsonify(error='Invalid session fields'), 400
        except Exception:
            return jsonify(error='Sessions unavailable'), 503

    @app.route('/api/<area>/sessions/<int:session_id>/messages', methods=['GET', 'POST'])
    def messages(area, session_id):
        if area not in ('homelab', 'factory'):
            return jsonify(error='Not found'), 404
        text = None
        if request.method == 'POST':
            payload = request.get_json(silent=True)
            text = payload.get('text') if isinstance(payload, dict) else None
            if not isinstance(text, str) or not text.strip() or len(text) > 32000:
                return jsonify(error='Message must contain 1–32000 characters'), 400
        try:
            return jsonify(backend().session_messages(area, session_id, text))
        except state.StateError as error:
            return jsonify(error=str(error)), 400
        except Exception:
            return jsonify(error='Messages unavailable'), 503

    def documents():
        return Documents(app.config['DOCUMENT_ROOT'])

    @app.errorhandler(DocumentNotFound)
    def missing_document(error):
        return jsonify(error='Document not found'), 404

    @app.get('/api/homelab/documents')
    def document_list():
        try:
            return jsonify(documents().search(request.args.get('q', '')))
        except OSError:
            return jsonify(error='Documents unavailable'), 503

    @app.get('/api/homelab/documents/<path:document>')
    def document_detail(document):
        try:
            return jsonify(documents().read(document))
        except OSError:
            return jsonify(error='Documents unavailable'), 503

    @app.route('/api/homelab/notes/<path:document>', methods=['GET', 'POST'])
    def document_notes(document):
        text = None
        if request.method == 'POST':
            payload = request.get_json(silent=True)
            text = payload.get('text') if isinstance(payload, dict) else None
            if not isinstance(text, str) or not text.strip() or len(text) > 16000:
                return jsonify(error='Note must contain 1–16000 characters'), 400
        try:
            documents().read(document)
            return jsonify(backend().document_notes(document, text))
        except DocumentNotFound:
            raise
        except Exception:
            return jsonify(error='Notes unavailable'), 503

    @app.post('/api/homelab/send-note/<int:note_id>/<path:document>')
    def send_note(note_id, document):
        payload = request.get_json(silent=True)
        sid = payload.get('session') if isinstance(payload, dict) else None
        if not isinstance(sid, int) or isinstance(sid, bool) or sid < 1:
            return jsonify(error='Choose a Home Lab session'), 400
        try:
            documents().read(document)
            return jsonify(backend().send_document_note(document, note_id, sid))
        except DocumentNotFound:
            raise
        except state.StateError as error:
            return jsonify(error=str(error)), 400
        except Exception:
            return jsonify(error='Note unavailable'), 503

    @app.post('/api/homelab/grills')
    def create_grill():
        from cplane.stores import validate_session
        payload = request.get_json(silent=True)
        try:
            if not isinstance(payload, dict) or not isinstance(payload.get('document'), str) or not payload['document']:
                raise ValueError()
            doc = documents().read(payload.get('document'))
            fields = validate_session({**payload, 'title': 'Grill: ' + doc['title'][:190]}, 'homelab')
            if not fields[3]:
                return jsonify(error='Name at least one repository'), 400
            message = ('Use the grilling skill for this Home Lab design. '
                       f'Read planning/{doc["path"]} and review it using the named repositories. '
                       'Once the owner agrees to a decision, write it into the document it belongs to and commit it.')
            return jsonify(id=backend().create_grill(fields, message)), 201
        except DocumentNotFound:
            raise
        except ValueError:
            return jsonify(error='Invalid grill fields'), 400
        except Exception:
            return jsonify(error='Grill unavailable'), 503

    @app.get('/')
    @app.get('/<path:path>')
    def frontend(path=''):
        if path == 'api' or path.startswith('api/'):
            return jsonify(error='Not found'), 404
        if path and (DIST / path).is_file():
            return send_from_directory(DIST, path)
        return send_from_directory(DIST, 'index.html')

    return app
