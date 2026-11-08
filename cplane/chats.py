"""Chat records on the store's serialized transaction path; never launches a CLI."""
from .features import bounded
from .state import StateError

KINDS = ('orchestrator', 'project', 'feature', 'legacy')


def public_chat_result(value):
    if isinstance(value, dict):
        return {k: public_chat_result(v) for k, v in value.items() if k not in ('cli_session_id', 'workspace_ready')}
    if isinstance(value, list):
        return [public_chat_result(v) for v in value]
    return value


class ChatStore:
    def chats(self, *, kind=None, project=None, archived=None):
        if kind is not None and kind not in KINDS:
            raise StateError('Unknown chat kind')
        if archived is not None and type(archived) is not bool:
            raise StateError('Archived must be a boolean')
        return [chat for chat in self.sessions()
                if (kind is None or chat['kind'] == kind)
                and (project is None or chat['project'] == project)
                and (archived is None or chat['archived'] == archived)]

    def chat_show(self, chat_id):
        chats = self.sessions(session_id=chat_id)
        if not chats:
            raise StateError('Chat not found')
        return chats[0]

    def chat_read(self, chat_id, *, unread=False):
        if type(unread) is not bool:
            raise StateError('Unread must be a boolean')
        with self.mutation():
            self.chat_show(chat_id)
            self.connection.execute(
                'UPDATE cplane_sessions SET last_read_at = %s WHERE id = %s',
                (None if unread else self.connection.execute('SELECT clock_timestamp()').fetchone()[0], chat_id))
            return self.chat_show(chat_id)

    def chat_open(self, chat_id):
        with self.mutation():
            chat = self.chat_read(chat_id)
            return dict(chat=chat, messages=self.session_messages(chat['area'], chat_id))

    def chat_defaults(self, kind=None, *, chat_tool=None, chat_model=None):
        if kind is not None and kind not in KINDS:
            raise StateError('Unknown chat kind')
        with self.mutation():
            if chat_tool is not None or chat_model is not None:
                if kind is None:
                    raise StateError('Choose a chat kind')
                current = self.chat_defaults(kind)[kind]
                tool = current['chat_tool'] if chat_tool is None else chat_tool
                model = current['chat_model'] if chat_model is None else chat_model
                self._chat_fields(tool, model)
                self.connection.execute(
                    'UPDATE cplane_chat_settings SET chat_tool = %s, chat_model = %s WHERE kind = %s',
                    (tool, model, kind))
            return {r[0]: dict(chat_tool=r[1], chat_model=r[2]) for r in self.connection.execute(
                'SELECT kind, chat_tool, chat_model FROM cplane_chat_settings '
                'WHERE (%s::text IS NULL OR kind = %s) ORDER BY kind', (kind, kind))}

    @staticmethod
    def _chat_fields(tool, model):
        from .stores import validate_session
        try:
            validate_session(dict(title='Chat', tool=tool, model=model), 'factory')
        except ValueError:
            raise StateError('Invalid chat tool or model') from None

    def chat_configure(self, chat_id, *, tool=None, model=None):
        with self.mutation():
            chat = self.chat_show(chat_id)
            tool = chat['tool'] if tool is None else tool
            model = chat['model'] if model is None else model
            self._chat_fields(tool, model)
            if chat['state'] == 'running':
                raise StateError('Chat has a running turn')
            cli_id = chat['cli_session_id']
            if tool != chat['tool']:
                saved = self.connection.execute(
                    'SELECT tool_sessions FROM cplane_sessions WHERE id = %s', (chat_id,)).fetchone()[0]
                cli_id = saved.get(tool)
            self.connection.execute(
                'UPDATE cplane_sessions SET tool = %s, model = %s, cli_session_id = %s WHERE id = %s',
                (tool, model, cli_id, chat_id))
            return self.chat_show(chat_id)

    def _project_repositories(self, project):
        from .stores import REPOSITORY
        row = self.connection.execute('SELECT repository FROM cplane_projects WHERE key = %s', (project,)).fetchone()
        if row is None:
            raise StateError('Unknown project')
        if row[0] is None:
            return []
        repository = row[0]
        if not REPOSITORY.fullmatch(repository) and not (
                '/' not in repository and REPOSITORY.fullmatch('owner/' + repository)):
            raise StateError('Invalid project repository')
        return self.resolve_chat_repositories([repository])

    def resolve_chat_repositories(self, repositories):
        """Use existing Factory records as evidence, never invent an owner.

        Plain names remain valid records when no unambiguous owner is known.
        The turn claimer resolves them again before preparing a workspace.
        """
        from .stores import REPOSITORY
        known = {}
        for (values,) in self.connection.execute(
                "SELECT repositories FROM cplane_sessions WHERE area = 'factory' ORDER BY id"):
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, str) and REPOSITORY.fullmatch(value):
                        known.setdefault(value.lower(), value)
        owners = {}
        for value in known.values():
            owner = value.split('/')[0]
            owners.setdefault(owner.lower(), owner)
        for (value,) in self.connection.execute("SELECT document->>'repo' FROM cplane_slices ORDER BY position"):
            if isinstance(value, str) and REPOSITORY.fullmatch(value):
                owner = value.split('/')[0]
                owners.setdefault(owner.lower(), owner)
        result = []
        for repository in repositories:
            if REPOSITORY.fullmatch(repository):
                result.append(repository)
                continue
            matches = [value for value in known.values()
                       if value.split('/')[1].lower() == repository.lower()]
            if len(matches) == 1:
                result.append(matches[0])
            elif not matches and len(owners) == 1:
                result.append(next(iter(owners.values())) + '/' + repository)
            else:
                result.append(repository)
        return result

    def _create_chat(self, kind, title, *, project=None, feature=None):
        from psycopg.types.json import Jsonb
        defaults = self.chat_defaults(kind)[kind]
        repositories = self._project_repositories(project) if project else []
        return self.connection.execute(
            'INSERT INTO cplane_sessions (area, title, tool, model, repositories, kind, project, feature) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id',
            ('homelab' if kind == 'orchestrator' else 'factory', title,
             defaults['chat_tool'], defaults['chat_model'], Jsonb(repositories), kind, project, feature)).fetchone()[0]

    def create_project_chat(self, project):
        with self.mutation():
            if self.connection.execute(
                    "SELECT 1 FROM cplane_sessions WHERE kind = 'project' AND project = %s", (project,)).fetchone():
                raise StateError('Project already has a chat')
            chat_id = self._create_chat('project', project, project=project)
            return self.chat_show(chat_id)

    def system_message(self, chat_id, text):
        bounded(text, 'System message', 32000)
        with self.mutation():
            chat = self.chat_show(chat_id)
            if chat['state'] == 'failed':
                raise StateError('Chat failed')
            return self.connection.execute(
                "INSERT INTO cplane_session_messages (session, role, text, status, automatic) "
                "VALUES (%s, 'system', %s, 'queued', true) RETURNING id", (chat_id, text)).fetchone()[0]

    def _feature_chat_stage(self, item, stage):
        """Called within the feature mutation, so failure rolls back its stage too."""
        if stage == 'grilling':
            if self.connection.execute('SELECT 1 FROM cplane_sessions WHERE feature = %s',
                                       (item['feature'],)).fetchone():
                return
            chat_id = self._create_chat('feature', item['title'], project=item['project'], feature=item['feature'])
            feature = self.feature_show(item['id'])
            text = f"Feature: {feature['id']}\nTitle: {feature['title']}\nProject: {feature['project']}\n\n"
            text += '\n\n'.join(f"## {s['name']}\n\n{s['text']}" for s in feature['sections'])
            text += '\n\nRun the grill for this feature.'
            # Feature sections are individually bounded, but their total is not.
            # Preserve every section in the opening event rather than truncating.
            self.connection.execute(
                "INSERT INTO cplane_session_messages (session, role, text, status, automatic) "
                "VALUES (%s, 'system', %s, 'queued', true)", (chat_id, text))
        elif stage == 'testing':
            linked = ', '.join(s['id'] for s in self._linked_slices(item['feature']))
            self._chat_event(item['feature'], None, 'testing', f"Feature {item['id']} entered Testing.\nSlices: {linked}\nRead the testing-review skill. Check installs and handovers, save the next numbered Testing review section, and ask the owner to test in open text.")
        elif stage == 'done':
            self.connection.execute('UPDATE cplane_sessions SET archived = true WHERE feature = %s', (item['feature'],))

    def _chat_event(self, feature, slice_id, kind, text, since=None, source=None):
        self.connection.execute(
            'INSERT INTO cplane_chat_events (feature, slice_id, kind, text, attention_since, source) '
            'VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (source) DO NOTHING',
            (feature, slice_id, kind, text, since, source))

    def capture_chat_events(self, data):
        """Capture transitions atomically, including planner-originated changes."""
        from .installation import installable, install_failure
        old = {r[0]: r[1] for r in self.connection.execute('SELECT id, document FROM cplane_slices')}
        for item in data['slices']:
            link = self.connection.execute('SELECT feature FROM cplane_feature_ids WHERE id = %s',
                                           (item.get('feature_id'),)).fetchone()
            if not link or link[0] is None:
                continue
            before = old.get(item['id'], {})
            attention = item['attention']
            previous = before.get('attention')
            if (attention and (attention['kind'] in ('question', 'escalation') or
                                   (attention['kind'] == 'node-step' and installable(item)))
                    and not install_failure(attention)
                    and attention['answer'] is None
                    and (not previous or any(attention[k] != previous[k] for k in ('kind', 'since', 'body')))):
                self._chat_event(link[0], item['id'], attention['kind'], attention['body'], attention['since'])
            if item['state'] == 'in review' and before.get('state') != 'in review':
                self.chat_handover(item, f"Handover ready for review against brief {item['brief']}.\nPR: {item['pr']}")

    def chat_can_take(self, chat_id):
        """Called under the store lock both at routing and at turn claim."""
        from .times import now
        count, paused, title = self.connection.execute(
            'SELECT auto_turns, auto_paused, title FROM cplane_sessions WHERE id = %s', (chat_id,)).fetchone()
        if paused:
            return False
        if count < self.limit_show()['chat_auto_turns']:
            return True
        self.connection.execute('UPDATE cplane_sessions SET auto_paused = true WHERE id = %s', (chat_id,))
        self.append_notices([dict(at=now().isoformat(), id=f'chat:{chat_id}', chat=chat_id,
                                 event='chat-paused', text=f'{title}: Chat paused after automatic turns; write a message to continue.')])
        return False

    def route_chat_events(self):
        """Runner delivery, serialized with slice writes and owner messages."""
        with self.mutation():
            rows = self.connection.execute(
                'SELECT id, feature, slice_id, kind, text, attention_since FROM cplane_chat_events '
                'WHERE NOT delivered ORDER BY id').fetchall()
            from .text_bounds import cut
            items = {s['id']: s for s in self.load()['slices']} if rows else {}
            for event_id, feature, slice_id, kind, text, since in rows:
                if slice_id and kind in ('question', 'escalation', 'node-step'):
                    from .installation import installable, install_failure
                    item = items.get(slice_id)
                    attention = item['attention'] if item else None
                    if (not attention or attention['answer'] is not None or
                            (attention['kind'], attention['since'], attention['body']) != (kind, since, text) or
                            install_failure(attention) or (kind == 'node-step' and not installable(item))):
                        self.connection.execute('UPDATE cplane_chat_events SET delivered = true WHERE id = %s', (event_id,))
                        continue
                row = self.connection.execute(
                    "SELECT s.id, s.state, s.archived FROM cplane_sessions s JOIN cplane_features f ON f.feature = %s "
                    "WHERE (s.kind = 'feature' AND s.feature = f.feature) "
                    "OR (s.kind = 'project' AND s.project = f.project) OR s.kind = 'orchestrator' "
                    "ORDER BY CASE s.kind WHEN 'feature' THEN 0 WHEN 'project' THEN 1 ELSE 2 END LIMIT 1",
                    (feature,)).fetchone()
                if not row or row[1] == 'failed' or row[2] or not self.chat_can_take(row[0]):
                    continue
                chat_id = row[0]
                message = f'Event: {kind}\nSlice: {slice_id or "(feature event)"}\n\n{text}'
                self.system_message(chat_id, cut(message, 32000))
                self.connection.execute('UPDATE cplane_chat_events SET delivered = true, chat = %s WHERE id = %s',
                                        (chat_id, event_id))

    def chat_attention(self, item):
        """Attention projection with durable chat ownership; state v1 stays intact."""
        attention = item['attention']
        from .installation import install_failure
        if not attention or install_failure(attention) or attention['kind'] not in ('question', 'escalation'):
            return attention
        with self.locked():
            row = self.connection.execute(
                'SELECT chat FROM cplane_chat_events WHERE feature = '
                '(SELECT feature FROM cplane_feature_ids WHERE id = %s) AND slice_id = %s AND kind = %s '
                'AND attention_since = %s AND text = %s AND delivered ORDER BY id DESC LIMIT 1',
                (item.get('feature_id'), item['id'], attention['kind'], attention['since'], attention['body'])).fetchone()
            return dict(attention, chat_id=row[0]) if row else attention

    def chat_handover(self, item, text):
        import hashlib
        import json
        link = self.connection.execute('SELECT feature FROM cplane_feature_ids WHERE id = %s',
                                       (item.get('feature_id'),)).fetchone()
        if link and link[0] is not None:
            from .text_bounds import cut
            text = f"Brief: {item['brief']}\nPR: {item['pr']}\n\n" + cut(text, 28000)
            source = hashlib.sha256(json.dumps([item['id'], item['log']]).encode()).hexdigest()
            self._chat_event(link[0], item['id'], 'in review', text, source=source)

    def finish_testing_review(self, turn):
        """A completed review reply starts one durable wait per Testing entry.

        Reading the chat does not acknowledge testing; only an owner message or
        leaving this Testing entry does. Notices also serve the existing bot outbox.
        """
        chat_id = turn['session']['id']
        rows = self.connection.execute(
            "SELECT e.id, f.id, f.title FROM cplane_chat_events e "
            "JOIN cplane_features f ON f.feature = e.feature "
            "WHERE e.kind = 'testing' AND e.delivered AND e.chat = %s AND f.stage = 'testing' "
            "AND e.id = (SELECT max(x.id) FROM cplane_chat_events x WHERE x.feature = e.feature AND x.kind = 'testing') "
            "AND EXISTS (SELECT 1 FROM cplane_feature_revisions r WHERE r.feature = f.feature "
            "AND r.section ~ '^Testing review [1-9][0-9]*$' AND r.time >= e.at "
            "AND NOT EXISTS (SELECT 1 FROM cplane_feature_revisions prior WHERE prior.feature = r.feature "
            "AND prior.section = r.section AND prior.time < e.at)) "
            "AND NOT EXISTS (SELECT 1 FROM cplane_notices n WHERE n.document->>'event' = 'testing-review' "
            "AND n.document->>'review_event' = e.id::text)", (chat_id,)).fetchall()
        from .times import now
        for event_id, feature_id, title in rows:
            self.append_notices([dict(at=now().isoformat(), id=feature_id, event='testing-review',
                review_event=event_id, chat=chat_id, message=turn['id'],
                text=f'{feature_id}: {title}: Testing review ready. Test and reply in the chat.')])

    def testing_review_waits(self):
        with self.locked():
            rows = self.connection.execute(
                "SELECT n.document, f.id, f.project, f.title FROM cplane_notices n "
                "JOIN cplane_chat_events e ON e.id::text = n.document->>'review_event' "
                "JOIN cplane_features f ON f.feature = e.feature "
                "WHERE n.document->>'event' = 'testing-review' AND f.stage = 'testing' "
                "AND e.id = (SELECT max(x.id) FROM cplane_chat_events x WHERE x.feature = f.feature AND x.kind = 'testing') "
                "AND NOT EXISTS (SELECT 1 FROM cplane_session_messages m WHERE m.session = e.chat "
                "AND m.role = 'owner' AND m.id > (n.document->>'message')::bigint)").fetchall()
            return [dict(kind='testing-review', id=identifier, project=project, title=title,
                         since=notice['at'], chat=notice['chat'], text=notice['text'])
                    for notice, identifier, project, title in rows]
