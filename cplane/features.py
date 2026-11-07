"""Postgres feature operations, using the store's locked transaction path."""
import re

from .state import StateError

STAGES = ('shortlist', 'grilling', 'ready', 'next', 'building', 'testing', 'done', 'parked')
TEXT_LIMIT = 16_000  # Same long-text bound as document notes.


def bounded(value, label, limit=200, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise StateError(f'{label} must not be empty')
    if len(value) > limit:
        raise StateError(f'{label} exceeds {limit} characters')
    if '\x00' in value:
        raise StateError(f'{label} contains a NUL character')
    return value


def stage_name(stage):
    if stage not in STAGES:
        raise StateError('Unknown feature stage; choose: ' + ', '.join(STAGES))


class FeatureStore:
    def _feature(self, identifier):
        row = self.connection.execute(
            'SELECT f.feature, f.id, f.project, f.title, f.stage, f.position, f.parked_from, f.backlog '
            'FROM cplane_feature_ids a JOIN cplane_features f ON f.feature = a.feature WHERE a.id = %s',
            (identifier,)).fetchone()
        if row is None:
            raise StateError(f'Feature not found: {identifier}')
        return dict(zip(('feature', 'id', 'project', 'title', 'stage', 'position', 'parked_from', 'backlog'), row))

    def _feature_number(self, project):
        row = self.connection.execute(
            'UPDATE cplane_projects SET feature_counter = feature_counter + 1 WHERE key = %s RETURNING feature_counter',
            (project,)).fetchone()
        if row is None:
            raise StateError(f'Project not found: {project}')
        return f'{project}-F{row[0]}'

    def _feature_position(self, project, stage):
        return self.connection.execute(
            'SELECT COALESCE(max(position) + 1, 0) FROM cplane_features WHERE project = %s AND stage = %s',
            (project, stage)).fetchone()[0]

    def _feature_event(self, feature, event, actor):
        bounded(actor, 'Actor')
        self.connection.execute('INSERT INTO cplane_feature_events (feature, event, actor) VALUES (%s, %s, %s)',
                                (feature, event, actor))

    def feature_add(self, project, title, *, stage='shortlist', actor='owner'):
        bounded(title, 'Title')
        stage_name(stage)
        with self.mutation():
            identifier = self._feature_number(project)
            feature = self.connection.execute(
                'INSERT INTO cplane_features (id, project, title, stage, position) VALUES (%s, %s, %s, %s, %s) RETURNING feature',
                (identifier, project, title, stage, self._feature_position(project, stage))).fetchone()[0]
            self.connection.execute('INSERT INTO cplane_feature_ids VALUES (%s, %s)', (identifier, feature))
            self._feature_event(feature, f'add {identifier}', actor)
            return self.feature_show(identifier)

    def feature_list(self, *, project=None, stage=None):
        if stage is not None:
            stage_name(stage)
        with self.locked():
            rows = self.connection.execute(
                'SELECT id FROM cplane_features WHERE (%s::text IS NULL OR project = %s) '
                'AND (%s::text IS NULL OR stage = %s) ORDER BY project, '
                "array_position(ARRAY['shortlist','grilling','ready','next','building','testing','done','parked'], stage), position",
                (project, project, stage, stage))
            return [self.feature_show(row[0]) for row in rows.fetchall()]

    def feature_show(self, identifier):
        with self.locked():
            item = self._feature(identifier)
            feature = item.pop('feature')
            item['aliases'] = [r[0] for r in self.connection.execute(
                'SELECT id FROM cplane_feature_ids WHERE feature = %s AND id <> %s ORDER BY id', (feature, item['id']))]
            item['sections'] = [dict(name=r[0], position=r[1], text=r[2]) for r in self.connection.execute(
                'SELECT name, position, text FROM cplane_feature_sections WHERE feature = %s ORDER BY position', (feature,))]
            return item

    def feature_stage(self, identifier, stage, *, actor='owner'):
        stage_name(stage)
        with self.mutation():
            item = self._feature(identifier)
            if stage != item['stage']:
                self.connection.execute(
                    'UPDATE cplane_features SET stage = %s, position = %s, parked_from = %s WHERE feature = %s',
                    (stage, self._feature_position(item['project'], stage),
                     item['stage'] if stage == 'parked' else None, item['feature']))
                self._feature_event(item['feature'], f'stage {stage}', actor)
            return self.feature_show(identifier)

    def feature_move(self, identifier, project, *, actor='owner'):
        with self.mutation():
            item = self._feature(identifier)
            if project != item['project']:
                new_id = self._feature_number(project)
                self.connection.execute('INSERT INTO cplane_feature_ids VALUES (%s, %s)', (new_id, item['feature']))
                self.connection.execute(
                    'UPDATE cplane_features SET id = %s, project = %s, position = %s WHERE feature = %s',
                    (new_id, project, self._feature_position(project, item['stage']), item['feature']))
                self._feature_event(item['feature'], f'move {item["id"]} to {new_id}', actor)
            return self.feature_show(identifier)

    def feature_section(self, identifier, section, text, *, actor='owner'):
        bounded(section, 'Section name')
        bounded(text, 'Section text', TEXT_LIMIT, empty=True)
        bounded(actor, 'Actor')
        with self.mutation():
            item = self._feature(identifier)
            feature = item['feature']
            row = self.connection.execute(
                'SELECT text FROM cplane_feature_sections WHERE feature = %s AND name = %s', (feature, section)).fetchone()
            if row is None or row[0] != text:
                self.connection.execute(
                    'INSERT INTO cplane_feature_sections (feature, name, position, text) '
                    'SELECT %s, %s, COALESCE(max(position) + 1, 0), %s FROM cplane_feature_sections WHERE feature = %s '
                    'ON CONFLICT (feature, name) DO UPDATE SET text = EXCLUDED.text', (feature, section, text, feature))
                self.connection.execute(
                    'INSERT INTO cplane_feature_revisions (feature, section, text, actor) VALUES (%s, %s, %s, %s)',
                    (feature, section, text, actor))
            return self.feature_show(identifier)

    def feature_history(self, identifier, section=None):
        with self.locked():
            item = self._feature(identifier)
            rows = self.connection.execute(
                'SELECT id, section, text, actor, time FROM cplane_feature_revisions '
                'WHERE feature = %s AND (%s::text IS NULL OR section = %s) ORDER BY id',
                (item['feature'], section, section))
            return [dict(id=r[0], section=r[1], text=r[2], actor=r[3], time=r[4].isoformat()) for r in rows]

    def feature_revert(self, identifier, revision, *, actor='owner'):
        with self.mutation():
            item = self._feature(identifier)
            row = self.connection.execute(
                'SELECT section, text FROM cplane_feature_revisions WHERE feature = %s AND id = %s',
                (item['feature'], revision)).fetchone()
            if row is None:
                raise StateError('Feature revision not found')
            bounded(actor, 'Actor')
            current = self.connection.execute(
                'SELECT text FROM cplane_feature_sections WHERE feature = %s AND name = %s',
                (item['feature'], row[0])).fetchone()
            if current is not None and current[0] == row[1]:
                # An explicit revert is an audit action even if already current.
                self.connection.execute(
                    'INSERT INTO cplane_feature_revisions (feature, section, text, actor) VALUES (%s, %s, %s, %s)',
                    (item['feature'], row[0], row[1], actor))
                return self.feature_show(identifier)
            return self.feature_section(identifier, row[0], row[1], actor=actor)

    def project_add(self, key, name, *, repository=None, actor='owner'):
        if not re.fullmatch(r'[A-Z]{3}', key):
            raise StateError('Project key must be three uppercase letters')
        bounded(name, 'Project name')
        bounded(actor, 'Actor')
        if repository is not None:
            bounded(repository, 'Repository')
        with self.mutation():
            if repository is not None and self.connection.execute(
                    'SELECT 1 FROM cplane_projects WHERE repository = %s', (repository,)).fetchone():
                raise StateError('Repository already has a project key')
            self.connection.execute('INSERT INTO cplane_projects (key, name, repository) VALUES (%s, %s, %s)',
                                    (key, name, repository))
            self.connection.execute('INSERT INTO cplane_project_events (project, actor) VALUES (%s, %s)', (key, actor))
        return dict(key=key, name=name, repository=repository)

    def feature_import_backlog(self, text, *, dry_run=False, actor='owner'):
        from psycopg.types.json import Jsonb
        from .backlog import parse
        with self.mutation():
            projects = list(self.connection.execute('SELECT key, repository FROM cplane_projects'))
            rows, report = parse(text, projects)
            if dry_run:
                return report
            if report['unparsed_rows'] or report['repositories_with_no_key']:
                raise StateError('Backlog import refused: unparsed rows or repositories without keys; run --dry-run')
            if self.connection.execute('SELECT 1 FROM cplane_features WHERE backlog IS NOT NULL LIMIT 1').fetchone():
                raise StateError('Backlog import refused: imported features already exist')
            for row in rows:
                item = self.feature_add(row['project'], row['title'], stage=row['stage'], actor=actor)
                self.connection.execute(
                    'UPDATE cplane_features SET backlog = %s, parked_from = %s WHERE id = %s',
                    (Jsonb(row['backlog']), 'shortlist' if row['stage'] == 'parked' else None, item['id']))
            return report

    def feature_export_snapshot(self):
        with self.locked():
            features = self.feature_list()
            repositories = dict(self.connection.execute('SELECT key, repository FROM cplane_projects'))
            for feature in features:
                feature['repository'] = repositories[feature['project']] or '—'
            return features
