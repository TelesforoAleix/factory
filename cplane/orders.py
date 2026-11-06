"""Collect confirmed owner orders. Called with the runner's state lock held."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from . import state
from .cli import change_for
from .executors import atomic_json
from .times import now

ACTIONS = {'start', 'slot', 'pause', 'resume', 'answer', 'approve', 'orchestrator'}
STATES = set(state.SCHEMA['$defs']['slice']['properties']['state']['enum'])
KINDS = {'question', 'escalation', 'merge', 'node-step', 'owner-check'}


class HTTPClient:
    def request(self, url, body=None):
        request = Request(url, data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=10) as response:
            return json.load(response) if body is None else None


class Tmux:
    def __init__(self, launch=subprocess.run):
        self.launch = launch

    def call(self, *args):
        try:
            return self.launch(['tmux', *args], capture_output=True, text=True)
        except (OSError, subprocess.SubprocessError):
            raise state.StateError('tmux launch failed') from None

    def open(self, target, folder, task):
        exists = self.call('has-session', '-t', '=frontline').returncode == 0
        if exists:
            windows = self.call('list-windows', '-t', '=frontline', '-F', '#{window_name}')
            if windows.returncode:
                raise state.StateError('cannot list frontline windows')
            if target in windows.stdout.splitlines():
                raise state.StateError('already open')
        prompt = (f'Start as this repository\'s orchestrator ({target}). '
                  'Do the owner\'s task quoted verbatim below and nothing more. '
                  'Put anything needing the owner on the concerned slice as a cplane attention.\n'
                  'Owner\'s task (verbatim):\n' + task)
        # Multiple command arguments make tmux exec directly, bypassing its shell.
        args = (['new-window', '-t', '=frontline'] if exists else
                ['new-session', '-s', 'frontline'])
        result = self.call(*args, '-d', '-n', target, '-c', str(folder), 'claude', '--', prompt)
        if result.returncode:
            # tmux errors can echo its command (and hence private order text).
            raise state.StateError('cannot open frontline window')


def timestamp(value):
    return (isinstance(value, str) and state.offset_timestamp(value))


def validate(order):
    if not isinstance(order, dict) or set(order) != {'id', 'created', 'action', 'slice', 'argument', 'expect'}:
        raise ValueError('malformed order fields')
    if not isinstance(order['id'], str) or not order['id']:
        raise ValueError('invalid order id')
    if not isinstance(order['action'], str) or order['action'] not in ACTIONS:
        raise ValueError('unknown action')
    if not timestamp(order['created']):
        raise ValueError('invalid created timestamp')
    action, argument, target = order['action'], order['argument'], order['slice']
    if not isinstance(target, str) or not target:
        raise ValueError('invalid target')
    if action != 'orchestrator' and not re.fullmatch(r'[^/\s]+/[^/\s]+', target):
        raise ValueError('invalid slice id')
    if argument is not None and not isinstance(argument, str):
        raise ValueError('invalid argument')
    if action in {'slot', 'answer', 'orchestrator'}:
        if not isinstance(argument, str):
            raise ValueError('argument required')
    elif argument is not None:
        raise ValueError('unexpected argument')
    if action in {'answer', 'orchestrator'} and len(argument) > 4000:
        raise ValueError('argument exceeds 4000 characters')
    expect = order['expect']
    if action == 'orchestrator':
        if expect is not None:
            raise ValueError('orchestrator expect must be null')
        return
    if (not isinstance(expect, dict) or set(expect) != {'state', 'paused', 'attention'}
            or not isinstance(expect['state'], str) or expect['state'] not in STATES
            or not isinstance(expect['paused'], bool)):
        raise ValueError('invalid expectation')
    attention = expect['attention']
    if attention is not None and (
            not isinstance(attention, dict) or set(attention) != {'kind', 'since'}
            or not isinstance(attention['kind'], str) or attention['kind'] not in KINDS
            or not timestamp(attention['since'])):
        raise ValueError('invalid attention expectation')


def mismatch(item, expect):
    if item is None:
        return 'slice no longer exists'
    if item['state'] != expect['state']:
        return 'state changed'
    if item['paused'] != expect['paused']:
        return 'pause changed'
    attention = item['attention']
    current = None if attention is None else {key: attention[key] for key in ('kind', 'since')}
    if current != expect['attention']:
        return 'attention changed or cleared from the orchestrator'
    return None


class Collector:
    def __init__(self, *, client=None, tmux=None):
        self.client = client or HTTPClient()
        self.tmux = tmux or Tmux()

    def record(self, path, order_id, result):
        atomic_json(path, {'id': order_id, 'result': result})
        # The receipt must survive a restart before any effect or acknowledgement.
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def dispatch(self, runner, order):
        validate(order)
        data = state.load(runner.path)
        target, action = order['slice'], order['action']
        if action == 'orchestrator':
            names = {item['repo'].split('/')[-1] for item in data['slices']}
            if target == 'development':
                folder = runner.path.parent
            elif (target in names and target not in {'.', '..'}
                  and not any(char in target for char in ('/', '\\', '\0'))):
                folder = (runner.repos / target).resolve()
                if not folder.is_relative_to(runner.repos):
                    raise ValueError('repository folder is outside CPLANE_REPOS')
            else:
                raise ValueError('unknown orchestrator target')
            if not folder.is_dir():
                raise ValueError('repository folder does not exist')
            self.tmux.open(target, folder, order['argument'])
            return {'outcome': 'done', 'detail': 'opened'}
        item = next((s for s in data['slices'] if s['id'] == target), None)
        detail = mismatch(item, order['expect'])
        if detail:
            notice = {'at': now().isoformat(), 'id': target, 'event': 'dropped',
                      'text': f'Dropped order {action} {target}: {detail}'}
            with Path(str(runner.path) + '.outbox.jsonl').open('a') as stream:
                stream.write(json.dumps(notice) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            return {'outcome': 'dropped', 'detail': detail}

        def change(item, data, at):
            notice, warning = change_for(action, order['argument'])(item, data, at)
            # CLI notices include answer and slot text; order notices never do.
            return (f'Order {action} {target}: done' if notice else None), warning

        state.update_locked(runner.path, target, action, 'frontline', change)
        return {'outcome': 'done', 'detail': 'recorded'}

    def collect(self, runner):
        """Return whether collection wrote state/outbox, for the pass's git commit."""
        base = os.environ.get('CPLANE_ORDERS_URL')
        if base is None:
            try:
                base = (runner.runs.parent.parent / 'orders-url').read_text().strip()
            except FileNotFoundError:
                return False
            except OSError:
                print('orders: configuration unavailable', file=sys.stderr)
                return False
        if not base:
            return False
        try:
            parsed = urlsplit(base)
            if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.query or parsed.fragment:
                raise ValueError('invalid URL')
            payload = self.client.request(base.rstrip('/') + '/orders')
            if not isinstance(payload, dict) or not isinstance(payload.get('orders'), list):
                raise ValueError('invalid response')
        except (OSError, ValueError):
            # Exceptions from HTTP can contain the private endpoint address.
            print('orders: collection unavailable', file=sys.stderr)
            return False
        folder = runner.runs / 'orders'
        folder.mkdir(parents=True, exist_ok=True)
        outbox = Path(str(runner.path) + '.outbox.jsonl')
        before = (runner.path.read_bytes(), outbox.read_bytes() if outbox.exists() else None)
        for order in payload['orders']:
            order_id = order.get('id') if isinstance(order, dict) else None
            if order_id is None or order_id == '':
                print('orders: skipped malformed order without id', file=sys.stderr)
                continue
            if not isinstance(order_id, str):
                order_id = json.dumps(order_id, sort_keys=True)
            receipt = folder / (hashlib.sha256(order_id.encode()).hexdigest() + '.json')
            if receipt.exists():
                result = json.loads(receipt.read_text())['result']
            else:
                # Fail closed on an interrupted dispatch: never execute it twice, even
                # if the process dies between an external effect and the final receipt.
                result = {'outcome': 'failed', 'detail': 'dispatch interrupted; inspect local state before retrying'}
                self.record(receipt, order_id, result)
                try:
                    result = self.dispatch(runner, order)
                except Exception as error:
                    # Expected command errors do not include argument text. Redact it
                    # defensively, including errors raised by an injected launcher.
                    detail = str(error)
                    argument = order.get('argument')
                    if isinstance(argument, str) and argument:
                        detail = detail.replace(argument, '[argument]')
                    result = {'outcome': 'failed', 'detail': detail[:700] or 'command failed'}
                self.record(receipt, order_id, result)
            action = order.get('action')
            target = order.get('slice')
            context = (f' {action} {target}' if isinstance(action, str) and action in ACTIONS
                       and isinstance(target, str) and re.fullmatch(r'[A-Za-z0-9_./-]+', target) else '')
            print(f'orders: {order_id!r}{context} {result["outcome"]}', file=sys.stderr)
            try:
                self.client.request(base.rstrip('/') + '/orders/' + quote(order_id, safe='') + '/ack', result)
            except (OSError, ValueError):
                print(f'orders: {order_id!r} acknowledgement unavailable', file=sys.stderr)
        return before != (runner.path.read_bytes(), outbox.read_bytes() if outbox.exists() else None)
