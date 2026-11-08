"""Read-only export/skill views and owner comment actions."""
from flask import jsonify, request
from cplane.state import StateError
from cplane.skills import instructions
from .documents import DocumentNotFound


def register_library(app, backend, documents):
    def respond(operation):
        try:
            return jsonify(operation())
        except DocumentNotFound:
            raise
        except (StateError, ValueError) as error:
            return jsonify(error=str(error)), 400
        except Exception:
            return jsonify(error='Library unavailable'), 503

    @app.get('/api/library')
    def tree():
        def operation():
            store = backend()
            projects = store.library_projects()
            project = request.args.get('project', '')
            chosen = next((p for p in projects if p['key'] == project), None)
            if project and chosen is None:
                raise StateError('Unknown project')
            repository = (chosen['repository'] or '').split('/')[-1] if chosen else None
            rows = documents().search(request.args.get('q', ''))
            hidden = {(p['repository'] or '').split('/')[-1] for p in projects if not p.get('active', True) and p['key'] != 'NEW'}
            rows = [d for d in rows if '/' not in d['path'] or d['path'].split('/')[0] not in hidden]
            if chosen:
                rows = [d for d in rows if '/' not in d['path'] or d['path'].split('/')[0] == repository]
            return dict(documents=rows, projects=projects)
        return respond(operation)

    @app.get('/api/library/documents/<path:document>')
    def detail(document):
        def operation():
            doc = documents().read(document)
            from cplane.chats import public_chat_result
            try:
                doc['receiver'] = public_chat_result(backend().document_receiver(document))
            except StateError as error:
                doc['receiver'] = None
                doc['receiver_error'] = str(error)
            return doc
        return respond(operation)

    @app.route('/api/library/comments/<path:document>', methods=['GET', 'POST'])
    def comments(document):
        def operation():
            # Comments remain readable when the source was removed from the export.
            from .documents import document_path
            document_path(document)
            payload = None
            if request.method == 'POST':
                documents().read(document)
                payload = request.get_json(silent=True)
                if payload is None:
                    raise StateError('Provide a comment and a text quote selector')
            return backend().document_comments(document, payload)
        return respond(operation)

    @app.post('/api/library/send/<path:document>')
    @app.post('/api/library/grill/<path:document>')
    def send(document):
        def operation():
            documents().read(document)
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict) or set(payload) - {'chat'}:
                raise StateError('Choose a chat')
            return backend().library_send(document, payload.get('chat'), grill=request.path.startswith('/api/library/grill/'))
        return respond(operation)

    @app.route('/api/skills/<name>', methods=['GET', 'POST'])
    def skill(name):
        def operation():
            store = backend()
            if request.method == 'POST':
                payload = request.get_json(silent=True)
                if (not isinstance(payload, dict) or set(payload) != {'project', 'enabled'}
                        or not isinstance(payload['project'], str) or type(payload['enabled']) is not bool):
                    raise StateError('Provide a project and enabled boolean')
                store.skill_set(name, payload['project'], payload['enabled'])
            item = next((s for s in store.skill_list() if s['name'] == name), None)
            if item is None:
                raise StateError('Unknown skill')
            return dict(**item, markdown=instructions(name))
        return respond(operation)
