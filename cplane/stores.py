"""Storage implementations; the state module remains the public command facade."""
from contextlib import contextmanager, nullcontext
import fcntl
from importlib.resources import files
import json
import os
import re
from pathlib import Path
from typing import Protocol, ContextManager

from . import state
from .features import FeatureStore
from .run_records import RunRecordStore
from .skills import SkillStore
from .chats import ChatStore
from .library import LibraryStore


class Store(Protocol):
    def locked(self) -> ContextManager: ...
    def mutation(self) -> ContextManager: ...
    def load(self) -> dict: ...
    def save(self, data, notices=()) -> None: ...
    def append_notices(self, notices, *, ensure_ascii=False) -> None: ...
    def notices(self, after=0) -> list: ...
    def snapshot(self): ...
    def size(self) -> int: ...
    def commit(self, command, slice_id) -> None: ...


class FileStore:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.outbox = Path(str(self.path) + '.outbox.jsonl')

    @contextmanager
    def locked(self):
        # Stable inode: the state file itself is replaced on every save.
        with Path(str(self.path) + '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield self

    def mutation(self):
        return nullcontext()

    def load(self):
        return state._file_load(self.path)

    def save(self, data, notices=()):
        state._file_save(self.path, data)
        self.append_notices(notices)

    def append_notices(self, notices, *, ensure_ascii=False):
        if not notices:
            return
        with self.outbox.open('a') as stream:
            for notice in notices:
                stream.write(json.dumps(notice, ensure_ascii=ensure_ascii) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def notices(self, after=0):
        if not self.outbox.exists():
            return []
        return [(i, json.loads(line)) for i, line in enumerate(self.outbox.read_text().splitlines(), 1) if i > after]

    def snapshot(self):
        return self.path.read_bytes(), self.outbox.read_bytes() if self.outbox.exists() else None

    def size(self):
        return self.path.stat().st_size

    def commit(self, command, slice_id):
        state._file_commit(self.path, self.outbox, command, slice_id)


# One scheduler per database. All writers and runner passes take this same
# transaction-scoped lock, including migration/import. It needs no sentinel row.
LOCK_KEY = 0x43504C414E45


class PostgresStore(FeatureStore, RunRecordStore, SkillStore, ChatStore, LibraryStore):
    def __init__(self, url):
        if not url:
            raise state.StateError("Postgres connection failed")
        global psycopg, Jsonb
        try:
            import psycopg
            from psycopg.types.json import Jsonb
        except ImportError:
            raise state.StateError('Postgres requires psycopg 3 and system libpq') from None
        self._url = url
        self.connection = None

    @contextmanager
    def locked(self):
        if self.connection is not None:
            try:
                yield self
            except psycopg.Error:
                raise state.StateError('Postgres operation failed') from None
            return
        # libpq diagnostics may contain the entire DSN or password. Never expose
        # them, even as exception context, to CLI or runner failure persistence.
        try:
            connection = psycopg.connect(self._url)
        except (psycopg.Error, ValueError):
            raise state.StateError('Postgres connection failed') from None
        try:
            with connection:
                self.connection = connection
                connection.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_KEY,))
                yield self
        except psycopg.Error:
            raise state.StateError('Postgres operation failed') from None
        finally:
            self.connection = None

    @contextmanager
    def mutation(self):
        with self.locked():
            try:
                # Recover an individual failed order without aborting the pass.
                with self.connection.transaction():
                    yield
            except psycopg.Error:
                raise state.StateError('Postgres operation failed') from None

    def load(self):
        with self.locked():
            data = {'version': 1, 'slices': [row[0] for row in self.connection.execute(
                'SELECT document FROM cplane_slices ORDER BY position')]}
            state.validate(data)
            return data

    def save(self, data, notices=()):
        state.validate(data)
        with self.mutation():
            self.capture_chat_events(data)
            self.connection.execute('DELETE FROM cplane_slices')
            with self.connection.cursor() as cursor:
                cursor.executemany('INSERT INTO cplane_slices (id, position, document) VALUES (%s, %s, %s)',
                                   [(item['id'], i, Jsonb(item)) for i, item in enumerate(data['slices'])])
            self.append_notices(notices)

    def append_notices(self, notices, *, ensure_ascii=False):
        with self.mutation():
            # Suppress only notices for an event actually taken in this transaction.
            # Previously exported notices remain append-only.
            retained = []
            for notice in notices:
                owner_install = (notice.get('event') == 'escalation' and
                                 notice.get('text', '').startswith(('Install ', 'escalation: Install ')))
                taken = not owner_install and notice.get('event') in ('question', 'escalation') and self.connection.execute(
                    'SELECT 1 FROM cplane_chat_events WHERE slice_id = %s AND attention_since = %s '
                    'AND kind = %s AND delivered AND chat IS NOT NULL LIMIT 1',
                    (notice.get('id'), notice.get('at'), notice.get('event'))).fetchone()
                if not taken:
                    retained.append(notice)
            notices = retained
            with self.connection.cursor() as cursor:
                cursor.executemany('INSERT INTO cplane_notices (document) VALUES (%s)',
                                   [(Jsonb(notice),) for notice in notices])

    def notices(self, after=0):
        with self.locked():
            return list(self.connection.execute(
                'SELECT id, document FROM cplane_notices WHERE id > %s ORDER BY id', (after,)))

    def snapshot(self):
        with self.locked():
            return self.load(), self.notices()

    def size(self):
        return len((json.dumps(self.load(), indent=2, ensure_ascii=False) + '\n').encode())

    def commit(self, command, slice_id):
        pass

    def migrate(self):
        with self.locked():
            self.connection.execute('CREATE TABLE IF NOT EXISTS cplane_migrations (name text PRIMARY KEY)')
            directory = files('cplane').joinpath('migrations')
            for migration in sorted(directory.iterdir(), key=lambda p: p.name):
                if not migration.name.endswith('.sql'):
                    continue
                applied = self.connection.execute('SELECT 1 FROM cplane_migrations WHERE name = %s', (migration.name,)).fetchone()
                if not applied:
                    self.connection.execute(migration.read_text())
                    self.connection.execute('INSERT INTO cplane_migrations VALUES (%s)', (migration.name,))

    def import_file(self, path):
        source = FileStore(path)
        data, notices = source.load(), source.notices()
        with self.mutation():
            if self.connection.execute('SELECT EXISTS (SELECT 1 FROM cplane_slices) OR EXISTS (SELECT 1 FROM cplane_notices)').fetchone()[0]:
                raise state.StateError('import requires an empty database')
            self.save(data, [notice for _, notice in notices])

    def sessions(self, area=None, session_id=None):
        with self.locked():
            rows = self.connection.execute(
                'SELECT id, area, title, tool, model, state, cli_session_id, repositories, '
                'skill_names, skill_version, kind, project, (SELECT f.id FROM cplane_features f WHERE f.feature = s.feature) AS feature, archived, last_read_at, workspace_ready, auto_turns, auto_paused, '
                "EXISTS (SELECT 1 FROM cplane_session_messages m WHERE m.session = s.id AND m.role = 'assistant' "
                'AND (s.last_read_at IS NULL OR m.time > s.last_read_at)) AS waiting '
                'FROM cplane_sessions s WHERE (%s::text IS NULL OR area = %s) '
                'AND (%s::bigint IS NULL OR s.id = %s) ORDER BY s.id',
                (area, area, session_id, session_id))
            keys = ('id', 'area', 'title', 'tool', 'model', 'state', 'cli_session_id', 'repositories', 'skill_names', 'skill_version',
                    'kind', 'project', 'feature', 'archived', 'last_read_at', 'workspace_ready', 'auto_turns', 'auto_paused', 'waiting')
            result = [dict(zip(keys, row)) for row in rows]
            for chat in result:
                if chat['last_read_at'] is not None:
                    chat['last_read_at'] = chat['last_read_at'].isoformat()
            return result

    def create_session(self, area, title, tool, model, repositories):
        title, tool, model, repositories = validate_session(
            dict(title=title, tool=tool, model=model, repositories=repositories), area)
        with self.mutation():
            return self.connection.execute(
                'INSERT INTO cplane_sessions (area, title, tool, model, repositories) '
                'VALUES (%s, %s, %s, %s, %s) RETURNING id',
                (area, title, tool, model, Jsonb(repositories))).fetchone()[0]

    def session_messages(self, area, session_id, text=None):
        with self.mutation():
            sessions = self.sessions(area, session_id)
            if not sessions:
                raise state.StateError('Session not found')
            if text is not None:
                from .features import bounded
                bounded(text, 'Message', 32000)
                if sessions[0]['state'] == 'failed':
                    raise state.StateError('Session failed; create a new session')
                self.connection.execute(
                    "INSERT INTO cplane_session_messages (session, role, text, status) VALUES (%s, 'owner', %s, 'queued')",
                    (session_id, text))
                self.connection.execute('UPDATE cplane_sessions SET auto_turns = 0, auto_paused = false WHERE id = %s', (session_id,))
            rows = self.connection.execute(
                'SELECT id, role, text, status, time, automatic FROM cplane_session_messages WHERE session = %s ORDER BY id',
                (session_id,))
            return [dict(id=r[0], role=r[1], text=r[2], status=r[3], time=r[4].isoformat(), automatic=r[5]) for r in rows]

    def document_notes(self, document, text=None):
        with self.mutation():
            if text is not None:
                self.connection.execute(
                    'INSERT INTO cplane_document_notes (document, text) VALUES (%s, %s)',
                    (document, text))
            rows = self.connection.execute(
                'SELECT id, text, time FROM cplane_document_notes WHERE document = %s ORDER BY id',
                (document,))
            return [dict(id=r[0], text=r[1], time=r[2].isoformat()) for r in rows]

    def send_document_note(self, document, note_id, session_id):
        with self.mutation():
            row = self.connection.execute(
                'SELECT text FROM cplane_document_notes WHERE document = %s AND id = %s',
                (document, note_id)).fetchone()
            if row is None:
                raise state.StateError('Note not found')
            return self.session_messages('homelab', session_id,
                                         f'Owner note on {document}:\n\n{row[0]}')

    def create_grill(self, fields, message):
        with self.mutation():
            sid = self.create_session('homelab', *fields)
            self.session_messages('homelab', sid, message)
            return sid

    def claim_session_turn(self):
        with self.mutation():
            if self.connection.execute("SELECT count(*) FROM cplane_session_messages WHERE status = 'running'").fetchone()[0] >= 2:
                return None
            rows = self.connection.execute(
                "SELECT m.id, m.session, m.text, s.area, m.role, m.automatic FROM cplane_session_messages m "
                "JOIN cplane_sessions s ON s.id = m.session WHERE m.status = 'queued' AND m.role IN ('owner', 'system') "
                "AND s.state = 'idle' AND (NOT s.archived OR m.role = 'owner') "
                "ORDER BY (m.role = 'owner') DESC, m.id").fetchall()
            active = {repository.lower() for chat in self.sessions() if chat['state'] == 'running'
                      for repository in chat['repositories']}
            for row in rows:
                session = self.sessions(row[3], row[1])[0]
                if row[5] and not self.chat_can_take(session['id']):
                    continue
                repositories = self.resolve_chat_repositories(session['repositories'])
                if any(not REPOSITORY.fullmatch(r) for r in repositories):
                    self.connection.execute("UPDATE cplane_session_messages SET status = 'failed' WHERE id = %s", (row[0],))
                    self.connection.execute(
                        "INSERT INTO cplane_session_messages (session, role, text, status, automatic) "
                        "VALUES (%s, 'system', 'Repository is unknown; cannot run this message.', 'done', true)",
                        (row[1],))
                    continue
                if any(r.lower() in active for r in repositories):
                    continue
                if repositories != session['repositories']:
                    self.connection.execute('UPDATE cplane_sessions SET repositories = %s WHERE id = %s',
                                            (Jsonb(repositories), session['id']))
                    session['repositories'] = repositories
                break
            else:
                return None
            if session['skill_names'] is None and not (session['cli_session_id'] or session['workspace_ready']):
                names, version = self.session_skills(session['repositories'])
                self.connection.execute(
                    'UPDATE cplane_sessions SET skill_names = %s, skill_version = %s WHERE id = %s',
                    (Jsonb(names), version, session['id']))
                session.update(skill_names=names, skill_version=version)
            if row[5]:
                self.connection.execute('UPDATE cplane_sessions SET auto_turns = auto_turns + 1 WHERE id = %s', (row[1],))
            else:
                self.connection.execute('UPDATE cplane_sessions SET auto_turns = 0, auto_paused = false WHERE id = %s', (row[1],))
            self.connection.execute("UPDATE cplane_session_messages SET status = 'running' WHERE id = %s", (row[0],))
            self.connection.execute("UPDATE cplane_sessions SET state = 'running' WHERE id = %s", (row[1],))
            owner_message = self.connection.execute(
                "SELECT max(id) FROM cplane_session_messages WHERE session = %s AND role = 'owner'",
                (row[1],)).fetchone()[0]
            return dict(id=row[0], session=session, text=row[2], role=row[4], automatic=row[5],
                        owner_message=owner_message)

    def finish_session_turn(self, turn, reply, cli_id=None, failed=False, *,
                            planning_commits=(), delivery_notice=None):
        with self.mutation():
            status = 'failed' if failed else 'done'
            self.connection.execute('UPDATE cplane_session_messages SET status = %s WHERE id = %s', (status, turn['id']))
            self.connection.execute(
                "INSERT INTO cplane_session_messages (session, role, text, status, automatic) VALUES (%s, 'assistant', %s, %s, %s)",
                (turn['session']['id'], reply, status, failed))
            for notice in ([delivery_notice] if delivery_notice else []) + [
                    'Planning pushed commit ' + commit for commit in planning_commits]:
                self.connection.execute(
                    "INSERT INTO cplane_session_messages (session, role, text, status, automatic) VALUES (%s, 'assistant', %s, 'done', true)",
                    (turn['session']['id'], notice))
            self.connection.execute(
                'UPDATE cplane_sessions SET state = %s, cli_session_id = COALESCE(%s, cli_session_id), '
                'workspace_ready = workspace_ready OR %s::text IS NOT NULL, '
                'tool_sessions = CASE WHEN %s::text IS NULL THEN tool_sessions '
                'ELSE jsonb_set(tool_sessions, ARRAY[tool], to_jsonb(%s::text)) END WHERE id = %s',
                ('failed' if failed else 'idle', cli_id, cli_id, cli_id, cli_id, turn['session']['id']))
            if not failed:
                self.finish_testing_review(turn)
            self.chat_can_take(turn['session']['id'])
            if failed:
                self.connection.execute("UPDATE cplane_session_messages SET status = 'failed' WHERE session = %s AND status = 'queued'",
                                        (turn['session']['id'],))

    def interrupted_session_turns(self):
        with self.locked():
            rows = list(self.connection.execute(
                "SELECT m.id, s.id, s.area, m.text FROM cplane_session_messages m JOIN cplane_sessions s ON s.id = m.session WHERE m.status = 'running'"))
            return [dict(id=r[0], session=self.sessions(r[2], r[1])[0], text=r[3]) for r in rows]


REPOSITORY = re.compile(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*')


def validate_session(payload, area):
    if area not in ('homelab', 'factory') or not isinstance(payload, dict):
        raise ValueError('Invalid session')
    title, tool, model = (payload.get(key) for key in ('title', 'tool', 'model'))
    repositories = payload.get('repositories', [])
    if (not isinstance(title, str) or not title.strip() or len(title) > 200
            or tool not in ('codex', 'claude') or not isinstance(model, str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}', model)
            or not isinstance(repositories, list) or len(repositories) > 20
            or any(not isinstance(r, str) or not REPOSITORY.fullmatch(r) for r in repositories)
            or len({r.split('/')[1] for r in repositories}) != len(repositories)):
        raise ValueError('Invalid session fields')
    return title.strip(), tool, model, repositories
