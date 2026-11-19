"""Synthetic credentials, local remotes and hostile copies; no node or real login."""
import fcntl
import json
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock

import pytest

from cplane import deny, executors, fence, review, state
from cplane.executors import Processes, command
from cplane.runner import Git, GitHub


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    monkeypatch.setattr('cplane.cut.skills_version', lambda: 'synthetic-installation-revision')
    # This fixture substitutes direct ownership; real privilege checks have separate coverage.
    monkeypatch.setattr(fence, 'require_ownership_support', lambda: None)
    tmp_path = tmp_path.resolve()
    monkeypatch.setenv('CPLANE_FENCE', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    for role in ('AUTHOR', 'COMMITTER'):
        monkeypatch.setenv(f'GIT_{role}_NAME', 'Synthetic')
        monkeypatch.setenv(f'GIT_{role}_EMAIL', 'synthetic@example.invalid')
    for key, value in [('ROOT_UID', os.getuid()), ('CLI_UID', os.getuid()), ('CLI_GID', os.getgid())]:
        monkeypatch.setattr(fence, key, value)
    for attr in ('WORK_ROOT', 'CLEAN_ROOT', 'LOGIN_ROOT'):
        root = tmp_path / attr.lower()
        root.mkdir(mode=0o700)
        monkeypatch.setattr(fence, attr, root)
    secret = 'synthetic-github-credential-DO-NOT-LOG'
    token = tmp_path / 'github-token'
    token.write_text(secret)
    token.chmod(0o600)
    monkeypatch.setattr(fence, 'TOKEN', token)
    deny_list = tmp_path / 'deny-list'
    deny_list.write_text('# synthetic list\n')
    deny_list.chmod(0o600)
    monkeypatch.setattr(deny, 'DENY_LIST', deny_list)
    monkeypatch.setattr(deny, 'ROOT_UID', os.getuid())
    real_run = subprocess.run

    def g(cwd, *args):
        return real_run(['git', '-C', str(cwd), *map(str, args)], check=True,
                        capture_output=True, text=True).stdout.strip()

    seed = tmp_path / 'seed'
    seed.mkdir()
    g(seed, 'init', '--initial-branch=main', '--template=')
    (seed / 'README').write_text('base\n')
    g(seed, 'add', '.')
    g(seed, 'commit', '-m', 'base')
    base = g(seed, 'rev-parse', 'HEAD')
    remote = tmp_path / 'remote.git'
    g(tmp_path, 'clone', '--bare', seed, remote)
    adapter = fence.Fence()
    clean = adapter.clean('example/repo')
    g(tmp_path, 'clone', '--bare', remote, clean)
    job = adapter.prepare('example/repo', 'slice/voice-W1', 'copy-1')
    work = Path(job['repo'])
    assert work.stat().st_mode & 0o777 == 0o700
    assert work.stat().st_uid == fence.CLI_UID and work.stat().st_gid == fence.CLI_GID
    assert not (work / '.git/hooks').exists()
    assert g(work, 'remote', 'get-url', 'origin') == str(clean)
    assert not (work / '.git/objects/info/alternates').exists()
    for obj in (work / '.git/objects').glob('*/*'):
        source = clean / 'objects' / obj.parent.name / obj.name
        if source.exists():
            assert source.stat().st_ino != obj.stat().st_ino
    (work / 'README').write_text('completed\n')
    g(work, 'add', '.')
    g(work, 'commit', '-m', 'complete')
    tip = g(work, 'rev-parse', 'HEAD')
    bundles = {}
    for kind, branch in [('good', job['branch']), ('wrong', 'wrong-branch')]:
        if kind == 'wrong':
            g(work, 'branch', branch)
        bundles[kind] = tmp_path / (kind + '.bundle')
        g(work, 'bundle', 'create', bundles[kind], 'HEAD', 'refs/heads/' + branch)
    g(seed, 'checkout', '--orphan', job['branch'])
    (seed / 'README').write_text('unrelated\n')
    g(seed, 'add', '.')
    g(seed, 'commit', '-m', 'unrelated')
    bundles['unrelated'] = tmp_path / 'unrelated.bundle'
    g(seed, 'bundle', 'create', bundles['unrelated'], 'HEAD', 'refs/heads/' + job['branch'])

    marker = tmp_path / 'HOST-CODE-EXECUTED'
    for name in ('pre-push', 'post-checkout', 'monitor'):
        hook = work / '.git/hooks' / name
        hook.parent.mkdir(exist_ok=True)
        hook.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
        hook.chmod(0o755)
    g(work, 'config', 'core.fsmonitor', str(work / '.git/hooks/monitor'))
    g(work, 'config', 'core.sshCommand', str(work / '.git/hooks/monitor'))
    g(work, 'config', 'credential.helper', '!' + str(work / '.git/hooks/monitor'))
    folder = tmp_path / 'runs/state/turn-1'
    folder.mkdir(parents=True, mode=0o711)
    (folder / 'io').mkdir(mode=0o700)
    job.update(run=str(folder), fence=True, tool='codex', model='synthetic', id='voice/W1',
               started_ns=time.time_ns(), session='synthetic-session', phase='ended')
    selection = ['good']
    calls = []

    def run(args, **kwargs):
        calls.append((list(map(str, args)), kwargs))
        assert secret not in str(args)
        assert Path(kwargs.get('cwd', '/')) != work
        if args[:2] == ['gh', 'api']:
            assert kwargs['env']['GH_TOKEN'] == secret
            return subprocess.CompletedProcess(args, 0, '{"private": false}', '')
        if args[0] == os.environ.get('CPLANE_FENCE_COMMAND', 'factory-cli'):
            assert args[1] == 'bundle'
            assert args[args.index('--repo') + 1] == str(work)
            output = Path(args[args.index('--run') + 1])
            shutil.copyfile(bundles[selection[0]], output / 'branch.bundle')
            return subprocess.CompletedProcess(args, 0, '', '')
        if args[0] == 'git':
            assert args[1:3] == ['-C', str(clean)], 'host Git must only run in the clean clone'
            result = real_run(args, **kwargs)
            if result.returncode and 'clone' in args:
                # This fixture uses only synthetic paths and credentials. Production
                # deliberately suppresses Git diagnostics, which can contain secrets.
                print('Synthetic Git clone failed:', result.stderr)
            return result
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', run)
    return dict(adapter=adapter, job=job, tip=tip, base=base, work=work, clean=clean,
                remote=remote, marker=marker, calls=calls, secret=secret, selection=selection,
                g=g, folder=folder, root=tmp_path, real_run=real_run, deny_list=deny_list,
                bundles=bundles)


def request(job):
    return dict(branch=job['branch'], title='Synthetic PR', body='Synthetic change', node_steps=None, contract_changes=None)


def test_prepare_initializes_a_new_clean_clone_and_pins_default_base(delivery, monkeypatch):
    d = delivery
    clean = d['adapter'].clean('example/fresh')
    calls = []
    def run(args, **kwargs):
        args = list(args)
        assert args[:3] == ['git', '-C', str(clean)]
        assert d['secret'] not in str(args)
        calls.append(args)
        # Redirect only the fixture's synthetic GitHub origin, with no network.
        if 'remote' in args and args[-3:-1] == ['add', 'origin']:
            args[-1] = str(d['remote'])
        return d['real_run'](args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', run)
    job = d['adapter'].prepare('example/fresh', 'slice/voice-W2', 'fresh-copy')
    work = Path(job['repo'])
    assert job['base'] == d['base'] and job['default'] == 'main'
    assert job['branch'] == 'slice/voice-W2'
    assert (work / '.git/HEAD').read_text() == 'ref: refs/heads/slice/voice-W2\n'
    assert work.stat().st_mode & 0o777 == 0o700
    assert work.stat().st_uid == fence.CLI_UID
    assert 'init' in calls[0] and '--bare' in calls[0]
    assert not (work / '.git/hooks').exists()
    assert d['secret'] not in (work / '.git/config').read_text()


def test_concurrent_first_preparations_share_one_clone(delivery, monkeypatch):
    d = delivery
    clean = d['adapter'].clean('example/concurrent')
    start = Barrier(2)
    def run(args, **kwargs):
        args = list(args)
        if 'init' in args:
            time.sleep(0.2)
        if 'remote' in args and args[-3:-1] == ['add', 'origin']:
            args[-1] = str(d['remote'])
        return d['real_run'](args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', run)
    def prepare(i):
        start.wait(timeout=5)
        return d['adapter'].prepare('example/concurrent', f'slice/concurrent-{i}', f'concurrent-{i}')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(prepare, i) for i in range(2)]
        jobs = [future.result() for future in futures]
    assert all(job['base'] == d['base'] for job in jobs)
    assert d['g'](clean, 'rev-parse', '--is-bare-repository') == 'true'
    assert d['g'](clean, 'remote', 'get-url', 'origin') == str(d['remote'])


@pytest.mark.parametrize('initialized', [False, True])
def test_incomplete_clean_clone_is_rebuilt(delivery, monkeypatch, initialized):
    d = delivery
    clean = d['adapter'].clean('example/incomplete')
    clean.mkdir(mode=0o700)
    if initialized:
        d['g'](clean, 'init', '--bare', '--template=')
    (clean / 'interrupted').write_text('partial')
    def run(args, **kwargs):
        args = list(args)
        if 'remote' in args and args[-3:-1] == ['add', 'origin']:
            args[-1] = str(d['remote'])
        return d['real_run'](args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', run)
    job = d['adapter'].prepare('example/incomplete', 'slice/rebuilt', 'rebuilt-copy')
    assert job['base'] == d['base']
    assert not (clean / 'interrupted').exists()
    assert d['g'](clean, 'rev-parse', '--is-bare-repository') == 'true'


def test_real_bundle_delivery_never_runs_host_git_in_hostile_copy(delivery, capsys, monkeypatch):
    monkeypatch.setenv('CPLANE_FENCE_COMMAND', 'homelab-fence')
    d = delivery
    assert d['adapter'].publish(d['job'], request(d['job'])) == d['tip']
    assert any(args[:2] == ['homelab-fence', 'bundle'] for args, _ in d['calls'])
    assert d['g'](d['remote'], 'rev-parse', 'refs/heads/' + d['job']['branch']) == d['tip']
    Git().tidy(d['work'])
    with pytest.raises(state.StateError, match='host branch read refused'):
        Git().branch(d['work'])
    with pytest.raises(state.StateError, match='host origin read refused'):
        GitHub().repository(d['work'])
    assert not d['marker'].exists()
    for args, options in d['calls']:
        if args[0] == 'git':
            assert 'transfer.fsckObjects=true' in args
            assert 'core.hooksPath=/dev/null' in args and 'core.fsmonitor=false' in args
            env = options['env']
            authenticated = 'ls-remote' in args or 'push' in args
            assert ('GH_TOKEN' in env) == authenticated
    # Neither the mutable copy nor trusted run records/config carry a credential.
    for root in (d['work'], d['clean'], d['folder']):
        for path in root.rglob('*'):
            if path.is_file():
                assert d['secret'].encode() not in path.read_bytes()
    assert d['secret'] not in str(capsys.readouterr())


@pytest.mark.parametrize('wrong', ['main', 'another-slice'])
def test_request_cannot_select_a_branch(delivery, wrong):
    d = delivery
    req = request(d['job'])
    req['branch'] = wrong
    with pytest.raises(state.StateError, match='slice branch'):
        d['adapter'].publish(d['job'], req)
    assert not d['calls']


def test_publish_refuses_a_branch_that_became_the_default(delivery):
    d = delivery
    ref = 'refs/heads/' + d['job']['branch']
    d['g'](d['remote'], 'update-ref', ref, d['base'])
    d['g'](d['remote'], 'symbolic-ref', 'HEAD', ref)
    with pytest.raises(state.StateError, match='now the default branch'):
        d['adapter'].publish(d['job'], request(d['job']))
    assert not any('push' in args for args, _ in d['calls'])


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('resume', [None, 'saved-session'])
def test_every_fenced_executor_command_uses_factory_cli(tmp_path, tool, resume, monkeypatch):
    monkeypatch.setenv('CPLANE_FENCE_COMMAND', 'homelab-fence')
    job = dict(tool=tool, run=str(tmp_path), repo='/srv/factory/work/copy', model='synthetic',
               prompt='-literal prompt', resume=resume, fence=True)
    args = command(job)
    assert args[:9] == ['homelab-fence', 'run', '--tool', tool, '--repo', job['repo'],
                        '--run', str(tmp_path / 'io'), '--']
    assert args[9] == tool
    assert args[-2:] == ['--', '-literal prompt']
    assert 'sandbox_workspace_write.network_access=true' not in args
    assert not any(str(Path.home()) in arg for arg in args)
    if tool == 'codex':
        assert args[args.index('-o') + 1] == '/run/factory/last.json'
    if resume:
        assert resume in args


@pytest.mark.parametrize('tool', ['codex', 'claude'])
def test_fenced_supervisor_collects_session_and_final_from_run_folder(tmp_path, monkeypatch, tool):
    folder = tmp_path.resolve()
    monkeypatch.setenv('CPLANE_FENCE_COMMAND', 'homelab-fence')
    monkeypatch.setattr(executors.os, 'chown', Mock())
    # This fixture substitutes direct ownership; real privilege checks have separate coverage.
    monkeypatch.setattr(fence, 'require_ownership_support', lambda: None)
    monkeypatch.setattr(executors.subprocess, 'Popen', Mock(return_value=Mock(pid=123)))
    job = dict(tool=tool, run=str(folder), repo='/untrusted/repo', model='synthetic',
               prompt='synthetic', fence=True, started_ns=0)
    Processes().start(job)
    assert (folder / 'request.json').stat().st_mode & 0o777 == 0o600
    assert not (folder / 'io/request.json').exists()
    assert 'GH_TOKEN' not in executors.subprocess.Popen.call_args.kwargs['env']
    assert executors.subprocess.Popen.call_args.kwargs['env']['CPLANE_FENCE_COMMAND'] == 'homelab-fence'
    final = dict(kind='waiting', body='synthetic')

    def run(args, **kwargs):
        assert args[:2] == ['homelab-fence', 'run']
        assert kwargs['cwd'] == str(folder)
        if tool == 'codex':
            kwargs['stdout'].write(b'{"type":"thread.started","thread_id":"saved-session"}\n')
            (folder / 'io/last.json').write_text(json.dumps(final))
        else:
            kwargs['stdout'].write(json.dumps(dict(session_id='saved-session', structured_output=final)).encode())
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(executors.subprocess, 'run', run)
    executors.supervise(folder)
    done, session, reply, _ = Processes().poll(job)
    assert done and session == 'saved-session' and reply == final


def test_fenced_output_refuses_host_symlink(tmp_path):
    (tmp_path / 'io').mkdir()
    secret = tmp_path / 'not-output'
    secret.write_text('{"kind":"handover","body":"must not be read"}')
    (tmp_path / 'io/last.json').symlink_to(secret)
    with pytest.raises(OSError):
        Processes().poll(dict(run=str(tmp_path), fence=True, tool='codex', started_ns=0))


def test_gh_token_is_only_in_call_environment_and_error_is_redacted(delivery, monkeypatch):
    d = delivery
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 1, d['secret'], d['secret'])
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(state.StateError, match='gh operation failed') as error:
        GitHub().call('example/repo', 'pr', 'list')
    assert d['secret'] not in str(error.value)
    args, options = calls[0]
    assert d['secret'] not in str(args)
    assert options['env']['GH_TOKEN'] == d['secret']
    assert options['cwd'] == '/'


def test_fenced_checks_bind_to_delivered_head():
    gh = GitHub()
    gh.call = Mock(return_value='{"headRefOid":"other"}')
    with pytest.raises(state.StateError, match='PR head differs'):
        gh.checks('example/repo', 1, expected='tip')
    gh.call.assert_called_once_with('example/repo', 'pr', 'view', '1', '--json',
                                    'headRefOid,state,title,body,isDraft,mergeStateStatus,mergeable')


@pytest.mark.parametrize('runs,jobs,expected', [
    ([], [], ('pending', '')),
    ([{'id': 1, 'status': 'completed'}], [[]], ('pending', '')),
    ([{'id': 1, 'status': 'completed'}], [[
        {'name': 'test', 'status': 'completed', 'conclusion': 'success'},
        {'name': 'lint', 'status': 'completed', 'conclusion': 'success'},
    ]], ('green', '')),
    ([{'id': 1, 'status': 'completed'}], [[
        {'name': 'test', 'status': 'completed', 'conclusion': 'failure'},
    ]], ('red', 'test')),
    ([{'id': 1, 'status': 'completed'}, {'id': 2, 'status': 'completed'}], [
        [{'name': 'test', 'status': 'completed', 'conclusion': 'cancelled'}],
        [{'name': 'test', 'status': 'completed', 'conclusion': 'success'}],
    ], ('green', '')),
    ([{'id': 1, 'status': 'in_progress'}], [[
        {'name': 'test', 'status': 'completed', 'conclusion': 'success'},
    ]], ('pending', '')),
    ([{'id': 1, 'status': 'completed'}], [[
        {'name': 'test', 'status': 'in_progress', 'conclusion': None},
        {'name': 'lint', 'status': 'completed', 'conclusion': 'success'},
    ]], ('pending', '')),
])
def test_fenced_checks_actions_results(runs, jobs, expected):
    gh = GitHub()
    responses = [json.dumps({'headRefOid': 'tip'}), json.dumps({'workflow_runs': runs})]
    responses.extend(json.dumps({'jobs': run_jobs}) for run_jobs in jobs)
    gh.call = Mock(side_effect=responses)
    assert gh.checks('example/repo', 1, expected='tip') == expected
    assert gh.call.call_args_list[1].args == (
        'example/repo', 'api', 'repos/example/repo/actions/runs?head_sha=tip&per_page=100')
    for index, run in enumerate(runs, start=2):
        assert gh.call.call_args_list[index].args == (
            'example/repo', 'api', f"repos/example/repo/actions/runs/{run['id']}/jobs?per_page=100")


def test_gh_api_uses_per_call_token_without_repo_flag(delivery, monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, '{}', '')
    monkeypatch.setattr(subprocess, 'run', run)
    GitHub().call('example/repo', 'api', 'repos/example/repo/actions/runs')
    assert calls[0][0] == ['gh', 'api', 'repos/example/repo/actions/runs']
    assert calls[0][1]['env']['GH_TOKEN'] == delivery['secret']


def test_fenced_merge_uses_match_head_and_rejects_replaced_head():
    gh = GitHub()
    gh.call = Mock(side_effect=[
        '{"state":"OPEN","title":"Example","headRefOid":"tip","mergeCommit":null}', '',
        '{"state":"MERGED","mergeCommit":{"oid":"merge-sha"}}'])
    assert gh.merge('example/repo', 12, expected='tip') == 'merge-sha'
    assert gh.call.call_args_list[1].args == (
        'example/repo', 'pr', 'merge', '12', '--squash', '--match-head-commit', 'tip')
    gh.call = Mock(return_value='{"state":"OPEN","headRefOid":"other","mergeCommit":null}')
    with pytest.raises(state.StateError, match='PR head differs'):
        gh.merge('example/repo', 12, expected='tip')
    assert gh.call.call_count == 1


@pytest.mark.parametrize('tool', ['codex', 'claude'])
def test_resume_reuses_copy_and_requires_existing_session(delivery, tool):
    d = delivery
    d['job']['tool'] = tool
    with pytest.raises(state.StateError, match='cannot find its session'):
        d['adapter'].resume(d['job'], 'synthetic-session')
    root = fence.LOGIN_ROOT / ('codex/sessions/2026/11/06' if tool == 'codex' else 'claude/projects/-work')
    root.mkdir(parents=True)
    name = 'rollout-time-synthetic-session.jsonl' if tool == 'codex' else 'synthetic-session.jsonl'
    (root / name).write_text('{}\n')
    metadata = d['adapter'].resume(d['job'], 'synthetic-session')
    assert metadata['repo'] == str(d['work']) and metadata['base'] == d['base']
    assert not d['calls'] and not d['marker'].exists()


def test_fenced_tidy_never_invokes_git(monkeypatch, tmp_path):
    monkeypatch.setenv('CPLANE_FENCE', '1')
    run = Mock(side_effect=AssertionError('host Git must not execute'))
    monkeypatch.setattr(subprocess, 'run', run)
    Git().tidy(tmp_path)
    run.assert_not_called()


@pytest.mark.parametrize('code', [0, 1])
def test_postgres_fenced_pass_pulls_briefs_ff_only(delivery, monkeypatch, code):
    d = delivery
    folder = d['root'] / 'briefs'
    folder.mkdir()
    (folder / '.git').mkdir()
    config = folder / '.git/config'
    deploy_config = '[core]\n\tsshCommand = ssh -i /synthetic/briefs-deploy-key\n'
    config.write_text(deploy_config)
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setenv('GH_TOKEN', d['secret'])
    monkeypatch.setattr(fence, 'github_environment', Mock(side_effect=AssertionError('briefs must not use the token')))
    trusted = Mock(wraps=fence.trusted_directory)
    monkeypatch.setattr(fence, 'trusted_directory', trusted)
    run = Mock(return_value=subprocess.CompletedProcess([], code, 'private diagnostics', 'private diagnostics'))
    monkeypatch.setattr(subprocess, 'run', run)
    if code:
        with pytest.raises(state.StateError) as error:
            Git().pull(folder / 'slices.json')
        assert str(error.value) == 'briefs fast-forward pull failed'
    else:
        Git().pull(folder / 'slices.json')
    trusted.assert_called_once_with(folder)
    args = run.call_args.args[0]
    assert args == ['git', '-C', str(folder), '-c', 'core.hooksPath=/dev/null',
                    '-c', 'core.fsmonitor=false', 'pull', '--ff-only']
    assert not any('credential.helper' in arg or 'core.sshCommand' in arg for arg in args)
    env = run.call_args.kwargs['env'].copy()
    assert env.pop('GIT_SSH_COMMAND').startswith('ssh -F /dev/null -i ')
    assert env == fence.host_environment()
    assert 'GH_TOKEN' not in run.call_args.kwargs['env']
    assert config.read_text() == deploy_config
    assert d['secret'] not in str(args)
    Git().pull(d['root'] / 'not-a-clone/slices.json')
    assert run.call_count == 1


def test_fenced_primer_never_starts_cli_on_host(delivery, monkeypatch):
    from cplane import primer
    d = delivery
    monkeypatch.setenv('CPLANE_RUNS', str(d['root'] / 'runs'))
    monkeypatch.setenv('CPLANE_FENCE_COMMAND', 'homelab-fence')
    run = Mock(return_value=subprocess.CompletedProcess([], 0, b'', b''))
    monkeypatch.setattr(subprocess, 'run', run)
    assert primer.prime()
    assert run.call_count == 2
    for call in run.call_args_list:
        assert call.args[0][:2] == ['homelab-fence', 'run']
        assert 'GH_TOKEN' not in call.kwargs['env']


@pytest.mark.parametrize('operation', ['delete', 'rename_out', 'rename_in'])
def test_workflow_path_listing_includes_deletions_and_both_rename_sides(delivery, operation):
    from cplane import classes
    d = delivery
    seed = d['root'] / 'rename-seed'
    d['g'](d['root'], 'clone', d['remote'], seed)
    workflow = seed / '.github/workflows/test.yml'
    source = seed / 'test.yml'
    workflow.parent.mkdir(parents=True)
    original = source if operation == 'rename_in' else workflow
    original.write_text('synthetic workflow\n')
    d['g'](seed, 'add', '.')
    d['g'](seed, 'commit', '-m', 'before')
    base = d['g'](seed, 'rev-parse', 'HEAD')
    # Publish the existing file on main before deleting or renaming it in the PR.
    d['g'](seed, 'push', 'origin', 'HEAD:refs/heads/main')
    if operation == 'delete':
        workflow.unlink()
    else:
        original.rename(workflow if operation == 'rename_in' else source)
    d['g'](seed, 'add', '-A')
    d['g'](seed, 'commit', '-m', 'after')
    tip = d['g'](seed, 'rev-parse', 'HEAD')
    d['g'](seed, 'push', 'origin', 'HEAD:refs/heads/renames')
    d['adapter'].git(d['clean'], 'fetch', 'origin', 'refs/heads/renames')
    number, guards = classes.changes(d['adapter'], {**d['job'], 'base': base, 'tip': tip})
    assert number == 4
    assert guards == ['.github/workflows/test.yml']


def test_fenced_gh_retries_reads_but_not_writes(delivery, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr(time, 'sleep', sleep)
    run = Mock(side_effect=[subprocess.CompletedProcess([], 1, '', 'secret'),
                            subprocess.CompletedProcess([], 0, 'ok', '')])
    monkeypatch.setattr(subprocess, 'run', run)
    assert GitHub().call('example/repo', 'pr', 'view', '1') == 'ok'
    assert run.call_count == 2
    sleep.assert_called_once_with(5)
    run.reset_mock(side_effect=True)
    run.return_value = subprocess.CompletedProcess([], 1, '', 'secret')
    for action in ('create', 'merge'):
        with pytest.raises(state.StateError, match='gh operation failed'):
            GitHub().call('example/repo', 'pr', action)
    assert run.call_count == 2


@pytest.mark.parametrize('auth', [None, 'token'])
@pytest.mark.parametrize('read_only', [None, '0'])
def test_legacy_token_mode_unchanged(delivery, monkeypatch, auth, read_only):
    from cplane import github_app
    if read_only is None:
        monkeypatch.delenv('CPLANE_GITHUB_READ_ONLY', raising=False)
    else:
        monkeypatch.setenv('CPLANE_GITHUB_READ_ONLY', read_only)
    if auth is None:
        monkeypatch.delenv('CPLANE_GITHUB_AUTH', raising=False)
    else:
        monkeypatch.setenv('CPLANE_GITHUB_AUTH', auth)
    mint = Mock(side_effect=AssertionError('legacy mode must not mint'))
    monkeypatch.setattr(github_app, 'installation_token', mint)
    assert fence.github_environment() == {**fence.host_environment(), 'GH_TOKEN': delivery['secret']}
    assert fence.github_environment(['example/repo']) == {
        **fence.host_environment(), 'GH_TOKEN': delivery['secret']}
    mint.assert_not_called()


def test_read_only_refuses_token_file_before_opening_it(monkeypatch):
    monkeypatch.setenv('CPLANE_GITHUB_AUTH', 'token')
    monkeypatch.setenv('CPLANE_GITHUB_READ_ONLY', '1')
    opened = Mock(side_effect=AssertionError('must not read token file'))
    monkeypatch.setattr(fence.os, 'open', opened)
    with pytest.raises(state.StateError, match='token mode cannot be narrowed'):
        fence.github_environment(['example/repo'])
    opened.assert_not_called()


def test_app_environment_ignores_old_state_repositories(make_state, slice_data, monkeypatch):
    from cplane import github_app
    items = [slice_data, dict(slice_data, id='old/W1', repo='med-ask', state='accepted'),
             dict(slice_data, id='foreign/W1', repo='foreign/other', state='accepted')]
    monkeypatch.setenv('CPLANE_STATE', str(make_state(items)))
    monkeypatch.setattr(state, 'load', Mock(side_effect=AssertionError('must not read state')))
    monkeypatch.setenv('CPLANE_GITHUB_AUTH', 'app')
    monkeypatch.setenv('GH_TOKEN', 'untrusted-ambient-token')
    mint = Mock(return_value='synthetic-installation-token')
    monkeypatch.setattr(github_app, 'installation_token', mint)
    env = fence.github_environment(['example/repo'])
    mint.assert_called_once_with(['example/repo'])
    assert env == {**fence.host_environment(), 'GH_TOKEN': 'synthetic-installation-token'}
    assert 'CPLANE_GITHUB_APP_ID' not in env


@pytest.mark.parametrize('repositories', [None, []])
def test_app_environment_requires_repository(monkeypatch, repositories):
    from cplane import github_app
    monkeypatch.setenv('CPLANE_GITHUB_AUTH', 'app')
    monkeypatch.delenv('CPLANE_STATE', raising=False)
    mint = Mock()
    monkeypatch.setattr(github_app, 'installation_token', mint)
    with pytest.raises(state.StateError) as error:
        fence.github_environment(repositories)
    assert str(error.value) == 'GitHub App needs the repository of the call'
    mint.assert_not_called()


@pytest.mark.parametrize('repo', ['example/repo', 'another/project.git'])
@pytest.mark.parametrize('operation', ['gh', 'git'])
def test_authenticated_calls_request_only_their_repository(tmp_path, monkeypatch, repo, operation):
    from cplane import github_app
    monkeypatch.setenv('CPLANE_FENCE', '1')
    monkeypatch.setenv('CPLANE_GITHUB_AUTH', 'app')
    monkeypatch.delenv('CPLANE_STATE', raising=False)
    mint = Mock(return_value='synthetic-installation-token')
    monkeypatch.setattr(github_app, 'installation_token', mint)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, 'ok', ''))
    monkeypatch.setattr(subprocess, 'run', run)
    if operation == 'gh':
        assert GitHub().call(repo, 'pr', 'view', '1') == 'ok'
    else:
        monkeypatch.setattr(fence, 'CLEAN_ROOT', tmp_path)
        monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
        owner, name = repo.split('/')
        clean = tmp_path / owner / (name + '.git')
        clean.mkdir(parents=True, mode=0o700)
        fence.Fence().git(clean, 'fetch', 'origin', auth=True)
    mint.assert_called_once_with([repo])
    assert run.call_args.kwargs['env'] == {
        **fence.host_environment(), 'GH_TOKEN': 'synthetic-installation-token'}


def test_unknown_github_auth_is_refused(monkeypatch):
    monkeypatch.setenv('CPLANE_GITHUB_AUTH', 'typo')
    with pytest.raises(state.StateError, match='must be token or app'):
        fence.github_environment()


def test_credential_helper_supplies_app_token_only_to_git(monkeypatch):
    import sys
    env = {**fence.host_environment(), 'GH_TOKEN': 'synthetic-installation-token'}
    result = subprocess.run([sys.executable, '-m', 'cplane.fence', 'credential', 'get'],
                            input='protocol=https\nhost=github.com\n\n', env=env,
                            text=True, capture_output=True, check=True)
    assert result.stdout == 'username=x-access-token\npassword=synthetic-installation-token\n'
    assert result.stderr == ''


def test_rewritten_remote_branch_rejected_without_force(delivery):
    d = delivery
    d['adapter'].publish(d['job'], request(d['job']))
    # A different descendant of the same pinned base rewrites the published tip.
    alternate = d['root'] / 'alternate'
    d['g'](d['root'], 'clone', '--branch', 'main', d['remote'], alternate)
    (alternate / 'alternate').write_text('different history\n')
    d['g'](alternate, 'add', '.')
    d['g'](alternate, 'commit', '-m', 'alternate history')
    other = d['g'](alternate, 'rev-parse', 'HEAD')
    d['g'](alternate, 'push', 'origin', f'HEAD:{d["job"]["branch"]}', '--force')
    with pytest.raises(state.StateError, match='^branch was rewritten; merge main instead of rebasing$'):
        d['adapter'].publish(d['job'], request(d['job']))
    assert d['g'](d['remote'], 'rev-parse', 'refs/heads/' + d['job']['branch']) == other
    assert not any('--force' in args for args, _ in d['calls'])


@pytest.mark.parametrize('operation', ['edit-policy', 'delete', 'rename'])
def test_classes_use_base_policy_and_include_deleted_paths(delivery, operation):
    from cplane import classes
    d = delivery
    seed = d['root'] / 'policy-seed'
    d['g'](d['root'], 'clone', d['remote'], seed)
    table = seed / '.github/change-classes'
    table.parent.mkdir()
    table.write_text('4 /guard/**\n2 /strong.py\n')
    guard = seed / 'guard/key'
    guard.parent.mkdir()
    guard.write_text('PRIVATE content never recorded')
    strong = seed / 'strong.py'
    strong.write_text('synthetic\n')
    d['g'](seed, 'add', '.')
    d['g'](seed, 'commit', '-m', 'policy base')
    base = d['g'](seed, 'rev-parse', 'HEAD')
    # Publish the policy and original paths on the base branch.
    d['g'](seed, 'push', 'origin', 'HEAD:refs/heads/main')
    if operation == 'edit-policy':
        table.write_text('1 /**\n')
        guard.write_text('changed private content')
        expected = (4, ['.github/change-classes', 'guard/key'])
    elif operation == 'delete':
        strong.unlink()
        expected = (2, [])
    else:
        guard.rename(seed / 'plain.txt')
        expected = (4, ['guard/key'])
    d['g'](seed, 'add', '-A')
    d['g'](seed, 'commit', '-m', 'change')
    tip = d['g'](seed, 'rev-parse', 'HEAD')
    d['g'](seed, 'push', 'origin', 'HEAD:refs/heads/policy-test')
    d['adapter'].git(d['clean'], 'fetch', 'origin', 'refs/heads/policy-test')
    assert classes.changes(d['adapter'], {**d['job'], 'base': base, 'tip': tip}) == expected
    assert not d['marker'].exists()


def test_missing_list_stops_public_push(delivery):
    d = delivery
    d['deny_list'].unlink()
    with pytest.raises(deny.Denied, match='deny-list unavailable'):
        d['adapter'].publish(d['job'], request(d['job']))
    assert not any('push' in args for args, _ in d['calls'])


def assert_clean_git_locked(monkeypatch, adapter, clean):
    git = adapter.git
    calls = []

    def checked(path, *args, **kwargs):
        with (open(clean.parent / ('.' + clean.name + '.lock'), 'r') as lock,
              pytest.raises(BlockingIOError)):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        calls.append(args[0])
        return git(path, *args, **kwargs)

    monkeypatch.setattr(adapter, 'git', checked)
    return calls


def test_review_fetch_and_clone_hold_clean_lock(delivery, monkeypatch):
    d = delivery
    d['adapter'].publish(d['job'], request(d['job']))
    calls = assert_clean_git_locked(monkeypatch, d['adapter'], d['clean'])
    result = review.prepare(d['adapter'], d['job'], 'review-lock-test')
    assert result['tip'] == d['tip']
    assert {'fetch', 'rev-parse', 'merge-base', 'update-ref', 'clone'} <= set(calls)
