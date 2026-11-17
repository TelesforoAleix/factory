"""Synthetic launcher protocol and Factory boundary checks; no containers."""
import array
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
from threading import Thread
from unittest.mock import Mock

import pytest

from cplane import eval_execution as runner
from cplane import executors, fence, launcher, models, planning, primer, review, sessions


@pytest.fixture
def server(tmp_path, monkeypatch):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    path = tmp_path / 'launcher.sock'
    listener.bind(str(path))
    listener.listen()
    listener.settimeout(0.1)
    monkeypatch.setenv('CPLANE_LAUNCHER_SOCKET', str(path))
    requests, failures = [], []
    reply = {'ok': True, 'exit_code': 0}
    output = [b'O', b'E']
    running = True

    def serve():
        while running:
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            with conn:
                descriptors = array.array('i')
                try:
                    data, ancillary, flags, _ = conn.recvmsg(65536, socket.CMSG_SPACE(8))
                    for level, kind, rights in ancillary:
                        assert (level, kind) == (socket.SOL_SOCKET, socket.SCM_RIGHTS)
                        descriptors.frombytes(rights)
                    while not data.endswith(b'\n'):
                        data += conn.recv(65536)
                    payload = json.loads(data)
                    assert len(descriptors) == (2 if payload['op'] == 'run' else 0)
                    requests.append(payload)
                    for fd, content in zip(descriptors, output):
                        os.write(fd, content)
                    conn.sendall(json.dumps(reply).encode() + b'\n')
                except BaseException as error:
                    failures.append(error)
                finally:
                    for fd in descriptors:
                        os.close(fd)
    thread = Thread(target=serve, daemon=True)
    thread.start()
    yield requests, reply, output
    running = False
    thread.join(3)
    listener.close()
    assert not thread.is_alive()
    assert not failures


def cli(*args):
    return subprocess.run([sys.executable, '-m', 'cplane.launcher', *map(str, args)],
                          capture_output=True, text=True)


@pytest.mark.parametrize('turn', [None, 7])
def test_client_descriptors_profiles_and_exit(server, turn):
    requests, reply, _ = server
    reply['exit_code'] = 23
    options = [] if turn is None else ['--session-turn', str(turn)]
    result = cli('run', '--repo', '/srv/factory/work/session-1',
                 '--run', '/srv/factory/runs/feature/slice/io', '--tool', 'codex', *options,
                 '--read-only-path', '/srv/factory/work/session-1/repos/factory-planning-export',
                 '--', 'codex', 'exec', '--', 'literal $(false)')
    assert (result.returncode, result.stdout, result.stderr) == (23, 'O', 'E')
    payload, = requests
    assert payload['profile'] == ('cli-run' if turn is None else 'chat')
    assert payload['folders'] == dict(work='session-1', run='feature/slice/io')
    assert payload['exports'] == ['factory-planning-export']
    assert payload['command'] == ['codex', 'exec', '--', 'literal $(false)']
    assert payload['run_id'] == 'turn-7' if turn else re.fullmatch('[0-9a-f]{32}', payload['run_id'])
    if turn:
        assert payload['turn'] == turn
    else:
        assert 'turn' not in payload


def test_bundle_and_cleanup(server):
    requests, _, _ = server
    assert cli('bundle', '--repo', '/srv/factory/work/session-1/planning',
               '--run', '/srv/factory/runs/session-turn-1/io', '--branch', 'session-1').returncode == 0
    assert requests[0]['profile'] == 'bundle'
    assert requests[0]['folders']['work'] == 'session-1/planning'
    assert requests[0]['branch'] == 'session-1'
    assert cli('session-cleanup', '12').returncode == 0
    assert requests[-1] == dict(op='stop', run_id='turn-12')
    assert cli('stop', 'usage-abc').returncode == 0
    assert requests[-1] == dict(op='stop', run_id='usage-abc')


@pytest.mark.parametrize('reason', ['run_exists', 'unknown_profile', 'invalid_folder', 'unavailable'])
def test_refusal(server, reason):
    server[1].update(ok=False, error=reason)
    result = cli('stop', 'usage-abc')
    assert (result.returncode, result.stderr) == (125, f'launcher: {reason}\n')


@pytest.mark.parametrize('role,path', [
    ('work', '/tmp/outside'), ('work', '/srv/factory/work'),
    ('work', '/srv/factory/work/a/b/c'), ('run', '/srv/factory/runs/a/b/c/d'),
    ('run', '/srv/factory/runs/../work/a'), ('work', 'relative'),
])
def test_invalid_paths_send_nothing(server, role, path):
    args = dict(repo='/srv/factory/work/a', run='/srv/factory/runs/a')
    args['repo' if role == 'work' else 'run'] = path
    result = cli('bundle', '--repo', args['repo'], '--run', args['run'], '--branch', 'slice')
    assert result.returncode == 125
    assert result.stderr == 'launcher: invalid_folder\n'
    assert server[0] == []


@pytest.mark.parametrize('options', [[], ['--run-id', 'models-abc-output']])
def test_fresh_and_explicit_ids(server, options):
    for _ in range(2):
        assert cli('run', '--repo', '/srv/factory/work/a', '--run', '/srv/factory/runs/a',
                   '--tool', 'claude', *options, '--', 'claude').returncode == 0
    ids = [p['run_id'] for p in server[0]]
    assert (ids[0] == ids[1]) == bool(options)


@pytest.fixture
def boundary(server, tmp_path, monkeypatch, service_identity):
    """Run call-site argv through translation and the real socket transport."""
    work, runs = tmp_path / 'work', tmp_path / 'runs'
    work.mkdir()
    runs.mkdir()
    monkeypatch.setenv('CPLANE_FENCE_COMMAND', 'socket')
    monkeypatch.setenv('CPLANE_FENCE', '1')
    monkeypatch.setenv('CPLANE_RUNS', str(runs))
    monkeypatch.setattr(fence, 'WORK_ROOT', work)
    monkeypatch.setattr(launcher, 'WORK_ROOT', work)
    monkeypatch.setattr(launcher, 'RUN_ROOT', runs)
    monkeypatch.setattr(sessions, 'WORK_ROOT', work)
    monkeypatch.setattr(sessions, 'RUNS', runs)
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())

    def run(argv, **kwargs):
        assert argv[:3] == [sys.executable, '-m', 'cplane.launcher']
        payload = launcher.translate(argv[3:])
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            reply = launcher.request(payload, (out.fileno(), err.fileno()) if payload['op'] == 'run' else ())
            out.seek(0)
            err.seek(0)
            stdout, stderr = out.read(), err.read()
        if kwargs.get('text'):
            stdout, stderr = stdout.decode(), stderr.decode()
        return subprocess.CompletedProcess(argv, reply.get('exit_code', 0), stdout, stderr)
    original_manage = launcher.manage

    def manage(operation, role, path):
        if operation == 'own':
            expected = 0o750 if Path(path).name == 'io' else 0o700
            assert Path(path).stat().st_mode & 0o7777 == expected
        return original_manage(operation, role, path)

    monkeypatch.setattr(launcher, 'manage', manage)
    monkeypatch.setattr(subprocess, 'run', run)
    return work, runs, server[0], server[1], server[2]


@pytest.mark.parametrize('tool', ['codex', 'claude'])
def test_executor_session_and_cleanup_call_sites(boundary, monkeypatch, tool):
    work, runs, requests, _, _ = boundary
    folder = runs / 'slice'
    folder.mkdir()
    monkeypatch.setattr(subprocess, 'Popen', Mock(return_value=Mock(pid=42)))
    job = dict(tool=tool, run=str(folder), repo=str(work / 'copy'), model='synthetic', prompt='hello')
    executors.Processes().start(job)
    assert requests.pop() == dict(op='own', role='run', folder_id='slice/io')
    assert subprocess.Popen.call_args.kwargs['env']['CPLANE_FENCE_COMMAND'] == 'socket'
    assert 'CPLANE_LAUNCHER_SOCKET' in subprocess.Popen.call_args.kwargs['env']
    executors.supervise(folder)
    assert requests[-1]['profile'] == 'cli-run'
    assert requests[-1]['folders'] == dict(work='copy', run='slice/io')
    turn = dict(id=7, text='hello', session=dict(tool=tool, model='synthetic', effort='medium', cli_session_id=None))
    subprocess.run(sessions.turn_command(turn, work / 'session-1',
                   [work / 'session-1/repos/repo'], runs / 'session-turn-7'))
    assert requests[-1]['profile'] == 'chat'
    assert requests[-1]['turn'] == 7
    assert requests[-1]['exports'] == ['repo']
    sessions.cleanup_interrupted_turn(turn)
    assert requests[-1] == dict(op='stop', run_id='turn-7')


def test_catalog_runs_and_recovery(boundary):
    work, runs, requests, _, output = boundary
    output[0] = b'{"modelUsage":{"synthetic":{}}}'
    assert len(models.refresh_catalog('claude')) == 4
    launched = [p for p in requests if p['op'] == 'run']
    assert len(launched) == 4
    assert len({p['run_id'] for p in launched}) == 4
    assert all(p['profile'] == 'cli-run' and 'turn' not in p for p in launched)
    assert [p['run_id'] for p in requests if p['op'] == 'stop'] == [p['run_id'] for p in launched]
    assert all(p['run_id'] == p['folders']['work'] + '-' + p['folders']['run'].split('/')[-1] for p in launched)
    assert requests[-1]['op'] == 'remove'
    token = 'a' * 32
    root = runs / ('models-' + token)
    (root / 'output-1').mkdir(parents=True)
    (root / 'output-2').mkdir()
    (work / root.name).mkdir()
    models.recover_catalog_runs()
    assert [p['run_id'] for p in requests if p['op'] == 'stop'][-2:] == [
        f'models-{token}-output-1', f'models-{token}-output-2']
    assert requests[-1] == dict(op='remove', role='work', folder_id='models-' + token)


def test_usage_probe(boundary):
    _, runs, requests, _, output = boundary
    output[0] = b''
    runner.probe_codex_usage(runs)
    own, run, stop, remove = requests
    assert run['profile'] == 'cli-run' and 'turn' not in run
    assert run['run_id'] == run['folders']['work']
    assert run['run_id'].startswith('usage-')
    assert stop == dict(op='stop', run_id=run['run_id'])
    assert own == dict(op='own', role='work', folder_id=run['folders']['work'])
    assert remove == {**own, 'op': 'remove'}


@pytest.mark.parametrize('tool', ['codex', 'claude'])
def test_primer_ownership_run_and_removal(boundary, tool):
    _, _, requests, _, _ = boundary
    assert primer.request(tool, []) == 'ok'
    assert [p['op'] for p in requests] == ['own', 'own', 'run', 'remove', 'remove']
    assert requests[2]['profile'] == 'cli-run'
    assert requests[2]['tool'] == tool
    assert requests[3] == {**requests[1], 'op': 'remove'}
    assert requests[4] == {**requests[0], 'op': 'remove'}


def test_bundle_call_sites(boundary):
    work, runs, requests, reply, _ = boundary
    reply['exit_code'] = 1  # Stop before any host Git delivery.
    copy = work / 'session-1/planning'
    run = runs / 'session-turn-1'
    run.mkdir()
    adapter = object.__new__(planning.Planning)
    adapter.session, adapter.branch = dict(area='homelab'), 'session-1'
    with pytest.raises(fence.StateError, match='bundle export refused'):
        adapter.deliver(copy, run)
    assert requests[-1]['folders'] == dict(work='session-1/planning', run='session-turn-1/io')
    adapter = fence.Fence()
    adapter.clean = Mock()
    job = dict(branch='slice/one', default='main', repository='example/repo', run=str(run), repo=str(work / 'copy'))
    with pytest.raises(fence.StateError, match='bundle export failed'):
        adapter.publish(job, dict(branch=job['branch']))
    assert requests[-1]['profile'] == 'bundle'
    assert requests[-1]['folders'] == dict(work='copy', run='session-turn-1/io')


@pytest.mark.parametrize('reviewing', [False, True])
def test_copy_ownership(boundary, monkeypatch, reviewing):
    work, _, requests, _, _ = boundary
    adapter = fence.Fence()
    clean = work.parent / 'clean'
    clean.mkdir()
    adapter.clean = Mock(return_value=clean)
    def git(clean, *args, **kwargs):
        if args[0] == 'clone':
            Path(args[-1]).mkdir()
        stdout = 'ref: refs/heads/main\tHEAD\n' if args[0] == 'ls-remote' else 'a' * 40
        return subprocess.CompletedProcess([], 0, stdout)
    adapter.git = git
    previous = dict(repository='example/repo', branch='slice/one', base='a' * 40, default='main')
    if reviewing:
        review.prepare(adapter, previous, 'review')
    else:
        adapter.prepare('example/repo', 'slice/one', 'copy')
    assert requests == [dict(op='own', role='work', folder_id='review' if reviewing else 'copy')]


def test_workspace_planning_ownership_keeps_factory_session(boundary, monkeypatch):
    work, _, requests, _, _ = boundary
    monkeypatch.setattr(sessions.Planning, 'prepare', lambda self, path: path.mkdir(mode=0o700))
    monkeypatch.setattr(sessions.Planning, '__init__', lambda self, session: None)
    monkeypatch.setattr(sessions.skills, 'install', lambda *args: None)
    chown = Mock()
    monkeypatch.setattr(sessions.os, 'chown', chown)
    sessions.workspace(dict(id=1, area='homelab', cli_session_id=None, repositories=[]))
    assert requests == [dict(op='own', role='work', folder_id='session-1/planning')]
    chown.assert_called_once_with(work / 'session-1', -1, 21000)
    assert (work / 'session-1').stat().st_mode & 0o7777 == 0o1770


def test_session_delivery_io_ownership(boundary, monkeypatch):
    work, _, requests, _, output = boundary
    output[0] = b'{"session_id":"saved-id","result":"hello"}'
    monkeypatch.setattr(sessions, 'workspace', lambda session: (work / 'session-1', []))
    monkeypatch.setattr(planning.Planning, '__init__', lambda self, session: None)
    monkeypatch.setattr(planning.Planning, 'deliver', lambda *args: [])
    turn = dict(id=7, text='hello', session=dict(id=1, area='homelab', tool='claude',
                model='synthetic', effort='low', cli_session_id=None))
    store = Mock()
    sessions._execute_turn(turn, store, {})
    assert requests[-1] == dict(op='own', role='run', folder_id='session-turn-7/io')
    store.finish_session_turn.assert_called_once_with(turn, 'hello', 'saved-id')




@pytest.mark.parametrize('probe', ['catalog', 'usage'])
def test_probe_timeout_still_stops_before_removal(boundary, monkeypatch, probe):
    _, runs, requests, _, _ = boundary
    original = subprocess.run
    def timeout(argv, **kwargs):
        result = original(argv, **kwargs)
        if 'run' == argv[3]:
            raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
        return result
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        models.refresh_catalog('codex') if probe == 'catalog' else runner.probe_codex_usage(runs)
    assert [p['op'] for p in requests] == ['own', 'run', 'stop', 'remove']
    assert requests[2]['run_id'] == requests[1]['run_id']


def test_all_catalog_stops_attempted_after_refusal(boundary, monkeypatch):
    _, _, requests, reply, output = boundary
    output[0] = b'{"modelUsage":{"synthetic":{}}}'
    original = subprocess.run
    def refuse_stops(argv, **kwargs):
        if argv[3] == 'stop':
            reply.update(ok=False, error='unavailable')
            with pytest.raises(launcher.LauncherError):
                original(argv, **kwargs)
            raise subprocess.CalledProcessError(125, argv)
        return original(argv, **kwargs)
    monkeypatch.setattr(subprocess, 'run', refuse_stops)
    with pytest.raises(subprocess.CalledProcessError):
        models.refresh_catalog('claude')
    assert len([p for p in requests if p['op'] == 'stop']) == 4
    assert not any(p['op'] == 'remove' for p in requests)


def test_remove_refusal_never_falls_back_to_host_rmtree(boundary, monkeypatch):
    import shutil
    work, _, requests, reply, _ = boundary
    reply.update(ok=False, error='unavailable')
    delete = Mock(side_effect=AssertionError('host delete attempted'))
    monkeypatch.setattr(shutil, 'rmtree', delete)
    with pytest.raises(launcher.LauncherError, match='unavailable'):
        with primer.warmup_directory(work, 'work'):
            pass
    assert requests[-1]['op'] == 'remove'
    delete.assert_not_called()


def test_oversize_request_is_local(server):
    result = cli('run', '--repo', '/srv/factory/work/a', '--run', '/srv/factory/runs/a',
                 '--tool', 'codex', '--', 'x' * 65536)
    assert result.returncode == 125
    assert result.stderr == 'launcher: request_too_large\n'
    assert not server[0]


def test_unavailable_socket(tmp_path, monkeypatch):
    monkeypatch.setenv('CPLANE_LAUNCHER_SOCKET', str(tmp_path / 'missing.sock'))
    result = cli('stop', 'turn-1')
    assert (result.returncode, result.stderr) == (125, 'launcher: unavailable\n')


def test_run_does_not_send_empty_bytes_after_server_reply(server, monkeypatch):
    # The peer can reply and close immediately after sendmsg. A later empty
    # sendall can raise EPIPE even though the run was successfully accepted.
    real_socket = socket.socket
    class EarlyCloseSocket(real_socket):
        def sendall(self, data, *args):
            if not data:
                raise BrokenPipeError('peer already replied and closed')
            return super().sendall(data, *args)
    monkeypatch.setattr(launcher.socket, 'socket', EarlyCloseSocket)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        reply = launcher.request(dict(op='run', profile='usage', run_id='test'),
                                 (out.fileno(), err.fileno()))
    assert reply['ok']


@pytest.fixture(params=[0, 21011], ids=['root', 'service'])
def service_identity(request, monkeypatch):
    """Inject ownership metadata without changing the test process's real identity."""
    actual = os.geteuid()
    euid = request.param
    original = Path.lstat

    def lstat(path):
        info = original(path)
        if info.st_uid == actual and not (info.st_uid == 0 and info.st_mode & 0o1000):
            fields = list(info)
            fields[4] = euid
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(os, 'geteuid', lambda: euid)
    monkeypatch.setattr(Path, 'lstat', lstat)
    return euid


def test_shared_session_and_export_checks(boundary, service_identity, monkeypatch):
    work, _, requests, _, _ = boundary
    monkeypatch.setattr(sessions.skills, 'install', lambda *args: None)
    monkeypatch.setattr(sessions.skills, 'ensure_readable', lambda *args: None)
    monkeypatch.setattr(sessions, 'export_tree', lambda _, path, ref, **kwargs: path.mkdir())
    original = Path.lstat
    groups = {}

    def lstat(path):
        info = original(path)
        if path in groups:
            fields = list(info)
            fields[5] = groups[path]
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(Path, 'lstat', lstat)
    chown = Mock(side_effect=lambda path, uid, gid: groups.update({path: gid}))
    monkeypatch.setattr(sessions.os, 'chown', chown)
    session = dict(id=1, cli_session_id=None, repositories=[])
    folder, _ = sessions.workspace(session)
    info = folder.lstat()
    assert (info.st_uid, info.st_gid, info.st_mode & 0o7777) == (service_identity, 21000, 0o1770)
    chown.assert_called_once_with(folder, -1, 21000)
    assert not requests  # The session itself is never transferred to the agent.
    for path in (folder / 'repos', folder / 'repos/factory-planning-export'):
        info = path.lstat()
        assert info.st_uid == service_identity and info.st_mode & 0o7777 == 0o755
    session.update(cli_session_id='saved')
    assert sessions.workspace(session)[0] == folder
    (folder / 'repos/factory-planning-export').chmod(0o775)
    with pytest.raises(fence.StateError, match='Planning export replaced'):
        sessions.workspace(session)
    (folder / 'repos/factory-planning-export').chmod(0o755)
    (folder / 'repos').chmod(0o775)
    with pytest.raises(fence.StateError, match='Planning export replaced'):
        sessions.workspace(session)


def test_old_session_removed_before_recreation(boundary, service_identity, monkeypatch):
    import shutil
    work, _, requests, _, _ = boundary
    folder = work / 'session-1'
    folder.mkdir(mode=0o700)
    (folder / 'old').write_text('old agent workspace')
    original = Path.lstat
    removed = []

    def lstat(path):
        info = original(path)
        if path == folder:
            fields = list(info)
            fields[4] = service_identity if removed else 21000
            fields[5] = 21000
            return os.stat_result(fields)
        return info

    def remove(path, role):
        assert (path, role) == (folder, 'work')
        removed.append(path)
        shutil.rmtree(path)

    monkeypatch.setattr(Path, 'lstat', lstat)
    monkeypatch.setattr(fence, 'remove', remove)
    monkeypatch.setattr(sessions.os, 'chown', Mock())
    monkeypatch.setattr(sessions.skills, 'install', lambda *args: None)
    monkeypatch.setattr(sessions, 'export_tree', lambda _, path, ref, **kwargs: path.mkdir())
    session = dict(id=1, cli_session_id=None, workspace_ready=True, repositories=[])
    sessions.workspace(session)
    assert removed == [folder] and not (folder / 'old').exists()
    assert sessions.session_directory(folder.lstat())
    assert not requests


def test_trusted_service_ancestor_and_write_bits(tmp_path, service_identity):
    ancestor = tmp_path / 'service'
    path = ancestor / 'clean'
    path.mkdir(parents=True)
    assert fence.trusted_directory(path) == path
    ancestor.chmod(0o775)
    with pytest.raises(fence.StateError, match='not writable by others'):
        fence.trusted_directory(path)


@pytest.mark.parametrize('switch', [None, 'factory-cli', '/custom/fence'])
@pytest.mark.parametrize('operation', ['tree', 'session'])
def test_nonroot_direct_chown_fails(tmp_path, monkeypatch, switch, operation):
    monkeypatch.setattr(os, 'geteuid', lambda: 21011)
    if switch is None:
        monkeypatch.delenv('CPLANE_FENCE_COMMAND', raising=False)
    else:
        monkeypatch.setenv('CPLANE_FENCE_COMMAND', switch)
    chown = Mock(side_effect=AssertionError('direct chown attempted'))
    monkeypatch.setattr(os, 'chown', chown)
    if operation == 'tree':
        action = lambda: fence.own(tmp_path, 'work', recursive=True)
    else:
        monkeypatch.setattr(sessions, 'trusted_directory', lambda path: path)
        monkeypatch.setattr(sessions, 'WORK_ROOT', tmp_path)
        action = lambda: sessions.workspace(dict(id=1, cli_session_id=None, repositories=[]))
    with pytest.raises(fence.StateError, match='Non-root.*CPLANE_FENCE_COMMAND=socket'):
        action()
    chown.assert_not_called()


@pytest.mark.parametrize('reader', ['bundle', 'reply'])
@pytest.mark.parametrize('kind', ['link', 'hardlink', 'unreadable'])
def test_output_refuses_unsafe_files(tmp_path, monkeypatch, reader, kind):
    io = tmp_path / 'io'
    io.mkdir(mode=0o750)
    source = tmp_path / 'source'
    source.write_text('synthetic output')
    path = io / ('branch.bundle' if reader == 'bundle' else 'last.json')
    if kind == 'link':
        path.symlink_to(source)
    elif kind == 'hardlink':
        os.link(source, path)
    else:
        path.write_text('unreadable')
        original = os.open

        def denied(name, flags, *args, **kwargs):
            if name == path.name:
                raise PermissionError('agent made output unreadable')
            return original(name, flags, *args, **kwargs)

        monkeypatch.setattr(os, 'open', denied)
    with pytest.raises((OSError, ValueError, fence.StateError)):
        fence.snapshot_bundle(tmp_path) if reader == 'bundle' else executors.read_output(path)


@pytest.mark.parametrize('mode,gid', [(0o770, 21000), (0o1775, 21000), (0o1770, 0)])
def test_session_reuse_requires_exact_mode_and_group(boundary, service_identity, monkeypatch, mode, gid):
    work, _, _, _, _ = boundary
    folder = work / 'session-1'
    folder.mkdir(mode=mode)
    folder.chmod(mode)
    original = Path.lstat

    def lstat(path):
        info = original(path)
        if path == folder:
            fields = list(info)
            fields[5] = gid
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(fence.StateError, match='Workspace unavailable'):
        sessions.workspace(dict(id=1, cli_session_id='saved', repositories=[]))


def test_root_direct_handoff_remains_available(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    monkeypatch.delenv('CPLANE_FENCE_COMMAND', raising=False)
    chown = Mock()
    monkeypatch.setattr(os, 'chown', chown)
    fence.own(tmp_path, 'work')
    chown.assert_called_once_with(tmp_path, 21000, 21000)


def test_unknown_run_stop_is_success(server):
    _, reply, _ = server
    reply.clear()
    reply.update(ok=False, error='unknown_run')
    result = cli('session-cleanup', '12')
    assert result.returncode == 0
    assert result.stderr.count('already stopped') == 1


def test_other_stop_error_is_failure(server):
    _, reply, _ = server
    reply.clear()
    reply.update(ok=False, error='unavailable')
    result = cli('session-cleanup', '12')
    assert result.returncode == 125
    assert 'unavailable' in result.stderr
