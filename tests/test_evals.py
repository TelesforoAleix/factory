"""Synthetic eval catalogue, versioning and expansion on CI's Postgres 17."""
import hashlib
import json

import pytest

from cplane import evals, state
from cplane.cli import main
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
    configurations = [dict(id=str(n), harness='codex', model='synthetic', route='test') for n in range(3)]
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
    assert main(['eval', 'run', 'create', '--title', 'CLI', '--set', 'cli', '--configuration',
                 '{"id":"a","harness":"codex","model":"synthetic","route":"test"}',
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
