"""Synthetic session stores, archives and fenced launches; no real model calls."""
import io
import os
from pathlib import Path
import subprocess
import tarfile
from unittest.mock import Mock

import pytest

from cplane import sessions
from factory_ui import create_app
from test_stores import pg_store


@pytest.fixture(autouse=True)
def synthetic_root(monkeypatch):
    monkeypatch.setattr('cplane.fence.ROOT_UID', os.getuid())


def create(store, area='factory'):
    return store.create_session(area, 'Test', 'codex', 'synthetic-model', [])


def test_queue_limit_order_and_failure(pg_store):
    ids = [create(pg_store) for _ in range(3)]
    for sid in ids:
        pg_store.session_messages('factory', sid, 'first')
    pg_store.session_messages('factory', ids[0], 'second')
    a, b = pg_store.claim_session_turn(), pg_store.claim_session_turn()
    assert a['session']['id'] != b['session']['id']
    assert pg_store.claim_session_turn() is None
    pg_store.finish_session_turn(a, 'reply', 'synthetic-resume')
    c = pg_store.claim_session_turn()
    assert c['session']['id'] == ids[2]
    pg_store.finish_session_turn(b, 'failed', failed=True)
    d = pg_store.claim_session_turn()
    assert d['session']['id'] == ids[0]
    assert d['session']['cli_session_id'] == 'synthetic-resume'
    assert d['text'] == 'second'
    assert len(pg_store.interrupted_session_turns()) == 2
    with pytest.raises(Exception):
        pg_store.session_messages('factory', ids[1], 'no retry')


def test_routes_guard_and_area(pg_store):
    client = create_app(pg_store).test_client()
    path = '/api/homelab/sessions'
    data = dict(title='Test', tool='codex', model='synthetic', repositories=[])
    assert client.post(path, json=data).status_code == 403
    response = client.post(path, json=data, headers={'X-Factory-UI': '1'})
    assert response.status_code == 201
    sid = response.json['id']
    assert 'cli_session_id' not in client.get(path).json[0]
    assert client.get('/api/factory/sessions').json == []
    messages = path + f'/{sid}/messages'
    assert client.post(messages, json={'text': 'hello'}).status_code == 403
    assert client.post(messages, json={'text': 'hello'}, headers={'X-Factory-UI': '1'}).json[0]['status'] == 'queued'
    assert client.get(f'/api/factory/sessions/{sid}/messages').status_code == 400
    assert client.post(path, json={**data, 'repositories': ['a/repo', 'b/repo']}, headers={'X-Factory-UI': '1'}).status_code == 400


def test_plain_export_and_planted_link(tmp_path):
    source = tmp_path / 'source'
    source.mkdir(mode=0o700)
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    (source / 'brief.md').write_text('synthetic')
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-qm', 'fixture'], check=True)
    destination = tmp_path / 'export'
    sessions.export_tree(source, destination)
    assert (destination / 'brief.md').read_text() == 'synthetic'
    assert not list(destination.rglob('.git'))
    outside = tmp_path / 'outside'
    outside.mkdir()
    planted = tmp_path / 'planted'
    planted.symlink_to(outside, target_is_directory=True)
    with pytest.raises(FileExistsError):
        sessions.export_tree(source, planted)
    assert list(outside.iterdir()) == []
    (source / 'link').symlink_to('/etc/passwd')
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Test', '-c', 'user.email=test@example.test', 'commit', '-qm', 'link'], check=True)
    linked_export = tmp_path / 'linked-export'
    sessions.export_tree(source, linked_export)
    assert (linked_export / 'brief.md').read_text() == 'synthetic'
    assert not os.path.lexists(linked_export / 'link')


@pytest.mark.parametrize('link_type', [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_export_omits_archive_links(tmp_path, monkeypatch, link_type):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        regular = tarfile.TarInfo('brief.md')
        regular.size = 9
        archive.addfile(regular, io.BytesIO(b'synthetic'))
        link = tarfile.TarInfo('.claude/skills')
        link.type = link_type
        link.linkname = 'brief.md'
        archive.addfile(link)
    monkeypatch.setattr(sessions.subprocess, 'run', Mock(return_value=
                        subprocess.CompletedProcess([], 0, buffer.getvalue())))
    destination = tmp_path / 'export'
    sessions.export_tree(tmp_path, destination)
    assert (destination / 'brief.md').read_text() == 'synthetic'
    assert not os.path.lexists(destination / '.claude/skills')
    assert not (destination / '.claude').exists()


@pytest.mark.parametrize('name,kind', [('/absolute', tarfile.REGTYPE),
                                     ('../escape', tarfile.REGTYPE),
                                     ('.git/config', tarfile.REGTYPE),
                                     ('pipe', tarfile.FIFOTYPE),
                                     ('/absolute-link', tarfile.SYMTYPE),
                                     ('../escape-link', tarfile.LNKTYPE)])
def test_export_still_refuses_unsafe_entries(tmp_path, monkeypatch, name, kind):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = 'brief.md'
        archive.addfile(member)
    monkeypatch.setattr(sessions.subprocess, 'run', Mock(return_value=
                        subprocess.CompletedProcess([], 0, buffer.getvalue())))
    destination = tmp_path / 'export'
    with pytest.raises(sessions.StateError, match='unsafe entries'):
        sessions.export_tree(tmp_path, destination)
    assert not destination.exists()


@pytest.mark.parametrize('repository', ['../outside', 'owner/../../outside',
                                       '/absolute/repo', 'owner/repo/extra', '', None])
@pytest.mark.parametrize('resume', [None, 'saved-id'])
def test_turn_rejects_invalid_stored_repository(tmp_path, monkeypatch, repository, resume):
    monkeypatch.setattr(sessions, 'WORK_ROOT', tmp_path)
    export = Mock(side_effect=AssertionError('export must not run'))
    launch = Mock(side_effect=AssertionError('CLI must not run'))
    monkeypatch.setattr(sessions, 'export_tree', export)
    monkeypatch.setattr(sessions.subprocess, 'run', launch)
    turn = dict(id=7, text='synthetic', session=dict(
        id=1, cli_session_id=resume, repositories=[repository]))
    store = Mock()
    sessions.execute_turn(turn, store)
    store.finish_session_turn.assert_called_once_with(
        turn, 'Turn failed. Create a new session.', failed=True)
    export.assert_not_called()
    launch.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_resume_rejects_link_without_host_write(tmp_path, monkeypatch):
    root = tmp_path / 'work'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (root / 'session-1').symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(sessions, 'WORK_ROOT', root)
    with pytest.raises(Exception, match='Workspace unavailable'):
        sessions.workspace(dict(id=1, cli_session_id='synthetic', repositories=[]))
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('resume', [None, 'saved-id'])
def test_one_message_and_resume(tool, resume, tmp_path):
    turn = dict(id=7, text='literal $(false)', session=dict(tool=tool, model='synthetic', cli_session_id=resume))
    args = sessions.turn_command(turn, tmp_path, [tmp_path / 'repos/name'], tmp_path / 'run')
    assert args[:2] == ['factory-cli', 'run']
    assert args[-1] == turn['text']
    assert args[args.index('--read-only-path') + 1] == str(tmp_path / 'repos/name')
    assert (('--resume' if tool == 'claude' else 'resume') in args) == bool(resume)
    assert ('saved-id' in args) == bool(resume)
    if tool == 'codex':
        assert args[args.index('-c') + 1] == 'model_reasoning_effort="medium"'


def test_timeout_short_failure_and_cleanup_uncertainty(tmp_path, monkeypatch):
    store = Mock()
    turn = dict(id=5, text='synthetic', session=dict(tool='codex', model='synthetic', cli_session_id=None))
    monkeypatch.setattr(sessions, 'workspace', lambda _: (tmp_path, []))
    monkeypatch.setattr(sessions, 'RUNS', tmp_path)
    monkeypatch.setattr(sessions.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 124, '', 'private detail'))
    sessions.execute_turn(turn, store)
    assert store.finish_session_turn.call_args.args[1] == 'Turn timed out after 20 minutes.'
    store.reset_mock()
    turn['id'] = 6
    monkeypatch.setattr(sessions.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 125, '', ''))
    with pytest.raises(sessions.CleanupError):
        sessions.execute_turn(turn, store)
    store.finish_session_turn.assert_not_called()


def test_web_has_no_execution_path():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'factory_ui/__init__.py').read_text()
    assert 'subprocess' not in source and 'cplane.sessions' not in source
    service = (root / 'node/systemd/factory-ui.service').read_text()
    assert 'User=factory-ui' in service and 'Group=factory-ui' in service
    assert 'InaccessiblePaths=-/run/docker.sock -/var/run/docker.sock' in service
    assert 'SupplementaryGroups' not in service


def test_cli_reply_parsing():
    assert sessions.parse_reply('claude', '{"session_id":"saved-id","result":"hello"}') == ('saved-id', 'hello')
    assert sessions.parse_reply('codex', '\n'.join([
        '{"type":"thread.started","thread_id":"saved-id"}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}',
    ])) == ('saved-id', 'hello')
    with pytest.raises(Exception):
        sessions.parse_reply('claude', '{"is_error":true,"result":"private error"}')
    with pytest.raises(Exception):
        sessions.parse_reply('codex', '{"type":"thread.started","thread_id":"../unsafe"}')


def test_concurrent_claims_respect_global_capacity(pg_store):
    from concurrent.futures import ThreadPoolExecutor
    from cplane.stores import PostgresStore
    for _ in range(6):
        sid = create(pg_store)
        pg_store.session_messages('factory', sid, 'synthetic')
    with ThreadPoolExecutor(max_workers=6) as pool:
        turns = list(pool.map(lambda _: PostgresStore(pg_store._url).claim_session_turn(), range(6)))
    claimed = [turn for turn in turns if turn]
    assert len(claimed) == 2
    assert len({turn['session']['id'] for turn in claimed}) == 2
