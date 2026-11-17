"""Postgres feature operations, using the store's locked transaction path."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .state import StateError
from .times import now
from .eligibility import eligibility

LIMIT_DESCRIPTIONS = {
    'building_limit': 'Stops more features entering Building when its capacity is full.',
    'waiting_limit': 'Stops promotion into Building when too many Building features have unanswered attention.',
    'chat_auto_turns': 'Stops a chat taking consecutive automatic turns until the owner writes.',
    'executors': 'Stops new slice runs when the executor capacity is full.',
    'repository_runs': 'Stops simultaneous slice runs in the same repository.',
}

STAGES = ('shortlist', 'grilling', 'ready', 'next', 'building', 'acceptance', 'testing', 'done', 'parked')
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
    ('building', 'acceptance'): ('runner',),
    ('acceptance', 'done'): ('owner', 'chat'),
    ('acceptance', 'building'): ('chat', 'runner'),
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


def slice_movable(item):
    """A reset does not make a previously issued slice draggable again."""
    return (item['state'] in ('planned', 'researching', 'ready')
            and not item.get('session') and not item.get('pr')
            and not any(e['event'] in ('started', 'resumed', 'state: issued')
                        or e['event'].startswith('state: issued (forced:')
                        for e in item['log']))


class FeatureStore:
    def ordered_slices(self, slices):
        """Reorder only each feature's existing slots; retain all other priority."""
        with self.locked():
            aliases = dict(self.connection.execute('SELECT id, feature FROM cplane_feature_ids'))
            ranks = {(f, sid): pos for f, sid, pos in self.connection.execute(
                'SELECT feature, slice_id, position FROM cplane_slice_order')}
            result = list(slices)
            groups = {}
            for index, item in enumerate(slices):
                feature = aliases.get(item.get('feature_id'))
                if feature is not None:
                    groups.setdefault(feature, []).append(index)
            for feature, indices in groups.items():
                group = sorted((slices[i] for i in indices),
                               key=lambda s: ranks.get((feature, s['id']), float('inf')))
                for index, item in zip(indices, group):
                    result[index] = item
            return result

    def slice_place(self, identifier, *, before=None, after=None, actor='owner'):
        bounded(actor, 'Actor')
        if (before is None) == (after is None):
            raise StateError('Choose exactly one placement')
        with self.mutation():
            data = self.load()
            by_id = {s['id']: s for s in data['slices']}
            item = by_id.get(identifier)
            anchor = by_id.get(before if before is not None else after)
            if item is None or anchor is None:
                raise StateError('Slice not found')
            if identifier == anchor['id']:
                raise StateError('Cannot place a slice relative to itself')
            if not item.get('feature_id') or not anchor.get('feature_id'):
                raise StateError('Placement requires linked slices')
            feature = self._feature(item['feature_id'])
            if self._feature(anchor['feature_id'])['feature'] != feature['feature']:
                raise StateError('Placement target is in another feature')
            if not slice_movable(item):
                raise StateError('This slice has already started')
            aliases = {feature['id'], *self.feature_show(feature['id'])['aliases']}
            original = [s for s in self.ordered_slices(data['slices']) if s.get('feature_id') in aliases]
            proposed = [s for s in original if s['id'] != identifier]
            index = next(i for i, s in enumerate(proposed) if s['id'] == anchor['id'])
            proposed.insert(index + (after is not None), item)
            if any(old['id'] != new['id'] and not slice_movable(old)
                   for old, new in zip(original, proposed)):
                raise StateError('Running and finished slices must stay in place')
            positions = {s['id']: i for i, s in enumerate(proposed)}
            if any(positions[dep] > positions[s['id']] for s in proposed
                   for dep in s['depends_on'] if dep in positions):
                raise StateError('A slice must stay after its dependencies')
            self.connection.execute('DELETE FROM cplane_slice_order WHERE feature = %s', (feature['feature'],))
            for position, entry in enumerate(proposed):
                self.connection.execute('INSERT INTO cplane_slice_order VALUES (%s, %s, %s)',
                                        (feature['feature'], entry['id'], position))
            event = f'place {identifier} ' + (f'before {before}' if before is not None else f'after {after}')
            item['log'].append(dict(at=now().isoformat(), actor=actor, event=event))
            self.save(data)
            self._feature_event(feature['feature'], event, actor)
            return [s['id'] for s in proposed]

    def _feature(self, identifier):
        row = self.connection.execute(
            'SELECT f.feature, f.id, f.project, f.title, f.stage, f.position, f.parked_from, f.backlog, f.design_agreed, f.review_passed, f.kind '
            'FROM cplane_feature_ids a JOIN cplane_features f ON f.feature = a.feature WHERE a.id = %s',
            (identifier,)).fetchone()
        if row is None:
            raise StateError(f'Feature not found: {identifier}')
        return dict(zip(('feature', 'id', 'project', 'title', 'stage', 'position', 'parked_from', 'backlog', 'design_agreed', 'review_passed', 'kind'), row))

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

    def feature_add(self, project, title, *, stage='shortlist', kind=None, actor='owner'):
        bounded(title, 'Title')
        stage_name(stage)
        self._feature_kind_validate(kind)
        with self.mutation():
            identifier = self._feature_number(project)
            feature = self.connection.execute(
                'INSERT INTO cplane_features (id, project, title, stage, position, parked_from, kind) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING feature',
                (identifier, project, title, stage, self._feature_position(stage),
                 'shortlist' if stage == 'parked' else None, kind)).fetchone()[0]
            self.connection.execute('INSERT INTO cplane_feature_ids VALUES (%s, %s)', (identifier, feature))
            self._feature_chat_stage(self._feature(identifier), stage)
            self._feature_event(feature, f'add {identifier}', actor)
            return self.feature_show(identifier)

    @staticmethod
    def _feature_kind_validate(kind):
        if kind not in (None, 'experience', 'functional'):
            raise StateError('Unknown feature kind')

    def feature_edit(self, identifier, *, kind, actor='owner'):
        self._feature_kind_validate(kind)
        actor_kind(actor)
        with self.mutation():
            item = self._feature(identifier)
            self.connection.execute('UPDATE cplane_features SET kind = %s WHERE feature = %s',
                                    (kind, item['feature']))
            self._feature_event(item['feature'], f'kind {item["kind"]!r} to {kind!r}', actor)
            return self.feature_show(identifier)

    def feature_title(self, identifier, title, *, actor='owner'):
        bounded(title, 'Title', 120)
        with self.mutation():
            item = self._feature(identifier)
            self.connection.execute('UPDATE cplane_features SET title = %s WHERE feature = %s',
                                    (title, item['feature']))
            self.connection.execute("UPDATE cplane_sessions SET title = %s WHERE feature = %s AND kind = 'feature'", (title, item['feature']))
            self._feature_event(item['feature'], f'title {item["title"]!r} to {title!r}', actor)
            return self.feature_show(identifier)

    def feature_close(self, identifier, reason, *, actor='owner'):
        if actor_kind(actor) != 'owner':
            raise StateError('Closing a feature requires actor owner')
        bounded(reason, 'Reason', TEXT_LIMIT)
        with self.mutation():
            item = self._feature(identifier)
            if item['stage'] in ('building', 'acceptance', 'testing'):
                raise StateError('Cannot close a feature in Building, Acceptance or Testing')
            if item['stage'] != 'done':
                self.connection.execute(
                    "UPDATE cplane_features SET stage = 'done', position = %s, parked_from = NULL WHERE feature = %s",
                    (self._feature_position('done'), item['feature']))
            self._feature_chat_stage(item, 'done')
            self._feature_event(item['feature'], f'stage {item["stage"]} to done: correction: {reason}', actor)
            return self.feature_show(identifier)

    def feature_list(self, *, project=None, stage=None):
        if stage is not None:
            stage_name(stage)
        with self.locked():
            rows = self.connection.execute(
                'SELECT id FROM cplane_features WHERE (%s::text IS NULL OR project = %s) '
                'AND (%s::text IS NULL OR stage = %s) ORDER BY '
                "array_position(ARRAY['shortlist','grilling','ready','next','building','acceptance','testing','done','parked'], stage), position",
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

    def feature_board(self, identifier=None):
        """Read board data together under the store lock; never expose run prompts."""
        from .run_records import TOKEN_FIELDS
        with self.locked():
            items = self.feature_list() if identifier is None else [self.feature_show(identifier)]
            slices = self.ordered_slices(self.page_state()['slices'])
            owned = self.chat_attentions(slices)
            for slice_item in slices:
                slice_item['attention'] = owned.get(slice_item['id'], slice_item['attention'])
            records = self.run_record_list()
            projects = self.library_projects()
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
                    allowed = (target == (item['parked_from'] or 'shortlist') if source == 'parked' else
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

    def feature_links(self):
        with self.locked():
            return dict(self.connection.execute(
                'SELECT a.id, f.id FROM cplane_feature_ids a JOIN cplane_features f ON f.feature = a.feature'))

    def feature_cards(self):
        """Bulk list projection; no sections, logs, handovers, moves or run records."""
        with self.locked():
            rows = self.connection.execute(
                "SELECT f.id, f.title, f.project, f.stage, f.position, f.parked_from, "
                "e.since FROM cplane_features f LEFT JOIN "
                "(SELECT feature, max(time) AS since FROM cplane_feature_events "
                "WHERE event LIKE 'stage %%' OR event LIKE 'add %%' GROUP BY feature) e "
                "ON e.feature = f.feature ORDER BY f.position, f.id").fetchall()
            aliases = self.feature_links()
            linked = {}
            for row in self.connection.execute(
                    "SELECT document->>'feature_id', document->>'title', document->>'state', "
                    "(document->>'paused')::boolean, document->'attention' FROM cplane_slices ORDER BY position"):
                feature, slice_title, state, paused, attention = row
                item = dict(title=slice_title, state=state, paused=paused, attention=attention)
                linked.setdefault(aliases.get(feature), []).append(item)
            cards = []
            for identifier, title, project, stage, position, parked, since in rows:
                group = linked.get(identifier, [])
                counts = {state: sum(s['state'] == state for s in group) for state in
                          ('planned', 'researching', 'ready', 'issued', 'awaiting handover', 'in review', 'accepted', 'escalated', 'dropped')}
                open_items = [s for s in group if s['state'] not in ('accepted', 'dropped') and s['attention'] and (
                    s['attention']['kind'] == 'owner-check' or
                    s['attention']['kind'] == 'merge' and not s['attention']['approved'] or
                    s['attention']['kind'] in ('question', 'escalation', 'node-step') and s['attention']['answer'] is None)]
                running = [s['title'] for s in group if s['state'] in ('issued', 'awaiting handover') and not s['paused']]
                extra = None
                if stage == 'ready':
                    extra = f'{len(group)} slices'
                elif stage == 'building':
                    extra = ('Waiting for you' if open_items else
                             f"{counts['accepted']} of {len(group)} slices done" +
                             (' · ' + ', '.join(running) if running else '') if group else None)
                elif stage == 'done' and since:
                    finished = since.astimezone(ZoneInfo('Europe/Copenhagen'))
                    extra = f'Finished {finished.day} {finished.strftime("%b %Y")}'
                elif stage == 'parked' and parked:
                    extra = f'From {parked.capitalize()}'
                cards.append(dict(id=identifier, title=title, project=project, stage=stage, position=position,
                                  extra=extra, slice_counts=counts, slice_count=len(group),
                                  open_attention=len(open_items), waiting=bool(open_items)))
            return dict(projects=self.library_projects(), features=cards)

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
                if stage != (item['parked_from'] or 'shortlist'):
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
            if stage == 'building' and source in ('acceptance', 'testing', 'parked'):
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
                return [s for s in self.ordered_slices(data['slices']) if s.get('feature_id') in aliases]

            def waiting(slices):
                return any(s['state'] not in ('accepted', 'dropped') and s['attention'] and s['attention']['answer'] is None for s in slices)

            data = self.load()
            building = [self._feature(f['id']) for f in self.feature_list(stage='building')]
            groups = [linked(f, data) for f in building]
            active = sum(any(s['state'] not in ('accepted', 'dropped') for s in group) and not waiting(group)
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
                active += bool(any(s['state'] not in ('accepted', 'dropped') for s in group) and not waiting(group))
                stopped += bool(waiting(group))

            # Reload to retain stage audit entries from feature_stage.
            data = self.load()
            ordered = []
            for feature in self.feature_list(stage='building'):
                internal = self._feature(feature['id'])
                group = linked(internal, data)
                if group and all(s['state'] in ('accepted', 'dropped') for s in group):
                    # Save accumulated slots/logs before the nested move loads them.
                    self.save(data)
                    self.feature_stage(feature['id'], 'acceptance' if internal['kind'] == 'functional' else 'testing', actor='runner')
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
                            and eligibility(item, data)['status'] == 'ready'
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
        if not isinstance(name, str) or name not in LIMIT_DESCRIPTIONS:
            raise StateError('Unknown limit')
        if type(value) is not int or value < 1:
            raise StateError('Limit must be a whole number of at least 1')
        if name == 'executors' and value > 4:
            raise StateError('Executors must be between 1 and 4')
        if name == 'repository_runs' and value != 1:
            raise StateError('Repository runs must be 1')
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
            revisions = [dict(id=r[0], section=r[1], text=r[2], actor=r[3], time=r[4].isoformat()) for r in rows]
            if section is not None:
                return revisions
            # Correction commands have no document revision to revert. Keep their
            # audit IDs separate so they cannot be mistaken for revision IDs.
            events = [dict(event_id=r[0], event=r[1], actor=r[2], time=r[3].isoformat())
                      for r in self.connection.execute(
                          "SELECT id, event, actor, time FROM cplane_feature_events WHERE feature = %s "
                          "AND (event LIKE 'title %%' OR event LIKE 'stage %% to done: correction: %%') ORDER BY id",
                          (item['feature'],))]
            return sorted([*revisions, *events], key=lambda entry: entry['time'])

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

    def project_active(self, key, active=None, *, actor='owner'):
        if active is not None and type(active) is not bool:
            raise StateError('Active must be a boolean')
        bounded(actor, 'Actor')
        with self.mutation():
            project = next((p for p in self.library_projects() if p['key'] == key), None)
            if project is None:
                raise StateError('Unknown project')
            if key == 'NEW' and active is False:
                raise StateError('NEW is always active')
            if active is not None:
                self.connection.execute('UPDATE cplane_projects SET active = %s WHERE key = %s', (active, key))
                if active and not self.connection.execute(
                        "SELECT 1 FROM cplane_sessions WHERE kind = 'project' AND project = %s", (key,)).fetchone():
                    self.create_project_chat(key)
                self.connection.execute(
                    'INSERT INTO cplane_project_events (project, actor, active) VALUES (%s, %s, %s)',
                    (key, actor, active))
                project['active'] = active
            return project

    @staticmethod
    def _project_fields(fields):
        from urllib.parse import urlsplit
        if not fields or set(fields) - {'name', 'about', 'public_url', 'repository_url'}:
            raise StateError('Choose project fields; keys cannot change')
        for field, value in fields.items():
            if field == 'name':
                bounded(value, 'Project name', 60)
            elif field == 'about':
                bounded(value, 'About', 600, empty=True)
            elif value is not None and value != '':
                if not isinstance(value, str):
                    raise StateError('URLs must use https://')
                try:
                    url = urlsplit(value)
                    valid = (value.startswith('https://') and url.hostname and url.port != 0
                             and not url.username and not url.password
                             and not any(c.isspace() or ord(c) < 32 for c in value)
                             and not any(c in value for c in ('\\', '<', '>', '"')))
                except ValueError:
                    valid = False
                if not valid:
                    raise StateError('URLs must use https:// and include a host')
        return {k: (v or None) if k.endswith('_url') else v for k, v in fields.items()}

    def project_show(self, key):
        with self.locked():
            row = self.connection.execute(
                'SELECT key, name, repository, active, about, public_url, repository_url '
                'FROM cplane_projects WHERE key = %s AND key <> \'NEW\'', (key,)).fetchone()
            if row is None:
                raise StateError('Project not found')
            return dict(zip(('key', 'name', 'repository', 'active', 'about', 'public_url', 'repository_url'), row))

    def project_set(self, key, *, actor='owner', **fields):
        from psycopg.types.json import Jsonb
        if actor != 'owner':
            raise StateError('Only the owner can edit project fields')
        fields = self._project_fields(fields)
        with self.mutation():
            self.project_show(key)
            self.connection.execute('UPDATE cplane_projects SET ' +
                                    ', '.join(f'{k} = %s' for k in fields) + ' WHERE key = %s',
                                    (*fields.values(), key))
            self.connection.execute(
                'INSERT INTO cplane_project_events (project, actor, changes) VALUES (%s, %s, %s)',
                (key, actor, Jsonb(fields)))
            return self.project_show(key)

    def project_add(self, key, name, *, repository=None, actor='owner', **fields):
        if not isinstance(key, str) or not re.fullmatch(r'[A-Z]{3}', key):
            raise StateError('Project key must be three uppercase letters')
        fields = self._project_fields(dict(name=name, **fields))
        bounded(actor, 'Actor')
        if repository is not None:
            bounded(repository, 'Repository')
        from psycopg.types.json import Jsonb
        with self.mutation():
            if self.connection.execute('SELECT 1 FROM cplane_projects WHERE key = %s', (key,)).fetchone():
                raise StateError('Project key already taken')
            if repository is not None and self.connection.execute(
                    'SELECT 1 FROM cplane_projects WHERE repository = %s', (repository,)).fetchone():
                raise StateError('Repository already has a project key')
            self.connection.execute('INSERT INTO cplane_projects (key, repository, ' + ', '.join(fields) +
                                    ') VALUES (' + ', '.join(['%s'] * (len(fields) + 2)) + ')',
                                    (key, repository, *fields.values()))
            self.create_project_chat(key)
            self.connection.execute(
                'INSERT INTO cplane_project_events (project, actor, active, changes) VALUES (%s, %s, true, %s)',
                (key, actor, Jsonb(fields)))
            return self.project_show(key)

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

    def feature_add_slice(self, identifier, title, brief, model, effort, *, depends_on=(),
                          stop_before_merge=False, allowed_files=None, actor):
        from .cut import sections
        from .planner import new_slice
        bounded(title, 'Title')
        bounded(brief, 'Brief', 65_536)
        if len(brief.encode('utf-8')) > 65_536:
            raise StateError('Brief exceeds 65536 bytes')
        sections(brief, identifier)
        with self.mutation():
            model = self.model_choice('codex', model, effort)
            feature = self._feature(identifier)
            if feature['stage'] not in ('grilling', 'ready', 'building', 'acceptance', 'testing'):
                raise StateError('Slices can only be added in Grilling, Ready, Building, Acceptance or Testing')
            repository = self.connection.execute(
                'SELECT repository FROM cplane_projects WHERE key = %s', (feature['project'],)).fetchone()[0]
            if not repository:
                raise StateError('Project has no repository')
            repositories = self._project_repositories(feature['project'])
            from .stores import REPOSITORY
            if not REPOSITORY.fullmatch(repositories[0]):
                raise StateError('Project repository owner is unresolved')
            linked = {s['id'] for s in self._linked_slices(feature['feature'])}
            if any(dep not in linked for dep in depends_on):
                raise StateError('Dependencies must be slices of the same feature')
            data = self.load()
            # Keep the counter across deletions and aliases/project transfers.
            while True:
                number = self.connection.execute(
                    'UPDATE cplane_features SET slice_counter = slice_counter + 1 '
                    'WHERE feature = %s RETURNING slice_counter', (feature['feature'],)).fetchone()[0]
                slice_id = f"{feature['id']}-S{number}"
                if not any(s['id'] == slice_id for s in data['slices']) and not self.connection.execute(
                        'SELECT 1 FROM cplane_slice_briefs WHERE slice_id = %s', (slice_id,)).fetchone():
                    break
            item = new_slice(slice_id)
            at = now().isoformat()
            item.update(repo=repositories[0], feature=feature['title'], feature_id=feature['id'],
                        title=title, state='ready', brief_id=slice_id, flow='cli',
                        executor=dict(tool='codex', model=model, effort=effort),
                        depends_on=list(depends_on), stop_before_merge=stop_before_merge)
            if allowed_files is not None:
                item['allowed_files'] = list(allowed_files)
            item['log'].append(dict(at=at, actor=actor, event='add_slice'))
            self.connection.execute(
                'INSERT INTO cplane_slice_briefs (slice_id, feature, text, actor) VALUES (%s, %s, %s, %s)',
                (slice_id, feature['feature'], brief, actor))
            self.slice_level(slice_id, 'standard')
            data['slices'].append(item)
            self.save(data, [dict(at=at, id=slice_id, event='add_slice', text=f'Added {slice_id}')])
            self._feature_event(feature['feature'], f'add_slice {slice_id}', actor)
            return item

    def stored_brief(self, brief_id):
        with self.locked():
            row = self.connection.execute(
                'SELECT text FROM cplane_slice_briefs WHERE slice_id = %s', (brief_id,)).fetchone()
            if row is None:
                raise StateError('Stored brief not found')
            return row[0]

    def feature_export_snapshot(self):
        with self.locked():
            features = self.feature_list()
            repositories = dict(self.connection.execute('SELECT key, repository FROM cplane_projects'))
            for feature in features:
                feature['repository'] = repositories[feature['project']] or '—'
                internal = self._feature(feature['id'])
                feature['briefs'] = [dict(id=r[0], text=r[1]) for r in self.connection.execute(
                    'SELECT slice_id, text FROM cplane_slice_briefs WHERE feature = %s ORDER BY time, slice_id',
                    (internal['feature'],))]
            return features
