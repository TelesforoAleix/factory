"""Synthetic Postgres and Unix socket tests for the fenced chat boundary."""
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
from unittest.mock import Mock

import pytest

from cplane import sessions
from cplane.stores import PostgresStore
from cplane.workshop import Workshop, WorkshopServer, TOOLS, SLICE_FIELDS
from factory_ui.documents import Documents
from test_stores import pg_store


def call(workshop, name, **arguments):
    return workshop.request(dict(jsonrpc='2.0', id=1, method='tools/call',
                                 params=dict(name=name, arguments=arguments)))['result']


def value(result):
    assert not result['isError'], result
    return json.loads(result['content'][0]['text'])


def refused(result, text):
    assert result['isError']
    assert text in result['content'][0]['text']


@pytest.fixture
def context(pg_store, tmp_path):
    # No repository resolution, remote fetch, or real chat execution.
    with pg_store.mutation():
        pg_store.connection.execute('UPDATE cplane_projects SET repository = NULL')
    own = pg_store.feature_add('FAC', 'Own', stage='grilling')['id']
    other = pg_store.feature_add('FAC', 'Other')['id']
    outside = pg_store.feature_add('LAB', 'Outside')['id']
    chats = dict(feature=pg_store.chats(kind='feature')[0],
                 project=pg_store.create_project_chat('FAC'),
                 orchestrator=pg_store.chats(kind='orchestrator')[0])
    root = tmp_path / 'docs'
    root.mkdir()
    (tmp_path / '.ui-docs.lock').touch()
    (root / 'brief.md').write_text('---\ntitle: Synthetic design\n---\n# Safe document\nBody')
    documents = Documents(root)
    workshops = {kind: Workshop(pg_store, chat['id'], documents) for kind, chat in chats.items()}
    return pg_store, workshops, chats, own, other, outside, documents


@pytest.mark.parametrize('kind', ['feature', 'project', 'orchestrator'])
def test_write_scopes(context, kind):
    store, workshops, chats, own, other, outside, _ = context
    workshop = workshops[kind]
    for target, allowed in [(own, True), (other, kind != 'feature'), (outside, kind == 'orchestrator')]:
        for operation, args in [
            ('save_section', dict(section='Design', text='Synthetic')),
            ('set_mark', dict(mark='design')),
            ('move_feature', dict(stage='parked')),
            ('place_feature', dict(bottom=True)),
        ]:
            result = call(workshop, operation, feature=target, **args)
            if allowed:
                value(result)
            else:
                refused(result, 'can only write')
    added = call(workshop, 'add_feature', project='FAC', title='Added')
    if kind == 'feature':
        refused(added, 'cannot add')
    else:
        value(added)
    added = call(workshop, 'add_feature', project='LAB', title='Added')
    if kind == 'orchestrator':
        value(added)
    else:
        assert added['isError']
    with store.locked():
        audit = list(store.connection.execute('SELECT chat, operation, time FROM cplane_workshop_writes'))
    assert audit and all(r[0] == chats[kind]['id'] and r[2] is not None for r in audit)


def test_transfer_scope_and_stable_identity(context):
    store, workshops, chats, own, other, outside, _ = context
    refused(call(workshops['project'], 'move_feature', feature=own, project='LAB'), 'inside its project')
    refused(call(workshops['feature'], 'move_feature', feature=other, project='LAB'), 'own feature')
    moved = value(call(workshops['orchestrator'], 'move_feature', feature=own, project='LAB'))
    assert moved['project'] == 'LAB'
    # Identity follows the feature, including writes through an old alias.
    value(call(workshops['feature'], 'save_section', feature=own, section='Design', text='Still own'))
    refused(call(workshops['project'], 'save_section', feature=own, section='Design', text='No'), 'inside its project')
    assert store.feature_show(moved['id'])['sections'][0]['text'] == 'Still own'


def test_refused_move_and_store_sentence(context):
    store, workshops, _, own, _, _, _ = context
    refused(call(workshops['feature'], 'move_feature', feature=own, stage='ready'), 'No agreed design yet')
    assert store.feature_show(own)['stage'] == 'grilling'
    assert value(call(workshops['feature'], 'set_mark', feature=own, mark='design'))['design_agreed']
    refused(call(workshops['feature'], 'move_feature', feature=own, stage='ready'), 'No linked slice yet')
    value(call(workshops['feature'], 'set_mark', feature=own, mark='design', clear=True))
    with store.locked():
        assert store.connection.execute('SELECT count(*) FROM cplane_workshop_writes').fetchone()[0] == 2


def test_cap_counts_refusals_and_is_per_turn(context):
    store, workshops, chats, own, _, _, documents = context
    workshop = workshops['feature']
    for _ in range(49):
        value(call(workshop, 'feature', feature=own))
    refused(call(workshop, 'move_feature', feature=own, stage='ready'), 'No agreed design yet')
    for name, args in [('board', {}), ('set_mark', dict(feature=own, mark='design')),
                       ('raise_decision', dict(text='Question', recommendation='Wait')), ('unknown', {})]:
        refused(call(workshop, name, **args), '50 calls per turn')
    assert store.feature_show(own)['design_agreed'] is None
    value(call(Workshop(store, chats['feature']['id'], documents), 'board'))


def test_owner_decision_and_noop_audit(context):
    store, workshops, chats, own, _, _, _ = context
    for kind, workshop in workshops.items():
        assert value(call(workshop, 'raise_decision', text='Choose this?', recommendation='Use A')) == {'raised': True}
    value(call(workshops['feature'], 'save_section', feature=own, section='Design', text='A'))
    value(call(workshops['feature'], 'save_section', feature=own, section='Design', text='A'))
    assert len(store.feature_history(own)) == 1
    notices = [notice for _, notice in store.notices()]
    assert len(notices) == 3
    for notice, chat in zip(notices, chats.values()):
        # chats and workshops share insertion order.
        assert notice['event'] == notice['kind'] == 'owner-check'
        assert notice['chat'] == chat['id'] and notice['actor'] == f"chat:{chat['id']}"
        assert notice['text'] == f"{chat['title']}: Choose this?\nRecommendation: Use A"
        assert notice['at']
    with store.locked():
        assert store.connection.execute('SELECT count(*) FROM cplane_workshop_writes').fetchone()[0] == 5


def test_all_reads_exclude_private_metadata(context, slice_data):
    store, workshops, _, own, _, _, documents = context
    secret = 'FORBIDDEN-SYNTHETIC-SECRET'
    slice_data.update(feature_id=own, executor=dict(tool='codex', model=secret),
                      session=dict(tool='codex', id=secret, folder='/tmp/synthetic'),
                      attention=dict(kind='question', body=secret, since='2026-10-15T12:00:00Z', answer=None, approved=False),
                      log=[dict(at='2026-10-15T12:00:00Z', actor='owner', event=secret)])
    store.save(dict(version=1, slices=[slice_data]))
    sid = store.create_session('factory', 'Other chat', 'codex', 'synthetic', [])
    store.session_messages('factory', sid, secret)
    with store.mutation():
        store.connection.execute('UPDATE cplane_sessions SET cli_session_id = %s WHERE id = %s', (secret, sid))
        store.connection.execute("INSERT INTO cplane_run_records (turn_key, kind, tool, feature_id, prompt) VALUES ('synthetic', 'chat', 'codex', %s, %s)", (own, secret))
        store.connection.execute("UPDATE cplane_settings SET value = 123")
        store.connection.execute("UPDATE cplane_chat_settings SET chat_model = %s", (secret,))
    for workshop in workshops.values():
        for operation, args in [('board', {}), ('feature', dict(feature=own)), ('slices', dict(feature=own)),
                                ('documents', {}), ('document', dict(path='brief.md'))]:
            result = value(call(workshop, operation, **args))
            assert secret not in json.dumps(result)
            for forbidden in ('executor', 'session', 'attention', 'log', 'prompt', 'cli_session_id', 'tool_sessions', 'settings'):
                assert f'"{forbidden}":' not in json.dumps(result)
        slices = value(call(workshop, 'slices', feature=own))
        assert slices[0]['id'] == slice_data['id']
        assert set(slices[0]) <= set(SLICE_FIELDS)
        assert value(call(workshop, 'documents')) == documents.search()
        assert value(call(workshop, 'document', path='brief.md')) == documents.read('brief.md')
        refused(call(workshop, 'document', path='../private.md'), 'Invalid document path')


@pytest.mark.parametrize('extra', ['chat', 'chat_id', 'actor', 'kind', 'project', 'feature_id'])
def test_client_cannot_supply_identity(context, extra):
    _, workshops, _, _, _, outside, _ = context
    refused(call(workshops['feature'], 'save_section', feature=outside, section='Design', text='No',
                 **{extra: 'orchestrator'}), 'Invalid workshop arguments')


def exchange(path, request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.connect(str(path))
        channel.sendall(json.dumps(request).encode() + b'\n')
        with channel.makefile('rb') as stream:
            return json.loads(stream.readline())


@pytest.fixture
def socket_owner(monkeypatch):
    # Non-root CI cannot chown to the fence UID. Check the requested ownership
    # there; root and UID 21000 runs exercise the actual socket ownership.
    if os.getuid() not in (0, 21000):
        chown = Mock()
        monkeypatch.setattr('cplane.workshop.os.chown', chown)
        yield os.getuid()
        assert chown.call_args.args[1:] == (21000, 21000)
    else:
        yield 21000


def test_socket_identity_lifecycle_and_stdio_client(context, tmp_path, socket_owner):
    store, _, chats, own, _, outside, documents = context
    run = tmp_path / 'run'
    run.mkdir(mode=0o700)
    with WorkshopServer(run, PostgresStore(store._url), chats['feature']['id'], documents) as server:
        info = server.path.stat()
        assert stat.S_ISSOCK(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == socket_owner
        assert stat.S_IMODE(run.stat().st_mode) == 0o755
        req = dict(jsonrpc='2.0', id=1, method='tools/call', params=dict(name='save_section', arguments=dict(
            feature=outside, section='Design', text='No')),
            chat=chats['orchestrator']['id'])
        refused(exchange(server.path, req)['result'], 'own feature')
        req['params']['arguments']['feature'] = own
        value(exchange(server.path, req)['result'])
        requests = [dict(jsonrpc='2.0', id=2, method='initialize', params=dict(protocolVersion='2024-11-05')),
                    dict(jsonrpc='2.0', method='notifications/initialized'),
                    dict(jsonrpc='2.0', id=3, method='tools/list'),
                    dict(jsonrpc='2.0', id=4, method='tools/call', params=dict(name='board'))]
        result = subprocess.run(['python3', str(run / 'workshop_mcp.py')],
                                input=''.join(json.dumps(r)+'\n' for r in requests),
                                text=True, capture_output=True, check=True)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        assert [r['id'] for r in replies] == [2, 3, 4]
        assert replies[0]['result']['capabilities'] == {'tools': {}}
        assert replies[1]['result']['tools'] == TOOLS
        value(replies[2]['result'])
    assert not server.path.exists()


@pytest.mark.parametrize('outcome', [0, 1, 124, 125, 'exception'])
def test_socket_removed_after_turn(context, tmp_path, monkeypatch, outcome, socket_owner):
    store, _, chats, _, _, _, _ = context
    chat = chats['feature']
    turn = dict(id=7, text='Synthetic', session=chat)
    monkeypatch.setattr(sessions, 'RUNS', tmp_path)
    monkeypatch.setattr(sessions, 'workspace', lambda _: (tmp_path, []))
    monkeypatch.setattr(sessions, 'trusted_directory', lambda _: None)
    monkeypatch.setattr(sessions.run_records, 'chat_record', Mock())
    store.finish_session_turn = Mock()

    def launch(*args, **kwargs):
        path = tmp_path / 'session-turn-7/workshop.sock'
        assert path.exists()
        value(exchange(path, dict(jsonrpc='2.0', id=1, method='tools/call', params=dict(name='board')))['result'])
        if outcome == 'exception':
            raise OSError('private error')
        return subprocess.CompletedProcess(args, outcome, '\n'.join([
            '{"type":"thread.started","thread_id":"synthetic"}',
            '{"type":"item.completed","item":{"type":"agent_message","text":"Done"}}']))

    monkeypatch.setattr(sessions.subprocess, 'run', launch)
    if outcome == 125:
        with pytest.raises(sessions.CleanupError):
            sessions.execute_turn(turn, store)
    else:
        sessions.execute_turn(turn, store)
        store.finish_session_turn.assert_called_once()
    assert not (tmp_path / 'session-turn-7/workshop.sock').exists()


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('resume', [None, 'synthetic'])
@pytest.mark.parametrize('kind', ['feature', 'project', 'orchestrator', 'legacy'])
def test_turn_mcp_arguments(tool, resume, kind, tmp_path):
    turn = dict(id=7, text='Synthetic', session=dict(tool=tool, model='synthetic', cli_session_id=resume, kind=kind))
    command = sessions.turn_command(turn, tmp_path, [], tmp_path / 'run')
    if kind == 'legacy':
        assert not any('workshop' in a for a in command)
    elif tool == 'codex':
        assert 'mcp_servers.workshop.command="python3"' in command
        assert 'mcp_servers.workshop.args=["/run/factory/workshop_mcp.py"]' in command
        if resume:
            assert command.index('mcp_servers.workshop.command="python3"') < command.index('resume')
    else:
        assert command[command.index('--mcp-config') + 1] == '/run/factory/workshop-mcp.json'


def test_legacy_chat_denied(context):
    store, _, _, _, _, _, documents = context
    sid = store.create_session('factory', 'Legacy', 'codex', 'synthetic', [])
    refused(call(Workshop(store, sid, documents), 'board'), 'no workshop access')


def test_errors_do_not_echo_diagnostics():
    store = Mock()
    store.mutation.side_effect = RuntimeError('SYNTHETIC PASSWORD')
    response = call(Workshop(store, 1, Mock()), 'board')
    refused(response, 'Workshop unavailable')
    assert 'PASSWORD' not in json.dumps(response)


@pytest.mark.parametrize('operation', ['settings', 'limit_show', 'roles', 'keys',
                                       'chats', 'session_messages', 'run_record_list', 'delete'])
def test_forbidden_operations_have_no_dispatch(context, operation):
    _, workshops, _, _, _, _, _ = context
    for workshop in workshops.values():
        refused(call(workshop, operation), 'Unknown workshop operation')


def test_protocol_errors_and_later_tool_calls(context):
    _, workshops, _, _, _, _, _ = context
    workshop = workshops['feature']
    assert workshop.request([])['error']['code'] == -32600
    assert workshop.request(dict(jsonrpc='2.0', id=1, method='server/discover'))['error']['code'] == -32601
    assert workshop.request(dict(jsonrpc='2.0', id=1, method='tools/call', params=[]))['result']['isError']
    assert workshop.calls == 1
    value(call(workshop, 'board'))


def test_socket_cleanup_if_setup_fails(context, tmp_path, monkeypatch):
    store, _, chats, _, _, _, documents = context
    run = tmp_path / 'run'
    run.mkdir()
    def fail(*args):
        raise PermissionError('Synthetic')
    monkeypatch.setattr('cplane.workshop.os.chown', fail)
    with pytest.raises(PermissionError):
        with WorkshopServer(run, store, chats['feature']['id'], documents):
            pytest.fail('Should not start')
    assert not (run / 'workshop.sock').exists()


def test_restart_cleans_interrupted_socket(tmp_path, monkeypatch):
    from cplane import fence
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
    monkeypatch.setattr(sessions, 'RUNS', tmp_path)
    launch = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(sessions.subprocess, 'run', launch)
    run = tmp_path / 'session-turn-7'
    run.mkdir()
    path = run / 'workshop.sock'
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.bind(str(path))
    sessions.cleanup_interrupted_turn(dict(id=7))
    assert not path.exists()
    launch.assert_called_once_with(['factory-cli', 'session-cleanup', '7'], check=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Missing old run directories are harmless; replaced ancestors are refused.
    sessions.cleanup_interrupted_turn(dict(id=8))
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'workshop.sock').touch()
    (tmp_path / 'session-turn-9').symlink_to(outside, target_is_directory=True)
    with pytest.raises(sessions.StateError, match='link or non-directory'):
        sessions.cleanup_interrupted_turn(dict(id=9))
    assert (outside / 'workshop.sock').exists()
