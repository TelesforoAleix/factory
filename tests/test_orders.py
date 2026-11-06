import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from cplane import state
from cplane.orders import Collector, HTTPClient, Tmux
from cplane.runner import Runner
from conftest import attention

NOW = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)


def order(item, action='pause', argument=None, **fields):
    a = item['attention']
    return dict(id='order-1', created=NOW.isoformat(), action=action, slice=item['id'],
                argument=argument, expect=dict(state=item['state'], paused=item['paused'],
                attention=None if a is None else {key: a[key] for key in ('kind', 'since')}), **fields)


class Client:
    def __init__(self, orders):
        self.orders = orders
        self.acks = []
        self.fail_ack = False

    def request(self, url, body=None):
        if body is None:
            return {'orders': self.orders}
        self.acks.append((url, copy.deepcopy(body)))
        if self.fail_ack:
            raise TimeoutError('private transport error')


@pytest.fixture
def build(make_state, tmp_path, monkeypatch):
    monkeypatch.setenv('CPLANE_ORDERS_URL', 'http://127.0.0.1:1')
    def make(item, orders):
        path = make_state([item])
        client = Client(orders)
        tmux = Mock()
        runner = Runner(path, orders=Collector(client=client, tmux=tmux),
                        git=Mock(), clock=lambda: NOW, runs=tmp_path / 'app/runs',
                        repos=tmp_path / 'repos', codex_reader=lambda: None,
                        claude_reader=lambda: None)
        return runner, client, tmux
    return make


def item(r):
    return state.load(r.path)['slices'][0]


@pytest.mark.parametrize('action,argument,field,expected', [
    ('start', None, 'slot', True),
    ('slot', '2026-10-23T09:30:00+02:00', 'slot', '2026-10-23T09:30:00+02:00'),
    ('pause', None, 'paused', True), ('resume', None, 'paused', False),
    ('answer', 'Owner\'s own words\nsecond line', 'attention', 'Owner\'s own words\nsecond line'),
    ('approve', None, 'attention', True),
])
def test_commands(build, slice_data, action, argument, field, expected, capsys):
    if action == 'resume':
        slice_data['paused'] = True
    if action in {'approve', 'answer'}:
        slice_data['attention'] = attention('merge' if action == 'approve' else 'question')
        if action == 'approve':
            slice_data['session'] = dict(tool='codex', id='external', folder='/tmp/repo')
            slice_data['attention']['review'] = dict(verdict='Ready', at=NOW.isoformat(), actor='planner')
    r, client, _ = build(slice_data, [order(slice_data, action, argument)])
    r.run()
    value = item(r)[field]
    if action == 'start':
        assert datetime.fromisoformat(value) <= datetime.now().astimezone()
    elif action in {'answer', 'approve'}:
        assert value['answer' if action == 'answer' else 'approved'] == expected
    else:
        assert value == expected
    assert item(r)['log'][0]['actor'] == 'frontline'
    assert client.acks[0][1]['outcome'] == 'done'
    if argument:
        assert argument not in capsys.readouterr().err
        assert argument not in json.dumps(item(r)['log'])
        assert argument not in Path(str(r.path) + '.outbox.jsonl').read_text()


@pytest.mark.parametrize('change,detail', [
    (lambda s: s.update(state='planned'), 'state changed'),
    (lambda s: s.update(paused=True), 'pause changed'),
    (lambda s: s.update(attention=attention('question')), 'attention changed'),
    (lambda s: s.update(id='other/W2'), 'no longer exists'),
])
def test_mismatch(build, slice_data, change, detail):
    queued = order(slice_data)
    change(slice_data)
    r, client, _ = build(slice_data, [queued])
    r.run()
    assert client.acks[0][1]['outcome'] == 'dropped'
    assert detail in client.acks[0][1]['detail']
    notice = json.loads(Path(str(r.path) + '.outbox.jsonl').read_text())
    assert notice['text'].startswith('Dropped order pause voice/W1: ')
    assert not item(r)['log']


def test_attention_since_mismatch(build, slice_data):
    slice_data['attention'] = attention('question')
    queued = order(slice_data, 'answer', 'secret')
    slice_data['attention']['since'] = NOW.isoformat()
    r, client, _ = build(slice_data, [queued])
    r.run()
    assert client.acks[0][1]['outcome'] == 'dropped'
    assert item(r)['attention']['answer'] is None


def test_unreviewed_approve(build, slice_data):
    slice_data['attention'] = attention('merge')
    r, client, _ = build(slice_data, [order(slice_data, 'approve')])
    r.run()
    assert client.acks[0][1]['outcome'] == 'failed'
    assert 'review' in client.acks[0][1]['detail']
    assert not item(r)['attention']['approved']


def test_lost_ack_restarts_and_reacks_without_running(build, slice_data):
    r, client, _ = build(slice_data, [order(slice_data)])
    client.fail_ack = True
    r.run()
    before = r.path.read_bytes()
    receipt = next((r.runs / 'orders').glob('*.json'))
    assert json.loads(receipt.read_text())['result'] == client.acks[0][1]
    assert receipt.stat().st_mode & 0o777 == 0o600
    client.fail_ack = False
    r.orders = Collector(client=client, tmux=Mock())
    r.run()
    assert client.acks[1] == client.acks[0]
    assert r.path.read_bytes() == before
    assert len(item(r)['log']) == 1


@pytest.mark.parametrize('error', [TimeoutError('hidden endpoint'), URLError('hidden endpoint'),
                                    HTTPError('hidden endpoint', 503, 'locked', {}, None)])
def test_unavailable_pass_continues(build, slice_data, error, capsys):
    r, client, _ = build(slice_data, [])
    client.request = Mock(side_effect=error)
    r.run()
    assert r.data['slices']
    assert capsys.readouterr().err == 'orders: collection unavailable\n'
    assert client.request.call_count == 1


def test_config_file_precedence_and_off(build, slice_data, monkeypatch):
    r, client, _ = build(slice_data, [])
    monkeypatch.delenv('CPLANE_ORDERS_URL')
    client.request = Mock(return_value={'orders': []})
    r.run()
    client.request.assert_not_called()
    config = r.runs.parent.parent / 'orders-url'
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('http://127.0.0.1:2\n')
    r.run()
    client.request.assert_called_with('http://127.0.0.1:2/orders')
    monkeypatch.setenv('CPLANE_ORDERS_URL', 'http://127.0.0.1:3')
    r.run()
    client.request.assert_called_with('http://127.0.0.1:3/orders')
    client.request.reset_mock()
    monkeypatch.setenv('CPLANE_ORDERS_URL', '')
    r.run()
    client.request.assert_not_called()


@pytest.mark.parametrize('target', ['repo', 'development'])
def test_orchestrator(build, slice_data, target):
    queued = order(slice_data, 'orchestrator', 'Do the task')
    queued.update(slice=target, expect=None)
    r, client, tmux = build(slice_data, [queued])
    (r.repos / 'repo').mkdir(parents=True)
    r.run()
    assert client.acks[0][1]['outcome'] == 'done'
    tmux.open.assert_called_once_with(target, r.path.parent if target == 'development' else r.repos / 'repo', 'Do the task')
    assert not item(r)['log']
    assert r.git.commit.call_count == 0


@pytest.mark.parametrize('target', ['unknown', '../repo', 'example/repo', '-option', 'repo'])
def test_orchestrator_invalid_or_missing(build, slice_data, target):
    queued = order(slice_data, 'orchestrator', 'task')
    queued.update(slice=target, expect=None)
    r, client, tmux = build(slice_data, [queued])
    r.run()
    assert client.acks[0][1]['outcome'] == 'failed'
    tmux.open.assert_not_called()


@pytest.mark.parametrize('exists', [False, True])
def test_tmux_argv_safety(tmp_path, exists):
    task = '$(touch SHOULD_NOT_EXIST) `echo unsafe` "quotes" \'single\'\nsecond line'
    launch = Mock(side_effect=[subprocess.CompletedProcess([], 0 if exists else 1),
                              *([subprocess.CompletedProcess([], 0, stdout='other\n')] if exists else []),
                              subprocess.CompletedProcess([], 0)])
    Tmux(launch).open('repo', tmp_path, task)
    args = launch.call_args.args[0]
    assert args[0] == 'tmux'
    assert args[-3:-1] == ['claude', '--']
    assert args[-1].endswith(task)
    assert task not in args[:-1]
    assert 'shell' not in launch.call_args.kwargs
    assert args[1] == ('new-window' if exists else 'new-session')
    assert not (tmp_path / 'SHOULD_NOT_EXIST').exists()


def test_tmux_already_open(build, slice_data):
    queued = order(slice_data, 'orchestrator', 'task')
    queued.update(slice='development', expect=None)
    r, client, _ = build(slice_data, [queued])
    launch = Mock(side_effect=[subprocess.CompletedProcess([], 0),
                              subprocess.CompletedProcess([], 0, stdout='development\n')])
    r.orders.tmux = Tmux(launch)
    r.run()
    assert client.acks[0][1] == {'outcome': 'failed', 'detail': 'already open'}
    assert launch.call_count == 2


@pytest.mark.parametrize('fields', [
    {'action': 'unslot'}, {'argument': 123}, {'created': None}, {'expect': None},
    {'expect': {'state': 'ready', 'paused': 0, 'attention': None}},
    {'action': 'answer', 'argument': 'x' * 4001},
    {'action': 'orchestrator', 'argument': 'x' * 4001, 'expect': None},
    {'action': 'answer', 'argument': None}, {'slice': 'bad'}, {'extra': True},
])
def test_malformed(build, slice_data, fields):
    queued = order(slice_data)
    queued.update(fields)
    r, client, _ = build(slice_data, [queued])
    r.run()
    assert client.acks[0][1]['outcome'] == 'failed'
    assert not item(r)['log']


def test_no_id_skipped(build, slice_data, capsys):
    r, client, _ = build(slice_data, [None, {'argument': 'private answer'}])
    r.run()
    assert not client.acks
    assert 'private answer' not in capsys.readouterr().err


def test_order_sequence_checked_after_each_mutation(build, slice_data):
    first = order(slice_data)
    second = dict(first, id='order-2', action='resume')
    r, client, _ = build(slice_data, [first, second])
    r.run()
    assert [ack[1]['outcome'] for ack in client.acks] == ['done', 'dropped']


def test_http_transport(monkeypatch):
    response = Mock()
    response.read.return_value = b'{"orders": []}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    open_url = Mock(return_value=response)
    monkeypatch.setattr('cplane.orders.urlopen', open_url)
    client = HTTPClient()
    assert client.request('http://127.0.0.1:1/orders') == {'orders': []}
    assert open_url.call_args.kwargs['timeout'] == 10
    client.request('http://127.0.0.1:1/orders/a/ack', {'outcome': 'done', 'detail': 'recorded'})
    request = open_url.call_args.args[0]
    assert request.get_method() == 'POST'
    assert json.loads(request.data)['outcome'] == 'done'


def test_interrupted_dispatch_never_reexecutes(build, slice_data, monkeypatch):
    r, client, _ = build(slice_data, [order(slice_data)])
    dispatch = Mock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(r.orders, 'dispatch', dispatch)
    with pytest.raises(KeyboardInterrupt):
        r.run()
    assert not client.acks
    dispatch.reset_mock()
    r.run()
    dispatch.assert_not_called()
    assert client.acks[0][1]['outcome'] == 'failed'
    assert 'interrupted' in client.acks[0][1]['detail']


def test_orchestrator_lost_ack_is_not_reopened(build, slice_data):
    queued = order(slice_data, 'orchestrator', 'private task')
    queued.update(slice='development', expect=None)
    r, client, tmux = build(slice_data, [queued])
    client.fail_ack = True
    r.run()
    r.run()
    assert tmux.open.call_count == 1
    assert client.acks[0][1] == client.acks[1][1]


@pytest.mark.parametrize('action', ['answer', 'orchestrator'])
def test_4000_characters_allowed(build, slice_data, action):
    if action == 'answer':
        slice_data['attention'] = attention('question')
    queued = order(slice_data, action, 'x' * 4000)
    if action == 'orchestrator':
        queued.update(slice='development', expect=None)
    r, client, _ = build(slice_data, [queued])
    r.run()
    assert client.acks[0][1]['outcome'] == 'done'


def test_url_and_task_never_logged_on_launcher_failure(build, slice_data, capsys):
    secret = '$(something) `else` "quoted"\nprivate task'
    queued = order(slice_data, 'orchestrator', secret)
    queued.update(slice='development', expect=None)
    r, client, _ = build(slice_data, [queued])
    launch = Mock(side_effect=subprocess.CalledProcessError(1, ['tmux', 'claude', secret]))
    r.orders.tmux = Tmux(launch)
    r.run()
    assert client.acks[0][1]['outcome'] == 'failed'
    output = capsys.readouterr().err
    assert secret not in output
    assert '127.0.0.1' not in output
    assert not Path(str(r.path) + '.outbox.jsonl').exists()


def test_no_saving_failure_ack_before_receipt(build, slice_data, monkeypatch):
    r, client, tmux = build(slice_data, [order(slice_data)])
    monkeypatch.setattr(r.orders, 'record', Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError):
        r.run()
    assert not client.acks
    assert not item(r)['paused']
    tmux.open.assert_not_called()


def test_malformed_numeric_id_can_be_acknowledged(build, slice_data):
    queued = order(slice_data)
    queued['id'] = 123
    r, client, _ = build(slice_data, [queued])
    r.run()
    assert client.acks[0][0].endswith('/orders/123/ack')
    assert client.acks[0][1]['outcome'] == 'failed'


def test_orchestrator_symlink_cannot_escape_repos(build, slice_data, tmp_path):
    queued = order(slice_data, 'orchestrator', 'task')
    queued.update(slice='repo', expect=None)
    r, client, tmux = build(slice_data, [queued])
    r.repos.mkdir()
    (r.repos / 'repo').symlink_to(tmp_path, target_is_directory=True)
    r.run()
    assert client.acks[0][1]['outcome'] == 'failed'
    tmux.open.assert_not_called()
