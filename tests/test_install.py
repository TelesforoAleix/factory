from test_stores import pg_store  # noqa: F401 - shared pytest fixture
from test_runner import setup  # noqa: F401 - shared pytest fixture
# ruff: noqa: F811 - shared pytest fixtures
"""Synthetic install requests and container wrapper checks; no installation is changed."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import SyntheticStore
from test_runner import item, pr_reply

from cplane import installation, state
from cplane.cli import main
from cplane.runner import Runner
from factory_ui import create_app

SHA = 'a' * 40


@pytest.mark.parametrize('reply_format', ['text', 'fenced-json', 'json'])
def test_node_step_after_null_merge_is_installable(setup, monkeypatch, reply_format):
    from test_run_api_runner import block, current
    runner, api, github = setup
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', item(runner)['repo'])
    github.merge.return_value = SHA
    runner.run()
    original = current(runner)
    api.finish(original, 'done', 'handover', pr_reply(None))
    runner.run()
    review = runner.jobs['voice/W1']['requests']['review-1']['run_id']
    api.finish(review, body=block({'verdict': 'pass', 'title': 'Reviewed', 'body': 'Passed'}))
    github.checks.return_value = ('green', '')
    runner.run()
    reply = 'Install the merged commit'
    if reply_format == 'json':
        reply = json.dumps({'node_steps': reply})
    elif reply_format == 'fenced-json':
        reply = block({'node_steps': reply}, 'Handover details')
    api.finish(original, 'waiting', 'waiting', reply)
    runner.run()
    job = runner.jobs['voice/W1']
    assert job['phase'] == 'node-step' and job['sha'] == SHA
    assert item(runner)['attention']['kind'] == 'node-step'
    assert main(['--state', str(runner.path), 'install', 'voice/W1']) == 0
    monkeypatch.setenv('CPLANE_DEPLOYER_SOCKET', '/unused')
    start = Mock(return_value=True)
    monkeypatch.setattr(installation, 'start_deployer', start)
    runner.run()
    request = next(installation.pending(state.load(runner.path)))[1]
    start.assert_called_once_with('repo', SHA, request, runner.runs / 'installs')
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
def test_pass_only_launches_after_explicit_request(setup, monkeypatch, owner_request):
    from test_run_api_runner import block, current
    runner, api, gh = setup
    runner.run()
    api.finish(current(runner), 'done', 'handover', pr_reply('Install at switch'))
    runner.run()
    review = runner.jobs['voice/W1']['requests']['review-1']['run_id']
    api.finish(review, body=block({'verdict': 'pass', 'title': 'Reviewed', 'body': 'Passed'}))
    gh.checks.return_value = ('green', '')
    runner.run()
    monkeypatch.setenv('CPLANE_DEPLOYER_SOCKET', '/unused')
    def start(application, sha, request, directory):
        (directory / (request + '.started')).write_text('{"deployer": true}')
        return True
    launches = Mock(side_effect=start)
    monkeypatch.setattr(installation, 'deployer_running', lambda marker: True)
    monkeypatch.setattr(installation, 'start_deployer', launches)
    runner.run()
    launches.assert_not_called()
    assert main(['--state', str(runner.path), '--actor', 'chat:21', 'install', 'voice/W1']) == 0
    runner.run()
    launches.assert_not_called()
    if owner_request == 'cli':
        assert main(['--state', str(runner.path), 'install', 'voice/W1']) == 0
    else:
        client = create_app(SyntheticStore(runner.path)).test_client()
        assert client.post('/api/slices/voice/W1/install', headers={'X-Factory-UI': '1'}).status_code == 202
    runner.run()
    runner.run()
    assert launches.call_count == 1
    assert launches.call_args.args[:2] == ('repo', gh.merge.return_value)




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
    # Environment files must not be sourced, even under a different name.
    import re
    assert not re.search(r'(^|[;\n])\s*(?:\.|source)\s', script)


@pytest.fixture
def factory_cplane_process(tmp_path, monkeypatch):
    """Run the real shell wrapper with only synthetic host commands on PATH."""
    import os
    import subprocess
    import sys
    import textwrap

    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    fake_id = fake_bin / 'id'
    fake_id.write_text('#!/bin/sh\n[ "$#" = 1 ] && [ "$1" = -u ] || exit 99\nprintf "%s\\n" "$FACTORY_TEST_UID"\n')
    fake_id.chmod(0o755)
    fake_docker = fake_bin / 'docker'
    fake_docker.write_text('#!' + sys.executable + '\n' + textwrap.dedent('''\
        import json
        import os
        import sys

        args = sys.argv[1:]
        with open(os.environ['FACTORY_TEST_CALLS'], 'a') as stream:
            stream.write(json.dumps(args) + '\\n')
        containers = json.loads(os.environ['FACTORY_TEST_CONTAINERS'])
        if len(args) == 4 and args[:3] == ['inspect', '--format', '{{.State.Running}}']:
            if args[3] not in containers:
                sys.stderr.write('unexpected container name\\n')
                sys.exit(98)
            running = containers[args[3]]
            if running == 'missing':
                sys.stderr.write('No such container\\n')
                sys.exit(1)
            print(running)
            sys.exit(0)
        if len(args) >= 4 and args[:2] == ['exec', '-i'] and args[2] in containers and args[3] == 'cplane':
            print(json.dumps({'argv': args, 'stdin': sys.stdin.read()}))
            sys.stderr.write('synthetic cplane stderr\\n')
            sys.exit(int(os.environ['FACTORY_TEST_EXIT']))
        sys.stderr.write('unexpected docker command\\n')
        sys.exit(99)
    '''))
    fake_docker.chmod(0o755)
    monkeypatch.setenv('PATH', str(fake_bin))
    calls_path = tmp_path / 'docker-calls.jsonl'
    wrapper = Path('node/bin/factory-cplane').resolve()

    def run(*, runner='true', sessions='true', uid='0', status=7,
            args=('pending',), stdin='synthetic input\n'):
        calls_path.write_text('')
        env = dict(os.environ, FACTORY_TEST_UID=uid,
                   FACTORY_TEST_CALLS=str(calls_path),
                   FACTORY_TEST_CONTAINERS=json.dumps({
                       'deployer-factory-runner-1': runner,
                       'deployer-factory-sessions-1': sessions,
                   }), FACTORY_TEST_EXIT=str(status))
        result = subprocess.run(
            ['/bin/sh', str(wrapper), *args], cwd=tmp_path, env=env,
            input=stdin, capture_output=True, text=True, check=False, timeout=5,
        )
        calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
        return result, calls

    return run


@pytest.mark.parametrize('uid', ['0', '21000'])
def test_factory_cplane_wrapper_preserves_process_io(factory_cplane_process, tmp_path, uid):
    args = ['show', 'slice with spaces', '', '$(touch injected)', '$(literal)',
            '--actor', 'owner; echo unsafe', '*', 'line one\nline two']
    stdin = 'synthetic input\n\n$(touch stdin-injected)\nlast line without newline'
    result, calls = factory_cplane_process(uid=uid, args=args, stdin=stdin)
    assert not (tmp_path / 'injected').exists()
    assert not (tmp_path / 'stdin-injected').exists()
    if uid == '0':
        expected = ['exec', '-i', 'deployer-factory-runner-1', 'cplane', *args]
        assert calls == [
            ['inspect', '--format', '{{.State.Running}}', 'deployer-factory-runner-1'],
            expected,
        ]
        assert json.loads(result.stdout) == {'argv': expected, 'stdin': stdin}
        assert result.stderr == 'synthetic cplane stderr\n'
        assert result.returncode == 7
    else:
        assert calls == []
        assert result.returncode == 1
        assert result.stdout == ''
        assert result.stderr == 'factory-cplane requires root\n'


@pytest.mark.parametrize('sessions', ['true', 'false', 'missing'])
def test_factory_cplane_running_runner(factory_cplane_process, sessions):
    result, calls = factory_cplane_process(sessions=sessions, status=0, args=(), stdin='')
    expected = ['exec', '-i', 'deployer-factory-runner-1', 'cplane']
    assert calls == [
        ['inspect', '--format', '{{.State.Running}}', 'deployer-factory-runner-1'],
        expected,
    ]
    assert result.returncode == 0
    assert json.loads(result.stdout) == {'argv': expected, 'stdin': ''}
    assert result.stderr == 'synthetic cplane stderr\n'


@pytest.mark.parametrize('status', [0, 1, 7, 125, 137])
def test_factory_cplane_runner_exit_status(factory_cplane_process, status):
    result, calls = factory_cplane_process(status=status)
    assert calls == [
        ['inspect', '--format', '{{.State.Running}}', 'deployer-factory-runner-1'],
        ['exec', '-i', 'deployer-factory-runner-1', 'cplane', 'pending'],
    ]
    assert result.returncode == status
    assert result.stderr == 'synthetic cplane stderr\n'


@pytest.mark.parametrize('runner', ['false', 'missing'])
@pytest.mark.parametrize('status', [0, 1, 7, 125, 137])
def test_factory_cplane_sessions_fallback(factory_cplane_process, tmp_path, runner, status):
    args = ['show', 'slice with spaces', '', '$(touch injected)', '--actor', 'owner']
    stdin = 'first\n\n$(touch stdin-injected)\nlast line without newline'
    result, calls = factory_cplane_process(runner=runner, status=status, args=args, stdin=stdin)
    expected = ['exec', '-i', 'deployer-factory-sessions-1', 'cplane', *args]
    assert calls == [
        ['inspect', '--format', '{{.State.Running}}', 'deployer-factory-runner-1'],
        ['inspect', '--format', '{{.State.Running}}', 'deployer-factory-sessions-1'],
        expected,
    ]
    assert result.returncode == status
    assert json.loads(result.stdout) == {'argv': expected, 'stdin': stdin}
    assert result.stderr == 'synthetic cplane stderr\n'
    assert not (tmp_path / 'injected').exists()
    assert not (tmp_path / 'stdin-injected').exists()


@pytest.mark.parametrize('runner', ['false', 'missing', 'True', 'running'])
@pytest.mark.parametrize('sessions', ['false', 'missing', 'True', 'running'])
def test_factory_cplane_no_running_container(factory_cplane_process, runner, sessions):
    result, calls = factory_cplane_process(runner=runner, sessions=sessions)
    assert calls == [
        ['inspect', '--format', '{{.State.Running}}', 'deployer-factory-runner-1'],
        ['inspect', '--format', '{{.State.Running}}', 'deployer-factory-sessions-1'],
    ]
    assert result.returncode == 1
    assert result.stdout == ''
    assert result.stderr == 'factory-cplane: no Factory container is running\n'


@pytest.mark.parametrize('runner,sessions', [('true', 'true'), ('false', 'true'), ('missing', 'missing')])
def test_factory_cplane_nonroot_before_inspection(factory_cplane_process, runner, sessions):
    result, calls = factory_cplane_process(uid='21000', runner=runner, sessions=sessions)
    assert calls == []
    assert result.returncode == 1
    assert result.stdout == ''
    assert result.stderr == 'factory-cplane requires root\n'


def test_factory_cplane_fallback_documentation():
    document = ' '.join(Path('docs/node.md').read_text().split())
    wrapper_section = document.split('## Automatic installs', 1)[0]
    assert (
        "Operator commands use a running Factory container's code, environment and state."
        in wrapper_section
    )
    for sentence in (
        'The wrapper uses `deployer-factory-runner-1` when it is running, otherwise '
        '`deployer-factory-sessions-1` when it is running.',
        'Running state is checked with `docker inspect`; the wrapper never starts or restarts containers.',
        'If neither container is running, it prints `factory-cplane: no Factory container is running` '
        'to stderr and exits 1.',
    ):
        assert sentence in wrapper_section
    for preserved in ('root-only', '-i', 'stdin', 'arguments', 'exit status',
                      'no host environment file', "configured service UID"):
        assert preserved in wrapper_section
    assert 'needs the runner container to be running' not in wrapper_section
    assert (
        'install `node/bin/factory-cplane` as `/usr/local/bin/factory-cplane`, root:root, mode 0755.'
        in document
    )
