"""Postgres feature operations, using the store's locked transaction path."""
import re
from datetime import datetime

from .state import StateError
from .times import now

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


MOVES = {
    ('shortlist', 'grilling'): ('owner', 'chat'),
    ('grilling', 'ready'): ('chat',),
    ('ready', 'next'): ('owner', 'chat'),
    ('next', 'building'): ('runner',),
    ('building', 'testing'): ('runner',),
    ('testing', 'done'): ('owner', 'chat'),
    ('testing', 'building'): ('chat', 'runner'),
    ('next', 'ready'): ('owner', 'chat'),
    ('ready', 'grilling'): ('owner', 'chat'),
    ('grilling', 'shortlist'): ('owner', 'chat'),
    ('building', 'next'): ('owner', 'chat'),
    ('building', 'ready'): ('owner', 'chat'),
}


def actor_kind(actor):
    bounded(actor, 'Actor')
    if actor in ('owner', 'runner'):
        return actor
    if actor.startswith('chat:') and actor[5:].strip():
        return 'chat'
    raise StateError('Actor must be owner, chat:<id>, or runner')


class FeatureStore:
    def _feature(self, identifier):
        row = self.connection.execute(
            'SELECT f.feature, f.id, f.project, f.title, f.stage, f.position, f.parked_from, f.backlog, f.design_agreed, f.review_passed '
            'FROM cplane_feature_ids a JOIN cplane_features f ON f.feature = a.feature WHERE a.id = %s',
            (identifier,)).fetchone()
        if row is None:
            raise StateError(f'Feature not found: {identifier}')
        return dict(zip(('feature', 'id', 'project', 'title', 'stage', 'position', 'parked_from', 'backlog', 'design_agreed', 'review_passed'), row))

    def _feature_number(self, project):
        row = self.connection.execute(
            'UPDATE cplane_projects SET feature_counter = feature_counter + 1 WHERE key = %s RETURNING feature_counter',
            (project,)).fetchone()
        if row is None:
            raise StateError(f'Project not found: {project}')
        return f'{project}-F{row[0]}'

    def _feature_position(self, stage):
        return self.connection.execute(
            'SELECT COALESCE(max(position) + 1, 0) FROM cplane_features WHERE stage = %s',
            (stage,)).fetchone()[0]

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
                (identifier, project, title, stage, self._feature_position(stage))).fetchone()[0]
            self.connection.execute('INSERT INTO cplane_feature_ids VALUES (%s, %s)', (identifier, feature))
            self._feature_chat_stage(self._feature(identifier), stage)
            self._feature_event(feature, f'add {identifier}', actor)
            return self.feature_show(identifier)

    def feature_list(self, *, project=None, stage=None):
        if stage is not None:
            stage_name(stage)
        with self.locked():
            rows = self.connection.execute(
                'SELECT id FROM cplane_features WHERE (%s::text IS NULL OR project = %s) '
                'AND (%s::text IS NULL OR stage = %s) ORDER BY '
                "array_position(ARRAY['shortlist','grilling','ready','next','building','testing','done','parked'], stage), position",
                (project, project, stage, stage))
            return [self.feature_show(row[0]) for row in rows.fetchall()]

    def feature_show(self, identifier):
        with self.locked():
            item = self._feature(identifier)
            feature = item.pop('feature')
            for mark in ('design_agreed', 'review_passed'):
                if item[mark] is not None:
                    item[mark] = item[mark].isoformat()
            item['aliases'] = [r[0] for r in self.connection.execute(
                'SELECT id FROM cplane_feature_ids WHERE feature = %s AND id <> %s ORDER BY id', (feature, item['id']))]
            item['sections'] = [dict(name=r[0], position=r[1], text=r[2]) for r in self.connection.execute(
                'SELECT name, position, text FROM cplane_feature_sections WHERE feature = %s ORDER BY position', (feature,))]
            return item

    def feature_board(self):
        """Read board data together under the store lock; never expose run prompts."""
        from .run_records import TOKEN_FIELDS
        with self.locked():
            items = self.feature_list()
            slices = self.load()['slices']
            for slice_item in slices:
                slice_item['attention'] = self.chat_attention(slice_item)
            records = self.run_record_list()
            projects = [dict(key=r[0], name=r[1]) for r in self.connection.execute(
                'SELECT key, name FROM cplane_projects ORDER BY name')]
            for item in items:
                internal = self._feature(item['id'])
                ids = {item['id'], *item['aliases']}
                linked = [s for s in slices if s.get('feature_id') in ids]
                item['slices'] = linked
                item['moves'] = []
                for target in STAGES:
                    if target == item['stage']:
                        continue
                    source = item['stage']
                    allowed = (target == item['parked_from'] if source == 'parked' else
                               target == 'parked' or 'owner' in MOVES.get((source, target), ()))
                    if not allowed:
                        continue
                    if target == 'parked' and source != 'building' and any(
                            s['state'] in ('issued', 'awaiting handover') and not s['paused'] for s in linked):
                        continue
                    try:
                        if source in ('grilling', 'parked') or target == 'done':
                            self._entry_conditions(internal, target, linked)
                    except StateError:
                        continue
                    item['moves'].append(target)
                event = self.connection.execute(
                    "SELECT time FROM cplane_feature_events WHERE feature = %s AND (event LIKE 'stage %%' OR event LIKE 'add %%') ORDER BY id DESC LIMIT 1",
                    (internal['feature'],)).fetchone()
                item['stage_since'] = event[0].isoformat() if event else None
                rows = [r for r in records if r.get('feature_id') in ids or r.get('slice_id') in {s['id'] for s in linked}]
                item['numbers'] = {}
                for field in (*TOKEN_FIELDS, 'seconds'):
                    values = [(r['turn_tokens'][field] if field in TOKEN_FIELDS else r[field]) for r in rows]
                    known = [v for v in values if v is not None]
                    item['numbers'][field] = sum(known) if known else None
            return dict(projects=projects, features=items)

    def _linked_slices(self, feature):
        return [r[0] for r in self.connection.execute(
            "SELECT s.document FROM cplane_slices s JOIN cplane_feature_ids a "
            "ON a.id = s.document->>'feature_id' WHERE a.feature = %s", (feature,))]

    def _entry_conditions(self, item, stage, linked):
        if stage == 'ready':
            if item['design_agreed'] is None:
                raise StateError('No agreed design yet')
            if not linked:
                raise StateError('No linked slice yet')
        if stage == 'done' and item['review_passed'] is None:
            raise StateError('Review has not passed yet')

    def _renumber_stage(self, stage, features):
        # The stage/position constraint is deferred until this transaction ends.
        for position, feature in enumerate(features):
            self.connection.execute('UPDATE cplane_features SET position = %s WHERE feature = %s AND stage = %s',
                                    (position, feature, stage))

    def feature_place(self, identifier, *, top=False, bottom=False, before=None, after=None, actor='owner'):
        if sum((bool(top), bool(bottom), before is not None, after is not None)) != 1:
            raise StateError('Choose exactly one placement')
        with self.mutation():
            item = self._feature(identifier)
            anchor = self._feature(before if before is not None else after) if before is not None or after is not None else None
            if anchor is not None:
                if anchor['stage'] != item['stage']:
                    raise StateError('Placement target is in another stage')
                if anchor['feature'] == item['feature']:
                    raise StateError('Cannot place a feature relative to itself')
            features = [r[0] for r in self.connection.execute(
                'SELECT feature FROM cplane_features WHERE stage = %s AND feature <> %s ORDER BY position',
                (item['stage'], item['feature']))]
            index = 0 if top else len(features)
            if anchor is not None:
                index = features.index(anchor['feature']) + (after is not None)
            features.insert(index, item['feature'])
            self._renumber_stage(item['stage'], features)
            self._feature_event(item['feature'], f'place {identifier} ' + (
                'top' if top else 'bottom' if bottom else f'before {before}' if before is not None else f'after {after}'), actor)
            return self.feature_show(identifier)

    def feature_stage(self, identifier, stage, *, actor='owner'):
        stage_name(stage)
        kind = actor_kind(actor)
        with self.mutation():
            item = self._feature(identifier)
            source = item['stage']
            linked = self._linked_slices(item['feature'])
            if source == 'parked':
                if stage != item['parked_from']:
                    raise StateError('Return to the stage this feature left')
                allowed = ('owner', 'chat')
            elif stage == 'parked':
                allowed = ('owner', 'chat')
            else:
                allowed = MOVES.get((source, stage), ())
            if not allowed:
                raise StateError(f'Cannot move from {source} to {stage}')
            if kind not in allowed:
                required = ' or '.join('chat:<id>' if role == 'chat' else role for role in allowed)
                raise StateError(f'This move requires actor {required}')
            if stage == 'parked' and source != 'building':
                if any(s['state'] in ('issued', 'awaiting handover') and not s['paused'] for s in linked):
                    raise StateError('A linked slice is still running unpaused')
            if source in ('grilling', 'parked') or stage == 'done':
                self._entry_conditions(item, stage, linked)
            if source == 'building' and stage in ('next', 'ready', 'parked'):
                data = self.load()
                linked_ids = {s['id'] for s in linked}
                for slice_item in data['slices']:
                    if (slice_item['id'] in linked_ids and not slice_item['paused']
                            and slice_item['state'] in ('issued', 'awaiting handover')):
                        slice_item['paused'] = True
                        self._pipeline_log(item, slice_item, 'pipeline pause')
                    if slice_item['id'] in linked_ids and slice_item['state'] == 'ready':
                        start = next((e for e in reversed(slice_item['log'])
                                      if e['event'] in ('start', 'slot', 'unslot')
                                      or e['event'].startswith('start:')), None)
                        if start and start['actor'] == 'runner' and start['event'].startswith('start:'):
                            slice_item['slot'] = None
                            self._pipeline_log(item, slice_item, 'pipeline unslot')
                self.save(data)
            if kind == 'runner':
                data = self.load()
                linked_ids = {s['id'] for s in linked}
                for slice_item in data['slices']:
                    if slice_item['id'] in linked_ids:
                        self._pipeline_log(item, slice_item, f'stage {source} to {stage}')
                self.save(data)
            self.connection.execute(
                'UPDATE cplane_features SET stage = %s, position = %s, parked_from = %s WHERE feature = %s',
                (stage, self._feature_position(stage), source if stage == 'parked' else None, item['feature']))
            if stage == 'building' and source in ('testing', 'parked'):
                self.feature_place(identifier, top=True, actor=actor)
            self._feature_chat_stage(item, stage)
            self._feature_event(item['feature'], f'stage {source} to {stage}', actor)
            return self.feature_show(identifier)

    def _pipeline_log(self, feature, item, event, at=None):
        event = f'{event}: {feature["id"]}'
        item['log'].append(dict(at=at or now().isoformat(), actor='runner', event=event))
        self._feature_event(feature['feature'], f'{event} slice {item["id"]}', 'runner')

    def pipeline_step(self, at):
        """Advance the board and slot work atomically; never launch an executor."""
        with self.mutation():
            def linked(feature, data):
                aliases = {r[0] for r in self.connection.execute(
                    'SELECT id FROM cplane_feature_ids WHERE feature = %s', (feature['feature'],))}
                return [s for s in data['slices'] if s.get('feature_id') in aliases]

            def waiting(slices):
                return any(s['attention'] and s['attention']['answer'] is None for s in slices)

            data = self.load()
            building = [self._feature(f['id']) for f in self.feature_list(stage='building')]
            groups = [linked(f, data) for f in building]
            active = sum(any(s['state'] != 'accepted' for s in group) and not waiting(group)
                         for group in groups)
            stopped = sum(waiting(group) for group in groups)
            limits = self.limit_show()
            for feature in self.feature_list(stage='next'):
                if active >= limits['building_limit'] or stopped >= limits['waiting_limit']:
                    break
                internal = self._feature(feature['id'])
                group = linked(internal, data)
                if not group:
                    continue
                self.feature_stage(feature['id'], 'building', actor='runner')
                active += bool(any(s['state'] != 'accepted' for s in group) and not waiting(group))
                stopped += bool(waiting(group))

            # Reload to retain stage audit entries from feature_stage.
            data = self.load()
            accepted = {s['id'] for s in data['slices'] if s['state'] == 'accepted'}
            ordered = []
            for feature in self.feature_list(stage='building'):
                internal = self._feature(feature['id'])
                group = linked(internal, data)
                if group and all(s['state'] == 'accepted' for s in group):
                    # Save accumulated slots/logs before the nested move loads them.
                    self.save(data)
                    self.feature_stage(feature['id'], 'testing', actor='runner')
                    data = self.load()
                    continue
                for item in group:
                    ordered.append(item['id'])
                    # The latest pause command owns the pause; manual commands win.
                    pause = next((e for e in reversed(item['log'])
                                  if e['event'] in ('pause', 'resume')
                                  or e['event'].startswith(('pipeline pause:', 'pipeline resume:'))), None)
                    if (item['paused'] and pause and pause['actor'] == 'runner'
                            and pause['event'].startswith('pipeline pause:')):
                        item['paused'] = False
                        self._pipeline_log(internal, item, 'pipeline resume', at)
                    if (item['state'] == 'ready' and not item['paused']
                            and all(dep in accepted for dep in item['depends_on'])
                            and (item['slot'] is None or datetime.fromisoformat(item['slot']) > datetime.fromisoformat(at))):
                        item['slot'] = at
                        self._pipeline_log(internal, item, 'start', at)
                        self.append_notices([dict(at=at, id=item['id'], event='start',
                                                  text=f"Started {item['id']} at {at}")])
            self.save(data)
            return ordered

    def feature_mark(self, identifier, mark, *, clear=False, actor='owner'):
        actor_kind(actor)
        columns = {'design': 'design_agreed', 'review': 'review_passed'}
        if mark not in columns:
            raise StateError('Choose design or review')
        with self.mutation():
            item = self._feature(identifier)
            self.connection.execute(
                f"UPDATE cplane_features SET {columns[mark]} = {'NULL' if clear else 'now()'} WHERE feature = %s",
                (item['feature'],))
            self._feature_event(item['feature'], f'mark {mark}' + (' clear' if clear else ''), actor)
            return self.feature_show(identifier)

    def limit_show(self):
        with self.locked():
            return {name: int(value) for name, value in self.connection.execute(
                'SELECT name, value FROM cplane_settings ORDER BY name')}

    def limit_set(self, name, value):
        if name not in ('building_limit', 'waiting_limit', 'chat_auto_turns'):
            raise StateError('Unknown limit; choose building_limit, waiting_limit or chat_auto_turns')
        if type(value) is not int or value < 1:
            raise StateError('Limit must be a whole number of at least 1')
        with self.mutation():
            self.connection.execute('UPDATE cplane_settings SET value = %s WHERE name = %s', (value, name))
            return self.limit_show()

    def feature_move(self, identifier, project, *, actor='owner'):
        with self.mutation():
            item = self._feature(identifier)
            if project != item['project']:
                new_id = self._feature_number(project)
                self.connection.execute('INSERT INTO cplane_feature_ids VALUES (%s, %s)', (new_id, item['feature']))
                self.connection.execute(
                    'UPDATE cplane_features SET id = %s, project = %s WHERE feature = %s',
                    (new_id, project, item['feature']))
                self.connection.execute('UPDATE cplane_sessions SET project = %s WHERE feature = %s',
                                        (project, item['feature']))
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
