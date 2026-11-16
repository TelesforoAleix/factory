"""Synthetic install requests and container wrapper checks; no installation is changed."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cplane import installation, state
from cplane.cli import main
from cplane.runner import Runner
from conftest import SyntheticStore
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
    monkeypatch.setenv('CPLANE_DEPLOYER_SOCKET', '/unused')
    start = Mock(return_value=True)
    monkeypatch.setattr(installation, 'start_deployer', start)
    runner.run()
    request = next(installation.pending(state.load(runner.path)))[1]
    start.assert_called_once_with('repo', SHA, request, runner.runs / 'installs')
    assert item(runner)['attention']['kind'] == 'node-step'
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
    proposed = state.load(path)['slices'][0]['log'][0]
    assert proposed['actor'] == 'chat:12'
    assert proposed['event'].startswith('install proposed: ')
    assert not list(installation.pending(state.load(path)))
    assert main(['--state', str(path), 'install', other['id']]) == 0
    assert main(['--state', str(path), 'install', slice_data['id']]) == 1
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
    client = create_app(SyntheticStore(path)).test_client()
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
    monkeypatch.setenv('CPLANE_DEPLOYER_SOCKET', '/unused')
    start = Mock(return_value=True)
    monkeypatch.setattr(installation, 'start_deployer', start)
    installation.process(runner)
    start.assert_called_once_with('repo', SHA, request, runner.runs / 'installs')
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


@pytest.mark.parametrize('owner_request', ['cli', 'tap'])
def test_pass_only_launches_after_explicit_request(tmp_path, slice_data, make_state, monkeypatch, owner_request):
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
    monkeypatch.setenv('CPLANE_DEPLOYER_SOCKET', '/unused')
    def start(application, sha, request, directory):
        (directory / (request + '.started')).write_text('{"deployer": true}')
        return True
    launches = Mock(side_effect=start)
    monkeypatch.setattr(installation, 'deployer_running', lambda marker: True)
    monkeypatch.setattr(installation, 'start_deployer', launches)
    runner.run()
    launches.assert_not_called()
    assert main(['--state', str(path), '--actor', 'chat:21', 'install', item['id']]) == 0
    runner.run()
    runner.run()
    launches.assert_not_called()
    assert not list(installation.pending(state.load(path)))
    if owner_request == 'cli':
        assert main(['--state', str(path), 'install', item['id']]) == 0
        assert main(['--state', str(path), 'install', item['id']]) == 1
    else:
        client = create_app(SyntheticStore(path)).test_client()
        url = '/api/slices/' + item['id'] + '/install'
        assert client.post(url, headers={'X-Factory-UI': '1'}).status_code == 202
        assert client.post(url, headers={'X-Factory-UI': '1'}).status_code == 400
    runner.run()
    runner.run()
    assert launches.call_count == 1
    assert launches.call_args.args[:2] == ('repo', SHA)
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


@pytest.mark.parametrize('event,actor', [
    ('install proposed: ', 'chat:12'),
    ('install proposed: ', 'owner'),
    (installation.REQUEST, 'chat:12'),
])
def test_process_ignores_proposals_and_legacy_chat_requests(tmp_path, slice_data, monkeypatch, event, actor):
    item = node_step(slice_data)
    item['log'].append(dict(at='2026-11-08T00:00:00Z', actor=actor, event=event + 'a' * 32))
    runner = Runner(tmp_path / 'slices.json', runs=tmp_path / 'runs')
    runner.data = dict(slices=[item])
    runner.jobs = {item['id']: dict(phase='node-step', sha=SHA)}
    command = Mock(side_effect=AssertionError('proposal must not query or start a unit'))
    monkeypatch.setattr(installation.subprocess, 'run', command)
    start = Mock()
    monkeypatch.setattr(installation, 'start_deployer', start)
    installation.process(runner)
    command.assert_not_called()
    start.assert_not_called()
    assert item['attention']['answer'] is None
    assert not runner.runs.exists()


@pytest.mark.parametrize('event', ['install proposed: ', installation.REQUEST])
def test_chat_proposal_is_once_per_attention_interval(slice_data, event):
    item = node_step(slice_data)
    item['log'].append(dict(at='2026-11-08T00:00:00Z', actor='chat:12', event=event + 'a' * 32))
    assert installation.chat_requested(item)
    with pytest.raises(state.StateError, match='already has a chat'):
        installation.request_change('chat:13')(item, dict(slices=[item]), '2026-11-08T00:01:00Z')
    item['attention']['since'] = '2026-11-08T00:02:00Z'
    assert not installation.chat_requested(item)
    installation.request_change('chat:13')(item, dict(slices=[item]), '2026-11-08T00:03:00Z')
    assert installation.chat_requested(item)


@pytest.mark.parametrize('marker', [None, '{}'])
def test_missing_deployer_socket_refuses_without_host_commands(tmp_path, slice_data, monkeypatch, marker):
    runner, item, request = prepared_runner(tmp_path, slice_data)
    monkeypatch.delenv('CPLANE_DEPLOYER_SOCKET', raising=False)
    if marker is not None:
        directory = runner.runs / 'installs'
        directory.mkdir(parents=True)
        (directory / (request + '.started')).write_text(marker)
    command = Mock(return_value=SimpleNamespace(stdout='LoadState=not-found', returncode=0))
    launch = Mock()
    monkeypatch.setattr(installation.subprocess, 'run', command)
    monkeypatch.setattr(installation, 'start_deployer', launch)
    installation.process(runner)
    assert 'CPLANE_DEPLOYER_SOCKET' in item['attention']['body']
    assert 'requires' in item['attention']['body']
    assert not list(installation.pending(runner.data))
    command.assert_not_called()
    launch.assert_not_called()


def test_factory_cplane_wrapper_command():
    script = Path('node/bin/factory-cplane').read_text()
    assert '[ "$(id -u)" = 0 ]' in script
    assert 'exec docker exec -i deployer-factory-runner-1 cplane "$@"' in script
    assert 'runner.env' not in script
    assert '/opt/factory' not in script


@pytest.mark.parametrize('uid', ['0', '21000'])
def test_factory_cplane_wrapper_preserves_process_io(tmp_path, monkeypatch, uid):
    import os
    import subprocess
    fake_id = tmp_path / 'id'
    fake_id.write_text('#!/bin/sh\necho ' + uid + '\n')
    fake_id.chmod(0o755)
    fake_docker = tmp_path / 'docker'
    fake_docker.write_text(
        '#!/usr/bin/env python3\n'
        'import json, sys\n'
        'print(json.dumps(sys.argv[1:]))\n'
        'print(sys.stdin.read(), end="")\n'
        'sys.exit(7)\n'
    )
    fake_docker.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    result = subprocess.run(
        ['sh', 'node/bin/factory-cplane', 'show', 'slice with spaces', '', '$(literal)'],
        input='synthetic input\n', capture_output=True, text=True, check=False,
    )
    if uid == '0':
        args, content = result.stdout.split('\n', 1)
        assert json.loads(args) == [
            'exec', '-i', 'deployer-factory-runner-1', 'cplane',
            'show', 'slice with spaces', '', '$(literal)',
        ]
        assert content == 'synthetic input\n'
        assert result.returncode == 7
    else:
        assert result.returncode == 1
        assert result.stdout == ''
        assert result.stderr == 'factory-cplane requires root\n'
