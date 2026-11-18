"""Synthetic eval catalogue, versioning and expansion on CI's Postgres 17."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from cplane import evals, state
from cplane.cli import main
from test_fence import start_chain  # noqa: F401
from test_fenced_runner import delivery  # noqa: F401
from test_stores import pg_store  # noqa: F401


def patch_file(path, lines):
    return (f'diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n'
            f'@@ -0,0 +1,{lines} @@\n' + '+synthetic\n' * lines)


@pytest.fixture
def cases(tmp_path):
    source = dict(repository='example/public', pr=53, base_commit='a' * 40, branch='synthetic',
                  tickets=[dict(title='Small', files=['small.py'], change='Synthetic task',
                                check='uv run pytest tests/test_small.py', tag_kind='new', language='python'),
                           dict(title='Large', files=['large.py'], change='Synthetic task two',
                                check='uv run pytest tests/test_large.py', tag_kind='fix', language='python')])
    (tmp_path / 'synthetic.json').write_text(json.dumps(source))
    (tmp_path / 'synthetic.patch').write_text(patch_file('small.py', 50) + patch_file('large.py', 201))
    return tmp_path, source


def test_migration_twice(pg_store):
    pg_store.migrate()
    pg_store.migrate()
    with pg_store.locked():
        assert pg_store.connection.execute(
            "SELECT count(*) FROM cplane_migrations WHERE name = '026_eval.sql'").fetchone()[0] == 1
        assert pg_store.connection.execute('SELECT count(*) FROM cplane_eval_cases').fetchone()[0] == 0
        assert pg_store.connection.execute(
            "SELECT count(*) FROM cplane_migrations WHERE name = '032_eval_records.sql'").fetchone()[0] == 1


def test_import_sizes_half_idempotency_and_updates(pg_store, cases):
    folder, source = cases
    assert evals.import_folder(pg_store, folder) == dict(inserted=2, updated=0, unchanged=0)
    rows = evals.case_list(pg_store)
    assert [r['size'] for r in rows] == ['S', 'L']
    expected = ('held-out' if int(hashlib.sha256(b'example/public#53').hexdigest()[:8], 16) % 5 < 2
                else 'development')
    assert {r['half'] for r in rows} == {expected}
    assert evals.import_folder(pg_store, folder) == dict(inserted=0, updated=0, unchanged=2)
    assert evals.case_list(pg_store) == rows
    source['tickets'][0]['change'] = 'Updated synthetic task'
    (folder / 'synthetic.json').write_text(json.dumps(source))
    assert evals.import_folder(pg_store, folder) == dict(inserted=0, updated=1, unchanged=1)


@pytest.mark.parametrize('tag', ['tag_kind', 'language'])
def test_missing_tag_rolls_back_all_cases(pg_store, cases, tag):
    folder, source = cases
    del source['tickets'][1][tag]
    (folder / 'synthetic.json').write_text(json.dumps(source))
    with pytest.raises(state.StateError, match=f'example/public#53/2: missing or invalid {tag}'):
        evals.import_folder(pg_store, folder)
    assert evals.case_list(pg_store) == []


def test_versions_run_expansion_and_verdicts(pg_store, cases):
    evals.import_folder(pg_store, cases[0])
    v1 = evals.set_create(pg_store, 'synthetic', title='Synthetic', filters={'size': 'S'}, actor='planner')
    assert v1['version'] == 1 and v1['members'] == ['example/public#53/1']
    v2 = evals.set_add(pg_store, 'synthetic', ['example/public#53/2', 'example/public#53/1'], actor='planner')
    assert v2['version'] == 2 and v2['members'] == ['example/public#53/1', 'example/public#53/2']
    assert evals.set_show(pg_store, 'synthetic', 1) == v1
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_eval_cases SET start_commit=%s", ('b' * 40,))
    configurations = [dict(id=str(n), harness='pi', model='base', route='platform', configuration='base') for n in range(3)]
    run = evals.run_create(pg_store, title='Synthetic run', sets=['synthetic:1', 'synthetic:2'],
                            configurations=configurations, repeats=2, actor='planner')
    assert len(run['attempts']) == 12
    assert len({(a['case'], a['configuration_id'], a['repeat']) for a in run['attempts']}) == 12
    assert all(a['state'] == 'planned' and a['metrics'] == {} and a['result'] is None for a in run['attempts'])
    assert run['state'] == 'planned' and run['scheduled_for'] is None
    attempt = run['attempts'][0]['id']
    for judge in ('judge-a@1', 'judge-b@2'):
        evals.verdict_add(pg_store, attempt, judge=judge, prompt_hash='abc', verdict='mergeable', reason='Synthetic')
    with pytest.raises(state.StateError):
        evals.verdict_add(pg_store, attempt, judge='judge-a@1', prompt_hash='abc', verdict='mergeable', reason='Duplicate')
    assert len(evals.run_show(pg_store, run['id'])['attempts'][0]['verdicts']) == 2
    assert evals.run_list(pg_store)[0]['created_by'] == 'planner'
    assert evals.set_list(pg_store)[0]['version'] == 2


@pytest.mark.parametrize(('lines', 'files', 'expected'), [(50, 2, 'S'), (51, 1, 'M'), (1, 3, 'M'),
                                                         (200, 1, 'M'), (201, 1, 'L'), (1, 6, 'L')])
def test_size_boundaries(lines, files, expected):
    patch = patch_file('file0', lines) + ''.join(patch_file(f'file{n}', 0) for n in range(1, files))
    assert evals.size(None, patch) == expected
    assert evals.size(None, patch, ['absent']) == 'S'


def test_cli_postgres_required(monkeypatch, capsys):
    monkeypatch.delenv('CPLANE_DATABASE_URL', raising=False)
    monkeypatch.delenv('CPLANE_DATABASE_URL_FILE', raising=False)
    assert main(['eval', 'case', 'list']) == 1
    assert 'eval commands require Postgres' in capsys.readouterr().err


def test_cli_commands(pg_store, cases, capsys, monkeypatch, tmp_path):
    assert main(['eval', 'import', str(cases[0])]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == dict(inserted=2, updated=0, unchanged=0)
    assert 'Synthetic task' not in output
    assert main(['eval', 'case', 'list', '--tag-kind', 'new']) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    assert main(['eval', 'set', 'create', 'cli', '--title', 'CLI', '--filter', '{"size":"S"}', '--actor', 'planner']) == 0
    assert json.loads(capsys.readouterr().out)['created_by'] == 'planner'
    assert main(['eval', 'set', 'add', 'cli', 'example/public#53/2']) == 0
    assert json.loads(capsys.readouterr().out)['version'] == 2
    assert main(['eval', 'set', 'show', 'cli', '--version', '1']) == 0
    assert len(json.loads(capsys.readouterr().out)['members']) == 1
    assert main(['eval', 'set', 'list']) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    with pg_store.mutation():
        pg_store.connection.execute("UPDATE cplane_eval_cases SET start_commit=%s", ('b' * 40,))
    assert main(['eval', 'run', 'create', '--title', 'CLI', '--set', 'cli', '--configuration',
                 '{"id":"a","harness":"pi","model":"base","route":"platform","configuration":"base"}',
                 '--repeats', '2', '--at', '2026-12-01T12:00:00Z']) == 0
    run = json.loads(capsys.readouterr().out)
    assert len(run['attempts']) == 4
    assert run['scheduled_for'].startswith('2026-12-01T12:00:00')
    assert main(['eval', 'run', 'show', str(run['id'])]) == 0
    assert json.loads(capsys.readouterr().out) == run
    # The URL-file path must work as well as the URL setting.
    url_file = tmp_path / 'url'
    url_file.write_text(pg_store._url)
    monkeypatch.delenv('CPLANE_DATABASE_URL')
    monkeypatch.setenv('CPLANE_DATABASE_URL_FILE', str(url_file))
    assert main(['eval', 'run', 'list']) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1


@pytest.mark.parametrize('kind', ['slice', 'review'])
def test_whole_slice_cases(pg_store, cases, kind):
    folder, source = cases
    source.pop('tickets')
    source.update(kind=kind, title='Whole slice', change='Synthetic whole task', tag_kind='change', language='python')
    if kind == 'slice':
        source['level'] = 'light'
    (folder / 'synthetic.json').write_text(json.dumps(source))
    assert evals.import_folder(pg_store, folder)['inserted'] == 1
    case, = evals.case_list(pg_store)
    assert case['id'] == 'example/public#53' and case['size'] == 'L'
    assert case['level'] == ('light' if kind == 'slice' else None)
    evals.set_create(pg_store, 'fence', title='Fence', filters={'kind': kind})
    configs = [{'id': tool, 'harness': tool, 'model': 'synthetic', 'route': 'test'}
               for tool in ('codex', 'claude')]
    run = evals.run_create(pg_store, title='Fence', sets=['fence'], configurations=configs, repeats=1)
    assert len(run['attempts']) == 2
    with pytest.raises(state.StateError, match='platform route requires ticket cases'):
        evals.run_create(pg_store, title='Bad', sets=['fence'], repeats=1,
                         configurations=[{'id': 'pi', 'harness': 'pi', 'model': 'base',
                                          'route': 'platform', 'configuration': 'base'}])


def test_invalid_planning_is_atomic(pg_store, cases):
    evals.import_folder(pg_store, cases[0])
    original = evals.set_create(pg_store, 's', title='S', filters={})
    with pytest.raises(state.StateError):
        evals.set_add(pg_store, 's', ['missing'])
    assert evals.set_show(pg_store, 's') == original
    for configs, repeats, selections in [([{}], 1, ['s']),
        ([dict(id='a', harness='h', model='m', route='r')] * 2, 1, ['s']),
        ([dict(id='a', harness='h', model='m', route='r')], 0, ['s']),
        ([dict(id='a', harness='h', model='m', route='r')], 1, ['s', 'missing'])]:
        with pytest.raises(state.StateError):
            evals.run_create(pg_store, title='Bad', sets=selections, configurations=configs, repeats=repeats)
    assert evals.run_list(pg_store) == []


def test_size_renames_binary_quoted_paths_and_deletions():
    patch = ('diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n'
             'diff --git a/image.png b/image.png\nBinary files a/image.png and b/image.png differ\n'
             'diff --git "a/\\303\\251.py" "b/\\303\\251.py"\n'
             '--- "a/\\303\\251.py"\n+++ "b/\\303\\251.py"\n@@ -1,25 +1,26 @@\n' +
             '-old\n' * 25 + '+new\n' * 26 + '-- \nSynthetic mail trailer\n')
    assert evals.size(None, patch) == 'M'
    assert evals.size(None, patch, ['é.py']) == 'M'
    assert evals.size(None, patch, ['old.py', 'image.png']) == 'S'


@pytest.fixture
def starts_cases(pg_store, cases, start_chain):  # noqa: F811 - shared pytest fixtures
    folder, source = cases
    source.update(repository='example/repo', base_commit=start_chain['base'])
    (folder / 'synthetic.json').write_text(json.dumps(source))
    evals.import_folder(pg_store, folder)
    return folder, start_chain


def test_import_starts_records_atomic_metadata_and_cli(pg_store, starts_cases, monkeypatch, capsys):  # noqa: F811 - shared pytest fixture
    folder, d = starts_cases
    bundle, commits = d['build']()
    assert all(row['has_start'] == 'no' for row in evals.case_list(pg_store))
    monkeypatch.setattr('cplane.fence.Fence', lambda: d['adapter'])
    assert main(['eval', 'starts', str(bundle), '--pr', 'example/repo#53']) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == {'updated': 2, 'unchanged': 0}
    assert 'synthetic' not in output and commits[0] not in output
    with pg_store.locked():
        rows = evals._rows(pg_store, 'SELECT * FROM cplane_eval_cases ORDER BY id')
    assert [r['start_commit'] for r in rows] == commits[:-1]
    assert [r['start_branch'] for r in rows] == ['eval/pr53-t1', 'eval/pr53-t2']
    assert [r['pinned_paths'] for r in rows] == [['pinned test.py']] * 2
    assert all(row['has_start'] == 'yes' for row in evals.case_list(pg_store))
    assert evals.import_starts(pg_store, bundle, 'example/repo#53', adapter=d['adapter']) == {'updated': 0, 'unchanged': 2}
    # Normal case import preserves start fields, including when updating task text.
    assert evals.import_folder(pg_store, folder) == {'inserted': 0, 'updated': 0, 'unchanged': 2}
    path = folder / 'synthetic.json'
    source = json.loads(path.read_text())
    source['tickets'][0]['change'] = 'Updated task'
    path.write_text(json.dumps(source))
    assert evals.import_folder(pg_store, folder) == {'inserted': 0, 'updated': 1, 'unchanged': 1}
    with pg_store.locked():
        after = evals._rows(pg_store, 'SELECT * FROM cplane_eval_cases ORDER BY id')
    for before, saved in zip(rows, after, strict=True):
        assert all(before[k] == saved[k] for k in ('start_commit', 'start_branch', 'pinned_paths', 'created_at'))


def test_import_starts_push_failure_rolls_back_pr_and_retry_recovers(pg_store, starts_cases, monkeypatch):  # noqa: F811 - shared pytest fixture
    _, d = starts_cases
    bundle, _ = d['build']()
    git = d['adapter'].git
    def fail_second(clean, *args, **kwargs):
        if args[0] == 'push' and args[-1].endswith(':refs/heads/eval/pr53-t2'):
            raise state.StateError('synthetic push failure')
        return git(clean, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(d['adapter'], 'git', fail_second)
        with pytest.raises(state.StateError, match='synthetic push failure'):
            evals.import_starts(pg_store, bundle, 'example/repo#53', adapter=d['adapter'])
    assert all(row['has_start'] == 'no' for row in evals.case_list(pg_store))
    with pg_store.locked():
        assert all(row['start_branch'] is None and row['pinned_paths'] is None for row in
                   evals._rows(pg_store, 'SELECT start_branch, pinned_paths FROM cplane_eval_cases'))
    assert evals.import_starts(pg_store, bundle, 'example/repo#53', adapter=d['adapter']) == {'updated': 2, 'unchanged': 0}


def test_starts_migration_preserves_existing_rows_and_checks_types(pg_store, cases):  # noqa: F811 - shared pytest fixture
    evals.import_folder(pg_store, cases[0])
    with pg_store.mutation():
        pg_store.connection.execute('ALTER TABLE cplane_eval_cases DROP COLUMN start_commit, '
                                    'DROP COLUMN start_branch, DROP COLUMN pinned_paths')
        pg_store.connection.execute("DELETE FROM cplane_migrations WHERE name='028_eval_starts.sql'")
    pg_store.migrate()
    pg_store.migrate()
    with pg_store.locked():
        assert pg_store.connection.execute(
            "SELECT count(*) FROM cplane_migrations WHERE name='028_eval_starts.sql'").fetchone()[0] == 1
        assert pg_store.connection.execute('SELECT count(*) FROM cplane_eval_cases WHERE start_commit IS NULL '
                                          'AND start_branch IS NULL AND pinned_paths IS NULL').fetchone()[0] == 2
    for sql in ["start_commit='invalid'", "pinned_paths=ARRAY['path',NULL]", "pinned_paths='not-an-array'", "pinned_paths=ARRAY[['a'],['b']]"]:
        with pytest.raises(state.StateError), pg_store.mutation():
            pg_store.connection.execute('UPDATE cplane_eval_cases SET ' + sql)


def test_platform_migration_and_import_backfill(pg_store, cases):  # noqa: F811
    evals.import_folder(pg_store, cases[0])
    with pg_store.mutation():
        before = evals._rows(pg_store, 'SELECT * FROM cplane_eval_cases ORDER BY id')
        pg_store.connection.execute('ALTER TABLE cplane_eval_cases DROP COLUMN allowed_files')
        pg_store.connection.execute('ALTER TABLE cplane_eval_attempts DROP COLUMN platform_task')
        pg_store.connection.execute("DELETE FROM cplane_migrations WHERE name='029_eval_platform.sql'")
    pg_store.migrate()
    pg_store.migrate()
    with pg_store.locked():
        assert pg_store.connection.execute(
            "SELECT count(*) FROM cplane_migrations WHERE name='029_eval_platform.sql'").fetchone()[0] == 1
        assert pg_store.connection.execute('SELECT count(*) FROM cplane_eval_cases WHERE allowed_files IS NULL').fetchone()[0] == 2
    assert evals.import_folder(pg_store, cases[0]) == {'inserted': 0, 'updated': 2, 'unchanged': 0}
    with pg_store.locked():
        after = evals._rows(pg_store, 'SELECT * FROM cplane_eval_cases ORDER BY id')
    assert [r['allowed_files'] for r in after] == [['small.py'], ['large.py']]
    assert before == after
    assert evals.import_folder(pg_store, cases[0]) == {'inserted': 0, 'updated': 0, 'unchanged': 2}


@pytest.mark.parametrize('problem', ['codex', 'claude', 'start', 'route', 'name', 'missing'])
def test_ticket_platform_planning_refusals_are_atomic(pg_store, cases, problem):  # noqa: F811
    evals.import_folder(pg_store, cases[0])
    evals.set_create(pg_store, 's', title='S', filters={})
    config = {'id': 'pi-base', 'harness': 'pi', 'model': 'base', 'route': 'platform', 'configuration': 'base'}
    if problem in ('codex', 'claude'):
        config['harness'] = problem
        with pg_store.mutation():
            pg_store.connection.execute('UPDATE cplane_eval_cases SET start_commit=%s', ('b' * 40,))
    elif problem == 'route':
        config['route'] = 'fence'
    elif problem == 'name':
        config['configuration'] = 'bad/name'
    elif problem == 'missing':
        del config['configuration']
    message = ('tickets require' if problem in ('codex', 'claude') else
               'ticket requires a start commit' if problem == 'start' else 'Pi requires')
    with pytest.raises(state.StateError, match=message):
        evals.run_create(pg_store, title='Bad', sets=['s'], configurations=[config], repeats=1)
    assert evals.run_list(pg_store) == []
    with pg_store.locked():
        assert pg_store.connection.execute('SELECT count(*) FROM cplane_eval_attempts').fetchone()[0] == 0


@pytest.mark.parametrize(('path', 'roles'), [
    ('slice', {'executor': {'harness': 'codex', 'model': 'synthetic', 'effort': 'medium'},
               'reviewer': {'harness': 'claude', 'model': 'synthetic'}}),
    ('tickets', {role: {'configuration': 'pi/synthetic-1.0_test'} for role in ('cutter', 'ticket', 'reviewer')})])
def test_named_configurations_are_stored_once(pg_store, path, roles):
    config = evals.config_add(pg_store, path, path=path, roles=roles, note='Synthetic', actor='planner')
    assert config['id'] == path and config['path'] == path and config['roles'] == roles
    assert config['note'] == 'Synthetic' and config['created_by'] == 'planner' and config['created_at']
    assert evals.config_list(pg_store) == [config]
    assert evals.config_show(pg_store, path) == config
    for replacement in (roles, {role: {'configuration': 'pi/other'} for role in roles}):
        with pytest.raises(state.StateError, match='already exists'):
            evals.config_add(pg_store, path, path=path, roles=replacement)
    for sql in ["UPDATE cplane_eval_configurations SET note='changed'", 'DELETE FROM cplane_eval_configurations']:
        with pytest.raises(state.StateError), pg_store.mutation():
            pg_store.connection.execute(sql)
    assert evals.config_show(pg_store, path) == config
    with pytest.raises(state.StateError, match='not found'):
        evals.config_show(pg_store, 'missing')


@pytest.mark.parametrize(('path', 'roles'), [
    ('other', {}), ('slice', {}), ('tickets', {'executor': {}, 'reviewer': {}}),
    ('slice', {'executor': {}, 'reviewer': {}, 'ticket': {}}),
    ('slice', []), ('slice', {'executor': None, 'reviewer': {}}),
])
def test_configuration_role_sets_are_refused(path, roles):
    with pytest.raises(state.StateError):
        evals.validate_configuration(path, roles)


@pytest.mark.parametrize('entry', [
    {'harness': 'codex', 'model': 'synthetic'},
    {'harness': 'codex', 'model': 'synthetic', 'effort': ' '},
    {'harness': 'codex', 'model': 42, 'effort': 'medium'},
    {'harness': 'unknown', 'model': 'synthetic'},
    {'harness': 'claude', 'model': 'synthetic', 'effort': 'medium'},
    {'harness': 'claude', 'model': ''},
    {'configuration': 'pi/bad/name'}, {'configuration': 'base'},
    {'configuration': 'pi/-bad'}, {'configuration': 'pi/' + 'a' * 65},
    {'configuration': 'pi/good', 'model': 'synthetic'}, {'configuration': None},
    {'harness': 'pi', 'configuration': 'pi/base'},
])
def test_invalid_executor_entries_are_refused_without_writes(pg_store, entry):
    with pytest.raises(state.StateError):
        evals.config_add(pg_store, 'bad', path='slice',
                         roles={'executor': entry, 'reviewer': {'configuration': 'pi/base'}})
    assert evals.config_list(pg_store) == []


def test_configuration_cli(pg_store, capsys):
    command = ['eval', 'config', 'add', 'synthetic', '--path', 'slice',
               '--role', 'executor={"harness":"codex","model":"synthetic","effort":"medium"}',
               '--role', 'reviewer={"configuration":"pi/base"}', '--note', 'Synthetic', '--actor', 'planner']
    assert main(command) == 0
    config = json.loads(capsys.readouterr().out)
    assert config['created_by'] == 'planner' and config['note'] == 'Synthetic'
    assert main(['eval', 'config', 'list']) == 0
    assert json.loads(capsys.readouterr().out) == [config]
    assert main(['eval', 'config', 'show', 'synthetic']) == 0
    assert json.loads(capsys.readouterr().out) == config
    for suffix in ([], ['--role', 'executor={"configuration":"pi/other"}']):
        assert main(command + suffix) == 1
        assert capsys.readouterr().err
    for role in ('executor', 'executor=not-json', 'executor=[]'):
        assert main(['eval', 'config', 'add', 'bad', '--path', 'slice', '--role', role]) == 1
        assert capsys.readouterr().err
    assert evals.config_list(pg_store) == [config]


@pytest.mark.parametrize('grade', ['tests_and_judge', 'judge'])
def test_slice_metadata_import_and_preservation(pg_store, cases, grade):
    folder, source = cases
    source.pop('tickets')
    metadata = dict(source_slice='factory/E6', merge_commit='b' * 40, hidden_paths=['tests/test_synthetic.py'],
                    grade=grade, validation='Synthetic qualification: the brief fixes the tested names.')
    source.update(kind='slice', level='strong', title='Synthetic slice', change='Synthetic brief',
                  tag_kind='change', language='python', **metadata)
    file = folder / 'synthetic.json'
    file.write_text(json.dumps(source))
    assert evals.import_folder(pg_store, folder) == dict(inserted=1, updated=0, unchanged=0)
    case, = evals.case_list(pg_store)
    assert case['level'] == 'strong'
    assert {k: case[k] for k in metadata} == metadata
    assert evals.import_folder(pg_store, folder) == dict(inserted=0, updated=0, unchanged=1)
    for k in metadata:
        del source[k]
    source['change'] = 'Updated brief'
    file.write_text(json.dumps(source))
    assert evals.import_folder(pg_store, folder)['updated'] == 1
    assert evals.case_list(pg_store) == [case]
    source.update({k: None for k in metadata})
    file.write_text(json.dumps(source))
    assert evals.import_folder(pg_store, folder)['updated'] == 1
    assert all(evals.case_list(pg_store)[0][k] is None for k in metadata)


@pytest.mark.parametrize(('field', 'value'), [
    ('source_slice', 'no-slice'), ('source_slice', 'too/many/parts'), ('merge_commit', 'not-a-commit'),
    ('hidden_paths', 'tests/test.py'), ('hidden_paths', [None]), ('hidden_paths', [['nested']]),
    ('grade', 'tests'), ('validation', ' '),
])
def test_invalid_slice_metadata_is_atomic(pg_store, cases, field, value):
    folder, source = cases
    source['tickets'][1][field] = value
    (folder / 'synthetic.json').write_text(json.dumps(source))
    with pytest.raises(state.StateError, match=f'invalid {field}'):
        evals.import_folder(pg_store, folder)
    assert evals.case_list(pg_store) == []


def test_attempt_runs_order_and_uniqueness(pg_store, cases):
    evals.import_folder(pg_store, cases[0])
    with pg_store.mutation():
        pg_store.connection.execute('UPDATE cplane_eval_cases SET start_commit=%s', ('b' * 40,))
    evals.set_create(pg_store, 's', title='Synthetic', filters={})
    run = evals.run_create(pg_store, title='Synthetic', sets=['s'], repeats=1,
                          configurations=[dict(id='pi', harness='pi', model='base', route='platform', configuration='base')])
    attempt, other = [a['id'] for a in run['attempts']]
    records = [evals.attempt_run_add(pg_store, attempt, position=position, role='ticket', purpose='execute', run_id=run_id)
               for position, run_id in [(3, 'platform-c'), (1, 'platform-a'), (2, 'platform-b')]]
    assert evals.attempt_run_list(pg_store, attempt) == sorted(records, key=lambda r: r['position'])
    assert evals.attempt_run_list(pg_store, other) == []
    for position, run_id in [(4, 'platform-a'), (1, 'platform-new')]:
        with pytest.raises(state.StateError):
            evals.attempt_run_add(pg_store, attempt, position=position, role='ticket', purpose='execute', run_id=run_id)
    evals.attempt_run_add(pg_store, attempt, position=4, role='check', purpose='grade', run_id='platform-a')
    evals.attempt_run_add(pg_store, other, position=1, role='ticket', purpose='execute', run_id='platform-a')
    assert evals.run_show(pg_store, run['id']) == run  # Legacy attempt links/output stay unchanged.


def test_records_migration_preserves_populated_legacy_store(request, monkeypatch, tmp_path, cases):
    # Start from migrations through 031, rather than empty tables already at 032.
    from cplane import stores
    old = tmp_path / 'old' / 'migrations'
    old.mkdir(parents=True)
    for migration in Path('cplane/migrations').glob('*.sql'):
        if migration.name < '032':
            shutil.copyfile(migration, old / migration.name)
    with monkeypatch.context() as patch:
        patch.setattr(stores, 'files', lambda _: old.parent)
        store = request.getfixturevalue('pg_store')
    evals.import_folder(store, cases[0])
    with store.mutation():
        store.connection.execute('UPDATE cplane_eval_cases SET start_commit=%s', ('b' * 40,))
        store.connection.execute("INSERT INTO cplane_eval_sets VALUES ('legacy','Legacy','')")
        evals._version(store, 'legacy', 1, ['example/public#53/1', 'example/public#53/2'], {}, '', 'planner')
    run = evals.run_create(store, title='Legacy', sets=['legacy'], repeats=1, configurations=[
        dict(id='pi-base', harness='pi', model='base', route='platform', configuration='base')])
    with store.mutation():
        record_id = store.connection.execute(
            "INSERT INTO cplane_run_records (turn_key,kind,tool) VALUES ('legacy','slice','codex') RETURNING id").fetchone()[0]
        store.connection.execute("UPDATE cplane_eval_runs SET state='done'")
        store.connection.execute("UPDATE cplane_eval_attempts SET state='done', platform_task=123, run_record=%s", (record_id,))
        before_cases = evals._rows(store, 'SELECT * FROM cplane_eval_cases ORDER BY id')
    evals.verdict_add(store, run['attempts'][0]['id'], judge='synthetic@1', prompt_hash='legacy',
                      verdict='mergeable', reason='Synthetic legacy verdict')
    before_run = evals.run_show(store, run['id'])
    # Completed pre-catalogue Codex runs keep their original inline shape too.
    from psycopg.types.json import Jsonb
    legacy_codex = [dict(id='codex-luna', harness='codex', model='gpt-6-luna', route='fence', effort='medium')]
    with store.mutation():
        codex_id = store.connection.execute(
            'INSERT INTO cplane_eval_runs (title,created_by,repeats,set_versions,configurations,state) '
            "VALUES ('Legacy Codex','planner',1,'[]',%s,'done') RETURNING id", (Jsonb(legacy_codex),)).fetchone()[0]
    before_codex = evals.run_show(store, codex_id)
    before_runs = evals.run_list(store)
    store.migrate()
    store.migrate()
    assert evals.run_show(store, run['id']) == before_run
    assert evals.run_show(store, codex_id) == before_codex
    assert evals.run_list(store) == before_runs
    with store.locked():
        after_cases = evals._rows(store, 'SELECT * FROM cplane_eval_cases ORDER BY id')
        assert [{k: r[k] for k in before_cases[0]} for r in after_cases] == before_cases
        assert all(r[k] is None for r in after_cases for k in evals.SLICE_FIELDS)
    assert len(evals.case_list(store)) == 2
    assert evals.config_list(store) == []
    assert evals.attempt_run_list(store, before_run['attempts'][0]['id']) == []
    # Database checks remain effective for the extended level and path domains.
    for sql in ["UPDATE cplane_eval_cases SET kind='slice', level='invalid'",
                "UPDATE cplane_eval_cases SET level='strong'",
                "INSERT INTO cplane_eval_configurations (id,path,roles,created_by) VALUES ('bad','other','{}','test')",
                "UPDATE cplane_eval_cases SET grade='invalid'"]:
        with pytest.raises(state.StateError), store.mutation():
            store.connection.execute(sql)


@pytest.fixture
def slice_case(pg_store, tmp_path):
    import subprocess
    from psycopg.types.json import Jsonb
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True, capture_output=True)
    git('init')
    git('config', 'user.email', 'synthetic@example.com')
    git('config', 'user.name', 'Synthetic')
    (tmp_path / 'briefs').mkdir()
    (tmp_path / 'briefs' / 'one.md').write_text('Synthetic brief\n')
    git('add', '.')
    git('commit', '-m', 'brief')
    git('rm', 'briefs/one.md')
    git('commit', '-m', 'accept')
    item = dict(id='project/one', repo='example/repo', pr=12, title='Synthetic', brief='briefs/one.md')
    with pg_store.mutation():
        pg_store.connection.execute('INSERT INTO cplane_slices (id, position, document) VALUES (%s, 1, %s)',
                                    (item['id'], Jsonb(item)))
        pg_store.connection.execute("INSERT INTO cplane_slice_outcomes (slice_id, verdict) VALUES (%s, 'accepted')", (item['id'],))
        pg_store.connection.execute("INSERT INTO cplane_slice_levels (slice_id, level) VALUES (%s, 'light')", (item['id'],))
    class Reader:
        merged = True
        paths = ['src/code.py', 'tests/test_code.py']
        def __call__(self, repo, path, **kwargs):
            assert repo == 'example/repo'
            if path == 'pulls/12':
                return json.dumps(dict(merged_at='2026-01-01' if self.merged else None, merge_commit_sha='b' * 40))
            if path.startswith('commits/'):
                return json.dumps(dict(parents=[dict(sha='a' * 40)]))
            if path.startswith('compare/'):
                return patch_file('src/code.py', 2) + patch_file('tests/test_code.py', 2)
            return json.dumps([dict(filename=p) for p in self.paths])
    return pg_store, tmp_path, Reader()


def build_slice(fixture, **kwargs):
    store, root, reader = fixture
    options = dict(kind='fix', check='pytest', grade='tests_and_judge', validation='Reviewed')
    options.update(kwargs)
    return evals.case_from_slice(store, 'project/one', root, reader=reader, **options)


def test_case_from_slice_deleted_brief_and_idempotence(slice_case, capsys):
    case = build_slice(slice_case)
    assert (case['task'], case['base_commit'], case['merge_commit']) == ('Synthetic brief\n', 'a' * 40, 'b' * 40)
    assert (case['level'], case['language'], case['hidden_paths']) == ('light', 'python', ['tests/test_code.py'])
    assert case['size'] == 'S' and case['source_slice'] == 'project/one'
    assert build_slice(slice_case, validation='Different') == case
    assert 'unchanged' in capsys.readouterr().err


def test_case_from_slice_hidden_override(slice_case):
    assert build_slice(slice_case, hidden=['custom/check.py'])['hidden_paths'] == ['custom/check.py']


@pytest.mark.parametrize('failure', ['unaccepted', 'unmerged', 'corrected', 'brief', 'hidden', 'language'])
def test_case_from_slice_refusals(slice_case, failure):
    store, root, reader = slice_case
    if failure == 'unaccepted':
        with store.mutation():
            store.connection.execute("UPDATE cplane_slice_outcomes SET verdict='corrected'")
    elif failure == 'unmerged':
        reader.merged = False
    elif failure == 'corrected':
        with store.mutation():
            store.connection.execute("INSERT INTO cplane_slice_outcomes (slice_id, corrects_slice) VALUES ('project/two', 'project/one')")
    elif failure == 'brief':
        from psycopg.types.json import Jsonb
        with store.mutation():
            store.connection.execute("UPDATE cplane_slices SET document = document || %s", (Jsonb({'brief': 'missing.md'}),))
    elif failure == 'hidden':
        reader.paths = ['src/code.py']
    else:
        reader.paths = ['readme.md']
    with pytest.raises(state.StateError):
        build_slice(slice_case)
    assert evals.case_list(store) == []
