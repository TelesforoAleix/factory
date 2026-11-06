"""Synthetic credentials, local remotes and hostile copies; no node or real login."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from unittest.mock import Mock

import pytest

from cplane import executors, fence, state
from cplane.executors import Processes, command
from cplane.runner import Git, GitHub, Runner


@pytest.fixture
def delivery(tmp_path, monkeypatch):
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
        if args[0] == 'factory-cli':
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
                g=g, folder=folder, root=tmp_path, real_run=real_run)


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


def test_real_bundle_delivery_never_runs_host_git_in_hostile_copy(delivery, capsys):
    d = delivery
    assert d['adapter'].publish(d['job'], request(d['job'])) == d['tip']
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
def test_every_fenced_executor_command_uses_factory_cli(tmp_path, tool, resume):
    job = dict(tool=tool, run=str(tmp_path), repo='/srv/factory/work/copy', model='synthetic',
               prompt='-literal prompt', resume=resume, fence=True)
    args = command(job)
    assert args[:9] == ['factory-cli', 'run', '--tool', tool, '--repo', job['repo'],
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
    monkeypatch.setattr(executors.os, 'chown', Mock())
    monkeypatch.setattr(executors.subprocess, 'Popen', Mock(return_value=Mock(pid=123)))
    job = dict(tool=tool, run=str(folder), repo='/untrusted/repo', model='synthetic',
               prompt='synthetic', fence=True, started_ns=0)
    Processes().start(job)
    assert (folder / 'request.json').stat().st_mode & 0o777 == 0o600
    assert not (folder / 'io/request.json').exists()
    assert 'GH_TOKEN' not in executors.subprocess.Popen.call_args.kwargs['env']
    final = dict(kind='waiting', body='synthetic')

    def run(args, **kwargs):
        assert args[:2] == ['factory-cli', 'run']
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


def test_fenced_checks_wait_for_test_and_bind_to_delivered_head(monkeypatch):
    gh = GitHub()
    gh.call = Mock(return_value='{"headRefOid":"tip","statusCheckRollup":[]}')
    assert gh.checks('example/repo', 1, expected='tip') == ('pending', '')
    gh.call = Mock(return_value='{"headRefOid":"other"}')
    with pytest.raises(state.StateError, match='PR head differs'):
        gh.checks('example/repo', 1, expected='tip')


def test_fenced_merge_uses_match_head_and_rejects_replaced_head():
    gh = GitHub()
    gh.call = Mock(side_effect=[
        '{"state":"OPEN","headRefOid":"tip","mergeCommit":null}', '',
        '{"state":"MERGED","mergeCommit":{"oid":"merge-sha"}}'])
    assert gh.merge('example/repo', 12, expected='tip') == 'merge-sha'
    assert gh.call.call_args_list[1].args == (
        'example/repo', 'pr', 'merge', '12', '--squash', '--match-head-commit', 'tip')
    gh.call = Mock(return_value='{"state":"OPEN","headRefOid":"other","mergeCommit":null}')
    with pytest.raises(state.StateError, match='PR head differs'):
        gh.merge('example/repo', 12, expected='tip')
    assert gh.call.call_count == 1


@pytest.mark.parametrize('unknown', [False, True])
def test_fenced_repository_capacity_uses_repository_identity(make_state, monkeypatch, unknown):
    monkeypatch.setenv('CPLANE_FENCE', '1')
    runner = Runner(make_state(), git=Mock())
    runner.data = state.load(runner.path)
    item = runner.data['slices'][0]
    other = copy.deepcopy(item)
    other.update(id='voice/W0', state='issued', repo='EXAMPLE/REPO')
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


def test_mode_switch_does_not_run_host_git_in_old_fenced_copy(delivery, make_state, monkeypatch):
    d = delivery
    monkeypatch.delenv('CPLANE_FENCE')
    path = make_state()
    runner = Runner(path, git=Mock(), github=Mock(), processes=Mock(), runs=d['root'] / 'control')
    (runner.runs / 'synthetic').mkdir(parents=True)
    job = {**d['job'], 'run': str(runner.runs / 'synthetic'), 'phase': 'ended',
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


def test_postgres_fenced_pass_pulls_briefs_ff_only(delivery, monkeypatch):
    d = delivery
    folder = d['root'] / 'briefs'
    folder.mkdir()
    (folder / '.git').mkdir()
    monkeypatch.setattr(state, 'postgres', lambda: True)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, '', ''))
    monkeypatch.setattr(subprocess, 'run', run)
    Git().pull(folder / 'slices.json')
    args = run.call_args.args[0]
    assert args[-2:] == ['pull', '--ff-only']
    assert 'core.hooksPath=/dev/null' in args
    assert d['secret'] not in str(args)
    Git().pull(d['root'] / 'not-a-clone/slices.json')
    assert run.call_count == 1


def test_fenced_primer_never_starts_cli_on_host(delivery, monkeypatch):
    from cplane import primer
    d = delivery
    monkeypatch.setenv('CPLANE_RUNS', str(d['root'] / 'runs'))
    run = Mock(return_value=subprocess.CompletedProcess([], 0, b'', b''))
    monkeypatch.setattr(subprocess, 'run', run)
    assert primer.prime()
    assert run.call_count == 2
    for call in run.call_args_list:
        assert call.args[0][:2] == ['factory-cli', 'run']
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
