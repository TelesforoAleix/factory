"""Install requests use the v1 mutation log; host results stay outside shared state."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

from . import state
from .executors import atomic_json

REQUEST = 'install requested: '
FINISHED = 'install finished: '
OUTPUT_LIMIT = 8192
NODE_STEPS = '\n\nNode steps:\n'


def output_tail(value, limit=OUTPUT_LIMIT):
    return value.encode('utf-8')[-limit:].decode('utf-8', errors='ignore')


def failure_text(answer):
    text = answer.get('error', 'Install failed; inspect the root install unit')
    for stream in ('stderr', 'stdout'):
        tail = output_tail(answer.get(stream, ''), 512)
        if tail:
            text += f'\n{stream}: {tail}'
    return text


def failed(runner, item, text):
    attention = item['attention']
    if attention and attention['kind'] == 'node-step' and attention['answer'] is None:
        # Preserve the original interval and job: answering by hand still closes it.
        original = attention['body']
        if install_failure(attention):
            original = original.split(NODE_STEPS, 1)[1]
        attention['body'] = text + NODE_STEPS + original
        runner.log(item, 'escalation: ' + text, True)
    else:
        runner.attention(item, 'escalation', text)


def pending(data):
    for item in data['slices']:
        done = {e['event'][len(FINISHED):] for e in item['log'] if e['event'].startswith(FINISHED)}
        for entry in item['log']:
            event = entry['event']
            if entry['actor'] == 'owner' and event.startswith(REQUEST) and event[len(REQUEST):] not in done:
                yield item, event[len(REQUEST):]


def installable(item):
    return item['repo'] in os.environ.get('CPLANE_INSTALL_REPOS', '').split(',')


def install_failure(attention):
    return bool(attention and attention['body'].startswith('Install ') and
                (attention['kind'] == 'escalation' or
                 (attention['kind'] == 'node-step' and NODE_STEPS in attention['body'])))


def chat_requested(item):
    """One chat proposal per attention interval, including legacy chat requests."""
    attention = item['attention']
    if not attention:
        return False
    from datetime import datetime
    return any(e['event'].startswith((REQUEST, 'install proposed: ')) and e['actor'].startswith('chat:')
               and datetime.fromisoformat(e['at']) >= datetime.fromisoformat(attention['since']) for e in item['log'])


def review_status(item):
    events = [e['event'] for e in item['log']]
    required = max((i for i, e in enumerate(events) if e.startswith((REQUEST, 'node-step:'))), default=-1)
    installed = max((i for i, e in enumerate(events) if e.startswith('Installed ')), default=-1)
    if install_failure(item['attention']):
        status = 'failed'
    elif any(pending(dict(slices=[item]))):
        status = 'pending'
    elif (item['attention'] and item['attention']['kind'] == 'node-step'
          and item['attention']['answer'] is None):
        status = 'required'
    elif installed > required:
        status = 'finished'
    elif required >= 0:
        status = 'unconfirmed'
    else:
        status = 'not-required'
    return dict(installable=installable(item), status=status)


def request_change(actor):
    if actor != 'owner' and not re.fullmatch(r'chat:[A-Za-z0-9_-]+', actor):
        raise state.StateError('install actor must be owner or chat:<id>')

    def change(item, data, at):
        attention = item['attention']
        if not attention or attention['kind'] != 'node-step' or attention['answer'] is not None:
            raise state.StateError('install requires an open node-step attention')
        if actor != 'owner' and install_failure(attention):
            raise state.StateError('Install failures belong to the owner')
        current = next(pending(data), None)
        if current:
            raise state.StateError('an install is already requested or running')
        if actor != 'owner' and chat_requested(item):
            raise state.StateError('This node step already has a chat install proposal')
        event = REQUEST if actor == 'owner' else 'install proposed: '
        item['log'].append({'at': at, 'actor': actor, 'event': event + uuid.uuid4().hex})
        action = 'requested' if actor == 'owner' else 'proposed'
        return f'Install {action} for {item["id"]}', None
    return change


def runs_path(path):
    base = Path(os.environ.get('CPLANE_RUNS', '/srv/factory/runs')).expanduser().resolve()
    return base / hashlib.sha256(str(Path(path).expanduser().resolve()).encode()).hexdigest()[:20]


def start_unit(slice_id, request, directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Persist intent before launching: a lost transient unit must never replay an install.
    atomic_json(directory / (request + '.started'), {'unit': 'factory-install-' + request})
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        launched = subprocess.run(['systemd-run', '--no-block', '--unit=factory-install-' + request,
                                  '--property=Type=oneshot', '--property=RemainAfterExit=yes',
                                  '--property=UMask=0077', '--property=EnvironmentFile=/etc/factory/runner.env',
                                  '--property=WorkingDirectory=/', '--',
                                  '/usr/local/bin/factory-install', slice_id, '--request', request],
                                 capture_output=True)
        return launched.returncode == 0
    except OSError:
        return False


def process(runner):
    """Called under the scheduler lock. A stable unit name makes launch retry safe."""
    for item, request in list(pending(runner.data)):
        if not re.fullmatch('[0-9a-f]{32}', request):
            raise state.StateError('invalid install request')
        directory = runner.runs / 'installs'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        result = directory / (request + '.json')
        unit = 'factory-install-' + request
        if result.exists():
            try:
                answer = json.loads(result.read_text())
                if answer['ok'] and not answer.get('manual'):
                    job = runner.jobs.get(item['id'], {})
                    if answer['commit'] != job.get('sha'):
                        raise ValueError()
                    attention = item['attention']
                    if not attention or attention['kind'] != 'node-step' or attention['answer'] is not None:
                        raise ValueError()
                    if install_failure(attention):
                        attention['body'] = attention['body'].split(NODE_STEPS, 1)[1]
                    attention['answer'] = 'Installed ' + answer['commit'] + '. Node steps are done. End with kind handover.'
                    runner.log(item, attention['answer'], True)
                else:
                    manual = answer.get('manual', [])
                    if answer['ok'] and manual:
                        runner.attention(item, 'escalation', 'Install needs attention: manual: ' + ', '.join(manual))
                    else:
                        failed(runner, item, failure_text(answer))
            except (ValueError, KeyError, TypeError):
                runner.attention(item, 'escalation', 'Install result invalid or node step changed; inspect the root install unit')
            runner.log(item, FINISHED + request)
            continue
        # A completed unit without a result is an interrupted/failed install, never retried.
        try:
            status = subprocess.run(['systemctl', 'show', unit, '--property=LoadState,ActiveState'],
                                    capture_output=True, text=True)
        except OSError:
            runner.attention(item, 'escalation', 'Install service manager unavailable')
            runner.log(item, FINISHED + request)
            continue
        if 'LoadState=loaded' in status.stdout:
            if 'ActiveState=failed' in status.stdout or 'ActiveState=inactive' in status.stdout:
                runner.attention(item, 'escalation', 'Install unit ended without a result; inspect the root install unit')
                runner.log(item, FINISHED + request)
            continue
        if (directory / (request + '.started')).exists():
            runner.attention(item, 'escalation', 'Install unit disappeared; inspect the node before retrying')
            runner.log(item, FINISHED + request)
            continue
        job = runner.jobs.get(item['id'])
        attention = item['attention']
        if not job or job.get('phase') != 'node-step' or not job.get('sha') or not attention or attention['kind'] != 'node-step' or attention['answer'] is not None:
            runner.attention(item, 'escalation', 'Install requires recorded merge metadata and an open node step')
            runner.log(item, FINISHED + request)
            continue
        if not start_unit(item['id'], request, directory):
            # Do not log subprocess diagnostics or environment values.
            runner.attention(item, 'escalation', 'Install unit could not start')
            runner.log(item, FINISHED + request)
        else:
            runner.defer(item, 'install started: ' + request)
