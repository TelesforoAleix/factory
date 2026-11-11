"""Synthetic state, archives and host commands; no host installation is changed."""
import copy
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cplane import installation, install_host, state
from cplane.cli import main
from cplane.runner import Runner
from cplane.stores import FileStore
from factory_ui import create_app
from test_stores import pg_store
from test_runner import setup, claude_start, edit, item, pr_reply

SHA = 'a' * 40


@pytest.mark.parametrize('reply_format', ['text', 'fenced-json', 'json'])
def test_node_step_after_null_merge_is_installable(setup, tmp_path, monkeypatch, reply_format):
    runner, processes, github = setup
    monkeypatch.setenv('CPLANE_RUNS', str(runner.runs.parent))
    monkeypatch.setenv('CPLANE_STATE', str(runner.path))
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', item(runner)['repo'])
    monkeypatch.setattr(install_host, 'INSTALL_ROOT', tmp_path)
    edit(runner, lambda s: s.update(stop_before_merge=False))
    github.merge.return_value = SHA
    claude_start(runner)
    processes.finish('waiting', pr_reply(None))
    runner.run()
    github.checks.return_value = 'green', ''
    runner.run()
    assert processes.started[-1]['sha'] == SHA
    assert item(runner)['attention'] is None
    reply = 'Install the merged commit; ignore reply sha ' + 'b' * 40
    if reply_format != 'text':
        reply = json.dumps(dict(branch='ignored', title='ignored', body='ignored',
                                node_steps='Install the merged commit', sha='b' * 40))
        if reply_format == 'fenced-json':
            reply = '```json\n' + reply + '\n```\nHandover details'
    processes.finish('waiting', reply)
    runner.run()
    newest = runner.jobs['voice/W1']
    assert newest['phase'] == 'node-step'
    assert newest['sha'] == SHA
    assert json.loads((Path(newest['run']) / 'job.json').read_text())['phase'] == 'node-step'
    assert item(runner)['attention']['kind'] == 'node-step'
    assert main(['--state', str(runner.path), 'install', 'voice/W1']) == 0
    with monkeypatch.context() as patch:
        patch.setattr(installation.subprocess, 'run', Mock(return_value=SimpleNamespace(
            stdout='LoadState=not-found', returncode=0)))
        start = Mock(return_value=True)
        patch.setattr(installation, 'start_unit', start)
        runner.run()
        start.assert_called_once()
        assert item(runner)['attention']['kind'] == 'node-step'
    paths = script_archive(monkeypatch, 'import json; print(json.dumps({"manual": []}))')
    request = next(installation.pending(state.load(runner.path)))[1]
    assert install_host.install('voice/W1', request) == {'ok': True, 'commit': SHA, 'manual': []}
    assert paths == [f'compare/{SHA}...main', f'tarball/{SHA}']
    github.open.assert_called_once()
    github.merge.assert_called_once()


def node_step(item):
    item['attention'] = {'kind': 'node-step', 'body': 'touch /NEVER-EXECUTE', 'since': '2026-11-01T00:00:00+00:00', 'answer': None, 'approved': False}
    return item


def test_request_validation_and_global_exclusion(make_state, slice_data):
    other = copy.deepcopy(slice_data)
    other['id'] = 'other/S1'
    path = make_state([node_step(slice_data), node_step(other)])
    assert main(['--state', str(path), '--actor', 'chat:12', 'install', slice_data['id']]) == 0
    assert list(installation.pending(state.load(path)))[0][0]['log'][0]['actor'] == 'chat:12'
    assert main(['--state', str(path), 'install', other['id']]) == 1
    assert main(['--state', str(path), '--actor', 'runner', 'install', other['id']]) == 1
    assert not Path('/NEVER-EXECUTE').exists()


def test_requires_open_node_step(make_state, slice_data):
    path = make_state()
    assert main(['--state', str(path), 'install', slice_data['id']]) == 1
    node_step(slice_data)['attention']['answer'] = 'done'
    path = make_state([slice_data])
    assert main(['--state', str(path), 'install', slice_data['id']]) == 1


def test_site_guard_and_request(make_state, slice_data):
    path = make_state([node_step(slice_data)])
    client = create_app(FileStore(path)).test_client()
    url = '/api/slices/' + slice_data['id'] + '/install'
    assert client.post(url).status_code == 403
    assert client.post(url, headers={'X-Factory-UI': '1'}).status_code == 202
    assert client.post(url, headers={'X-Factory-UI': '1'}).status_code == 400
    assert state.load(path)['slices'][0]['log'][0]['actor'] == 'owner'


def prepared_runner(tmp_path, slice_data):
    item = node_step(slice_data)
    data = {'slices': [item]}
    installation.request_change('owner')(item, data, 'now')
    runner = Runner(tmp_path / 'slices.json', runs=tmp_path / 'runs')
    runner.data = data
    runner.at = 'now'
    runner.jobs = {item['id']: {'phase': 'node-step', 'sha': SHA}}
    request = list(installation.pending(data))[0][1]
    return runner, item, request


@pytest.mark.parametrize('result,kind', [({'ok': True, 'commit': SHA, 'manual': []}, 'node-step'),
                                        ({'ok': True, 'commit': SHA, 'manual': ['node/proxy']}, 'escalation'),
                                        ({'ok': False}, 'node-step')])
def test_launch_then_result(tmp_path, slice_data, monkeypatch, result, kind):
    runner, item, request = prepared_runner(tmp_path, slice_data)
    calls = []
    loaded = False
    def command(args, **kwargs):
        nonlocal loaded
        calls.append(args)
        if args[0] == 'systemctl':
            return SimpleNamespace(stdout='LoadState=loaded\nActiveState=activating' if loaded else 'LoadState=not-found', returncode=0)
        loaded = True
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(installation.subprocess, 'run', command)
    installation.process(runner)
    installation.process(runner)
    assert sum(c[0] == 'systemd-run' for c in calls) == 1
    assert all('touch /NEVER-EXECUTE' not in c for c in calls)
    assert '--no-block' in calls[1]
    assert calls[1][-3:] == [item['id'], '--request', request]
    assert '--property=EnvironmentFile=/etc/factory/runner.env' in calls[1]
    with pytest.raises(state.StateError, match='already'):
        installation.request_change('owner')(item, runner.data, 'now')
    (runner.runs / 'installs' / (request + '.json')).write_text(json.dumps(result))
    installation.process(runner)
    assert item['attention']['kind'] == kind
    if result['ok'] and not result.get('manual'):
        assert item['attention']['answer'] == 'Installed ' + SHA + '. Node steps are done. End with kind handover.'
    if not result['ok']:
        assert item['attention']['answer'] is None
        assert installation.install_failure(item['attention'])
        assert runner.jobs[item['id']]['sha'] == SHA
    assert not list(installation.pending(runner.data))


@pytest.mark.parametrize('status', ['LoadState=loaded\nActiveState=failed', 'LoadState=loaded\nActiveState=inactive'])
def test_interrupted_unit_not_retried(tmp_path, slice_data, monkeypatch, status):
    runner, item, _ = prepared_runner(tmp_path, slice_data)
    command = Mock(return_value=SimpleNamespace(stdout=status, returncode=0))
    monkeypatch.setattr(installation.subprocess, 'run', command)
    installation.process(runner)
    assert command.call_count == 1
    assert item['attention']['kind'] == 'escalation'
    assert not list(installation.pending(runner.data))


def host_setup(tmp_path, make_state, slice_data, monkeypatch):
    path = make_state([node_step(slice_data)])
    monkeypatch.setenv('CPLANE_STATE', str(path))
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', slice_data['repo'])
    runs = installation.runs_path(path)
    folder = runs / 'job'
    folder.mkdir(parents=True)
    (folder / 'job.json').write_text(json.dumps({'id': slice_data['id'], 'phase': 'node-step', 'sha': SHA, 'started_ns': 1}))
    monkeypatch.setattr(install_host, 'INSTALL_ROOT', tmp_path)
    return path


@pytest.mark.parametrize('allowed,comparison,message', [('', {}, 'allowlisted'),
    ('example/repo', {'status': 'diverged', 'merge_base_commit': {'sha': SHA}}, 'not on main'),
    ('example/repo', {'status': 'ahead', 'merge_base_commit': {'sha': 'b' * 40}}, 'not on main')])
def test_refuses_unlisted_or_off_main(tmp_path, make_state, slice_data, monkeypatch, allowed, comparison, message):
    host_setup(tmp_path, make_state, slice_data, monkeypatch)
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', allowed)
    github = Mock(return_value=comparison)
    monkeypatch.setattr(install_host, 'github', github)
    with pytest.raises(state.StateError, match=message):
        install_host.install(slice_data['id'])
    assert github.call_count == (1 if allowed else 0)


def test_exact_archive_and_clean_installer_environment(tmp_path, make_state, slice_data, monkeypatch):
    host_setup(tmp_path, make_state, slice_data, monkeypatch)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w:gz') as tar:
        content = b'print("reviewed installer")'
        info = tarfile.TarInfo('root/node/install')
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    paths = []
    def github(repo, path, output=None):
        paths.append(path)
        if output:
            output.write(archive.getvalue())
        else:
            return {'status': 'ahead', 'merge_base_commit': {'sha': SHA}}
    monkeypatch.setattr(install_host, 'github', github)
    monkeypatch.setenv('GH_TOKEN', 'synthetic-never-forward')
    monkeypatch.setenv('PATH', '/opt/factory/.venv/bin:/usr/local/bin:/usr/bin:/bin')
    monkeypatch.setenv('LANG', 'C.UTF-8')
    command = Mock(return_value=SimpleNamespace(returncode=0, stdout='{"manual": []}'))
    monkeypatch.setattr(install_host.subprocess, 'run', command)
    assert install_host.install(slice_data['id']) == {'ok': True, 'commit': SHA, 'manual': []}
    assert paths == [f'compare/{SHA}...main', f'tarball/{SHA}']
    assert 'GH_TOKEN' not in command.call_args.kwargs['env']
    env = command.call_args.kwargs['env']
    assert env['PATH'] == '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    assert env['HOME'] == '/root'
    assert env['LANG'] == 'C.UTF-8'
    assert env['CPLANE_INSTALL_REPOS'] == slice_data['repo']
    assert command.call_args.args[0][-1] == SHA


@pytest.mark.parametrize('name,link', [('../outside', False), ('/outside', False), ('root/link', True)])
def test_archive_rejects_traversal_and_links(tmp_path, name, link):
    archive = tmp_path / 'archive'
    with tarfile.open(archive, 'w') as tar:
        info = tarfile.TarInfo(name)
        if link:
            info.type = tarfile.SYMTYPE
            info.linkname = '/etc/factory/github-token'
        tar.addfile(info)
    with pytest.raises(state.StateError):
        install_host.unpack(archive, tmp_path / 'out')


@pytest.fixture
def installer(tmp_path, monkeypatch):
    loader = importlib.machinery.SourceFileLoader('node_installer', 'node/install')
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    target = tmp_path / 'factory'
    stage = tmp_path / 'stage'
    for path in (target, stage):
        (path / 'node/bin').mkdir(parents=True)
        (path / 'node/systemd').mkdir()
        (path / 'node/cli').mkdir()
        (path / 'node/cli/Dockerfile').write_text('old fence')
        (path / 'node/bin/launcher').write_text('old bin')
        (path / 'code').write_text('old code')
    (target / '.venv').mkdir()
    (target / '.venv/python').write_text('old environment')
    (stage / 'code').write_text('new code')
    (stage / 'node/bin/launcher').write_text('new bin')
    (stage / 'node/cli/Dockerfile').write_text('new fence')
    bin_dir, units = tmp_path / 'bin', tmp_path / 'systemd'
    bin_dir.mkdir()
    units.mkdir()
    (bin_dir / 'launcher').write_text('old bin')
    monkeypatch.setattr(module, 'TARGET', target)
    monkeypatch.setattr(module, 'BIN', bin_dir)
    monkeypatch.setattr(module, 'SYSTEMD', units)
    monkeypatch.setattr(module.grp, 'getgrnam', lambda name: SimpleNamespace(gr_gid=23002))
    monkeypatch.setattr(module.os, 'chown', lambda *a: None)
    # Executable fakes exercise argv, sync, UI build, restart and failing health check.
    commands = tmp_path / 'commands'
    commands.mkdir()
    log = tmp_path / 'commands.log'
    for name in ('uv', 'docker', 'systemctl', 'factory-cplane', 'chown', 'chmod', 'curl', 'groupadd', 'usermod', 'useradd'):
        script = commands / name
        script.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + ' $*" >> "$INSTALL_TEST_LOG"\n' +
                          ('if [ "$1" = python ]; then echo /opt/python/3.13/bin/python; fi\n' if name == 'uv' else '') +
                          ('if [ -f "$INSTALL_TEST_FAIL" ]; then rm "$INSTALL_TEST_FAIL"; exit 1; fi\n' if name == 'curl' else '') + 'exit 0\n')
        script.chmod(0o755)
    monkeypatch.setenv('PATH', str(commands) + ':' + os.environ['PATH'])
    monkeypatch.setenv('INSTALL_TEST_LOG', str(log))
    monkeypatch.setenv('INSTALL_TEST_FAIL', str(tmp_path / 'fail'))
    return module, target, stage, log


def test_install_manual_preserves_fence_and_backup(installer):
    module, target, stage, log = installer
    assert module.install(stage, SHA) == {'manual': ['node/cli/Dockerfile']}
    assert (target / 'node/cli/Dockerfile').read_text() == 'old fence'
    assert (target / 'REVISION').read_text() == SHA + '\n'
    assert (target / 'code').read_text() == 'new code'
    assert (target.with_name('factory.previous') / 'code').read_text() == 'old code'
    assert not (target.with_name('factory.previous') / '.venv').exists()
    assert (module.BIN / 'launcher').read_text() == 'new bin'
    commands = log.read_text()
    assert 'uv sync --project' in commands and '--frozen --no-dev' in commands
    assert 'npm ci && npm run build' in commands
    assert 'factory-cplane migrate' in commands
    assert 'groupadd --force --system factory-intake' in commands
    assert 'useradd --system --gid factory-intake --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin factory-intake' in commands
    assert 'usermod --append --groups factory-intake homelab-bot' in commands
    assert commands.index('systemctl restart factory-ui factory-sessions') < commands.index('systemctl restart factory-intake.service')
    assert 'systemctl daemon-reload' in commands


@pytest.mark.parametrize('old,new', [('old fence', 'new fence'), ('old fence', None),
                                     (None, 'new fence'), ('old fence', 'old fence')])
@pytest.mark.parametrize('fail_check', [False, True])
def test_install_leaves_fence_launcher_alone(installer, old, new, fail_check):
    module, target, stage, _ = installer
    launcher = 'node/bin/factory-cli'
    for root, content in ((target, old), (stage, new)):
        if content is not None:
            (root / launcher).write_text(content)
    host = module.BIN / 'factory-cli'
    host.write_text('installed fence')
    host.chmod(0o751)
    before = host.stat()
    if fail_check:
        Path(os.environ['INSTALL_TEST_FAIL']).touch()
        with pytest.raises(subprocess.CalledProcessError):
            module.install(stage, SHA)
    else:
        result = module.install(stage, SHA)
        assert (launcher in result['manual']) == (old != new)
        assert (module.BIN / 'launcher').read_text() == 'new bin'
    if old is None:
        assert not (target / launcher).exists()
    else:
        assert (target / launcher).read_text() == old
    assert host.read_text() == 'installed fence'
    after = host.stat()
    assert (after.st_ino, after.st_mode, after.st_mtime_ns, after.st_ctime_ns) == (
        before.st_ino, before.st_mode, before.st_mtime_ns, before.st_ctime_ns)


def test_failed_check_rolls_back_code_and_managed_files(installer):
    module, target, stage, log = installer
    Path(os.environ['INSTALL_TEST_FAIL']).touch()
    with pytest.raises(subprocess.CalledProcessError):
        module.install(stage, SHA)
    assert (target / 'code').read_text() == 'old code'
    assert (target / '.venv/python').exists()
    assert (module.BIN / 'launcher').read_text() == 'old bin'
    commands = log.read_text()
    assert commands.count('uv sync ') == 2
    assert commands.count('systemctl restart factory-ui factory-sessions') == 2
    assert commands.count('factory-cplane migrate') == 1


def test_postgres_request_route_and_transaction(pg_store, slice_data):
    with pg_store.locked():
        pg_store.save({'version': 1, 'slices': [node_step(slice_data)]})
    client = create_app(pg_store).test_client()
    url = '/api/slices/' + slice_data['id'] + '/install'
    assert client.post(url, headers={'X-Factory-UI': '1'}).status_code == 202
    assert client.post(url, headers={'X-Factory-UI': '1'}).status_code == 400
    with pg_store.locked():
        data = pg_store.load()
        assert len(list(installation.pending(data))) == 1
        assert data['slices'][0]['log'][0]['actor'] == 'owner'
        assert len(pg_store.notices()) == 1


def test_pass_only_launches_after_explicit_request(tmp_path, slice_data, make_state, monkeypatch):
    from test_runner import FakeProcesses, FakeGitHub, NOW
    monkeypatch.setenv('CPLANE_FENCE', '1')
    item = node_step(slice_data)
    item.update(state='issued', session={'tool': 'codex', 'id': 'session-1', 'folder': '/unused'})
    item['log'].append({'at': NOW.isoformat(), 'actor': 'runner', 'event': 'merged: ' + SHA})
    path = make_state([item])
    runner = Runner(path, processes=FakeProcesses(), github=FakeGitHub(), git=Mock(), clock=lambda: NOW)
    job_dir = runner.runs / 'turn-1'
    job_dir.mkdir(parents=True)
    (job_dir / 'job.json').write_text(json.dumps({'id': item['id'], 'phase': 'node-step', 'sha': SHA,
        'started_ns': 1, 'run': str(job_dir), 'fence': True, 'tool': 'codex', 'request': {'node_steps': item['attention']['body']}}))
    fake_bin = tmp_path / 'fake-systemd'
    fake_bin.mkdir()
    launches = tmp_path / 'launches'
    for name, script in [('systemctl', '#!/bin/sh\nif [ -f "$INSTALL_LAUNCHES" ]; then echo LoadState=loaded; echo ActiveState=activating; else echo LoadState=not-found; fi\n'),
                         ('systemd-run', '#!/bin/sh\nprintf "%s\\n" "$@" >> "$INSTALL_LAUNCHES"\n')]:
        executable = fake_bin / name
        executable.write_text(script)
        executable.chmod(0o755)
    monkeypatch.setenv('PATH', str(fake_bin) + ':' + os.environ['PATH'])
    monkeypatch.setenv('INSTALL_LAUNCHES', str(launches))
    runner.run()
    assert not launches.exists()
    assert main(['--state', str(path), '--actor', 'chat:21', 'install', item['id']]) == 0
    runner.run()
    runner.run()
    assert launches.read_text().count('/usr/local/bin/factory-install') == 1
    assert 'touch' not in launches.read_text()
    assert not runner.processes.started
    request = next(installation.pending(state.load(path)))[1]
    (runner.runs / 'installs' / (request + '.json')).write_text(json.dumps({'ok': False, 'stderr': 'migration missing'}))
    runner.run()
    runner.run()
    failed_item = state.load(path)['slices'][0]
    assert installation.install_failure(failed_item['attention'])
    assert failed_item['attention']['kind'] == 'node-step'
    assert failed_item['attention']['answer'] is None
    recorded = json.loads((job_dir / 'job.json').read_text())
    assert recorded['phase'] == 'node-step' and recorded['sha'] == SHA
    assert not runner.processes.started
    assert main(['--state', str(path), 'install', item['id']]) == 0
    request = next(installation.pending(state.load(path)))[1]
    (runner.runs / 'installs' / (request + '.json')).write_text(json.dumps({'ok': True, 'commit': SHA, 'manual': []}))
    runner.launch = Mock()
    runner.run()
    runner.launch.assert_called_once()
    assert runner.launch.call_args.args[1] == 'Installed ' + SHA + '. Node steps are done. End with kind handover.'
    assert not list(installation.pending(state.load(path)))


def test_root_lock_refuses_second_process_without_overwriting_result(tmp_path, monkeypatch, capsys):
    import fcntl
    from cplane import fence
    monkeypatch.setattr(install_host, 'INSTALL_ROOT', tmp_path)
    monkeypatch.setattr(fence, 'trusted_directory', lambda p: p)
    monkeypatch.setattr(install_host.os, 'geteuid', lambda: 0)
    monkeypatch.setattr('sys.argv', ['factory-install', 'example/one', '--request', 'b' * 32])
    with (tmp_path / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert install_host.main() == 1
    assert 'already running' in capsys.readouterr().out
    assert not list(tmp_path.glob('*.json'))


def test_root_only_entry_point(monkeypatch):
    monkeypatch.setattr(install_host.os, 'geteuid', lambda: 21000)
    monkeypatch.setattr('sys.argv', ['factory-install', 'example/one'])
    with pytest.raises(SystemExit) as error:
        install_host.main()
    assert error.value.code == 2


def test_lost_unit_after_durable_intent_never_replayed(tmp_path, slice_data, monkeypatch):
    runner, item, request = prepared_runner(tmp_path, slice_data)
    directory = runner.runs / 'installs'
    directory.mkdir(parents=True)
    (directory / (request + '.started')).write_text('{}')
    command = Mock(return_value=SimpleNamespace(stdout='LoadState=not-found', returncode=0))
    monkeypatch.setattr(installation.subprocess, 'run', command)
    installation.process(runner)
    assert command.call_count == 1
    assert 'disappeared' in item['attention']['body']
    assert not list(installation.pending(runner.data))


def test_launch_failure_diagnostics_never_enter_state(tmp_path, slice_data, monkeypatch):
    runner, item, request = prepared_runner(tmp_path, slice_data)
    command = Mock(side_effect=[SimpleNamespace(stdout='LoadState=not-found', returncode=0),
                               SimpleNamespace(returncode=1, stderr='synthetic-sensitive-diagnostic')])
    monkeypatch.setattr(installation.subprocess, 'run', command)
    installation.process(runner)
    assert 'could not start' in item['attention']['body']
    assert 'sensitive' not in json.dumps(runner.data)
    assert (runner.runs / 'installs' / (request + '.started')).exists()


def test_direct_command_starts_separate_unit(tmp_path, make_state, slice_data, monkeypatch):
    from cplane import fence
    host_setup(tmp_path, make_state, slice_data, monkeypatch)
    monkeypatch.setattr(fence, 'trusted_directory', lambda p: p)
    monkeypatch.setattr(install_host.os, 'geteuid', lambda: 0)
    monkeypatch.setattr('sys.argv', ['factory-install', slice_data['id']])
    start = Mock(return_value=True)
    monkeypatch.setattr(installation, 'start_unit', start)
    monkeypatch.setattr(install_host, 'install', Mock(side_effect=AssertionError('must run in separate unit')))
    assert install_host.main() == 0
    start.assert_called_once()
    assert start.call_args.args[0] == slice_data['id']
    assert len(list(installation.pending(state.load(Path(os.environ['CPLANE_STATE']))))) == 1


def test_all_manual_paths_and_removed_managed_files(installer):
    module, target, stage, _ = installer
    for name in ('node/proxy/policy', 'node/compose.yaml', 'node/check-fence.py'):
        (target / name).parent.mkdir(exist_ok=True)
        (stage / name).parent.mkdir(exist_ok=True)
        (target / name).write_text('old fence')
        (stage / name).write_text('new fence')
    (target / 'node/systemd/removed.service').write_text('old service')
    (module.SYSTEMD / 'removed.service').write_text('old service')
    answer = module.install(stage, SHA)
    assert set(answer['manual']) == {'node/cli/Dockerfile', 'node/proxy/policy', 'node/compose.yaml', 'node/check-fence.py'}
    for name in answer['manual']:
        assert (target / name).read_text() == 'old fence'
    assert not (module.SYSTEMD / 'removed.service').exists()


def test_running_unit_keeps_request_pending_if_attention_changes(tmp_path, slice_data, monkeypatch):
    runner, item, _ = prepared_runner(tmp_path, slice_data)
    item['attention'] = None
    monkeypatch.setattr(installation.subprocess, 'run', Mock(return_value=SimpleNamespace(
        stdout='LoadState=loaded\nActiveState=activating', returncode=0)))
    installation.process(runner)
    assert len(list(installation.pending(runner.data))) == 1
    other = node_step(copy.deepcopy(slice_data))
    other['id'] = 'other/one'
    runner.data['slices'].append(other)
    with pytest.raises(state.StateError, match='already'):
        installation.request_change('owner')(other, runner.data, 'now')


def test_review_status_needs_latest_install_evidence(slice_data):
    item = slice_data
    at = '2026-11-08T00:00:00Z'
    def log(event):
        item['log'].append(dict(at=at, actor='runner', event=event))
    assert installation.review_status(item)['status'] == 'not-required'
    log('node-step: Install')
    assert installation.review_status(item)['status'] == 'unconfirmed'
    log('Installed ' + SHA)
    assert installation.review_status(item)['status'] == 'finished'
    log('node-step: Install a later merge')
    assert installation.review_status(item)['status'] == 'unconfirmed'


def test_runner_timer_cadence_and_oneshot_unit():
    root = Path(__file__).resolve().parents[1]
    timer = (root / 'node/systemd/factory-runner.timer').read_text()
    service = (root / 'node/systemd/factory-runner.service').read_text()
    assert 'OnBootSec=60s\n' in timer
    assert 'Description=Run the Factory scheduler every minute\n' in timer
    assert 'OnUnitActiveSec=60s\n' in timer
    assert 'Unit=factory-runner.service\n' in timer
    assert 'Type=oneshot\n' in service


def script_archive(monkeypatch, script):
    # The production root interpreter path need not exist in the test container.
    real_run = subprocess.run

    def run(args, **kwargs):
        if args[0] == '/usr/bin/python3':
            args = [sys.executable, *args[1:]]
        return real_run(args, **kwargs)

    monkeypatch.setattr(install_host.subprocess, 'run', run)
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w:gz') as tar:
        content = script.encode()
        info = tarfile.TarInfo('root/node/install')
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    paths = []

    def github(repo, path, output=None):
        paths.append(path)
        if output:
            output.write(archive.getvalue())
        else:
            return {'status': 'ahead', 'merge_base_commit': {'sha': SHA}}
    monkeypatch.setattr(install_host, 'github', github)
    return paths


def test_failed_script_persists_bounded_output_and_retries_same_commit(
        tmp_path, make_state, slice_data, monkeypatch, capsys):
    from cplane import fence
    path = host_setup(tmp_path, make_state, slice_data, monkeypatch)
    marker = tmp_path / 'first-attempt'
    paths = script_archive(monkeypatch, f'''
import json, sys
from pathlib import Path
marker = Path({str(marker)!r})
if not marker.exists():
    marker.touch()
    print('é' * 12000 + ' stdout cause')
    print('界' * 12000 + ' migration missing', file=sys.stderr)
    sys.exit(7)
print(json.dumps({{'manual': []}}))
''')
    monkeypatch.setattr(install_host.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(fence, 'trusted_directory', lambda p: p)
    assert main(['--state', str(path), 'install', slice_data['id']]) == 0
    request = next(installation.pending(state.load(path)))[1]
    monkeypatch.setattr('sys.argv', ['factory-install', slice_data['id'], '--request', request])
    assert install_host.main() == 1
    record = json.loads((installation.runs_path(path) / 'installs' / (request + '.json')).read_text())
    assert record['returncode'] == 7
    assert record['commit'] == SHA
    assert record['repository'] == slice_data['repo']
    for stream in ('stderr', 'stdout'):
        assert 8100 < len(record[stream].encode()) <= 8192
    assert record['stderr'].endswith('migration missing\n')
    assert record['stdout'].endswith('stdout cause\n')
    runner = Runner(path)
    runner.data, runner.at = state.load(path), '2026-11-08T00:00:00+00:00'
    runner.jobs = {slice_data['id']: {'phase': 'node-step', 'sha': SHA}}
    installation.process(runner)
    item = runner.data['slices'][0]
    assert item['attention']['kind'] == 'node-step'
    assert item['attention']['answer'] is None
    assert 'migration missing' in item['attention']['body']
    state.save(path, runner.data)
    from factory_ui.home import home_data
    store = SimpleNamespace(load=lambda: runner.data, notices=lambda: [], chats=lambda **kw: [],
                            limit_show=lambda: {'waiting_limit': 10})
    card = home_data(store, {'features': [], 'projects': []}, lambda x: x, None)['attention'][0]
    assert card['kind'] == 'failure'
    assert card['retry_install']
    assert 'migration missing' in card['text']
    assert len(card['text'].encode()) < 1200
    capsys.readouterr()
    assert main(['--state', str(path), 'show', slice_data['id']]) == 0
    shown = capsys.readouterr().out
    assert json.dumps(record) in shown
    with pytest.raises(state.StateError, match='belong to the owner'):
        installation.request_change('chat:22')(item, runner.data, runner.at)
    assert main(['--state', str(path), 'install', slice_data['id']]) == 0
    request2 = next(installation.pending(state.load(path)))[1]
    assert request2 != request
    monkeypatch.setattr('sys.argv', ['factory-install', slice_data['id'], '--request', request2])
    assert install_host.main() == 0
    assert json.loads((runner.runs / 'installs' / (request2 + '.json')).read_text())['commit'] == SHA
    assert paths == [f'compare/{SHA}...main', f'tarball/{SHA}'] * 2
    runner.data = state.load(path)
    installation.process(runner)
    assert runner.data['slices'][0]['attention']['answer'].startswith('Installed ' + SHA)


@pytest.mark.parametrize('changed', ['sha', 'repository'])
def test_retry_refuses_changed_merge_metadata(tmp_path, make_state, slice_data, monkeypatch, changed):
    path = host_setup(tmp_path, make_state, slice_data, monkeypatch)
    script_archive(monkeypatch, 'import sys; sys.exit(1)')
    failure = install_host.install(slice_data['id'])
    directory = installation.runs_path(path) / 'installs'
    directory.mkdir()
    (directory / ('b' * 32 + '.json')).write_text(json.dumps(failure))
    job_path = installation.runs_path(path) / 'job/job.json'
    job = json.loads(job_path.read_text())
    job[changed] = 'b' * 40 if changed == 'sha' else 'other/repository'
    if changed == 'repository':
        data = state.load(path)
        data['slices'][0]['repo'] = job[changed]
        state.save(path, data)
        monkeypatch.setenv('CPLANE_INSTALL_REPOS', job[changed])
    job_path.write_text(json.dumps(job))
    github = Mock()
    monkeypatch.setattr(install_host, 'github', github)
    with pytest.raises(state.StateError, match='same recorded merged commit'):
        install_host.install(slice_data['id'])
    github.assert_not_called()


def test_node_installer_keeps_command_stderr(installer, monkeypatch):
    module, *_ = installer
    command = Mock()
    monkeypatch.setattr(module.subprocess, 'run', command)
    module.run('factory-cplane', 'migrate')
    assert 'stderr' not in command.call_args.kwargs


@pytest.mark.parametrize('error,detail', [
    (FileNotFoundError(2, 'synthetic-sensitive-value', 'groupadd'),
     'FileNotFoundError: groupadd'),
    (subprocess.CalledProcessError(7, ['/usr/local/bin/uv', 'synthetic-sensitive-value'],
                                 output='synthetic-sensitive-value', stderr='synthetic-sensitive-value'),
     'CalledProcessError: uv exited with return code 7'),
    (subprocess.CalledProcessError(9, 'curl synthetic-sensitive-value'),
     'CalledProcessError: curl exited with return code 9'),
    (ValueError('invalid installation'), 'ValueError: invalid installation'),
    (RuntimeError('x' * 300), ('RuntimeError: ' + 'x' * 300)[:200]),
    (ValueError('first line\nsecond line'), 'ValueError: first line second line'),
])
def test_node_installer_failure_output(monkeypatch, capsys, error, detail):
    source = compile(Path('node/install').read_text(), 'node/install', 'exec')
    monkeypatch.setenv('INSTALL_TEST_SECRET', 'synthetic-sensitive-value')
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    monkeypatch.setattr(sys, 'argv', ['node/install', '/synthetic-stage', SHA])
    # Fail before install is entered; exercise the actual __main__ exception handler.
    monkeypatch.setattr(Path, 'resolve', Mock(side_effect=error))
    with pytest.raises(SystemExit) as exited:
        exec(source, {'__name__': '__main__'})
    assert exited.value.code == 1
    output = capsys.readouterr()
    assert output.out == ''
    assert output.err.splitlines() == [
        'Install failed; rollback attempted; migrations are not undone', detail]
    assert 'synthetic-sensitive-value' not in output.err
    assert len(output.err.splitlines()[1]) <= 200


@pytest.mark.parametrize('postgres', [False, True])
def test_failed_node_step_can_be_answered_by_hand(make_state, slice_data, request, postgres):
    path = make_state([node_step(slice_data)])
    if postgres:
        store = request.getfixturevalue('pg_store')
        store.import_file(path)
    runner = Runner(path)
    runner.data = state.load(path)
    runner.at = '2026-11-08T00:00:00+00:00'
    item = runner.data['slices'][0]
    installation.failed(runner, item, 'Install failed; migration missing')
    state.save(path, runner.data)
    assert main(['--state', str(path), 'answer', item['id'], 'Installed by hand']) == 0
    assert state.load(path)['slices'][0]['attention']['answer'] == 'Installed by hand'
    assert main(['--state', str(path), 'install', item['id']]) == 1


def test_intake_account_creation_and_idempotence(installer, monkeypatch):
    module, _, _, _ = installer
    command = Mock()
    monkeypatch.setattr(module, 'run', command)
    monkeypatch.setattr(module.pwd, 'getpwnam', Mock(side_effect=KeyError))
    module.intake_account()
    command.assert_called_once_with('useradd', '--system', '--gid', 'factory-intake',
                                    '--no-create-home', '--home-dir', '/nonexistent',
                                    '--shell', '/usr/sbin/nologin', 'factory-intake')
    command.reset_mock()
    monkeypatch.setattr(module.pwd, 'getpwnam', lambda name: SimpleNamespace(
        pw_uid=23001, pw_gid=23002, pw_dir='/nonexistent', pw_shell='/usr/sbin/nologin'))
    monkeypatch.setattr(module.grp, 'getgrnam', lambda name: SimpleNamespace(gr_gid=23002))
    module.intake_account()
    command.assert_not_called()


@pytest.mark.parametrize('changes', [dict(pw_uid=0), dict(pw_gid=0), dict(pw_dir='/root'),
                                     dict(pw_shell='/bin/sh')])
def test_intake_account_refuses_conflicting_identity(installer, monkeypatch, changes):
    module, _, _, _ = installer
    account = dict(pw_uid=23001, pw_gid=23002, pw_dir='/nonexistent', pw_shell='/usr/sbin/nologin')
    account.update(changes)
    monkeypatch.setattr(module.pwd, 'getpwnam', lambda name: SimpleNamespace(**account))
    monkeypatch.setattr(module.grp, 'getgrnam', lambda name: SimpleNamespace(gr_gid=23002))
    command = Mock()
    monkeypatch.setattr(module, 'run', command)
    with pytest.raises(ValueError, match='dedicated unprivileged'):
        module.intake_account()
    command.assert_not_called()


def test_intake_account_refuses_privileged_group_before_creating_user(installer, monkeypatch):
    module, _, _, _ = installer
    monkeypatch.setattr(module.grp, 'getgrnam', lambda name: SimpleNamespace(gr_gid=0))
    lookup = Mock(side_effect=KeyError)
    monkeypatch.setattr(module.pwd, 'getpwnam', lookup)
    command = Mock()
    monkeypatch.setattr(module, 'run', command)
    with pytest.raises(ValueError, match='dedicated unprivileged service group'):
        module.intake_account()
    lookup.assert_not_called()
    command.assert_not_called()


def test_install_github_uses_same_scoped_app_auth(monkeypatch):
    from cplane import fence, github_app
    monkeypatch.setenv('CPLANE_GITHUB_AUTH', 'app')
    mint = Mock(return_value='synthetic-app-token')
    monkeypatch.setattr(github_app, 'installation_token', mint)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=b'{"ok": true}'))
    monkeypatch.setattr(install_host.subprocess, 'run', run)
    assert install_host.github('example/repo', 'compare/sha...main') == {'ok': True}
    mint.assert_called_once_with(['example/repo'])
    assert run.call_args.kwargs['env'] == {**fence.host_environment(), 'GH_TOKEN': 'synthetic-app-token'}
    assert 'synthetic-app-token' not in str(run.call_args.args)
