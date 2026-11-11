"""Real synthetic repositories at the bundle/host trust boundary; no Docker/network."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from cplane import fence, planning, sessions
from cplane.state import StateError


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
    monkeypatch.setattr(fence, 'CLI_UID', os.getuid())
    monkeypatch.setattr(fence, 'CLI_GID', os.getgid())
    clean_root = tmp_path / 'clean'
    clean_root.mkdir(mode=0o700)
    monkeypatch.setattr(fence, 'CLEAN_ROOT', clean_root)
    monkeypatch.setenv('CPLANE_PLANNING_REMOTE', 'git@github.com:synthetic/planning.git')
    for role in ('AUTHOR', 'COMMITTER'):
        monkeypatch.setenv(f'GIT_{role}_NAME', 'Synthetic')
        monkeypatch.setenv(f'GIT_{role}_EMAIL', 'synthetic@example.invalid')
    real_run = subprocess.run

    def git(repo, *args):
        return real_run(['git', '-C', str(repo), '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                         *map(str, args)], capture_output=True, text=True, check=True).stdout.strip()

    seed = tmp_path / 'seed'
    seed.mkdir(mode=0o700)
    git(seed, 'init', '-b', 'main', '--template=')
    (seed / 'brief.md').write_text('base\n')
    git(seed, 'add', '.')
    git(seed, 'commit', '-m', 'base')
    remote = tmp_path / 'remote.git'
    git(seed, 'clone', '--bare', seed, remote)
    adapter = planning.Planning(dict(id=1, area='homelab'))
    copy = tmp_path / 'copy'
    run = tmp_path / 'run'
    run.mkdir(mode=0o700)
    (run / 'io').mkdir(mode=0o700)
    calls = []
    selected = [None]

    def execute(args, **kwargs):
        calls.append((args, kwargs))
        for key in (planning.READ_KEY, planning.WRITE_KEY):
            assert str(key) not in str(args)
            assert str(key) not in str(kwargs.get('cwd', ''))
        ssh = kwargs.get('env', {}).get('GIT_SSH_COMMAND', '')
        if ssh:
            key = planning.WRITE_KEY if 'push' in args else planning.READ_KEY
            assert 'push' in args or 'fetch' in args
            assert f'-i {key}' in ssh
            assert '-o IdentitiesOnly=yes' in ssh
            assert f'-o UserKnownHostsFile={planning.KNOWN_HOSTS}' in ssh
        if args[0] == os.environ.get('CPLANE_FENCE_COMMAND', 'factory-cli'):
            assert not ssh
        if args[0] == os.environ.get('CPLANE_FENCE_COMMAND', 'factory-cli'):
            assert args[1] == 'bundle'
            if selected[0]:
                shutil.copyfile(selected[0], run / 'io/branch.bundle')
            else:
                git(copy, 'bundle', 'create', run / 'io/branch.bundle', 'HEAD',
                    'refs/heads/' + adapter.branch)
            return subprocess.CompletedProcess(args, 0)
        assert args[:3] == ['git', '-C', str(adapter.clean)], 'host Git entered untrusted copy'
        if 'remote' in args and args[-3:-1] == ['add', 'origin']:
            args = [*args[:-1], str(remote)]
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', execute)
    adapter.prepare(copy)
    base = git(remote, 'rev-parse', 'main')
    marker = tmp_path / 'HOST-HOOK-RAN'
    for repo in (copy, adapter.clean):
        hooks = repo / '.git/hooks'
        hooks.mkdir(exist_ok=True)
        for hook in ('pre-push', 'post-checkout', 'pre-rebase', 'post-rewrite', 'monitor'):
            script = hooks / hook
            script.write_text('#!/bin/sh\ntouch ' + str(marker) + '\n')
            script.chmod(0o755)
        git(repo, 'config', 'core.fsmonitor', str(hooks / 'monitor'))
    calls.clear()
    return dict(adapter=adapter, copy=copy, run=run, git=git, remote=remote, seed=seed,
                base=base, marker=marker, calls=calls, selected=selected, root=tmp_path)


def commit(d, name='brief.md', text='session\n'):
    path = d['copy'] / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    d['git'](d['copy'], 'add', '.')
    d['git'](d['copy'], 'commit', '-m', 'session change')
    return d['git'](d['copy'], 'rev-parse', 'HEAD')


def publish(d):
    return d['adapter'].deliver(d['copy'], d['run'])


def test_delivery_no_hooks_credentials_or_replay(delivery, caplog, monkeypatch):
    monkeypatch.setenv('CPLANE_FENCE_COMMAND', 'homelab-fence')
    d = delivery
    tip = commit(d)
    assert publish(d) == [tip]
    assert any(args[:2] == ['homelab-fence', 'bundle'] for args, _ in d['calls'])
    assert d['git'](d['remote'], 'rev-parse', 'main') == tip
    assert publish(d) == []
    tip2 = commit(d, 'next.md', 'next\n')
    assert publish(d) == [tip2]
    assert not d['marker'].exists()
    pushes = [(args, kw) for args, kw in d['calls'] if 'push' in args]
    assert len(pushes) == 2
    assert all(str(planning.WRITE_KEY) in kw['env']['GIT_SSH_COMMAND'] for _, kw in pushes)
    assert all(str(planning.WRITE_KEY) not in str(kw.get('env', {}))
               for args, kw in d['calls'] if 'push' not in args)
    fetches = [(args, kw) for args, kw in d['calls']
               if 'fetch' in args and 'origin' in args]
    assert len(fetches) == 2
    assert all(str(planning.READ_KEY) in kw['env']['GIT_SSH_COMMAND'] for _, kw in fetches)
    assert all(str(planning.READ_KEY) not in str(kw.get('env', {}))
               for args, kw in d['calls'] if not ('fetch' in args and 'origin' in args))
    for key in (planning.READ_KEY, planning.WRITE_KEY):
        assert str(key) not in caplog.text
    for path in d['root'].rglob('*'):
        if path.is_file():
            for key in (planning.READ_KEY, planning.WRITE_KEY):
                assert str(key).encode() not in path.read_bytes()


@pytest.mark.parametrize('name', ['code.py', '.github/readme.md', '.claude/guide.md',
                                 '.agents/guide.md', 'AGENTS.md', 'nested/AGENTS.md',
                                 'nested/.github/a.md', 'link.md'])
def test_forbidden_change_refuses_whole_delivery(delivery, name):
    d = delivery
    commit(d, 'allowed.md')
    if name == 'link.md':
        (d['copy'] / name).symlink_to('/etc/passwd')
        d['git'](d['copy'], 'add', '.')
        d['git'](d['copy'], 'commit', '-m', 'link')
    else:
        commit(d, name)
    with pytest.raises(StateError, match='refused'):
        publish(d)
    assert d['git'](d['remote'], 'rev-parse', 'main') == d['base']
    assert not any('push' in args for args, _ in d['calls'])
    assert not d['marker'].exists()


def test_transient_forbidden_change_is_refused(delivery):
    d = delivery
    commit(d, 'bad.py')
    d['git'](d['copy'], 'rm', 'bad.py')
    d['git'](d['copy'], 'commit', '-m', 'remove forbidden file')
    with pytest.raises(StateError, match='refused'):
        publish(d)
    assert d['git'](d['remote'], 'rev-parse', 'main') == d['base']


def test_unrelated_commit_is_refused(delivery):
    d = delivery
    d['git'](d['copy'], 'checkout', '--orphan', 'orphan')
    commit(d)
    d['git'](d['copy'], 'branch', '-f', d['adapter'].branch, 'HEAD')
    with pytest.raises(StateError, match='descend'):
        publish(d)
    assert d['git'](d['remote'], 'rev-parse', 'main') == d['base']


@pytest.mark.parametrize('conflict', [False, True])
def test_rebase_latest_main_and_conflict_stops(delivery, conflict):
    d = delivery
    commit(d)
    file = 'brief.md' if conflict else 'upstream.md'
    (d['seed'] / file).write_text('upstream\n')
    d['git'](d['seed'], 'add', '.')
    d['git'](d['seed'], 'commit', '-m', 'upstream')
    d['git'](d['seed'], 'push', str(d['remote']), 'main')
    latest = d['git'](d['remote'], 'rev-parse', 'main')
    if conflict:
        with pytest.raises(StateError, match='conflict'):
            publish(d)
        assert d['git'](d['remote'], 'rev-parse', 'main') == latest
        assert not any('push' in args for args, _ in d['calls'])
    else:
        pushed = publish(d)
        assert len(pushed) == 1
        assert d['git'](d['remote'], 'rev-parse', 'main^') == latest
        # Original copy stays on its own history; subsequent delivery replays
        # only the new commits, without duplicating the earlier rebased change.
        commit(d, 'second.md', 'second\n')
        assert len(publish(d)) == 1
        assert d['git'](d['remote'], 'rev-list', '--count', 'main') == '4'
    assert not d['marker'].exists()


@pytest.mark.parametrize('kind', ['extra', 'head'])
def test_bundle_ref_contract(delivery, kind):
    d = delivery
    commit(d)
    bundle = d['root'] / 'wrong.bundle'
    if kind == 'extra':
        d['git'](d['copy'], 'branch', 'extra')
        d['git'](d['copy'], 'bundle', 'create', bundle, '--all')
    else:
        d['git'](d['copy'], 'checkout', '--detach', 'HEAD~1')
        d['git'](d['copy'], 'bundle', 'create', bundle, 'HEAD', 'refs/heads/' + d['adapter'].branch)
    d['selected'][0] = bundle
    with pytest.raises(StateError, match='branch or HEAD'):
        publish(d)
    assert not any('push' in args for args, _ in d['calls'])


def test_factory_session_never_exports_or_pushes(delivery):
    d = delivery
    commit(d)
    d['adapter'].session['area'] = 'factory'
    assert publish(d) == []
    assert d['calls'] == []
    assert d['git'](d['remote'], 'rev-parse', 'main') == d['base']


@pytest.mark.parametrize(('step', 'notice'), [
    ('fetch', 'Planning fetch failed; no delivery confirmed.'),
    ('rebase', 'Planning rebase failed, possibly due to a conflict with main: nothing pushed. Resolve the conflicting changes in this session and try again.'),
    ('push', 'Planning push failed; no delivery confirmed.'),
])
def test_failed_delivery_step_has_safe_notice(delivery, monkeypatch, caplog, step, notice):
    d = delivery
    commit(d)
    execute = subprocess.run

    def fail_step(args, **kwargs):
        if args[0] == 'git' and step in args and (step != 'fetch' or 'origin' in args):
            return subprocess.CompletedProcess(args, 1, 'secret git output', 'secret git error')
        return execute(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', fail_step)
    with pytest.raises(StateError) as error:
        publish(d)
    assert str(error.value) == notice
    assert 'secret git' not in str(error.value)
    assert 'secret git' not in caplog.text


def test_homelab_workspace_git_copy_and_resume(delivery, monkeypatch):
    from unittest.mock import Mock
    d = delivery
    shutil.rmtree(d['adapter'].clean)
    work = d['root'] / 'work'
    work.mkdir(mode=0o700)
    monkeypatch.setattr(sessions, 'WORK_ROOT', work)
    monkeypatch.setattr(sessions, 'Planning', lambda _: d['adapter'])
    monkeypatch.setattr(sessions.os, 'chown', Mock())
    real_lstat = Path.lstat

    def owner(path):
        info = real_lstat(path)
        if path == work / 'session-1':
            values = list(info)
            values[4] = 21000
            return os.stat_result(values)
        return info

    monkeypatch.setattr(Path, 'lstat', owner)
    session = dict(id=1, area='homelab', cli_session_id=None, repositories=[])
    folder, paths = sessions.workspace(session)
    assert paths == []
    assert (folder / 'planning/.git').is_dir()
    assert not (folder / 'planning/.git/hooks').exists()
    assert not (folder / 'planning/.git/objects/info/alternates').exists()
    assert d['git'](folder / 'planning', 'rev-parse', 'HEAD') == d['base']
    assert d['git'](folder / 'planning', 'remote', 'get-url', 'origin') == str(d['adapter'].clean)
    d['calls'].clear()
    session['cli_session_id'] = 'synthetic-resume'
    assert sessions.workspace(session) == (folder, paths)
    assert not d['calls']


@pytest.mark.parametrize('notice', [None, 'Planning conflict with main: nothing pushed.'])
def test_turn_records_pushes_or_delivery_refusal(tmp_path, monkeypatch, notice):
    from unittest.mock import Mock
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
    turn = dict(id=7, text='synthetic', session=dict(
        id=1, area='homelab', tool='claude', model='synthetic', effort='medium', cli_session_id=None))
    monkeypatch.setattr(sessions, 'workspace', lambda _: (tmp_path, []))
    monkeypatch.setattr(sessions, 'RUNS', tmp_path)
    monkeypatch.setattr(sessions.os, 'chown', Mock())
    monkeypatch.setattr(sessions.subprocess, 'run', Mock(return_value=
                        subprocess.CompletedProcess([], 0, '{"session_id":"synthetic","result":"reply"}')))
    adapter = Mock()
    adapter.deliver.side_effect = StateError(notice) if notice else None
    adapter.deliver.return_value = ['a' * 40]
    monkeypatch.setattr(sessions, 'Planning', lambda _: adapter)
    store = Mock()
    sessions.execute_turn(turn, store)
    args = store.finish_session_turn.call_args
    assert args.args[2] == 'synthetic'
    assert args.kwargs == ({'delivery_notice': notice} if notice else {'planning_commits': ['a' * 40]})
    assert 'failed' not in args.kwargs
