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
IMPORT_FIELDS = ('id', 'kind', 'level', 'repository', 'pr', 'base_commit', 'title', 'task',
                 'check_command', 'reference_diff', 'tag_kind', 'size', 'language', 'half', 'allowed_files')
SLICE_FIELDS = ('source_slice', 'merge_commit', 'hidden_paths', 'grade', 'validation')
CASE_FIELDS = IMPORT_FIELDS + ('start_commit', 'start_branch', 'pinned_paths') + SLICE_FIELDS
CONFIGURATION_ROLES = {'slice': {'executor', 'reviewer'}, 'tickets': {'cutter', 'ticket', 'reviewer'}}


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


def validate_configuration(path, roles):
    """Validate a named configuration's exact platform executor shapes for reuse."""
    if not isinstance(path, str) or path not in CONFIGURATION_ROLES:
        raise StateError('Configuration path must be slice or tickets')
    if not isinstance(roles, dict) or set(roles) != CONFIGURATION_ROLES[path]:
        raise StateError(f'Configuration {path} roles must be exactly ' + ', '.join(sorted(CONFIGURATION_ROLES[path])))
    for role, entry in roles.items():
        if not isinstance(entry, dict):
            raise StateError(f'{role}: executor entry must be an object')
        if set(entry) == {'configuration'}:
            if not isinstance(entry['configuration'], str) or not re.fullmatch(
                    r'pi/[A-Za-z0-9][A-Za-z0-9._-]{0,63}', entry['configuration']):
                raise StateError(f'{role}: invalid Pi configuration name')
            continue
        harness = entry.get('harness')
        if harness not in ('codex', 'claude'):
            raise StateError(f'{role}: unknown executor harness')
        expected = {'harness', 'model', 'effort'} if harness == 'codex' else {'harness', 'model'}
        if set(entry) != expected:
            raise StateError(f'{role}: {harness} entry requires exactly ' + ', '.join(sorted(expected)))
        for field in expected:
            _text(entry[field], field, role)


def config_add(store, identifier, *, path, roles, note='', actor='owner'):
    from psycopg.types.json import Jsonb
    _text(identifier, 'id', 'configuration')
    _text(actor, 'actor', identifier)
    if not isinstance(note, str):
        raise StateError('Configuration note must be text')
    validate_configuration(path, roles)
    with store.mutation():
        if _rows(store, 'SELECT id FROM cplane_eval_configurations WHERE id=%s', (identifier,)):
            raise StateError(f'Eval configuration already exists: {identifier}')
        return _rows(store, 'INSERT INTO cplane_eval_configurations (id, path, roles, note, created_by) '
                     'VALUES (%s,%s,%s,%s,%s) RETURNING *', (identifier, path, Jsonb(roles), note, actor))[0]


def config_list(store):
    with store.locked():
        return _rows(store, 'SELECT * FROM cplane_eval_configurations ORDER BY id')


def config_show(store, identifier):
    with store.locked():
        rows = _rows(store, 'SELECT * FROM cplane_eval_configurations WHERE id=%s', (identifier,))
        if not rows:
            raise StateError(f'Eval configuration not found: {identifier}')
        return rows[0]


def _slice_fields(item, source, identifier):
    fields = {key: item.get(key, source.get(key)) for key in SLICE_FIELDS if key in item or key in source}
    for key, value in fields.items():
        if value is None:
            continue
        if key == 'hidden_paths':
            valid = isinstance(value, list) and all(isinstance(p, str) and p.strip() for p in value)
        elif key == 'grade':
            valid = value in ('tests_and_judge', 'judge')
        elif key == 'merge_commit':
            valid = isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{40}', value)
        elif key == 'source_slice':
            valid = isinstance(value, str) and re.fullmatch(r'[^/\s]+/[^/\s]+', value)
        else:
            valid = isinstance(value, str) and bool(value.strip())
        if not valid:
            raise StateError(f'{identifier}: invalid {key}')
    return fields


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
            if kind == 'slice' and level not in ('light', 'standard', 'strong'):
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
                        reference_diff=patch, allowed_files=files, size=size(store, patch, files),
                        half=half(store, repository, pr), **tags, **_slice_fields(item, source, key))
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
            fields = IMPORT_FIELDS + tuple(k for k in SLICE_FIELDS if k in case)
            assignments = ', '.join(f'{k} = EXCLUDED.{k}' for k in fields if k != 'id')
            store.connection.execute('INSERT INTO cplane_eval_cases (' + ', '.join(fields) + ') VALUES (' +
                                     ', '.join(['%s'] * len(fields)) + ') ON CONFLICT (id) DO UPDATE SET ' + assignments,
                                     tuple(case[k] for k in fields))
            counts['updated' if prior else 'inserted'] += 1
    return counts


def import_starts(store, bundle, pr, *, adapter=None):
    """Publish validated ticket starts, then atomically record the PR's metadata."""
    from .fence import Fence
    match = re.fullmatch(r'([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([1-9][0-9]*)', pr)
    if not match:
        raise StateError('Eval starts requires repository#pr')
    repository, number = match[1], int(match[2])
    with store.mutation():
        cases = _rows(store, "SELECT * FROM cplane_eval_cases WHERE repository=%s AND pr=%s AND kind='ticket'",
                      (repository, number))
        if not cases:
            raise StateError(f'{pr}: no ticket cases')
        by_id = {case['id']: case for case in cases}
        expected = [f'{pr}/{n}' for n in range(1, len(cases) + 1)]
        if set(by_id) != set(expected):
            raise StateError(f'{pr}: ticket IDs must be consecutive from 1')
        cases = [by_id[key] for key in expected]
        if len({case['base_commit'] for case in cases}) != 1:
            raise StateError(f'{pr}: ticket base commits differ')
        starts = (adapter or Fence()).publish_eval_starts(repository, number, cases[0]['base_commit'],
                                                         len(cases), bundle)
        counts = {'updated': 0, 'unchanged': 0}
        for case, start in zip(cases, starts, strict=True):
            if all(case[key] == value for key, value in start.items()):
                counts['unchanged'] += 1
                continue
            store.connection.execute('UPDATE cplane_eval_cases SET start_commit=%s, start_branch=%s, pinned_paths=%s '
                                     'WHERE id=%s',
                                     (start['start_commit'], start['start_branch'], start['pinned_paths'], case['id']))
            counts['updated'] += 1
        return counts


def case_list(store, **filters):
    filters = {k: v for k, v in filters.items() if v is not None}
    if any(k not in FILTERS or v not in FILTERS[k] for k, v in filters.items()):
        raise StateError('Invalid eval case filter')
    with store.locked():
        return _rows(store, 'SELECT id, kind, level, repository, pr, title, tag_kind, size, language, half, created_at, '
                     + ', '.join(SLICE_FIELDS) + ', '
                     "CASE WHEN start_commit IS NULL THEN 'no' ELSE 'yes' END AS has_start "
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
        if config['harness'] not in ('codex', 'claude', 'pi'):
            raise StateError(f"harness {config['harness']} is not available yet")
        if config['harness'] == 'pi' and (config['route'] != 'platform' or
                not isinstance(config.get('configuration'), str) or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', config['configuration'])):
            raise StateError('Pi requires route platform and a valid configuration name')
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
        for member in sorted(members):
            case = _rows(store, 'SELECT kind, start_commit FROM cplane_eval_cases WHERE id=%s', (member,))[0]
            if case['kind'] == 'ticket':
                if any(c['harness'] != 'pi' for c in configurations):
                    raise StateError(f'{member}: tickets require the platform route')
                if not case['start_commit']:
                    raise StateError(f'{member}: ticket requires a start commit')
            elif any(c['harness'] == 'pi' for c in configurations):
                raise StateError(f'{member}: platform route requires ticket cases')
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


def attempt_run_add(store, attempt, *, position, role, purpose, run_id):
    """Record a platform run without using the legacy local run_record link."""
    if type(position) is not int or position < 1:
        raise StateError('Attempt run position must be >= 1')
    for field, value in (('role', role), ('purpose', purpose), ('run_id', run_id)):
        _text(value, field, 'attempt run')
    with store.mutation():
        return _rows(store, 'INSERT INTO cplane_eval_attempt_runs (attempt, position, role, purpose, run_id) '
                     'VALUES (%s,%s,%s,%s,%s) RETURNING *', (attempt, position, role, purpose, run_id))[0]


def attempt_run_list(store, attempt):
    with store.locked():
        return _rows(store, 'SELECT * FROM cplane_eval_attempt_runs WHERE attempt=%s ORDER BY position', (attempt,))


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


def _brief(root, path):
    import subprocess
    if not isinstance(path, str) or not path or Path(path).is_absolute() or '..' in Path(path).parts:
        raise StateError('Slice brief path is invalid')

    def git(*args):
        return subprocess.run(['git', '-C', str(root), '-c', 'core.hooksPath=/dev/null',
                               '-c', 'core.fsmonitor=false', *args], capture_output=True)

    result = git('show', 'HEAD:' + path)
    if result.returncode:
        deletion = git('log', '-1', '--format=%H', '--diff-filter=D', '--', path)
        commit = deletion.stdout.decode('ascii', errors='replace').strip()
        if not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise StateError('Slice brief cannot be found')
        result = git('show', commit + '^:' + path)
    try:
        if result.returncode:
            raise ValueError()
        return _text(result.stdout.decode('utf-8'), 'brief', 'slice')
    except (UnicodeError, ValueError):
        raise StateError('Slice brief cannot be found') from None


def case_from_slice(store, slice_id, briefs, *, kind, check, grade, validation, hidden=None, reader=None):
    """Store a qualified slice once; repository and brief access are read-only."""
    import sys
    from .github_app import read_repository
    reader = reader or read_repository
    _text(slice_id, 'id', 'slice')
    _text(check, 'check', slice_id)
    _text(validation, 'validation', slice_id)
    if kind not in FILTERS['tag_kind'] or grade not in ('tests_and_judge', 'judge'):
        raise StateError('Invalid case kind or grade')
    if hidden is not None and (not isinstance(hidden, list) or any(not isinstance(p, str) or not p.strip() for p in hidden)):
        raise StateError('Invalid hidden paths')
    identifier = 'slice:' + slice_id
    with store.mutation():
        prior = _rows(store, 'SELECT * FROM cplane_eval_cases WHERE id=%s', (identifier,))
        if prior:
            print(f'{identifier}: already exists; unchanged', file=sys.stderr)
            return prior[0]
        rows = _rows(store, 'SELECT s.document, l.level, o.verdict FROM cplane_slices s '
                     'LEFT JOIN cplane_slice_levels l ON l.slice_id=s.id '
                     'LEFT JOIN cplane_slice_outcomes o ON o.slice_id=s.id WHERE s.id=%s', (slice_id,))
        if not rows or rows[0]['document'].get('state') != 'accepted' or rows[0]['verdict'] == 'corrected':
            raise StateError(f'{slice_id}: slice is not accepted')
        if _rows(store, 'SELECT slice_id FROM cplane_slice_outcomes WHERE corrects_slice=%s', (slice_id,)):
            raise StateError(f'{slice_id}: slice has been corrected')
        item, level = rows[0]['document'], rows[0]['level'] or 'standard'
        repo, pr = item.get('repo'), item.get('pr')
        if not isinstance(repo, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) or type(pr) is not int or pr < 1:
            raise StateError(f'{slice_id}: slice has no repository or PR')
        task = _brief(briefs, item.get('brief'))
        try:
            pull = json.loads(reader(repo, f'pulls/{pr}'))
            merge = pull.get('merge_commit_sha')
            if not pull.get('merged_at') or not isinstance(merge, str) or not re.fullmatch(r'[0-9a-f]{40}', merge):
                raise StateError(f'{slice_id}: PR is not merged')
            commit = json.loads(reader(repo, f'commits/{merge}'))
            base = commit['parents'][0]['sha']
            if not re.fullmatch(r'[0-9a-f]{40}', base):
                raise ValueError()
            patch = reader(repo, f'compare/{base}...{merge}', accept='application/vnd.github.v3.diff')
            paths = []
            for page in range(1, 32):
                entries = json.loads(reader(repo, f'pulls/{pr}/files?per_page=100&page={page}'))
                if not isinstance(entries, list):
                    raise ValueError()
                paths.extend(entry['filename'] for entry in entries)
                if len(paths) >= 3000:
                    raise StateError('PR file listing exceeds GitHub limit')
                if len(entries) < 100:
                    break
            else:
                raise StateError('PR file listing exceeds GitHub limit')
        except (ValueError, KeyError, IndexError, TypeError):
            raise StateError('Invalid GitHub PR response') from None
        extensions = {'.py': 'python', '.swift': 'swift', '.ts': 'typescript', '.tsx': 'typescript'}
        counts = {language: sum(Path(p).suffix.lower() in [ext for ext, lang in extensions.items() if lang == language]
                                for p in paths) for language in FILTERS['language']}
        language = max(counts, key=counts.get)
        if not counts[language]:
            raise StateError(f'{slice_id}: no supported language in changed files')
        if hidden is None:
            hidden = [p for p in paths if any(part in ('test', 'tests') for part in Path(p).parts[:-1])
                      or Path(p).name.startswith('test_') or re.search(r'_test\.[^.]+$|\.test\.', Path(p).name)]
        if grade == 'tests_and_judge' and not hidden:
            raise StateError(f'{slice_id}: tests_and_judge requires hidden paths')
        case = dict(id=identifier, kind='slice', level=level, repository=repo, pr=pr, base_commit=base,
                    title=_text(item.get('title'), 'title', slice_id), task=task, check_command=check,
                    reference_diff=patch, tag_kind=kind, size=size(store, patch), language=language,
                    half=half(store, repo, pr), allowed_files=None, source_slice=slice_id, merge_commit=merge,
                    hidden_paths=hidden, grade=grade, validation=validation)
        fields = IMPORT_FIELDS + SLICE_FIELDS
        return _rows(store, 'INSERT INTO cplane_eval_cases (' + ', '.join(fields) + ') VALUES (' +
                     ', '.join(['%s'] * len(fields)) + ') RETURNING *', tuple(case[k] for k in fields))[0]
