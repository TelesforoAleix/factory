"""Library comments and delivery; all writes share the scheduler transaction lock."""
from .features import bounded
from .state import StateError


def batch_message(document, drafts):
    return f'Comments on document: {document}\n\n' + '\n\n'.join(
        f'Comment {i}:\nQuote: {c["selector"]["exact"]}\nComment: {c["text"]}' for i, c in enumerate(drafts, 1))


class LibraryStore:
    def library_projects(self):
        with self.locked():
            return [dict(key=k, name=n, repository=r, active=a) for k, n, r, a in self.connection.execute(
                'SELECT key, name, repository, active FROM cplane_projects ORDER BY key')]

    def document_receiver(self, document, chat_id=None):
        if chat_id is not None and (type(chat_id) is not int or chat_id < 1):
            raise StateError('Choose a chat')
        with self.locked():
            if chat_id is None:
                folder = document.split('/')[0] if '/' in document else None
                row = self.connection.execute(
                    "SELECT s.id FROM cplane_sessions s LEFT JOIN cplane_projects p ON p.key = s.project "
                    "WHERE NOT s.archived AND (s.kind = 'orchestrator' OR "
                    "(s.kind = 'project' AND split_part(p.repository, '/', -1) = %s)) "
                    "ORDER BY (s.kind = 'project') DESC, s.id LIMIT 1", (folder,)).fetchone()
                if not row:
                    raise StateError('No receiving chat available')
                chat_id = row[0]
            chat = self.chat_show(chat_id)
            if chat['archived']:
                raise StateError('Choose a non-archived chat')
            if chat['state'] == 'failed':
                raise StateError('Chat failed')
            return chat

    def document_comments(self, document, payload=None):
        from factory_ui.documents import document_path
        document_path(document)
        with self.mutation():
            if payload is not None:
                if not isinstance(payload, dict) or set(payload) != {'text', 'selector'}:
                    raise StateError('Provide a comment and a text quote selector')
                bounded(payload['text'], 'Comment', 16000)
                selector = payload['selector']
                if not isinstance(selector, dict) or set(selector) != {'type', 'exact', 'prefix', 'suffix'} or selector['type'] != 'TextQuoteSelector':
                    raise StateError('Invalid text quote selector')
                bounded(selector['exact'], 'Quote', 16000)
                for key in ('prefix', 'suffix'):
                    if not isinstance(selector[key], str) or len(selector[key]) > 256 or '\x00' in selector[key]:
                        raise StateError('Invalid quote context')
                drafts = [c for c in self.document_comments(document) if not c['sent_at']]
                bounded(batch_message(document, drafts + [payload]), 'Draft batch (send existing drafts first)', 32000)
                self.connection.execute(
                    'INSERT INTO cplane_document_comments (document, quote, prefix, suffix, text) VALUES (%s,%s,%s,%s,%s)',
                    (document, selector['exact'], selector['prefix'], selector['suffix'], payload['text']))
            rows = self.connection.execute(
                'SELECT c.id, c.quote, c.prefix, c.suffix, c.text, c.time, c.sent_at, c.chat, s.title, c.legacy_note '
                'FROM cplane_document_comments c LEFT JOIN cplane_sessions s ON s.id = c.chat '
                'WHERE c.document = %s ORDER BY c.id', (document,))
            return [dict(id=r[0], selector=(dict(type='TextQuoteSelector', exact=r[1], prefix=r[2], suffix=r[3]) if r[1] else None),
                         text=r[4], time=r[5].isoformat(), sent_at=r[6].isoformat() if r[6] else None,
                         chat=r[7], chat_title=r[8], imported=r[9] is not None) for r in rows]

    def library_send(self, document, chat_id=None, *, grill=False):
        from factory_ui.documents import document_path
        document_path(document)
        with self.mutation():
            chat = self.document_receiver(document, chat_id)
            drafts = [c for c in self.document_comments(document) if not c['sent_at']]
            if grill:
                text = f'Use the grilling skill to grill this document. Read planning/{document}. Ask one question at a time.'
            else:
                if not drafts:
                    raise StateError('No draft comments to send')
                text = batch_message(document, drafts)
            bounded(text, 'Batch message (send fewer or shorter comments)', 32000)
            messages = self.session_messages(chat['area'], chat['id'], text)
            message = messages[-1]['id']
            if not grill:
                self.connection.execute(
                    'UPDATE cplane_document_comments SET sent_at = clock_timestamp(), chat = %s, message = %s '
                    'WHERE document = %s AND sent_at IS NULL', (chat['id'], message, document))
            return dict(chat=chat['id'], message=message, comments=self.document_comments(document))
