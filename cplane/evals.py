"""Postgres eval catalogue and experiment planning; never launches an executor."""
import ast
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from .state import StateError

FILTERS = {'kind': ('ticket', 'slice', 'review'),
           'tag_kind': ('new', 'change', 'fix', 'tests', 'docs'),
           'size': ('S', 'M', 'L'), 'language': ('python', 'swift', 'typescript'),
           'half': ('development', 'held-out')}
CASE_FIELDS = ('id', 'kind', 'level', 'repository', 'pr', 'base_commit', 'title', 'task',
               'check_command', 'reference_diff', 'tag_kind', 'size', 'language', 'half')


def _rows(store, sql, parameters=()):
    from psycopg.rows import dict_row
    with store.connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(sql, parameters)
        return [{k: v.isoformat() if isinstance(v, datetime) else v for k, v in row.items()}
                for row in cursor.fetchall()]


def half(store, repository, pr):
    return ('held-out' if int(hashlib.sha256(f'{repository}#{pr}'.encode()).hexdigest()[:8], 16) % 5 < 2
            else 'development')


def size(store, patch, files=None):
    """Count changed hunk lines and changed files, including binary/rename diffs."""
    paths = set()
    lines = 0
    selected = False
    old_left = new_left = 0
    quoted = r'"(?:[^"\\]|\\.)*"'
    for line in patch.splitlines():
        if line.startswith('diff --git '):
            match = re.fullmatch(r'diff --git (' + quoted + r'|a/.*?) (' + quoted + r'|b/.*)', line)
            if match is None:
                raise StateError('Invalid git diff paths')
            try:
                old, new = (ast.literal_eval('b' + p).decode('utf-8') if p.startswith('"') else p
                            for p in match.groups())
            except (ValueError, SyntaxError, UnicodeError):
                raise StateError('Invalid git diff paths') from None
            if not old.startswith('a/') or not new.startswith('b/'):
                raise StateError('Invalid git diff paths')
            old, new = old[2:], new[2:]
            selected = files is None or old in files or new in files
            if selected:
                paths.add(new)
            old_left = new_left = 0
        elif line.startswith('@@ '):
            match = re.match(r'@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@', line)
            if match is None:
                raise StateError('Invalid git diff hunk')
            old_left, new_left = (int(n) if n is not None else 1 for n in match.groups())
        elif old_left or new_left:
            if line.startswith('+'):
                new_left -= 1
                lines += int(selected)
            elif line.startswith('-'):
                old_left -= 1
                lines += int(selected)
            elif line.startswith(' '):
                old_left -= 1
                new_left -= 1
    return 'S' if lines <= 50 and len(paths) <= 2 else 'M' if lines <= 200 and len(paths) <= 5 else 'L'


def _text(value, field, identifier):
    if not isinstance(value, str) or not value.strip():
        raise StateError(f'{identifier}: missing or invalid {field}')
    return value


def import_folder(store, folder):
    folder = Path(folder)
    if not folder.is_dir():
        raise StateError('Eval import requires a folder')
    cases = {}
    for path in sorted(folder.glob('*.json')):
        try:
            source = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError):
            raise StateError(f'{path.name}: invalid case JSON') from None
        if not isinstance(source, dict):
            raise StateError(f'{path.name}: expected an object')
        repository = _text(source.get('repository'), 'repository', path.name)
        pr = source.get('pr')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or type(pr) is not int or pr < 1:
            raise StateError(f'{path.name}: invalid repository or pr')
        identifier = f'{repository}#{pr}'
        branch = _text(source.get('branch'), 'branch', identifier)
        if Path(branch).name != branch or branch in ('.', '..'):
            raise StateError(f'{identifier}: branch must be a filename')
        patch = (folder / f'{branch}.patch').read_text(encoding='utf-8')
        kind = source.get('kind', 'ticket')
        if kind not in FILTERS['kind']:
            raise StateError(f'{identifier}: invalid kind')
        items = source.get('tickets') if kind == 'ticket' else [source]
        if not isinstance(items, list) or not items:
            raise StateError(f'{identifier}: tickets must be a nonempty list')
        for n, item in enumerate(items, 1):
            key = f'{identifier}/{n}' if kind == 'ticket' else identifier
            if not isinstance(item, dict):
                raise StateError(f'{key}: expected a case object')
            tags = {}
            for field in ('tag_kind', 'language'):
                value = item.get(field, source.get(field))
                if value not in FILTERS[field]:
                    raise StateError(f'{key}: missing or invalid {field}')
                tags[field] = value
            level = item.get('level') if kind == 'slice' else None
            if kind == 'slice' and level not in ('light', 'standard'):
                raise StateError(f'{key}: missing or invalid level')
            files = item.get('files') if kind == 'ticket' else None
            if kind == 'ticket' and (not isinstance(files, list) or not files or
                                      any(not isinstance(f, str) or not f for f in files)):
                raise StateError(f'{key}: missing or invalid files')
            case = dict(id=key, kind=kind, level=level, repository=repository, pr=pr,
                        base_commit=_text(source.get('base_commit'), 'base_commit', key),
                        title=_text(item.get('title'), 'title', key),
                        task=_text(item.get('change'), 'change', key),
                        check_command=(_text(item.get('check'), 'check', key) if kind == 'ticket' else item.get('check')),
                        reference_diff=patch, size=size(store, patch, files),
                        half=half(store, repository, pr), **tags)
            if key in cases:
                raise StateError(f'{key}: duplicate case in import')
            cases[key] = case
    counts = dict(inserted=0, updated=0, unchanged=0)
    with store.mutation():
        for case in cases.values():
            prior = _rows(store, 'SELECT * FROM cplane_eval_cases WHERE id = %s', (case['id'],))
            if prior and all(prior[0][k] == v for k, v in case.items()):
                counts['unchanged'] += 1
                continue
            assignments = ', '.join(f'{k} = EXCLUDED.{k}' for k in CASE_FIELDS if k != 'id')
            store.connection.execute('INSERT INTO cplane_eval_cases (' + ', '.join(CASE_FIELDS) + ') VALUES (' +
                                     ', '.join(['%s'] * len(CASE_FIELDS)) + ') ON CONFLICT (id) DO UPDATE SET ' + assignments,
                                     tuple(case[k] for k in CASE_FIELDS))
            counts['updated' if prior else 'inserted'] += 1
    return counts


def case_list(store, **filters):
    filters = {k: v for k, v in filters.items() if v is not None}
    if any(k not in FILTERS or v not in FILTERS[k] for k, v in filters.items()):
        raise StateError('Invalid eval case filter')
    with store.locked():
        return _rows(store, 'SELECT id, kind, level, repository, pr, title, tag_kind, size, language, half, created_at '
                     'FROM cplane_eval_cases' + (' WHERE ' + ' AND '.join(f'{k} = %s' for k in filters) if filters else '') +
                     ' ORDER BY id', tuple(filters.values()))


def set_show(store, identifier, version=None):
    with store.locked():
        rows = _rows(store, 'SELECT s.*, v.version, v.note, v.tag_filter, v.created_at, v.created_by '
                     'FROM cplane_eval_sets s JOIN cplane_eval_set_versions v ON v."set" = s.id '
                     'WHERE s.id = %s' + (' AND v.version = %s' if version is not None else '') +
                     ' ORDER BY v.version DESC LIMIT 1', (identifier, version) if version is not None else (identifier,))
        if not rows:
            raise StateError(f'Eval set version not found: {identifier}')
        result = rows[0]
        result['members'] = [r['case'] for r in _rows(store,
            'SELECT "case" FROM cplane_eval_set_members WHERE "set" = %s AND version = %s ORDER BY "case"',
            (identifier, result['version']))]
        return result


def _version(store, identifier, version, members, tag_filter, note, actor):
    from psycopg.types.json import Jsonb
    store.connection.execute('INSERT INTO cplane_eval_set_versions ("set", version, tag_filter, note, created_by) '
                             'VALUES (%s, %s, %s, %s, %s)', (identifier, version, Jsonb(tag_filter), note, actor))
    for member in sorted(set(members)):
        store.connection.execute('INSERT INTO cplane_eval_set_members VALUES (%s, %s, %s)', (identifier, version, member))
    return set_show(store, identifier, version)


def set_create(store, identifier, *, title, filters, actor='owner', description='', note=''):
    if not isinstance(filters, dict):
        raise StateError('Eval filter must be a JSON object')
    _text(identifier, 'id', 'set')
    _text(title, 'title', identifier)
    with store.mutation():
        members = [c['id'] for c in case_list(store, **filters)]
        store.connection.execute('INSERT INTO cplane_eval_sets VALUES (%s, %s, %s)', (identifier, title, description))
        return _version(store, identifier, 1, members, filters, note, actor)


def set_add(store, identifier, cases, *, actor='owner', note=''):
    with store.mutation():
        prior = set_show(store, identifier)
        for case in cases:
            if not _rows(store, 'SELECT id FROM cplane_eval_cases WHERE id = %s', (case,)):
                raise StateError(f'Eval case not found: {case}')
        return _version(store, identifier, prior['version'] + 1, prior['members'] + list(cases),
                        prior['tag_filter'], note, actor)


def set_list(store):
    with store.locked():
        return _rows(store, 'SELECT s.*, max(v.version) AS version FROM cplane_eval_sets s '
                     'JOIN cplane_eval_set_versions v ON v."set" = s.id GROUP BY s.id ORDER BY s.id')


def run_create(store, *, title, sets, configurations, repeats, scheduled_for=None, actor='owner'):
    from psycopg.types.json import Jsonb
    _text(title, 'title', 'run')
    if type(repeats) is not int or repeats < 1 or not sets or not configurations:
        raise StateError('Eval run requires sets, configurations and repeats >= 1')
    ids = []
    for config in configurations:
        if not isinstance(config, dict) or any(not isinstance(config.get(k), str) or not config[k].strip()
                                                for k in ('id', 'harness', 'model', 'route')):
            raise StateError('Configuration requires nonempty id, harness, model and route')
        if config['harness'] not in ('codex', 'claude'):
            raise StateError(f"harness {config['harness']} is not available yet")
        if 'effort' in config and (not isinstance(config['effort'], str) or not config['effort'].strip()):
            raise StateError('Configuration effort must be nonempty text')
        ids.append(config['id'])
    if len(ids) != len(set(ids)):
        raise StateError('Duplicate configuration id')
    if scheduled_for is not None:
        try:
            scheduled_for = datetime.fromisoformat(scheduled_for)
            if scheduled_for.utcoffset() is None:
                raise ValueError
        except (ValueError, TypeError):
            raise StateError('--at must be an ISO timestamp with timezone') from None
    with store.mutation():
        versions, members = [], set()
        for selection in sets:
            identifier, separator, version = selection.rpartition(':')
            selected = set_show(store, identifier if separator else selection, int(version) if separator else None)
            ref = dict(set=selected['id'], version=selected['version'])
            if ref not in versions:
                versions.append(ref)
            members.update(selected['members'])
        run = store.connection.execute('INSERT INTO cplane_eval_runs '
            '(title, created_by, scheduled_for, repeats, set_versions, configurations) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id',
            (title, actor, scheduled_for, repeats, Jsonb(versions), Jsonb(configurations))).fetchone()[0]
        for case in sorted(members):
            for config in ids:
                for repeat in range(1, repeats + 1):
                    store.connection.execute('INSERT INTO cplane_eval_attempts (eval_run, "case", configuration_id, repeat) '
                                             'VALUES (%s,%s,%s,%s)', (run, case, config, repeat))
        return run_show(store, run)


def run_list(store):
    with store.locked():
        return _rows(store, 'SELECT * FROM cplane_eval_runs ORDER BY id')


def run_show(store, identifier):
    with store.locked():
        rows = _rows(store, 'SELECT * FROM cplane_eval_runs WHERE id = %s', (identifier,))
        if not rows:
            raise StateError('Eval run not found')
        result = rows[0]
        result['attempts'] = _rows(store, 'SELECT * FROM cplane_eval_attempts WHERE eval_run = %s ORDER BY id', (identifier,))
        verdicts = _rows(store, 'SELECT v.* FROM cplane_eval_verdicts v JOIN cplane_eval_attempts a ON a.id = v.attempt '
                         'WHERE a.eval_run = %s ORDER BY v.id', (identifier,))
        for attempt in result['attempts']:
            attempt['verdicts'] = [v for v in verdicts if v['attempt'] == attempt['id']]
        return result


def verdict_add(store, attempt, *, judge, prompt_hash, verdict, reason):
    """Judge identity includes model and version, e.g. model@version."""
    _text(judge, 'judge', 'verdict')
    _text(prompt_hash, 'prompt_hash', 'verdict')
    if verdict not in ('mergeable', 'not_mergeable') or not isinstance(reason, str):
        raise StateError('Invalid eval verdict')
    with store.mutation():
        return _rows(store, 'INSERT INTO cplane_eval_verdicts (attempt, judge, prompt_hash, verdict, reason) '
                     'VALUES (%s,%s,%s,%s,%s) RETURNING *', (attempt, judge, prompt_hash, verdict, reason))[0]


def run_cancel(store, identifier):
    with store.mutation():
        if not store.connection.execute(
                "UPDATE cplane_eval_runs SET state = 'cancelled' WHERE id = %s RETURNING id",
                (identifier,)).fetchone():
            raise StateError('Eval run not found')
        return run_show(store, identifier)
