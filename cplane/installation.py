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


def pending(data):
    for item in data['slices']:
        done = {e['event'][len(FINISHED):] for e in item['log'] if e['event'].startswith(FINISHED)}
        for entry in item['log']:
            event = entry['event']
            if event.startswith(REQUEST) and event[len(REQUEST):] not in done:
                yield item, event[len(REQUEST):]


def installable(item):
    return item['repo'] in os.environ.get('CPLANE_INSTALL_REPOS', '').split(',')


def install_failure(attention):
    return bool(attention and attention['kind'] == 'escalation' and attention['body'].startswith('Install '))


def chat_requested(item):
    """One chat request per attention interval, even after a failed attempt."""
    attention = item['attention']
    if not attention:
        return False
    from datetime import datetime
    return any(e['event'].startswith(REQUEST) and e['actor'].startswith('chat:')
               and datetime.fromisoformat(e['at']) >= datetime.fromisoformat(attention['since']) for e in item['log'])


def review_status(item):
    events = [e['event'] for e in item['log']]
    if install_failure(item['attention']):
        status = 'failed'
    elif any(pending(dict(slices=[item]))):
        status = 'pending'
    elif any(e.startswith('Installed ') for e in events):
        status = 'finished'
    elif item['attention'] and item['attention']['kind'] == 'node-step':
        status = 'required'
    elif any(e.startswith(REQUEST) for e in events):
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
        current = next(pending(data), None)
        if current and actor == 'owner' and current[0]['id'] == item['id'] and any(
                e['event'] == REQUEST + current[1] and e['actor'].startswith('chat:') for e in item['log']):
            return f'Install already requested for {item["id"]}', None
        if current:
            raise state.StateError('an install is already requested or running')
        item['log'].append({'at': at, 'actor': actor, 'event': REQUEST + uuid.uuid4().hex})
        return f'Install requested for {item["id"]}', None
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
                    attention['answer'] = 'Installed ' + answer['commit'] + '. Node steps are done. End with kind handover.'
                    runner.log(item, attention['answer'], True)
                else:
                    manual = answer.get('manual', [])
                    runner.attention(item, 'escalation', 'Install needs attention: manual: ' + ', '.join(manual)
                                     if answer['ok'] and manual else 'Install failed; inspect the root install unit')
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
