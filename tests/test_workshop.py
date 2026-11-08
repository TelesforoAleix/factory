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


BRIEF = '# Synthetic task\n\n## Fixed decisions\nKeep the contract.\n'


def slice_args(feature, **overrides):
    return dict(feature=feature, title='Synthetic slice', brief=BRIEF,
                model='example-model', effort='high', **overrides)


def repository(store):
    with store.mutation():
        store.connection.execute("UPDATE cplane_projects SET repository = 'example/repo' WHERE key = 'FAC'")
        store.connection.execute("UPDATE cplane_projects SET repository = 'example/outside' WHERE key = 'LAB'")


@pytest.mark.parametrize('kind', ['feature', 'project', 'orchestrator'])
def test_add_slice_scope_and_audit(context, kind):
    store, workshops, chats, own, other, outside, _ = context
    repository(store)
    with store.mutation():
        store.connection.execute("UPDATE cplane_features SET stage = 'grilling'")
    for target, allowed in [(own, True), (other, kind != 'feature'), (outside, kind == 'orchestrator')]:
        result = call(workshops[kind], 'add_slice', **slice_args(target))
        if not allowed:
            refused(result, 'can only write')
            continue
        created = value(result)
        assert created['id'] == f'{target}-S1'
        item = next(s for s in store.load()['slices'] if s['id'] == created['id'])
        assert item['state'] == 'ready' and item['flow'] == 'cli'
        assert item['brief'] is None and item['brief_id'] == item['id']
        assert item['slot'] is None and item['session'] is None
        assert item['repo'] == ('example/outside' if target == outside else 'example/repo')
        assert item['executor'] == dict(tool='codex', model='example-model', effort='high')
        assert not item['stop_before_merge']
        assert item['log'][-1]['actor'] == f"chat:{chats[kind]['id']}"
        assert store.stored_brief(item['brief_id']) == BRIEF
    with store.locked():
        rows = list(store.connection.execute('SELECT chat, operation, time FROM cplane_workshop_writes'))
        assert len(rows) == (1 if kind == 'feature' else 2 if kind == 'project' else 3)
        assert all(r[0] == chats[kind]['id'] and r[1] == 'add_slice' and r[2] for r in rows)
        rows = list(store.connection.execute('SELECT actor, time FROM cplane_slice_briefs'))
        assert all(r[0] == f"chat:{chats[kind]['id']}" and r[1] for r in rows)


@pytest.mark.parametrize('stage', ['shortlist', 'grilling', 'ready', 'next', 'building', 'testing', 'done', 'parked'])
def test_add_slice_stages(context, stage):
    store, workshops, _, own, _, _, _ = context
    repository(store)
    with store.mutation():
        store.connection.execute('UPDATE cplane_features SET stage = %s WHERE id = %s', (stage, own))
    result = call(workshops['feature'], 'add_slice', **slice_args(own))
    if stage in ('grilling', 'ready', 'building', 'testing'):
        value(result)
        assert store.feature_show(own)['stage'] == stage
    else:
        refused(result, 'only be added')
        assert not store.load()['slices']


@pytest.mark.parametrize('brief, error', [
    ('x' * 65537, 'exceeds'), ('## Do not\n' + 'é' * 32764, 'bytes'),
    ('', 'empty'), ('## Do not\n\x00', 'NUL'), ('# Task\nNo sections', 'neither'),
    ('```markdown\n## Do not\n```', 'neither'),
])
def test_add_slice_brief_refusals(context, brief, error):
    store, workshops, _, own, _, _, _ = context
    repository(store)
    args = slice_args(own)
    args['brief'] = brief
    refused(call(workshops['feature'], 'add_slice', **args), error)
    assert not store.load()['slices']
    with store.locked():
        assert store.connection.execute('SELECT slice_counter FROM cplane_features WHERE id = %s', (own,)).fetchone()[0] == 0
        assert not list(store.connection.execute('SELECT * FROM cplane_slice_briefs'))
        assert not list(store.connection.execute('SELECT * FROM cplane_workshop_writes'))


def test_add_slice_repository_and_arguments(context):
    store, workshops, _, own, _, _, _ = context
    refused(call(workshops['feature'], 'add_slice', **slice_args(own)), 'no repository')
    repository(store)
    for key, val in [('effort', 'invalid'), ('tool', 'claude'), ('flow', 'tickets'),
                     ('repo', 'evil/repo'), ('actor', 'owner'), ('stop_before_merge', 'yes')]:
        args = slice_args(own)
        args[key] = val
        refused(call(workshops['feature'], 'add_slice', **args), 'Invalid workshop arguments')
    with store.mutation():
        store.connection.execute("UPDATE cplane_projects SET repository = 'unresolved' WHERE key = 'FAC'")
    refused(call(workshops['feature'], 'add_slice', **slice_args(own)), 'unresolved')
    assert not store.load()['slices']


def test_add_slice_dependencies_identity_and_immutable_brief(context):
    from cplane import state
    from cplane.cli import main
    store, workshops, _, own, other, _, _ = context
    repository(store)
    first = value(call(workshops['feature'], 'add_slice', **slice_args(own)))
    second = value(call(workshops['feature'], 'add_slice', **slice_args(
        own, depends_on=[first['id']], stop_before_merge=True)))
    assert second['depends_on'] == [first['id']] and second['stop_before_merge']
    for deps in [['missing'], [first['id'], first['id']]]:
        assert call(workshops['feature'], 'add_slice', **slice_args(own, depends_on=deps))['isError']
    store.feature_stage(other, 'grilling')
    refused(call(workshops['project'], 'add_slice', **slice_args(other, depends_on=[first['id']])), 'same feature')
    assert main(['edit', first['id'], '--brief', 'replacement.md']) == 1
    assert store.stored_brief(first['id']) == BRIEF
    with pytest.raises(state.StateError):
        with store.mutation():
            store.connection.execute('UPDATE cplane_slice_briefs SET text = %s WHERE slice_id = %s', ('changed', first['id']))
    data = store.load()
    data['slices'] = []
    store.save(data)
    third = value(call(workshops['feature'], 'add_slice', **slice_args(own)))
    assert third['id'] == f'{own}-S3'
    moved = store.feature_move(own, 'LAB')
    fourth = value(call(workshops['feature'], 'add_slice', **slice_args(own)))
    assert fourth['id'] == f"{moved['id']}-S4" and fourth['repo'] == 'example/outside'
    exported = next(f for f in store.feature_export_snapshot() if f['id'] == moved['id'])
    assert {b['id'] for b in exported['briefs']} == {first['id'], second['id'], third['id'], fourth['id']}


def test_add_slice_full_byte_bound_over_socket(context, tmp_path):
    store, _, chats, own, _, _, documents = context
    repository(store)
    # Maximal JSON expansion of ASCII controls still fits the transport.
    brief = '## Do not\n' + '\t' * (65536 - len('## Do not\n'))
    run = tmp_path / 'max-brief'
    run.mkdir()
    with WorkshopServer(run, store, chats['feature']['id'], documents) as server:
        request = dict(jsonrpc='2.0', id=1, method='tools/call',
                       params=dict(name='add_slice', arguments={**slice_args(own), 'brief': brief}))
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(str(server.path))
            client.sendall(json.dumps(request).encode() + b'\n')
            response = json.loads(client.makefile('rb').readline())
        created = value(response['result'])
    assert store.stored_brief(created['brief_id']) == brief


def test_add_slice_parallel_numbers_and_atomic_failure(context, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    store, _, chats, own, _, _, documents = context
    repository(store)
    barrier = Barrier(2)
    def create():
        backend = PostgresStore(store._url)
        barrier.wait(timeout=5)
        return Workshop(backend, chats['feature']['id'], documents).call('add_slice', slice_args(own))
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(create) for _ in range(2)]
        assert {f.result(timeout=10)['id'] for f in futures} == {f'{own}-S1', f'{own}-S2'}
    before = store.snapshot()
    def fail(*args):
        raise RuntimeError('synthetic post-insert failure')
    monkeypatch.setattr(store, 'save', fail)
    failed = call(Workshop(store, chats['feature']['id'], documents), 'add_slice', **slice_args(own))
    refused(failed, 'Workshop unavailable')
    assert store.snapshot() == before
    with store.locked():
        assert store.connection.execute('SELECT slice_counter FROM cplane_features WHERE id = %s', (own,)).fetchone()[0] == 2
        assert store.connection.execute('SELECT count(*) FROM cplane_slice_briefs').fetchone()[0] == 2
        assert store.connection.execute('SELECT count(*) FROM cplane_workshop_writes').fetchone()[0] == 2
