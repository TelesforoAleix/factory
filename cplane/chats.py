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
        elif stage == 'done':
            self.connection.execute('UPDATE cplane_sessions SET archived = true WHERE feature = %s', (item['feature'],))
