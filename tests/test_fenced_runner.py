"""Synthetic credentials, local remotes and hostile copies; no node or real login."""
import copy
from datetime import datetime, timedelta, timezone
import json
from itertools import count
import os
from pathlib import Path
import shutil
import subprocess
import time
from unittest.mock import Mock

import pytest

from cplane import deny, executors, fence, state
from cplane.executors import Processes, command
from cplane.runner import Git, GitHub, Runner


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    monkeypatch.setattr('cplane.cut.skills_version', lambda: 'synthetic-installation-revision')
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
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', run)
    return dict(adapter=adapter, job=job, tip=tip, base=base, work=work, clean=clean,
                remote=remote, marker=marker, calls=calls, secret=secret, selection=selection,
                g=g, folder=folder, root=tmp_path, real_run=real_run, deny_list=deny_list,
                bundles=bundles)


def request(job):
    return dict(branch=job['branch'], title='Synthetic PR', body='Synthetic change', node_steps=None)


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


@pytest.mark.parametrize('kind', ['wrong', 'unrelated'])
def test_invalid_bundle_raises_attention_before_push(delivery, make_state, kind):
    d = delivery
    d['selection'][0] = kind
    runner = Runner(make_state(), git=Mock(), github=Mock(), runs=d['root'] / 'control')
    runner.at = datetime.now(timezone.utc).isoformat()
    item = state.load(runner.path)['slices'][0]
    job = d['job']
    job['final'] = dict(kind='waiting', body='```json\n' + json.dumps(request(job)) + '\n```')
    runner.jobs = {item['id']: job}
    try:
        runner.apply_final(item, job)
    except state.StateError:
        runner.slice_failure(item, 'collect/deliver')
    assert item['attention']['kind'] == 'escalation'
    assert item['state'] == 'escalated'
    assert ('wrong branch' if kind == 'wrong' else 'base commit') in item['attention']['body']
    runner.github.open.assert_not_called()
    assert not any('push' in args for args, _ in d['calls'])
    assert not d['marker'].exists()


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


def test_git_failure_cannot_put_token_in_attention_logs_or_notices(delivery, make_state, monkeypatch):
    d = delivery
    wrapped_run = subprocess.run
    def run(args, **kwargs):
        if args[0] == 'git' and 'push' in args:
            assert d['secret'] not in str(args)
            return subprocess.CompletedProcess(args, 1, d['secret'], d['secret'])
        return wrapped_run(args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', run)
    runner = Runner(make_state(), git=Mock(), github=Mock(), runs=d['root'] / 'control')
    runner.at = datetime.now(timezone.utc).isoformat()
    item = state.load(runner.path)['slices'][0]
    job = d['job']
    job['final'] = dict(kind='waiting', body='```json\n' + json.dumps(request(job)) + '\n```')
    try:
        runner.apply_final(item, job)
    except state.StateError:
        runner.slice_failure(item, 'collect/deliver')
    assert item['attention']['kind'] == 'escalation'
    assert 'fenced Git operation failed' in item['attention']['body']
    assert d['secret'] not in json.dumps(item) + json.dumps(runner.notices)
    assert not d['marker'].exists()


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


def test_fenced_usage_reads_login_folders_only(tmp_path, monkeypatch):
    from cplane.runner import codex_usage, claude_usage
    monkeypatch.setenv('CPLANE_FENCE', '1')
    monkeypatch.setattr(fence, 'LOGIN_ROOT', tmp_path)
    assert codex_usage() is None and claude_usage() is None
    sessions = tmp_path / 'codex/sessions'
    sessions.mkdir(parents=True)
    (sessions / 'synthetic.jsonl').write_text(json.dumps(dict(payload=dict(rate_limits=dict(primary=dict(used_percent=37))))))
    (tmp_path / 'claude').mkdir()
    data = dict(at=10, rate_limits=dict(five_hour=dict(used_percentage=42)))
    (tmp_path / 'claude/usage-now.json').write_text(json.dumps(data))
    assert codex_usage() == 37 and claude_usage() == data


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


@pytest.mark.parametrize('unknown', [False, True])
@pytest.mark.parametrize('paused', [False, True])
def test_fenced_repository_capacity_uses_repository_identity(make_state, monkeypatch, unknown, paused):
    monkeypatch.setenv('CPLANE_FENCE', '1')
    runner = Runner(make_state(), git=Mock())
    runner.data = state.load(runner.path)
    item = runner.data['slices'][0]
    other = copy.deepcopy(item)
    other.update(id='voice/W0', state='issued', repo='EXAMPLE/REPO', paused=paused)
    runner.data['slices'].append(other)
    runner.jobs = {} if unknown else {other['id']: dict(id=other['id'], phase='running',
                                                     repo='/srv/factory/work/unrelated-path', repository='EXAMPLE/REPO')}
    assert runner.room(item) == 'deferred: repository busy (voice/W0)'
    if not unknown:
        runner.jobs['voice/W2'] = dict(id='voice/W2', phase='running', repo='/other', repository='example/other')
        assert 'executor limit' in runner.room(item)


def test_show_fenced_codex_final_uses_io_without_following_links(make_state, monkeypatch, capsys):
    from cplane.cli import main
    monkeypatch.setenv('CPLANE_FENCE', '1')
    path = make_state()
    runner = Runner(path)
    folder = runner.runs / 'synthetic'
    (folder / 'io').mkdir(parents=True)
    (folder / 'job.json').write_text(json.dumps(dict(id='voice/W1', tool='codex', fence=True, started_ns=1)))
    last = folder / 'io/last.json'
    last.write_text('{"kind":"waiting","body":"Synthetic final"}')
    assert main(['--state', str(path), 'show', 'voice/W1', '--final']) == 0
    assert capsys.readouterr().out == 'kind: waiting\nbody: Synthetic final\n'
    last.unlink()
    secret = folder / 'unrelated.json'
    secret.write_text('{"kind":"handover","body":"Not output"}')
    last.symlink_to(secret)
    assert main(['--state', str(path), 'show', 'voice/W1', '--final']) == 0
    assert capsys.readouterr().out == 'final: unavailable\n'


def test_old_unfenced_job_is_not_resumed(delivery, make_state):
    d = delivery
    path = make_state()
    runner = Runner(path, git=Mock(), github=Mock(), processes=Mock(), runs=d['root'] / 'control')
    (runner.runs / 'synthetic').mkdir(parents=True)
    job = {**d['job'], 'fence': False, 'run': str(runner.runs / 'synthetic'), 'phase': 'ended',
           'final': dict(kind='handover', body='Synthetic')}
    runner.save_job(job)
    runner.run()
    assert state.load(path)['slices'][0]['attention']['kind'] == 'escalation'
    runner.git.branch.assert_not_called()
    runner.github.repository.assert_not_called()
    runner.processes.start.assert_not_called()
    assert not d['marker'].exists()


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


def test_fenced_approval_stops_and_rechecks_before_merge(delivery, make_state):
    d = delivery
    gh = Mock()
    gh.checks.return_value = ('green', '')
    gh.merge.return_value = 'merge-sha'
    runner = Runner(make_state(), git=Mock(), github=gh, runs=d['root'] / 'control')
    runner.at = datetime.now(timezone.utc).isoformat()
    item = state.load(runner.path)['slices'][0]
    item.update(pr=12, session=dict(tool='codex', id='synthetic-session', folder=str(d['work'])))
    job = d['job']
    d['adapter'].publish(job, request(job))
    job.update(phase='pr', tip=d['tip'], request=request(job))
    runner.jobs = {item['id']: job}
    runner.pr_checks(item, job)
    assert item['attention']['kind'] == 'merge'
    gh.merge.assert_not_called()
    runner.deliver(item)
    gh.merge.assert_not_called()
    item['attention']['approved'] = True
    gh.checks.return_value = ('pending', '')
    runner.deliver(item)
    gh.merge.assert_not_called()
    gh.checks.return_value = ('green', '')
    runner.launch = Mock()
    runner.deliver(item)
    gh.merge.assert_called_once_with('example/repo', 12, expected=d['tip'])
    runner.launch.assert_called_once_with(item, 'merged as merge-sha', resume=True)


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
    assert run.call_args.kwargs['env'] == fence.host_environment()
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


class SyntheticProcesses:
    def __init__(self):
        self.started = []
        self.results = {}

    def start(self, job):
        folder = Path(job['run'])
        saved = json.loads((folder / 'job.json').read_text())
        assert saved['branch'] == job['branch'] and saved['base'] == job['base']
        assert (folder / 'job.json').stat().st_mode & 0o777 == 0o600
        assert folder.stat().st_mode & 0o777 == 0o700
        (folder / 'io').mkdir(mode=0o700)
        self.started.append(copy.deepcopy(job))
        return len(self.started)

    def poll(self, job):
        return self.results.get(job['run'], (False, 'synthetic-session', None, ''))

    def finish(self, kind, body):
        self.results[self.started[-1]['run']] = (True, 'synthetic-session', dict(kind=kind, body=body), '')


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('stop', [True, False])
def test_fenced_full_runner_delivery_approval_resume_and_handover(delivery, make_state, tool, stop, capsys):
    d = delivery
    path = make_state()
    data = state.load(path)
    item = data['slices'][0]
    item.update(slot='2020-01-01T00:00:00+00:00', stop_before_merge=stop)
    item['executor'].update(tool=tool, model='sonnet' if tool == 'claude' else 'synthetic')
    state.save(path, data)
    brief = path.parent / item['brief']
    brief.parent.mkdir()
    brief.write_text('Use branch from-the-brief.\n')
    processes = SyntheticProcesses()
    gh = Mock()
    gh.repository.side_effect = AssertionError('fenced runner must use the trusted repository name')
    gh.find_pr.side_effect = AssertionError('fenced runner must publish its bundle before opening a PR')
    gh.open.return_value = 12
    gh.checks.return_value = ('green', '')
    gh.merge.return_value = 'merge-sha'
    at = datetime.now(timezone.utc)
    runner = Runner(path, processes=processes, github=gh, git=Mock(), runs=d['root'] / 'control',
                    clock=lambda: at, codex_reader=lambda: 5,
                    claude_reader=lambda: dict(at=at.timestamp(), rate_limits=dict(five_hour=dict(used_percentage=5))))
    # A real fresh clone/base was made by the fixture before the hostile-copy trap.
    # Reuse it here so synthetic agent commits/bundles need no host Git in the copy.
    metadata = {key: d['job'][key] for key in ('repo', 'repository', 'branch', 'base', 'default')}
    runner.fence.prepare = Mock(return_value=metadata)
    session_root = fence.LOGIN_ROOT / ('codex/sessions' if tool == 'codex' else 'claude/projects/-work')
    session_root.mkdir(parents=True)
    (session_root / 'synthetic-session.jsonl').write_text('{}\n')
    runner.run()
    runner.fence.prepare.assert_called_once()
    assert runner.fence.prepare.call_args.args[:2] == ('example/repo', 'slice/voice-W1')
    first = processes.started[-1]
    assert first['branch'] == 'slice/voice-W1' and first['base'] == d['base']
    assert 'overrides any branch named in the brief' in first['prompt']
    assert 'nothing can be pushed from inside' in first['prompt']
    processes.finish('waiting', '```json\n' + json.dumps(request(first)) + '\n```')
    runner.run()
    assert state.load(path)['slices'][0]['pr'] == 12
    assert d['g'](d['remote'], 'rev-parse', 'refs/heads/' + first['branch']) == d['tip']
    gh.checks.assert_not_called()
    runner.run()
    if stop:
        item = state.load(path)['slices'][0]
        assert item['attention']['kind'] == 'merge'
        gh.merge.assert_not_called()
        assert len(processes.started) == 1
        state.update(path, item['id'], 'approve', 'synthetic-owner',
                     lambda s, *_: (s['attention'].update(approved=True) or None, None))
        runner.run()
    gh.merge.assert_called_once_with('example/repo', 12, expected=d['tip'])
    resumed = processes.started[-1]
    assert len(processes.started) == 2
    assert resumed['resume'] == 'synthetic-session'
    assert resumed['repo'] == first['repo'] and resumed['run'] != first['run']
    assert {key: resumed[key] for key in metadata} == metadata
    assert resumed['prompt'].startswith('merged as merge-sha')
    assert 'overrides any branch named in the brief' in resumed['prompt']
    runner.fence.prepare.assert_called_once()
    processes.finish('handover', 'Synthetic handover')
    runner.run()
    assert state.load(path)['slices'][0]['state'] == 'in review'
    assert d['work'].is_dir() and not d['marker'].exists()
    runner.git.tidy.assert_not_called()
    for root in (runner.runs, d['work'], d['clean']):
        for file in root.rglob('*'):
            if file.is_file():
                assert d['secret'].encode() not in file.read_bytes()
    assert d['secret'] not in path.read_text()
    assert d['secret'] not in Path(str(path) + '.outbox.jsonl').read_text()
    assert d['secret'] not in str(capsys.readouterr())


@pytest.fixture
def ticket_runner(delivery, make_state, monkeypatch):
    from cplane import cut
    d = delivery
    path = make_state()
    data = state.load(path)
    item = data['slices'][0]
    item.update(flow='tickets', slot='2020-01-01T00:00:00+00:00')
    state.save(path, data)
    brief = path.parent / item['brief']
    brief.parent.mkdir()
    brief.write_text('## Fixed decisions\nKeep this rule.\n## Do not\nNever that.\n')
    processes = SyntheticProcesses()
    # Saved fake turns are ordered by started_ns. Use a logical sequence rather
    # than CLOCK_REALTIME, which can step backwards on a CI VM between reviews.
    # These fake processes do not read output files or compare filesystem mtimes.
    starts = count(time.time_ns())
    monkeypatch.setattr(time, 'time_ns', lambda: next(starts))
    runner = Runner(path, processes=processes, github=Mock(), git=Mock(),
                    runs=d['root'] / 'control', codex_reader=lambda: 5)
    runner.github.open.return_value = 12
    runner.github.checks.return_value = ('pending', '')
    metadata = {key: d['job'][key] for key in ('repo', 'repository', 'branch', 'base', 'default')}
    runner.fence.prepare = Mock(return_value=metadata)
    monkeypatch.setattr(cut, 'skills_version', Mock(return_value='synthetic-revision'))
    status = Mock(return_value=[])
    submit = Mock(return_value=['id-1'])
    monkeypatch.setattr(cut, 'status', status)
    monkeypatch.setattr(cut, 'submit', submit)
    runner.run()
    plan = dict(tickets=[dict(title='Implement', files=['src/a.py'], change='Implement it', check='pytest')],
                test_files=['tests/test_a.py'])
    return runner, processes, plan, status, submit


def ticket(position=1, status='queued', reason=None):
    return dict(id=f'id-{position}', position=position, title=f'Ticket {position}', status=status, reason=reason)


def finish_cut(processes, plan):
    processes.finish('waiting', '```json\n' + json.dumps(plan) + '\n```')


def test_ticket_cut_delivers_and_submits_once(ticket_runner, delivery):
    runner, processes, plan, status, submit = ticket_runner
    first = processes.started[0]
    assert 'Change test files only' in first['prompt']
    assert 'kind "waiting"' in first['prompt']
    assert 'PR description' not in first['prompt']
    finish_cut(processes, plan)
    runner.run()
    submit.assert_called_once()
    task = submit.call_args.args[0]
    assert task['base_commit'] == delivery['tip']
    assert task['branch'] == first['branch']
    assert task['tasks'][0]['pinned_paths'] == plan['test_files']
    assert 'Keep this rule.' in task['tasks'][0]['goal']
    assert delivery['g'](delivery['remote'], 'rev-parse', 'refs/heads/' + first['branch']) == delivery['tip']
    status.return_value = [ticket()]
    runner.run()
    runner.run()
    assert status.call_count == 4
    assert submit.call_count == 1 and len(processes.started) == 1
    runner.github.open.assert_not_called()


@pytest.mark.parametrize('plan', [None, {}, {'tickets': [], 'test_files': []}])
def test_invalid_ticket_plan_never_delivers_or_submits(ticket_runner, plan):
    runner, processes, _, status, submit = ticket_runner
    runner.fence.publish = Mock()
    finish_cut(processes, plan)
    runner.run()
    item = state.load(runner.path)['slices'][0]
    assert item['attention']['kind'] == 'escalation'
    assert 'invalid plan' in item['attention']['body']
    runner.fence.publish.assert_not_called()
    submit.assert_not_called()


def test_existing_tickets_are_followed_without_submit(ticket_runner):
    runner, processes, plan, status, submit = ticket_runner
    status.return_value = [ticket(status='running')]
    runner.fence.publish = Mock(side_effect=AssertionError('existing workers own the branch'))
    finish_cut(processes, plan)
    runner.run()
    runner.run()
    submit.assert_not_called()
    assert state.load(runner.path)['slices'][0]['attention'] is None


@pytest.mark.parametrize('error', [state.StateError('submit refused'), OSError('could not start'),
                                  ValueError('bad reply')])
def test_failed_submission_is_never_retried(ticket_runner, error):
    runner, processes, plan, status, submit = ticket_runner
    submit.side_effect = error
    finish_cut(processes, plan)
    runner.run()
    assert state.load(runner.path)['slices'][0]['attention']['kind'] == 'escalation'
    runner.run()
    # Even clearing attention cannot authorize an automatic duplicate submit.
    data = state.load(runner.path)
    data['slices'][0]['attention'] = None
    state.save(runner.path, data)
    runner.run()
    assert submit.call_count == 1
    assert 'will not retry' in state.load(runner.path)['slices'][0]['attention']['body']


@pytest.mark.parametrize('outcome', ['queued', 'running', 'done', 'failed', 'escalated'])
def test_ticket_outcomes(ticket_runner, outcome):
    runner, processes, plan, status, submit = ticket_runner
    finish_cut(processes, plan)
    runner.run()
    status.return_value = [ticket(status=outcome, reason='synthetic reason')]
    runner.run()
    attention = state.load(runner.path)['slices'][0]['attention']
    if outcome in ('queued', 'running'):
        assert attention is None
    elif outcome == 'done':
        assert attention is None
        assert len(processes.started) == 2
        assert processes.started[-1]['review'] is True
    else:
        assert attention['kind'] == 'escalation'
        assert 'id-1' in attention['body'] and 'synthetic reason' in attention['body']
    runner.github.open.assert_not_called()
    assert submit.call_count == 1


def test_ticket_done_waits_for_every_ticket(ticket_runner):
    runner, processes, plan, status, _ = ticket_runner
    finish_cut(processes, plan)
    runner.run()
    status.return_value = [ticket(status='done'), ticket(2, 'running')]
    runner.run()
    assert state.load(runner.path)['slices'][0]['attention'] is None


def test_interrupted_submission_follows_but_does_not_retry(ticket_runner):
    runner, processes, plan, status, submit = ticket_runner
    finish_cut(processes, plan)
    runner.run()
    job = runner.jobs['voice/W1']
    job['phase'] = 'submitting'
    runner.save_job(job)
    status.return_value = [ticket(status='running')]
    runner.run()
    assert runner.jobs['voice/W1']['phase'] == 'tickets'
    assert submit.call_count == 1




@pytest.mark.parametrize('node_steps', [None, '', '  ', 'Install the merged commit'])
@pytest.mark.parametrize('reply_format', ['text', 'json'])
def test_resume_after_merge_waiting_cannot_publish(delivery, make_state, node_steps, reply_format):
    d = delivery
    runner = Runner(make_state(), github=Mock(), git=Mock(), processes=Mock(start=Mock(return_value=123)), codex_reader=lambda: 5)
    item = state.load(runner.path)['slices'][0]
    item['session'] = dict(tool='codex', id='synthetic-session', folder=str(d['work']))
    previous = {**d['job'], 'sha': 'merged-sha', 'phase': 'node-step'}
    runner.jobs = {item['id']: previous}
    runner.data = dict(slices=[item])
    runner.at = datetime.now(timezone.utc).isoformat()
    runner.fence.resume = Mock(return_value={key: previous[key] for key in ('repo', 'repository', 'branch', 'base', 'default')})
    runner.fence.publish = Mock()
    assert runner.launch(item, 'Node step answered', resume=True)
    resumed = runner.jobs[item['id']]
    assert resumed['sha'] == 'merged-sha'
    reply = {**request(resumed), 'node_steps': node_steps, 'sha': 'untrusted-reply-sha'}
    body = '```json\n' + json.dumps(reply) + '\n```' if reply_format == 'json' else node_steps or ''
    resumed.update(phase='ended', final=dict(kind='waiting', body=body))
    runner.apply_final(item, resumed)
    runner.fence.publish.assert_not_called()
    runner.github.open.assert_not_called()
    assert resumed['sha'] == 'merged-sha'
    if node_steps and node_steps.strip():
        assert item['attention']['kind'] == 'node-step'
        assert item['attention']['body'] == node_steps
        assert resumed['phase'] == 'node-step'
    else:
        assert item['state'] == 'in review'
        assert item['attention'] is None
        assert item['log'][-2]['event'] == 'finished'
    resumed.update(phase='ended', final=dict(kind='handover', body='Handover'))
    runner.apply_final(item, resumed)
    assert item['state'] == 'in review'


@pytest.mark.parametrize('prefix', [
    'Summary of the tests.\n\n',
    '```json\n{"not": "the plan"}\n```\n\nSummary.\n\n',
])
def test_ticket_plan_uses_last_fenced_block(ticket_runner, prefix):
    runner, processes, plan, status, submit = ticket_runner
    processes.finish('waiting', prefix + '```json\n' + json.dumps(plan) + '\n```')
    runner.run()
    submit.assert_called_once()
    assert submit.call_args.args[0]['tasks'][0]['title'] == plan['tickets'][0]['title']


@pytest.mark.parametrize('body', ['No plan here.', '```json\n{invalid}\n```'])
def test_ticket_plan_missing_or_invalid_json_stops(ticket_runner, body):
    runner, processes, plan, status, submit = ticket_runner
    processes.finish('waiting', body)
    runner.run()
    attention = state.load(runner.path)['slices'][0]['attention']
    assert attention['kind'] == 'escalation'
    assert 'invalid plan: expected fenced JSON' in attention['body']
    submit.assert_not_called()


def test_status_failure_prevents_submit(ticket_runner):
    runner, processes, plan, status, submit = ticket_runner
    status.side_effect = state.StateError('status command failed')
    finish_cut(processes, plan)
    runner.run()
    assert state.load(runner.path)['slices'][0]['attention']['kind'] == 'escalation'
    submit.assert_not_called()


def test_submission_recovers_when_state_save_was_lost(ticket_runner, monkeypatch):
    runner, processes, plan, status, submit = ticket_runner
    finish_cut(processes, plan)
    before = runner.path.read_bytes()
    with monkeypatch.context() as context:
        context.setattr(state, 'save', Mock(side_effect=OSError('interrupted state save')))
        with pytest.raises(OSError):
            runner.run()
    assert runner.path.read_bytes() == before
    status.return_value = [ticket(status='running')]
    runner.run()
    item = state.load(runner.path)['slices'][0]
    assert item['state'] == 'issued' and item['session']['id'] == 'synthetic-session'
    assert len(processes.started) == 1 and submit.call_count == 1


def test_explicit_cli_flow_keeps_existing_delivery(delivery, make_state, monkeypatch):
    from cplane import cut
    runner = Runner(make_state(), github=Mock(), git=Mock())
    item = state.load(runner.path)['slices'][0]
    item['flow'] = 'cli'
    job = delivery['job']
    job['final'] = dict(kind='waiting', body='```json\n' + json.dumps(request(job)) + '\n```')
    runner.at = datetime.now(timezone.utc).isoformat()
    status = Mock(side_effect=AssertionError('CLI flow never reads the queue'))
    monkeypatch.setattr(cut, 'status', status)
    runner.apply_final(item, job)
    assert job['phase'] == 'pr' and job['tip'] == delivery['tip']
    runner.github.open.assert_called_once_with('example/repo', request(job))
    status.assert_not_called()


def start_slice_review(ticket_runner):
    runner, processes, plan, status, submit = ticket_runner
    finish_cut(processes, plan)
    runner.run()
    status.return_value = [ticket(status='done')]
    runner.run()
    return ticket_runner


def review_answer(processes, verdict='pass', plan=None):
    answer = (dict(verdict='pass', title='Reviewed slice', body='Tests passed; whole brief checked.')
              if verdict == 'pass' else dict(verdict='fix', **plan))
    processes.finish('waiting', '```json\n' + json.dumps(answer) + '\n```')


def test_slice_review_pass_opens_pr_from_fresh_copy(ticket_runner, delivery):
    runner, processes, plan, status, submit = start_slice_review(ticket_runner)
    original, review = processes.started
    assert review['repo'] != original['repo']
    assert review['resume'] is None
    assert review['base'] == original['base']
    assert review['tip'] == delivery['tip']
    assert review['branch'] == original['branch']
    assert review['skills'] == 'synthetic-revision'
    assert 'Change nothing' in review['prompt']
    assert 'Keep this rule.' in review['prompt'] and 'Never that.' in review['prompt']
    assert not (Path(review['repo']) / '.git/hooks').exists()
    assert not (Path(review['repo']) / '.git/objects/info/alternates').exists()
    runner.fence.publish = Mock(side_effect=AssertionError('review must not publish'))
    review_answer(processes)
    runner.run()
    assert runner.jobs['voice/W1']['phase'] == 'pr'
    runner.github.open.assert_called_once_with('example/repo', dict(
        branch=original['branch'], title='Reviewed slice',
        body='Tests passed; whole brief checked.', node_steps=None))
    assert submit.call_count == 1 and not delivery['marker'].exists()


def begin_repair(ticket_runner):
    runner, processes, plan, status, submit = start_slice_review(ticket_runner)
    status.side_effect = lambda name: [] if name.endswith('/repair') else [ticket(status='done')]
    review_answer(processes, 'fix', plan)
    runner.run()
    return ticket_runner


def test_fix_submits_repair_once_and_reviews_once_more(ticket_runner, delivery):
    runner, processes, plan, status, submit = begin_repair(ticket_runner)
    assert submit.call_count == 2
    repair = submit.call_args.args[0]
    assert repair['slice'] == 'voice/W1/repair'
    assert repair['base_commit'] == delivery['tip']
    assert repair['branch'] == processes.started[0]['branch']
    assert repair['tasks'][0]['check_command'] == plan['tickets'][0]['check']
    assert repair['tasks'][0]['pinned_paths'] == plan['test_files']
    status.side_effect = lambda name: [ticket(status='running')]
    runner.run()
    runner.run()
    assert submit.call_count == 2 and len(processes.started) == 2
    status.side_effect = lambda name: [ticket(status='done')]
    runner.run()
    assert len(processes.started) == 3
    assert processes.started[-1]['repair'] is True
    assert processes.started[-1]['repo'] != processes.started[-2]['repo']
    review_answer(processes)
    runner.run()
    assert runner.jobs['voice/W1']['phase'] == 'pr'
    assert submit.call_count == 2
    assert status.call_args.args == ('voice/W1/repair',)


def test_second_fix_raises_attention_with_remaining_work(ticket_runner):
    runner, processes, plan, status, submit = begin_repair(ticket_runner)
    status.side_effect = lambda name: [ticket(status='done')]
    runner.run()
    review_answer(processes, 'fix', plan)
    runner.run()
    attention = state.load(runner.path)['slices'][0]['attention']
    assert attention['kind'] == 'escalation'
    assert 'still needs fixes after repair' in attention['body']
    assert 'Implement it' in attention['body']
    runner.run()
    assert submit.call_count == 2 and len(processes.started) == 3
    runner.github.open.assert_not_called()


@pytest.mark.parametrize('outcome', ['failed', 'escalated'])
def test_failed_repair_raises_attention(ticket_runner, outcome):
    runner, processes, plan, status, submit = begin_repair(ticket_runner)
    status.side_effect = lambda name: [ticket(status=outcome, reason='remaining defect')]
    runner.run()
    attention = state.load(runner.path)['slices'][0]['attention']
    assert attention['kind'] == 'escalation'
    assert 'id-1' in attention['body'] and 'remaining defect' in attention['body']
    assert submit.call_count == 2 and len(processes.started) == 2
    runner.github.open.assert_not_called()


@pytest.mark.parametrize('repair', [False, True])
def test_review_pass_recovers_lost_state_save_without_resubmitting(ticket_runner, monkeypatch, repair):
    if repair:
        runner, processes, plan, status, submit = begin_repair(ticket_runner)
        status.side_effect = lambda name: [ticket(status='done')]
        runner.run()
    else:
        runner, processes, plan, status, submit = start_slice_review(ticket_runner)
    runner.github.open.return_value = 12
    runner.github.checks.return_value = ('pending', '')
    review_answer(processes)
    with monkeypatch.context() as context:
        context.setattr(state, 'save', Mock(side_effect=OSError('interrupted state save')))
        with pytest.raises(OSError):
            runner.run()
    runner.run()
    runner.run()
    assert state.load(runner.path)['slices'][0]['pr'] == 12
    assert runner.jobs['voice/W1']['phase'] == 'pr'
    assert submit.call_count == (2 if repair else 1)
    assert len(processes.started) == (3 if repair else 2)


@pytest.mark.parametrize('existing', [False, True])
def test_repair_submission_interruption_uses_same_retry_safety(ticket_runner, existing):
    runner, processes, plan, status, submit = begin_repair(ticket_runner)
    job = runner.jobs['voice/W1']
    job['phase'] = 'submitting'
    runner.save_job(job)
    status.side_effect = lambda name: [ticket(status='running')] if existing else []
    runner.run()
    if existing:
        assert runner.jobs['voice/W1']['phase'] == 'tickets'
    else:
        assert 'will not retry' in state.load(runner.path)['slices'][0]['attention']['body']
    assert submit.call_count == 2


@pytest.mark.parametrize('answer', [None, {}, dict(verdict='pass', title='x'),
                                    dict(verdict='fix', tickets=[], test_files=[]),
                                    dict(verdict='pass', title='x', body='x', tickets=[])])
def test_invalid_review_never_submits_or_opens_pr(ticket_runner, answer):
    runner, processes, _, _, submit = start_slice_review(ticket_runner)
    processes.finish('waiting', '```json\n' + json.dumps(answer) + '\n```')
    runner.run()
    assert 'invalid review' in state.load(runner.path)['slices'][0]['attention']['body']
    assert submit.call_count == 1
    runner.github.open.assert_not_called()


@pytest.mark.parametrize('flow', ['cli', 'tickets'])
@pytest.mark.parametrize('changed_path,expected', [
    ('.github/workflows/test.yml', 4), ('guard/key', 4),
    ('source.py', 1), ('cplane/runner.py', 2), ('query.sql', 2), ('uv.lock', 2),
])
def test_change_classes_merge_in_both_flows(delivery, make_state, flow, changed_path, expected):
    d = delivery
    # Build commits only in the synthetic seed, never in an agent copy.
    seed = d['root'] / 'workflow-seed'
    d['g'](d['root'], 'clone', d['remote'], seed)
    table = seed / '.github/change-classes'
    table.parent.mkdir()
    table.write_text('4 /guard/**\n2 /cplane/runner.py\n')
    d['g'](seed, 'add', '.')
    d['g'](seed, 'commit', '-m', 'base policy')
    base = d['g'](seed, 'rev-parse', 'HEAD')
    path = seed / changed_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('synthetic\n')
    d['g'](seed, 'add', '.')
    d['g'](seed, 'commit', '-m', 'change')
    tip = d['g'](seed, 'rev-parse', 'HEAD')
    d['g'](seed, 'push', 'origin', 'HEAD:refs/heads/workflow-test')
    d['adapter'].git(d['clean'], 'fetch', 'origin', 'refs/heads/workflow-test')
    gh = Mock()
    gh.checks.return_value = ('green', '')
    gh.merge.return_value = 'merged-sha'
    runner = Runner(make_state(), github=gh, git=Mock())
    runner.at = datetime.now(timezone.utc).isoformat()
    item = state.load(runner.path)['slices'][0]
    item.update(flow=flow, pr=12, stop_before_merge=False,
                session=dict(tool='codex', id='synthetic-session', folder=str(d['work'])))
    job = {**d['job'], 'base': base, 'tip': tip, 'phase': 'pr', 'request': request(d['job'])}
    runner.jobs = {item['id']: job}
    runner.launch = Mock()
    runner.pr_checks(item, job)
    assert job['change_class'] == expected
    if expected == 4:
        assert item['attention']['kind'] == 'merge'
        assert changed_path in item['attention']['body']
        gh.merge.assert_not_called()
        item['attention']['approved'] = True
        runner.deliver(item)
        gh.merge.assert_called_once_with('example/repo', 12, expected=tip)
    else:
        gh.merge.assert_called_once_with('example/repo', 12, expected=tip)
    assert not d['marker'].exists()


def test_repair_pins_workers_latest_tip_and_second_review_keeps_original_base(ticket_runner, delivery):
    runner, processes, plan, status, submit = ticket_runner
    def diagnostics():
        item = state.load(runner.path)['slices'][0]
        review_count = sum(bool(job.get('review')) for job in processes.started)
        return f"attention={item['attention']!r}, job={runner.jobs.get(item['id'])!r}, review_count={review_count}"

    finish_cut(processes, plan)
    runner.run()
    d = delivery
    seed = d['root'] / 'worker-seed'
    d['g'](d['root'], 'clone', '--branch', processes.started[0]['branch'], d['remote'], seed)
    (seed / 'worker.py').write_text('first worker result\n')
    d['g'](seed, 'add', '.')
    d['g'](seed, 'commit', '-m', 'worker result')
    d['g'](seed, 'push', 'origin', 'HEAD')
    worker_tip = d['g'](seed, 'rev-parse', 'HEAD')
    status.return_value = [ticket(status='done')]
    runner.run()
    assert sum(bool(job.get('review')) for job in processes.started) == 1, diagnostics()
    assert processes.started[-1]['tip'] == worker_tip, diagnostics()
    status.side_effect = lambda name: [] if name.endswith('/repair') else [ticket(status='done')]
    review_answer(processes, 'fix', plan)
    runner.run()
    assert submit.call_args.args[0]['base_commit'] == worker_tip, diagnostics()
    (seed / 'worker.py').write_text('repaired worker result\n')
    d['g'](seed, 'commit', '-am', 'repair result')
    d['g'](seed, 'push', 'origin', 'HEAD')
    repaired_tip = d['g'](seed, 'rev-parse', 'HEAD')
    status.side_effect = lambda name: [ticket(status='done')]
    runner.run()
    assert sum(bool(job.get('review')) for job in processes.started) == 2, diagnostics()
    review = processes.started[-1]
    assert review['tip'] == repaired_tip and review['base'] == d['base'], diagnostics()
    assert (Path(review['repo']) / 'worker.py').read_text() == 'repaired worker result\n', diagnostics()
    assert not d['marker'].exists(), diagnostics()


def test_post_merge_review_session_does_not_resubmit_or_publish(ticket_runner):
    runner, processes, plan, status, submit = start_slice_review(ticket_runner)
    review_answer(processes)
    runner.run()
    data = state.load(runner.path)
    data['slices'][0]['stop_before_merge'] = False
    state.save(runner.path, data)
    sessions = fence.LOGIN_ROOT / 'codex/sessions'
    sessions.mkdir(parents=True)
    (sessions / 'synthetic-session.jsonl').write_text('{}\n')
    runner.github.checks.return_value = ('green', '')
    runner.github.merge.return_value = 'merged-sha'
    runner.run()
    resumed = processes.started[-1]
    assert resumed['prompt'].startswith('merged as merged-sha')
    assert resumed['sha'] == 'merged-sha'
    assert not resumed.get('review')
    runner.fence.publish = Mock(side_effect=AssertionError('cannot publish after merge'))
    reply = {**request(resumed), 'node_steps': 'Install the merged commit'}
    processes.finish('waiting', '```json\n' + json.dumps(reply) + '\n```')
    runner.run()
    assert state.load(runner.path)['slices'][0]['attention']['kind'] == 'node-step'
    data = state.load(runner.path)
    data['slices'][0]['attention']['answer'] = 'Proceed to handover'
    state.save(runner.path, data)
    runner.run()
    assert processes.started[-1]['sha'] == 'merged-sha'
    processes.finish('handover', 'Handover')
    runner.run()
    assert state.load(runner.path)['slices'][0]['state'] == 'in review'
    assert submit.call_count == 1
    runner.github.open.assert_called_once()


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


@pytest.mark.parametrize('reason', ['paused', 'capacity'])
def test_review_waits_for_pause_and_capacity(ticket_runner, reason):
    runner, processes, plan, status, submit = ticket_runner
    finish_cut(processes, plan)
    runner.run()
    status.return_value = [ticket(status='done')]
    if reason == 'paused':
        data = state.load(runner.path)
        data['slices'][0]['paused'] = True
        state.save(runner.path, data)
    else:
        runner.codex_reader = lambda: 100
    runner.run()
    assert runner.jobs['voice/W1']['phase'] == 'review-ready'
    assert len(processes.started) == 1
    data = state.load(runner.path)
    data['slices'][0]['paused'] = False
    state.save(runner.path, data)
    runner.codex_reader = lambda: 5
    runner.run()
    runner.run()
    assert len(processes.started) == 2 and submit.call_count == 1


def test_existing_tickets_done_placeholder_continues_into_review(ticket_runner):
    runner, processes, plan, status, submit = ticket_runner
    finish_cut(processes, plan)
    runner.run()
    data = state.load(runner.path)
    data['slices'][0]['attention'] = dict(kind='node-step', body='tickets done',
                                         since=runner.at, answer=None, approved=False)
    state.save(runner.path, data)
    status.return_value = [ticket(status='done')]
    runner.run()
    assert len(processes.started) == 2
    assert state.load(runner.path)['slices'][0]['attention'] is None
    assert submit.call_count == 1


def test_failed_repair_submission_is_not_retried(ticket_runner):
    runner, processes, plan, status, submit = start_slice_review(ticket_runner)
    status.side_effect = lambda name: []
    submit.side_effect = state.StateError('repair submit refused')
    review_answer(processes, 'fix', plan)
    runner.run()
    assert 'repair submit refused' in state.load(runner.path)['slices'][0]['attention']['body']
    data = state.load(runner.path)
    data['slices'][0]['attention'] = None
    state.save(runner.path, data)
    runner.run()
    assert 'will not retry' in state.load(runner.path)['slices'][0]['attention']['body']
    assert submit.call_count == 2


def test_review_cannot_bypass_pr_flow_with_handover(ticket_runner):
    runner, processes, _, _, submit = start_slice_review(ticket_runner)
    processes.finish('handover', 'Premature handover')
    runner.run()
    item = state.load(runner.path)['slices'][0]
    assert item['state'] == 'escalated' and 'invalid review' in item['attention']['body']
    assert submit.call_count == 1
    runner.github.open.assert_not_called()


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




def test_read_failure_duration_and_success_resets(delivery, make_state, monkeypatch):
    d = delivery
    path = make_state()
    data = state.load(path)
    item = data['slices'][0]
    item.update(state='issued', pr=12, session=dict(tool='codex', id='synthetic-session', folder=str(d['work'])))
    item['log'].append(dict(at=datetime.now(timezone.utc).isoformat(), actor='runner',
                            event='collected turn: turn-1'))
    state.save(path, data)
    runner = Runner(path, git=Mock(), runs=d['root'] / 'control')
    folder = runner.runs / 'turn-1'
    folder.mkdir(parents=True)
    job = d['job']
    job.update(run=str(folder), phase='pr', tip=d['tip'], request=request(job), github_read_failures=3)
    runner.save_job(job)
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    failing = [True]
    def run(args, **kwargs):
        if failing[0]:
            return subprocess.CompletedProcess(args, 1, '', d['secret'])
        response = {'state': 'OPEN', 'title': 'Synthetic PR', 'headRefOid': d['tip']} if args[1:3] == ['pr', 'view'] else {'workflow_runs': []}
        return subprocess.CompletedProcess(args, 0, json.dumps(response), '')
    monkeypatch.setattr(subprocess, 'run', run)
    start = datetime.now(timezone.utc)
    current = [start]
    runner.clock = lambda: current[0]
    for minute in (0, 1, 24):
        current[0] = start + timedelta(minutes=minute)
        runner.run()
        assert json.loads((folder / 'job.json').read_text())['github_read_failure_since'] == start.isoformat()
        assert 'github_read_failures' not in json.loads((folder / 'job.json').read_text())
        assert state.load(path)['slices'][0]['attention'] is None
    failing[0] = False
    runner.run()
    assert 'github_read_failure_since' not in json.loads((folder / 'job.json').read_text())
    failing[0] = True
    current[0] = start + timedelta(minutes=25)
    runner.run()
    current[0] = start + timedelta(minutes=49, seconds=59)
    runner.run()
    assert state.load(path)['slices'][0]['attention'] is None
    current[0] = start + timedelta(minutes=50)
    runner.run()
    saved = state.load(path)['slices'][0]
    assert saved['attention']['kind'] == 'escalation'
    assert d['secret'] not in saved['attention']['body']


def test_invalid_plan_is_collected_once_then_answer_resumes(ticket_runner):
    runner, processes, plan, status, submit = ticket_runner
    finish_cut(processes, {})
    runner.run()
    first = state.load(runner.path)['slices'][0]
    assert first['attention']['kind'] == 'escalation'
    runner.run()
    second = state.load(runner.path)['slices'][0]
    assert second['attention'] == first['attention']
    assert sum(e['event'].startswith('escalation:') for e in second['log']) == 1
    assert sum(e['event'].startswith('collected turn:') for e in second['log']) == 1
    sessions = fence.LOGIN_ROOT / 'codex/sessions'
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / 'synthetic-session.jsonl').write_text('{}\n')
    second['attention']['answer'] = 'Fix the plan'
    data = state.load(runner.path)
    data['slices'][0] = second
    state.save(runner.path, data)
    runner.run()
    assert len(processes.started) == 2
    assert processes.started[-1]['prompt'].startswith('Fix the plan')
    finish_cut(processes, plan)
    runner.run()
    assert state.load(runner.path)['slices'][0]['attention'] is None
    submit.assert_called_once()


def test_accepted_plan_clears_answered_attention(ticket_runner):
    runner, processes, plan, status, submit = ticket_runner
    data = state.load(runner.path)
    data['slices'][0]['attention'] = dict(kind='escalation', body='Earlier problem',
                                          since=runner.at, answer='Resolved', approved=False)
    state.save(runner.path, data)
    finish_cut(processes, plan)
    runner.run()
    assert state.load(runner.path)['slices'][0]['attention'] is None
    submit.assert_called_once()


@pytest.mark.parametrize('answer,paused,starts', [
    ('Resolved', False, True),
    (None, False, False),
    ('Resolved', True, False),
])
def test_review_ready_attention_and_pause(ticket_runner, answer, paused, starts):
    runner, processes, plan, status, submit = ticket_runner
    finish_cut(processes, plan)
    runner.run()
    data = state.load(runner.path)
    data['slices'][0].update(paused=paused, attention=dict(
        kind='escalation', body='Earlier problem', since=runner.at,
        answer=answer, approved=False))
    state.save(runner.path, data)
    status.return_value = [ticket(status='done')]
    runner.run()
    assert (len(processes.started) == 2) is starts
    attention = state.load(runner.path)['slices'][0]['attention']
    assert (attention is None) is (answer is not None)
    assert submit.call_count == 1


@pytest.mark.parametrize('auth', [None, 'token'])
def test_legacy_token_mode_unchanged(delivery, monkeypatch, auth):
    from cplane import github_app
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


def test_usage_probe_discards_workspace_prompt_and_output(delivery, monkeypatch):
    from cplane.runner import probe_codex_usage, codex_usage
    d = delivery
    (fence.LOGIN_ROOT / 'codex/sessions').mkdir(parents=True)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[1] == 'run':
            assert args[-1] == 'Reply only: OK'
            assert args[args.index('-m') + 1] == 'gpt-6-luna'
            assert 'model_reasoning_effort="low"' in args
            assert 'history.persistence="none"' in args and '--json' in args
            assert kwargs['env'] == fence.host_environment()
            session = fence.LOGIN_ROOT / 'codex/sessions/probe-session.jsonl'
            session.write_text('\n'.join([
                json.dumps({'prompt': 'Reply only: OK', 'output': 'OK'}),
                json.dumps({'payload': {'rate_limits': {'primary': {'used_percent': 0}}}})]))
            return subprocess.CompletedProcess(args, 0,
                '{"type":"thread.started","thread_id":"probe-session"}\n', '')
        return subprocess.CompletedProcess(args, 0, '', '')
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setenv('CPLANE_RUNS', str(d['folder'].parent))
    probe_codex_usage(d['folder'])
    assert calls[-1][1] == 'session-cleanup'
    assert not list(fence.WORK_ROOT.glob('usage-*'))
    assert not [p for p in d['folder'].glob('usage-*') if p.is_dir()]
    report = d['folder'] / 'usage-report.jsonl'
    assert 'prompt' not in report.read_text() and 'OK' not in report.read_text()
    assert codex_usage() == 0
    assert not (fence.LOGIN_ROOT / 'codex/sessions/probe-session.jsonl').exists()


def test_github_updated_head_is_fetched_in_clean_clone_before_merge(delivery, make_state):
    d = delivery
    d['adapter'].publish(d['job'], request(d['job']))
    seed = d['root'] / 'update-seed'
    d['g'](d['root'], 'clone', d['remote'], seed)
    (seed / 'main-change').write_text('new main\n')
    d['g'](seed, 'add', '.')
    d['g'](seed, 'commit', '-m', 'advance main')
    d['g'](seed, 'push', 'origin', 'main')
    d['g'](seed, 'checkout', d['job']['branch'])
    d['g'](seed, 'merge', 'main', '--no-edit')
    updated = d['g'](seed, 'rev-parse', 'HEAD')
    gh = Mock()
    gh.merge_info.return_value = dict(mergeStateStatus='BEHIND', mergeable='MERGEABLE')
    def update(*args):
        d['g'](seed, 'push', 'origin', 'HEAD')
        gh.merge_info.return_value = dict(mergeStateStatus='CLEAN', mergeable='MERGEABLE')
        return updated
    gh.update_branch.side_effect = update
    gh.checks.return_value = ('pending', '')
    runner = Runner(make_state(), github=gh, git=Mock())
    runner.fence = d['adapter']
    runner.at = datetime.now(timezone.utc).isoformat()
    item = state.load(runner.path)['slices'][0]
    item.update(pr=12, stop_before_merge=False)
    job = dict(d['job'], phase='pr', tip=d['tip'], request=request(d['job']))
    runner.pr_checks(item, job)
    assert job['updated_head'] and job['tip'] == updated
    gh.checks.assert_called_once_with('example/repo', 12, expected=d['tip'])
    gh.checks.reset_mock()
    assert d['adapter'].git(d['clean'], 'cat-file', '-e', updated, allow_failure=True).returncode
    runner.pr_checks(item, job)
    assert 'updated_head' not in job
    gh.checks.assert_called_once_with('example/repo', 12, expected=updated)
    gh.merge.assert_not_called()
    gh.checks.return_value = ('green', '')
    gh.merge.return_value = 'merged-sha'
    runner.pr_checks(item, job)
    gh.merge.assert_called_once_with('example/repo', 12, expected=updated)
    assert job['base'] == d['base']
    assert not d['marker'].exists()


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
@pytest.mark.parametrize('location', [
    'diff', 'commit message', 'PR body', 'PR title', 'branch name', 'earlier commit',
    'binary diff', 'renamed file', 'private filename', 'non-UTF8 filename',
    'merge resolution', 'canary'])
def test_public_delivery_blocks_private_content_before_push(delivery, make_state, location, capsys):
    d = delivery
    planted = 'SYNTHETIC-PRIVATE-PHRASE'
    d['deny_list'].write_text(planted.lower() + '\n')
    job = d['job']
    req = request(job)

    def git(*args):
        return d['g'](d['work'], '-c', 'core.hooksPath=/dev/null',
                      '-c', 'core.fsmonitor=false', *args)

    if location in ('diff', 'earlier commit', 'binary diff', 'canary', 'merge resolution'):
        content = deny.CANARY if location == 'canary' else planted
        if location == 'merge resolution':
            git('checkout', '-b', 'side')
            (d['work'] / 'side').write_text('side\n')
            git('add', '.')
            git('commit', '-m', 'side')
            git('checkout', job['branch'])
            git('merge', '--no-ff', '--no-commit', 'side')
        (d['work'] / 'README').write_text('safe\n' + content + ('\0' if location == 'binary diff' else '') + '\n')
        git('add', '.')
        git('commit', '-m', 'synthetic addition')
        if location == 'earlier commit':
            (d['work'] / 'README').write_text('safe\n')
            git('add', '.')
            git('commit', '-m', 'synthetic removal')
    elif location in ('renamed file', 'private filename', 'non-UTF8 filename'):
        filename = {'renamed file': 'renamed\tfile', 'private filename': planted,
                    'non-UTF8 filename': os.fsdecode(b'bad-\xff')}[location]
        git('mv', 'README', filename)
        (d['work'] / filename).write_text(planted + '\n')
        git('add', '.')
        git('commit', '-m', 'rename')
    elif location == 'commit message':
        git('commit', '--allow-empty', '-m', 'prefix ' + planted + ' suffix')
    elif location == 'branch name':
        job['branch'] = 'slice/' + planted
        req['branch'] = job['branch']
        git('branch', '-m', job['branch'])
    else:
        req['body' if location == 'PR body' else 'title'] = 'prefix ' + planted + ' suffix'
    git('bundle', 'create', d['bundles']['good'], 'HEAD', 'refs/heads/' + job['branch'])
    # Only delivery calls count; synthetic fixture setup uses offline Git.
    d['calls'].clear()
    runner = Runner(make_state(), git=Mock(), github=Mock(), runs=d['root'] / 'control')
    runner.at = datetime.now(timezone.utc).isoformat()
    item = state.load(runner.path)['slices'][0]
    job['final'] = dict(kind='waiting', body='```json\n' + json.dumps(req) + '\n```')
    runner.jobs = {item['id']: job}
    try:
        runner.apply_final(item, job)
    except state.StateError:
        runner.slice_failure(item, 'collect/deliver')
    attention = item['attention']
    assert attention['kind'] == 'escalation'
    assert 'private-content check:' in attention['body']
    if location in ('diff', 'earlier commit', 'binary diff', 'merge resolution', 'canary'):
        assert "'README':2" in attention['body']
    elif location == 'renamed file':
        assert "renamed\\tfile':1" in attention['body']
    elif location == 'private filename':
        assert 'file ' in attention['body']
    elif location == 'non-UTF8 filename':
        assert 'bad-\\udcff' in attention['body']
    else:
        assert location in attention['body']
    assert planted.casefold() not in json.dumps(item['log']).casefold()
    assert planted.casefold() not in attention['body'].casefold()
    assert deny.CANARY not in attention['body']
    runner.github.open.assert_not_called()
    assert not any('push' in args for args, _ in d['calls'])
    assert planted not in str(capsys.readouterr())
    assert not d['marker'].exists()


def test_missing_list_stops_public_push(delivery):
    d = delivery
    d['deny_list'].unlink()
    with pytest.raises(deny.Denied, match='deny-list unavailable'):
        d['adapter'].publish(d['job'], request(d['job']))
    assert not any('push' in args for args, _ in d['calls'])


def test_private_repository_skips_content_and_list_checks(delivery, monkeypatch):
    d = delivery
    d['deny_list'].unlink()
    original_run = subprocess.run

    def run(args, **kwargs):
        if args[:2] == ['gh', 'api']:
            assert kwargs['env']['GH_TOKEN'] == d['secret']
            return subprocess.CompletedProcess(args, 0, '{"private": true}', '')
        return original_run(args, **kwargs)

    monkeypatch.setattr(subprocess, 'run', run)
    req = request(d['job'])
    req['body'] = deny.CANARY
    assert d['adapter'].publish(d['job'], req) == d['tip']
    assert not any('rev-list' in args for args, _ in d['calls'])
    # The PR send point shares the same private visibility decision.
    runner = Runner(d['root'] / 'state.json', github=Mock())
    runner.fence = d['adapter']
    runner.github.open.return_value = 42
    assert runner.open_pr('example/repo', req) == 42
