"""Synthetic tables and real temporary remotes, never private planning data."""
import os
from pathlib import Path
import subprocess

import pytest

from cplane import fence, planning
from cplane.backlog import generated_table, parse
from cplane.feature_export import FeatureExport
from cplane.state import StateError
from test_stores import pg_store

HEADER = '| Feature | Kind | Area | Repo | Horizon | Order | Slices | Readiness | Depends on |\r\n'
SEPARATOR = '| --- | --- | --- | --- | --- | --- | --- | --- | --- |\r\n'
TABLE = ('Hand-written introduction.\r\n\r\n' + HEADER + SEPARATOR +
         '| **Synthetic** [link](https://example.invalid) `code` | idea | lab | factory | later | 1 | A | waiting | — |\r\n'
         '| Second \\| text | idea | lab | — | next | 2 | B | ready to plan | `x|y` |\r\n'
         '\r\nHand-written ending.\r\n')


def features():
    rows, report = parse(TABLE, [('FAC', 'factory'), ('NEW', None)])
    assert not report['unparsed_rows']
    return [dict(row, id=f"{row['project']}-F1", sections=[]) for row in rows]


def test_roundtrip_and_stage():
    items = features()
    assert generated_table(TABLE, items).encode() == TABLE.encode()
    items[0]['stage'] = 'building'
    assert generated_table(TABLE, items) == TABLE.replace('| later |', '| now |')
    rows, report = parse(TABLE.replace('| later |', '| unknown |'), [('FAC', 'factory')])
    assert report['rows_found'] == 2
    assert report['unparsed_rows'] == [5]
    assert len(rows) == 1
    _, report = parse(TABLE, [])
    assert report['repositories_with_no_key'] == ['factory']


def test_import_transaction_and_projects(pg_store):
    store = pg_store
    before = store.feature_export_snapshot()
    report = store.feature_import_backlog(TABLE, dry_run=True)
    assert report['rows_found'] == 2
    assert report['rows_per_stage'] == {'parked': 1, 'ready': 1}
    assert store.feature_export_snapshot() == before
    for bad in (TABLE.replace('| later |', '| unknown |'), TABLE.replace('| factory |', '| missing |')):
        with pytest.raises(StateError, match='refused'):
            store.feature_import_backlog(bad)
        assert store.feature_export_snapshot() == before
    store.feature_import_backlog(TABLE, actor='planner')
    items = store.feature_export_snapshot()
    assert generated_table(TABLE, items) == TABLE
    assert items[0]['parked_from'] == 'shortlist'
    with pytest.raises(StateError, match='already exist'):
        store.feature_import_backlog(TABLE)
    store.project_add('XYZ', 'Synthetic project', repository='synthetic', actor='planner')
    assert store.feature_add('XYZ', 'New')['id'] == 'XYZ-F1'
    with pytest.raises(StateError):
        store.project_add('BAD', 'Duplicate', repository='synthetic')
    with store.locked():
        assert store.connection.execute('SELECT actor FROM cplane_project_events').fetchone()[0] == 'planner'


@pytest.fixture
def publication(tmp_path, monkeypatch):
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
    root = tmp_path / 'clean'
    root.mkdir(mode=0o700)
    monkeypatch.setattr(fence, 'CLEAN_ROOT', root)
    monkeypatch.setenv('CPLANE_PLANNING_REMOTE', 'git@github.com:synthetic/example.git')
    real_run = subprocess.run

    def git(repo, *args):
        return real_run(['git', '-C', str(repo), '-c', 'user.name=Synthetic', '-c',
                         'user.email=synthetic@example.invalid', *map(str, args)],
                        check=True, capture_output=True, text=True).stdout.strip()

    seed = tmp_path / 'seed'
    seed.mkdir()
    git(seed, 'init', '-b', 'main')
    (seed / 'backlog.md').write_bytes(TABLE.encode())
    git(seed, 'add', '.')
    git(seed, 'commit', '-m', 'seed')
    remote = tmp_path / 'remote.git'
    git(seed, 'clone', '--bare', seed, remote)
    calls = []

    def execute(args, **kwargs):
        calls.append((args, kwargs))
        ssh = kwargs.get('env', {}).get('GIT_SSH_COMMAND', '')
        if 'push' in args:
            assert str(planning.WRITE_KEY) in ssh
        else:
            assert str(planning.WRITE_KEY) not in ssh
        if 'fetch' in args:
            assert str(planning.READ_KEY) in ssh
        if args[-3:-1] == ['add', 'origin']:
            args = [*args[:-1], str(remote)]
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', execute)
    return FeatureExport(), git, remote, seed, calls


def test_publish_switch_off_and_idempotent(publication):
    adapter, git, remote, _, calls = publication
    adapter.publish(features(), False)
    assert git(remote, 'show', 'main:backlog.md').replace('\r', '') == TABLE.strip().replace('\r', '')
    assert '# **Synthetic**' in git(remote, 'show', 'main:features/FAC-F1.md')
    assert git(remote, 'rev-list', '--count', 'main') == '2'
    # A fresh scheduled invocation owns a fresh clean directory.
    FeatureExport().publish(features(), False)
    assert git(remote, 'rev-list', '--count', 'main') == '2'


def test_empty_export(publication):
    adapter, git, remote, _, _ = publication
    adapter.publish([], False)
    assert git(remote, 'rev-list', '--count', 'main') == '1'


def test_generated_roundtrip(publication):
    adapter, git, remote, _, _ = publication
    adapter.publish(features(), True)
    content = subprocess.run(['git', '-C', str(remote), 'show', 'main:backlog.md'], capture_output=True, check=True).stdout
    assert content == TABLE.encode()


def test_outside_path_refused(publication, monkeypatch):
    adapter, git, remote, _, calls = publication
    render = adapter.render

    def tamper(*args):
        (adapter.clean / 'outside.md').write_text('unwanted')
        adapter.git('add', '--', 'outside.md')
        render(*args)

    monkeypatch.setattr(adapter, 'render', tamper)
    with pytest.raises(StateError, match='refused'):
        adapter.publish(features(), False)
    assert not any('push' in args for args, _ in calls)
    assert git(remote, 'rev-list', '--count', 'main') == '1'


@pytest.mark.parametrize('always_reject', [False, True])
def test_rejected_push_retried_once(publication, monkeypatch, always_reject):
    adapter, git, remote, seed, calls = publication
    execute = subprocess.run
    pushes = []

    def race(args, **kwargs):
        if 'push' in args:
            pushes.append(args)
            if len(pushes) == 1:
                (seed / 'other.md').write_text('concurrent writer\n')
                git(seed, 'add', '.')
                git(seed, 'commit', '-m', 'concurrent')
                git(seed, 'push', remote, 'main')
            if always_reject:
                return subprocess.CompletedProcess(args, 1, '[rejected]', 'private text')
        return execute(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', race)
    if always_reject:
        with pytest.raises(StateError, match='push failed'):
            adapter.publish(features(), False)
    else:
        adapter.publish(features(), False)
        assert git(remote, 'show', 'main:other.md') == 'concurrent writer'
        assert git(remote, 'rev-list', '--count', 'main') == '3'
    assert len(pushes) == 2
    assert len([args for args, _ in calls if 'fetch' in args]) == 2


@pytest.mark.parametrize(('horizon', 'readiness', 'stage'), [
    ('now', 'waiting', 'building'), ('next', 'ready now', 'ready'),
    ('next', 'waiting', 'shortlist'), ('later', 'waiting', 'parked'),
    ('parked', 'waiting', 'parked'), ('done', 'waiting', 'done'),
])
def test_mapping(horizon, readiness, stage):
    from cplane.backlog import stage_for
    assert stage_for(['title', '', '', '—', horizon, '', '', readiness, '']) == stage


def test_atomic_rollback_and_cli(pg_store, monkeypatch, tmp_path, capsys):
    from cplane.cli import main
    path = tmp_path / 'backlog.md'
    path.write_bytes(TABLE.encode())
    assert main(['feature', 'import-backlog', str(path), '--dry-run']) == 0
    assert 'rows_found' in capsys.readouterr().out
    original = pg_store.feature_add
    count = 0

    def fail_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise StateError('Synthetic failure')
        return original(*args, **kwargs)

    monkeypatch.setattr(pg_store, 'feature_add', fail_second)
    with pytest.raises(StateError, match='Synthetic'):
        pg_store.feature_import_backlog(TABLE)
    assert pg_store.feature_list() == []
    assert main(['project', 'add', 'XYZ', 'Synthetic', '--repository', 'synthetic', '--actor', 'planner']) == 0
    assert 'XYZ' in capsys.readouterr().out
    assert main(['feature', 'import-backlog', str(path)]) == 0
    capsys.readouterr()
    assert len(pg_store.feature_list()) == 2


def test_non_rejection_is_not_retried(publication, monkeypatch):
    adapter, _, _, _, _ = publication
    execute = subprocess.run
    pushes = []

    def fail(args, **kwargs):
        if 'push' in args:
            pushes.append(args)
            return subprocess.CompletedProcess(args, 1, '', 'private authentication failure')
        return execute(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', fail)
    with pytest.raises(StateError, match='push failed'):
        adapter.publish(features(), False)
    assert len(pushes) == 1


def test_symlink_refused(publication):
    adapter, git, remote, seed, _ = publication
    (seed / 'features').symlink_to('/nonexistent')
    git(seed, 'add', '.')
    git(seed, 'commit', '-m', 'synthetic symlink')
    git(seed, 'push', remote, 'main')
    with pytest.raises(StateError, match='refused'):
        adapter.publish(features(), False)


def test_timer_wrapper_sanitizes_errors(tmp_path):
    executable = tmp_path / 'factory-cplane'
    executable.write_text('#!/bin/sh\necho "private database diagnostic" >&2\nexit 1\n')
    executable.chmod(0o755)
    script = Path(__file__).resolve().parents[1] / 'node/bin/factory-feature-export'
    result = subprocess.run([str(script)], env=os.environ | {'PATH': f'{tmp_path}:/usr/bin:/bin'},
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert result.stdout == ''
    assert result.stderr == 'Factory feature export failed\n'
