"""Storage implementations; the state module remains the public command facade."""
from contextlib import contextmanager, nullcontext
import fcntl
from importlib.resources import files
import json
import os
from pathlib import Path
from typing import Protocol, ContextManager

from . import state


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


class PostgresStore:
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
            self.connection.execute('DELETE FROM cplane_slices')
            with self.connection.cursor() as cursor:
                cursor.executemany('INSERT INTO cplane_slices (id, position, document) VALUES (%s, %s, %s)',
                                   [(item['id'], i, Jsonb(item)) for i, item in enumerate(data['slices'])])
            self.append_notices(notices)

    def append_notices(self, notices, *, ensure_ascii=False):
        with self.mutation():
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
