"""Owner web view of Factory state."""
import os
import re
from pathlib import Path
from argparse import Namespace

from cplane import cli, planner, state

from flask import Flask, jsonify, request, send_from_directory, redirect
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

    @app.get('/api/home')
    def home():
        from .home import home_data
        try:
            return jsonify(home_data(backend(), board_data(), clean, view))
        except Exception:
            return jsonify(error='Home unavailable'), 503

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

    def chat_response(operation, project_names=False):
        from cplane.chats import public_chat_result
        try:
            result = public_chat_result(operation())
            if project_names:
                names = {p['key']: p.get('name') or p['key'] for p in backend().library_projects()}
                def add_name(chat):
                    if isinstance(chat, dict) and chat.get('project'):
                        chat['project_name'] = names.get(chat['project'], chat['project'])
                    return chat
                if isinstance(result, list):
                    result = [add_name(chat) for chat in result]
                elif isinstance(result, dict) and 'chat' in result:
                    add_name(result['chat'])
                else:
                    add_name(result)
            return jsonify(result)
        except (state.StateError, ValueError) as error:
            return jsonify(error=str(error)), 400
        except Exception:
            return jsonify(error='Chats unavailable'), 503

    @app.get('/api/chats')
    def chats():
        def operation():
            archived = request.args.get('archived')
            if archived is not None and archived not in ('true', 'false'):
                raise ValueError('Archived must be true or false')
            return backend().chats(kind=request.args.get('kind'), project=request.args.get('project'),
                                   archived=None if archived is None else archived == 'true')
        return chat_response(operation, project_names=True)

    @app.post('/api/chats/project')
    def project_chat():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get('project'), str):
            return jsonify(error='Project key required'), 400
        response = chat_response(lambda: backend().create_project_chat(payload['project']), project_names=True)
        return response if isinstance(response, tuple) else (response, 201)

    @app.route('/api/chats/defaults', methods=['GET'])
    @app.route('/api/chats/defaults/<kind>', methods=['GET', 'PATCH'])
    def chat_defaults(kind=None):
        payload = request.get_json(silent=True) if request.method == 'PATCH' else {}
        if not isinstance(payload, dict) or any(k not in ('chat_tool', 'chat_model') for k in payload):
            return jsonify(error='Invalid chat defaults'), 400
        if any(v is None for v in payload.values()):
            return jsonify(error='Invalid chat defaults'), 400
        return chat_response(lambda: backend().chat_defaults(kind, **payload))

    @app.route('/api/chats/<int:chat_id>', methods=['GET', 'PATCH'])
    def chat_detail(chat_id):
        if request.method == 'GET':
            return chat_response(lambda: backend().chat_show(chat_id), project_names=True)
        payload = request.get_json(silent=True)
        if (not isinstance(payload, dict) or any(k not in ('tool', 'model') for k in payload)
                or any(v is None for v in payload.values())):
            return jsonify(error='Invalid chat configuration'), 400
        return chat_response(lambda: backend().chat_configure(chat_id, **payload), project_names=True)

    @app.get('/api/chats/<int:chat_id>/usage')
    def chat_usage(chat_id):
        def operation():
            from datetime import datetime
            store = backend()
            chat = store.chat_show(chat_id)
            messages = store.session_messages(chat['area'], chat_id)
            records = [r for r in store.run_record_list()
                       if r['kind'] == 'chat' and r['session_id'] == str(chat_id) and r['started_at']]
            records.sort(key=lambda r: r['started_at'])
            result = {}
            for index, record in enumerate(records):
                start = datetime.fromisoformat(record['started_at'])
                end = datetime.fromisoformat(records[index + 1]['started_at']) if index + 1 < len(records) else None
                reply = next((m for m in messages if m['role'] == 'assistant'
                              and (not m['automatic'] or m['status'] == 'failed')
                              and datetime.fromisoformat(m['time']) >= start
                              and (end is None or datetime.fromisoformat(m['time']) < end)), None)
                if reply:
                    result[str(reply['id'])] = dict(tokens=record['turn_tokens'], seconds=record['seconds'])
            return result
        return chat_response(operation)

    @app.post('/api/chats/<int:chat_id>/open')
    def open_chat(chat_id):
        return chat_response(lambda: backend().chat_open(chat_id), project_names=True)

    @app.post('/api/chats/<int:chat_id>/read')
    def read_chat(chat_id):
        return chat_response(lambda: backend().chat_read(chat_id), project_names=True)

    @app.post('/api/chats/<int:chat_id>/unread')
    def unread_chat(chat_id):
        return chat_response(lambda: backend().chat_read(chat_id, unread=True), project_names=True)

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

    from .library import register_library
    register_library(app, backend, documents)

    @app.get('/home-lab')
    @app.get('/home-lab/<path:old>')
    def old_home_lab(old=''):
        if old == 'sessions':
            sid = request.args.get('session', '')
            return redirect('/chats/' + sid if sid.isdigit() else '/chats', code=302)
        if old.startswith('documents/'):
            from urllib.parse import quote
            return redirect('/library/documents/' + quote(old[10:], safe='/'), code=302)
        return redirect('/library/documents/backlog.md' if old == 'backlog' else '/library', code=302)

    @app.get('/')
    @app.get('/<path:path>')
    def frontend(path=''):
        if path == 'api' or path.startswith('api/'):
            return jsonify(error='Not found'), 404
        if path and (DIST / path).is_file():
            return send_from_directory(DIST, path)
        return send_from_directory(DIST, 'index.html')

    return app
