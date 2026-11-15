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
from cplane.workshop import Workshop, WorkshopServer, TOOLS, SLICE_FIELDS, SECRETARY_WRITES
from factory_ui.documents import Documents
from test_stores import pg_store
from conftest import seed_model_choices


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
    seed_model_choices(pg_store)
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


def test_decision_chain_and_noop_audit(context):
    store, workshops, chats, own, _, _, _ = context
    identifier = value(call(workshops['feature'], 'raise_decision', text='Choose this?', recommendation='Use A'))['decision']
    for kind in ('project', 'orchestrator'):
        messages = store.session_messages(chats[kind]['area'], chats[kind]['id'])
        message = messages[-1]
        assert message['role'] == 'system' and message['automatic'] and message['status'] == 'queued'
        for text in (identifier, chats['feature']['title'], 'Choose this?', 'Use A'):
            assert text in message['text']
        assert not any(n['event'] == 'owner-check' for _, n in store.notices())
        assert value(call(workshops[kind], 'raise_decision', decision=identifier,
                          text='Choose this?', recommendation='Use A')) == dict(raised=True, decision=identifier)
    notices = [n for _, n in store.notices() if n['event'] == 'owner-check']
    assert len(notices) == 1
    notice = notices[0]
    assert notice['chat'] == chats['orchestrator']['id']
    assert notice['actor'] == f"chat:{chats['orchestrator']['id']}"
    assert notice['kind'] == 'owner-check' and notice['at']
    assert f"{chats['feature']['title']}: Choose this?" in notice['text']
    refused(call(workshops['orchestrator'], 'raise_decision', decision=identifier,
                 text='Duplicate?', recommendation='No'), 'already reached the owner')
    value(call(workshops['feature'], 'save_section', feature=own, section='Design', text='A'))
    value(call(workshops['feature'], 'save_section', feature=own, section='Design', text='A'))
    assert len(store.feature_history(own)) == 1
    with store.locked():
        assert store.connection.execute('SELECT count(*) FROM cplane_workshop_writes').fetchone()[0] == 5


@pytest.mark.parametrize('kind,source', [('project', 'feature'), ('orchestrator', 'project')])
@pytest.mark.parametrize('pause', ['paused', 'limit'])
def test_paused_decision_level_holds_until_reactivated(context, kind, source, pause):
    store, workshops, chats, *_ = context
    sid = chats[kind]['id']
    with store.mutation():
        store.connection.execute(
            'UPDATE cplane_sessions SET auto_turns = %s, auto_paused = %s WHERE id = %s',
            (store.limit_show()['chat_auto_turns'], pause == 'paused', sid))
    identifier = value(call(workshops[source], 'raise_decision', text='Question', recommendation='A'))['decision']
    record = store.notices()[-1][1]
    assert record['decision'] == identifier and record['holder'] == sid and record['status'] == 'open'
    assert not any(n['event'] == 'owner-check' for _, n in store.notices())
    messages = store.session_messages(chats[kind]['area'], sid)
    assert len(messages) == 1
    assert messages[0]['automatic'] and messages[0]['status'] == 'queued'
    assert identifier in messages[0]['text']
    with store.mutation():
        assert not store.chat_can_take(sid)
    assert store.chat_show(sid)['auto_paused']
    assert store.session_messages(chats[kind]['area'], sid) == messages


@pytest.mark.parametrize('unavailable', ['archived', 'failed', 'missing'])
def test_unavailable_project_decision_level_is_skipped(context, unavailable):
    store, workshops, chats, *_ = context
    sid = chats['project']['id']
    if unavailable == 'archived':
        store.chat_archive(sid)
    else:
        with store.mutation():
            if unavailable == 'failed':
                store.connection.execute("UPDATE cplane_sessions SET state = 'failed' WHERE id = %s", (sid,))
            else:
                store.connection.execute('DELETE FROM cplane_sessions WHERE id = %s', (sid,))
    identifier = value(call(workshops['feature'], 'raise_decision', text='Question', recommendation='A'))['decision']
    record = store.notices()[-1][1]
    assert record['decision'] == identifier and record['holder'] == chats['orchestrator']['id']
    assert record['status'] == 'open'
    assert not any(n['event'] == 'owner-check' for _, n in store.notices())
    if unavailable != 'missing':
        assert store.session_messages(chats['project']['area'], sid) == []


@pytest.mark.parametrize('kind', ['feature', 'project', 'orchestrator'])
def test_reactivate_is_not_a_workshop_tool(context, kind):
    store, workshops, chats, *_ = context
    assert 'reactivate' not in [tool['name'] for tool in TOOLS]
    before = store.snapshot()
    assert call(workshops[kind], 'reactivate', chat=chats['orchestrator']['id'])['isError']
    assert store.snapshot() == before


@pytest.mark.parametrize('answer_at', ['project', 'orchestrator', 'owner'])
def test_decision_answer_returns_to_first_chat_and_closes(context, answer_at):
    store, workshops, chats, *_ = context
    identifier = value(call(workshops['feature'], 'raise_decision', text='Question', recommendation='A'))['decision']
    for kind in ('feature', 'orchestrator'):
        refused(call(workshops[kind], 'answer_decision', decision=identifier, text='Intruder'), 'holding chat')
        refused(call(workshops[kind], 'raise_decision', decision=identifier,
                     text='Intruder', recommendation='No'), 'holding chat')
    if answer_at != 'project':
        value(call(workshops['project'], 'raise_decision', decision=identifier,
                   text='More context', recommendation='A'))
    if answer_at == 'owner':
        value(call(workshops['orchestrator'], 'raise_decision', decision=identifier,
                   text='Owner choice', recommendation='A'))
    holder = workshops['project' if answer_at == 'project' else 'orchestrator']
    assert value(call(holder, 'answer_decision', decision=identifier, text='Use recorded A')) == dict(answered=True, decision=identifier)
    message = store.session_messages('factory', chats['feature']['id'])[-1]
    assert message['role'] == 'system' and message['automatic'] and message['status'] == 'queued'
    assert identifier in message['text'] and 'Use recorded A' in message['text']
    before = store.snapshot()
    refused(call(holder, 'answer_decision', decision=identifier, text='Again'), 'closed')
    refused(call(holder, 'raise_decision', decision=identifier, text='Again', recommendation='A'), 'closed')
    assert store.snapshot() == before


@pytest.mark.parametrize('operation', ['answer_decision', 'raise_decision'])
def test_unknown_decision_refused(context, operation):
    store, workshops, *_ = context
    before = store.snapshot()
    args = dict(decision='unknown', text='Question')
    if operation == 'raise_decision':
        args['recommendation'] = 'A'
    refused(call(workshops['project'], operation, **args), 'Decision not found')
    assert store.snapshot() == before


@pytest.mark.parametrize('kind', ['feature', 'project', 'orchestrator'])
def test_new_decision_starts_at_callers_level(context, kind):
    store, workshops, chats, *_ = context
    identifier = value(call(workshops[kind], 'raise_decision', text='Question', recommendation='A'))['decision']
    record = store.notices()[-1][1]
    assert record['decision'] == identifier and record['origin'] == chats[kind]['id']
    expected = {'feature': 'project', 'project': 'orchestrator', 'orchestrator': 'orchestrator'}[kind]
    assert record['holder'] == chats[expected]['id']
    assert record['status'] == ('owner' if kind == 'orchestrator' else 'open')


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
        store.connection.execute("UPDATE cplane_settings SET value = 123 WHERE name IN ('building_limit','waiting_limit','chat_auto_turns')")
        store.connection.execute("UPDATE cplane_roles SET model = %s", (secret,))
    for workshop in workshops.values():
        for operation, args in [('board', {}), ('feature', dict(feature=own)), ('slices', dict(feature=own)),
                                ('documents', {}), ('document', dict(path='brief.md'))]:
            result = value(call(workshop, operation, **args))
            assert secret not in json.dumps(result)
            for forbidden in ('executor', 'session', 'attention', 'log', 'prompt', 'cli_session_id', 'tool_sessions', 'settings'):
                assert f'"{forbidden}":' not in json.dumps(result)
        slices = value(call(workshop, 'slices', feature=own))
        assert slices[0]['id'] == slice_data['id']
        assert set(slices[0]) <= set(SLICE_FIELDS) | {'installation', 'handovers'}
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
    # CI without the fence group checks the requested group change; other
    # runs exercise the actual socket group while retaining service ownership.
    if os.geteuid() != 0 and 21000 not in (os.getegid(), *os.getgroups()):
        chown = Mock()
        monkeypatch.setattr('cplane.workshop.os.chown', chown)
        yield os.getuid()
        assert chown.call_args.args[1:] == (-1, 21000)
    else:
        yield os.geteuid()


def test_socket_identity_lifecycle_and_stdio_client(context, tmp_path, socket_owner):
    store, _, chats, own, _, outside, documents = context
    run = tmp_path / 'run'
    run.mkdir(mode=0o700)
    with WorkshopServer(run, PostgresStore(store._url), chats['feature']['id'], documents) as server:
        info = server.path.stat()
        assert stat.S_ISSOCK(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o660 and info.st_uid == socket_owner
        if os.geteuid() == 0 or 21000 in (os.getegid(), *os.getgroups()):
            assert info.st_gid == 21000
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
        listed = replies[1]['result']['tools']
        assert [t['name'] for t in listed] == [t['name'] for t in TOOLS if t['name'] not in SECRETARY_WRITES]
        add = next(t for t in listed if t['name'] == 'add_slice')['inputSchema']['properties']
        assert 'example-model' in add['model']['enum']
        assert 'high' in add['effort']['enum']
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
    sessions.execute_turn(turn, store)
    store.finish_session_turn.assert_called_once()
    assert not (tmp_path / 'session-turn-7/workshop.sock').exists()


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('resume', [None, 'synthetic'])
@pytest.mark.parametrize('kind', ['feature', 'project', 'orchestrator', 'legacy'])
def test_turn_mcp_arguments(tool, resume, kind, tmp_path):
    turn = dict(id=7, text='Synthetic', session=dict(tool=tool, model='synthetic', effort='medium', cli_session_id=resume, kind=kind))
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
    monkeypatch.setenv('CPLANE_FENCE_COMMAND', 'homelab-fence')
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
    launch.assert_called_once_with(['homelab-fence', 'session-cleanup', '7'], check=True,
                                   stdout=subprocess.DEVNULL)
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
    store.feature_stage(other, 'grilling')
    store.feature_stage(outside, 'grilling')
    for target, allowed in [(own, True), (other, kind != 'feature'), (outside, kind == 'orchestrator')]:
        result = call(workshops[kind], 'add_slice', **slice_args(target))
        if not allowed:
            refused(result, 'can only write')
            continue
        created = value(result)
        assert created['id'] == f'{target}-S1'
        item = next(s for s in store.load()['slices'] if s['id'] == created['id'])
        assert item['feature_id'] == target
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
        store.connection.execute('UPDATE cplane_features SET stage = %s, position = 99 WHERE id = %s', (stage, own))
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
], ids=['characters', 'utf8-bytes', 'empty', 'nul', 'missing-section', 'fenced-section'])
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
    assert main(['edit', first['id'], '--no-feature', 'One-off']) == 1
    assert store.stored_brief(first['id']) == BRIEF
    read = value(call(workshops['feature'], 'slices', feature=own))
    assert read[0]['brief_text'] == BRIEF
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


def test_add_slice_full_byte_bound_over_socket(context, tmp_path, socket_owner):
    store, _, chats, own, _, _, documents = context
    repository(store)
    # Maximal JSON expansion of ASCII controls still fits the transport.
    brief = '## Do not\n' + '\x01' * (65536 - len('## Do not\n'))
    run = tmp_path / 'max-brief'
    run.mkdir()
    with WorkshopServer(run, store, chats['feature']['id'], documents) as server:
        request = dict(jsonrpc='2.0', id=1, method='tools/call',
                       params=dict(name='add_slice', arguments={**slice_args(own), 'brief': brief}))
        result = subprocess.run(['python3', str(run / 'workshop_mcp.py')],
                                input=json.dumps(request) + '\n', capture_output=True,
                                text=True, check=True, timeout=10)
        response = json.loads(result.stdout)
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


@pytest.mark.parametrize('kind', ['feature', 'project', 'orchestrator'])
def test_install_slice_scope_limits_and_audit(context, slice_data, monkeypatch, kind):
    from copy import deepcopy
    from cplane.installation import pending
    store, workshops, chats, own, other, outside, _ = context
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', 'example/repo')
    data = dict(version=1, slices=[])
    for n, feature in enumerate((own, other, outside)):
        item = deepcopy(slice_data)
        item.update(id=f'example/S{n}', feature_id=feature, state='awaiting handover',
                    attention=dict(kind='node-step', body='Install the reviewed change',
                                   since='2026-01-01T00:00:00+00:00', answer=None, approved=False))
        data['slices'].append(item)
    store.save(data)
    for item, allowed in zip(data['slices'], (True, kind != 'feature', kind == 'orchestrator')):
        result = call(workshops[kind], 'install_slice', slice=item['id'])
        if not allowed:
            refused(result, 'can only write')
            continue
        value(result)
        saved = store.load()
        target = next(s for s in saved['slices'] if s['id'] == item['id'])
        request = next(e for e in target['log'] if e['event'].startswith('install proposed: '))
        assert request['actor'] == f"chat:{chats[kind]['id']}"
        assert target['log'][-1]['event'] == 'install_slice'
        refused(call(workshops[kind], 'install_slice', slice=item['id']), 'already has a chat')
        assert not list(pending(saved))
    with store.locked():
        rows = list(store.connection.execute("SELECT chat FROM cplane_workshop_writes WHERE operation = 'install_slice'"))
        assert len(rows) == (1 if kind == 'feature' else 2 if kind == 'project' else 3)


def test_install_slice_refusals_and_owner_pending_request(context, slice_data, monkeypatch):
    from cplane.installation import request_change, pending
    store, workshops, _, own, _, _, _ = context
    slice_data.update(feature_id=own)
    data = dict(version=1, slices=[slice_data])
    store.save(data)
    refused(call(workshops['feature'], 'install_slice', slice=slice_data['id']), 'not installable')
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', 'example/repo')
    refused(call(workshops['feature'], 'install_slice', slice=slice_data['id']), 'open node-step')
    for kind, answer in [('question', None), ('node-step', 'Done')]:
        slice_data['attention'] = dict(kind=kind, body='Do it', since='2026-01-01T00:00:00Z', answer=answer, approved=False)
        store.save(data)
        refused(call(workshops['feature'], 'install_slice', slice=slice_data['id']), 'open node-step')
    slice_data['attention']['answer'] = None
    store.save(data)
    value(call(workshops['feature'], 'install_slice', slice=slice_data['id']))
    saved = store.load()
    request_change('owner')(saved['slices'][0], saved, '2026-11-08T00:00:00Z')
    assert len(list(pending(saved))) == 1
    refused(call(workshops['feature'], 'install_slice', slice='missing'), 'linked')
    slice_data.pop('feature_id')
    store.save(data)
    refused(call(workshops['feature'], 'install_slice', slice=slice_data['id']), 'linked')


def test_install_failure_cannot_be_answered_by_chat(context, slice_data):
    store, workshops, _, own, _, _, _ = context
    slice_data.update(feature_id=own, state='escalated', attention=dict(kind='escalation',
        body='Install failed; inspect the root install unit', since='2026-01-01T00:00:00Z', answer=None, approved=False))
    store.save(dict(version=1, slices=[slice_data]))
    refused(call(workshops['feature'], 'answer_slice', slice=slice_data['id'], text='Retry'), 'belong to the owner')


def test_review_sections_keep_original_text_and_numbering(context):
    store, workshops, _, own, _, _, _ = context
    w = workshops['feature']
    refused(call(w, 'save_section', feature=own, section='Testing review 2', text='Review'), 'next numbered')
    value(call(w, 'save_section', feature=own, section='Testing review 1', text='Review'))
    refused(call(w, 'save_section', feature=own, section='Testing review 1', text='Replacement'), 'cannot be overwritten')
    value(call(w, 'save_section', feature=own, section='Testing review 1', text='Review\n\nIdeas from testing\nAn idea'))
    value(call(w, 'save_section', feature=own, section='Testing review 2', text='Only the correction changed.'))
    assert len(store.feature_show(own)['sections']) == 2


def test_install_requests_serialize_and_roll_back(context, slice_data, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from cplane.installation import pending
    store, _, chats, own, _, _, documents = context
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', 'example/repo')
    slice_data.update(feature_id=own, attention=dict(kind='node-step', body='Install',
        since='2026-01-01T00:00:00Z', answer=None, approved=False))
    store.save(dict(version=1, slices=[slice_data]))
    failing = Workshop(store, chats['feature']['id'], documents)
    original = store.save
    monkeypatch.setattr(store, 'save', Mock(side_effect=RuntimeError('synthetic write failure')))
    refused(call(failing, 'install_slice', slice=slice_data['id']), 'Workshop unavailable')
    monkeypatch.setattr(store, 'save', original)
    assert not list(pending(store.load()))
    barrier = Barrier(2)
    def request():
        backend = PostgresStore(store._url)
        workshop = Workshop(backend, chats['feature']['id'], documents)
        barrier.wait(timeout=5)
        return call(workshop, 'install_slice', slice=slice_data['id'])
    with ThreadPoolExecutor(2) as pool:
        results = [f.result(timeout=10) for f in [pool.submit(request), pool.submit(request)]]
    assert sum(not r['isError'] for r in results) == 1
    saved = store.load()
    assert not list(pending(saved))
    assert sum(e['event'].startswith('install proposed: ') for e in saved['slices'][0]['log']) == 1
    with store.locked():
        assert store.connection.execute("SELECT count(*) FROM cplane_workshop_writes WHERE operation = 'install_slice'").fetchone()[0] == 1


def test_install_refuses_when_another_request_is_pending(context, slice_data, monkeypatch):
    from copy import deepcopy
    from cplane.installation import request_change
    store, workshops, _, own, _, _, _ = context
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', 'example/repo')
    slice_data.update(feature_id=own, attention=dict(kind='node-step', body='Install',
        since='2026-01-01T00:00:00Z', answer=None, approved=False))
    other = deepcopy(slice_data)
    other['id'] = 'example/other'
    data = dict(version=1, slices=[slice_data, other])
    request_change('owner')(other, data, '2026-11-08T00:00:00Z')
    store.save(data)
    refused(call(workshops['feature'], 'install_slice', slice=slice_data['id']), 'already requested or running')


def test_review_read_has_install_evidence_and_handovers(context, slice_data, monkeypatch):
    from cplane.installation import REQUEST, FINISHED
    store, workshops, _, own, _, _, _ = context
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', 'example/repo')
    slice_data.update(feature_id=own, state='in review', log=[
        dict(at='2026-11-08T00:00:00Z', actor='chat:1', event=REQUEST + 'a'*32),
        dict(at='2026-11-08T00:01:00Z', actor='runner', event='Installed ' + 'b'*40),
        dict(at='2026-11-08T00:01:00Z', actor='runner', event=FINISHED + 'a'*32)])
    with store.mutation():
        store.chat_handover(slice_data, 'Synthetic handover with checks and results')
        store.save(dict(version=1, slices=[slice_data]))
    read = value(call(workshops['feature'], 'slices', feature=own))[0]
    assert read['installation'] == dict(installable=True, status='finished')
    assert any('Synthetic handover' in text for text in read['handovers'])
    assert 'log' not in read and 'attention' not in read


def test_decision_follows_current_project_after_transfer(context):
    store, workshops, chats, own, *_, documents = context
    moved = store.feature_move(own, 'LAB')
    project = store.create_project_chat('LAB')
    identifier = value(call(workshops['feature'], 'raise_decision', text='Transferred question', recommendation='A'))['decision']
    assert store.notices()[-1][1]['holder'] == project['id']
    refused(call(workshops['project'], 'answer_decision', decision=identifier, text='Old project'), 'holding chat')
    value(call(Workshop(store, project['id'], documents), 'answer_decision', decision=identifier, text='Recorded A'))
    assert store.chat_show(chats['feature']['id'])['feature'] == moved['id']
    assert 'Recorded A' in store.session_messages('factory', chats['feature']['id'])[-1]['text']
