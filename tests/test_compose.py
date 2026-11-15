"""Guard the owner-installed service boundary, independent of Docker availability."""
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'homelab-deployer-factory:${HOMELAB_DEPLOY_TAG:?commit required}'
USERS = {'ui': '992:978', 'intake': '991:977', 'sessions': '21011:21011', 'runner': '21010:21010'}
DOCS_PARENT = '/var/lib/factory/workshop'
DOCS = f'{DOCS_PARENT}/ui-docs'
LAUNCH = '/run/homelab-launcher.sock'
DEPLOY = '/run/homelab-deployer.sock'
MOUNTS = {
    'ui': {DOCS_PARENT: True},
    'intake': {'/run/factory-intake': False},
    'sessions': {'/srv/factory/work': False, DOCS_PARENT: False,
                 '/srv/factory/clean-sessions': False, '/srv/factory/runs/sessions': False,
                 '/var/lib/factory/sessions': False,
                 '/srv/factory/briefs': True, '/srv/factory/runs': True, LAUNCH: False},
    'runner': {**{f'/srv/factory/{p}': False for p in
                  ('briefs', 'runs', 'work', 'clean', 'exports', 'bot-export')},
               '/srv/homelab/factory-state': False, LAUNCH: False, DEPLOY: False},
}
SECRET_SETTINGS = {
    'CPLANE_DATABASE_URL_FILE': 'database-url',
    'CPLANE_GITHUB_APP_KEY': 'github-app.pem',
    'CPLANE_BRIEFS_KEY': 'briefs-key',
    'CPLANE_BRIEFS_KNOWN_HOSTS': 'briefs-known-hosts',
    'CPLANE_PLANNING_WRITE_KEY': 'planning-write-key',
    'CPLANE_DENY_LIST': 'deny-list',
    'CPLANE_EVAL_TASK_KEY_FILE': 'eval-task-key',
}
RUNNER_SETTINGS = {
    'CPLANE_FENCE': '1', 'CPLANE_GITHUB_AUTH': 'app',
    'CPLANE_STATE': '/srv/factory/briefs/slices.json', 'CPLANE_RUNS': '/srv/factory/runs',
    'CPLANE_REPOS': '/srv/factory/work',
    'CPLANE_EXPORT_DIR': '/srv/homelab/factory-state',
    'CPLANE_BOT_EXPORT': '/srv/factory/bot-export', 'CPLANE_FENCE_COMMAND': 'socket',
    'CPLANE_USAGE_SOURCE': 'launcher', 'CPLANE_DEPLOYER_SOCKET': DEPLOY,
    'CPLANE_EVAL_TASK_URL': 'http://api:8000',
}
UI_SETTINGS = {key: RUNNER_SETTINGS[key] for key in ('CPLANE_STATE', 'CPLANE_RUNS', 'CPLANE_REPOS')}
UI_SETTINGS.update(CPLANE_UI_DOCS=DOCS, FACTORY_UI_HOST='0.0.0.0',
                   HOMELAB_API_URL='http://api:8000')
SESSIONS_SETTINGS = {
    'CPLANE_GITHUB_AUTH': 'app', 'CPLANE_SESSIONS_CLEAN_ROOT': '/srv/factory/clean-sessions',
    'CPLANE_SESSION_RUNS': '/srv/factory/runs/sessions',
    'CPLANE_SESSIONS_LOCK': '/var/lib/factory/sessions/sessions.lock',
    'CPLANE_UI_DOCS': DOCS, 'CPLANE_FENCE_COMMAND': 'socket',
}
COMMANDS = {
    'ui': ['python', '-m', 'factory_ui.serve'],
    'intake': ['python', '-m', 'cplane.intake'],
    'sessions': ['python', '-m', 'cplane.sessions'],
    'runner': ['cplane', '--actor', 'runner', 'run', '--every', '60'],
}


def looks_secret(value):
    return (urlsplit(value).password is not None
            or re.search(r'-----BEGIN .*PRIVATE KEY|\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_]+', value)
            or re.search(r'(?i)(?:password|token|secret|api[_-]?key)\s*[=:]\s*\S+', value))


def assert_nonsecret_environment(environment):
    for key, value in environment.items():
        if key.endswith('_FILE') or key in SECRET_SETTINGS:
            assert value.startswith('/run/secrets/')
        elif key not in ('HOMELAB_API_URL', 'CPLANE_EVAL_TASK_URL'):
            assert not key.endswith(('_KEY', '_TOKEN', '_PASSWORD', '_URL')), key
        assert not looks_secret(value), key


@pytest.mark.parametrize('key,value', [
    ('SERVICE_KEY', 'synthetic'), ('SERVICE_TOKEN', 'synthetic'),
    ('SERVICE_PASSWORD', 'synthetic'),
    ('CPLANE_ORDERS_URL', 'https://example.invalid/orders'),
    ('ENDPOINT', 'https://user:synthetic@example.invalid/'),
    ('CPLANE_GITHUB_APP_KEY', 'synthetic'),
])
def test_inline_credentials_and_urls_are_refused(key, value):
    with pytest.raises(AssertionError):
        assert_nonsecret_environment({key: value})


def test_secret_paths_and_nonsecret_settings_are_allowed():
    assert_nonsecret_environment({
        'CPLANE_DATABASE_URL_FILE': '/run/secrets/database-url',
        'CPLANE_GITHUB_APP_KEY': '/run/secrets/github-app.pem',
        'CPLANE_GITHUB_APP_ID': '123', 'HOME': '/tmp',
        'GH_CONFIG_DIR': '/tmp/.config/gh',
    })


def test_contained_services():
    config = yaml.safe_load((ROOT / 'compose.yaml').read_text())
    assert set(config) == {'services', 'networks'}
    assert config['networks'] == {'homelab_default': {'external': True, 'name': 'homelab_default'}}
    assert list(config['services']) == list(USERS)
    seen_secrets = set()
    for name, service in config['services'].items():
        # Reject alternate Compose mechanisms (extends, lifecycle hooks, API
        # socket injection, etc.) that could bypass the reviewed fields below.
        fields = {'image', 'read_only', 'tmpfs', 'cap_drop', 'security_opt',
                  'mem_limit', 'pids_limit', 'restart', 'logging', 'networks',
                  'user', 'command', 'environment', 'volumes', 'healthcheck'}
        if name in ('ui', 'sessions', 'runner'):
            fields.add('env_file')
        if name == 'ui':
            fields.add('ports')
        if name in ('sessions', 'runner'):
            fields.add('group_add')
        assert set(service) == fields
        assert service['image'] == IMAGE
        assert service['command'] == COMMANDS[name]
        assert service['user'] == USERS[name]
        assert int(service['user'].split(':')[0]) != 0
        assert service['read_only'] is True
        assert service['tmpfs'] == ['/tmp']
        assert service['cap_drop'] == ['ALL']
        assert not service.get('cap_add')
        assert not service.get('privileged')
        assert not service.get('devices')
        assert not service.get('network_mode')
        assert not service.get('pid')
        assert not service.get('ipc')
        assert not service.get('volumes_from')
        assert not service.get('secrets')
        assert not service.get('configs')
        assert not service.get('build')
        assert service['security_opt'] == ['no-new-privileges:true']
        assert service['restart'] == 'unless-stopped'
        assert service['logging'] == {'driver': 'journald'}
        assert service['mem_limit'] and service['pids_limit'] > 0
        assert service['networks'] == ['homelab_default']
        assert service.get('group_add', []) == (
            ['976', '975', '21000'] if name == 'runner'
            else ['976', '21000'] if name == 'sessions' else [])
        assert service.get('ports', []) == (['127.0.0.1:8300:8300'] if name == 'ui' else [])
        expected_secrets = {'CPLANE_DATABASE_URL_FILE': 'database-url'}
        if name == 'sessions':
            expected_secrets['CPLANE_BRIEFS_KEY'] = 'briefs-key'
            expected_secrets['CPLANE_BRIEFS_KNOWN_HOSTS'] = 'briefs-known-hosts'
            expected_secrets['CPLANE_PLANNING_WRITE_KEY'] = 'planning-write-key'
            expected_secrets['CPLANE_GITHUB_APP_KEY'] = 'github-app.pem'
        if name == 'runner':
            expected_secrets = SECRET_SETTINGS
        expected_env = {key: f'/run/secrets/{file}' for key, file in expected_secrets.items()}
        expected_env['HOME'] = '/tmp'
        if name in ('sessions', 'runner'):
            expected_env['GH_CONFIG_DIR'] = '/tmp/.config/gh'
        if name == 'ui':
            expected_env.update(UI_SETTINGS)
        if name == 'intake':
            expected_env['CPLANE_INTAKE_GID'] = '977'
        if name == 'sessions':
            expected_env.update(SESSIONS_SETTINGS)
        if name == 'runner':
            expected_env.update(RUNNER_SETTINGS)
        # Closed settings list catches arbitrary inline keys/tokens, including
        # credentials without a recognizable provider prefix.
        assert service['environment'] == expected_env
        assert_nonsecret_environment(service['environment'])
        assert service.get('env_file', []) == (
            [{'path': f'./{name}.env', 'required': True}]
            if name in ('ui', 'sessions', 'runner') else [])
        mounts = {}
        secret_targets = set()
        for mount in service['volumes']:
            assert set(mount) == {'type', 'source', 'target', 'read_only', 'bind'}
            assert mount['type'] == 'bind'
            assert mount['bind'] == {'create_host_path': False}
            source, target = mount['source'], mount['target']
            assert 'docker.sock' not in source and 'docker.sock' not in target
            for path in (source, target):
                assert not PurePosixPath(path).is_relative_to('/srv/factory/logins')
                assert not PurePosixPath(path).is_relative_to(DOCS)
                assert path != '/var/lib/factory/ui-docs'
            assert '..' not in PurePosixPath(source).parts
            assert target not in mounts and target not in secret_targets
            if target.startswith('/run/secrets/'):
                file = PurePosixPath(target).name
                assert source == f'/etc/factory/secrets/{name}/{file}'
                assert source not in seen_secrets
                seen_secrets.add(source)
                assert mount['read_only'] is True
                secret_targets.add(target)
            else:
                assert source == target
                mounts[target] = mount['read_only']
        assert mounts == MOUNTS[name]
        assert secret_targets == {f'/run/secrets/{file}' for file in expected_secrets.values()}
        health = service['healthcheck']
        assert health['test'][:3] == ['CMD', 'python', '-c']
        assert health['interval'] and health['timeout'] and health['retries'] > 0
        compile(health['test'][3], f'{name} healthcheck', 'exec')
        if name == 'ui':
            assert "urlopen('http://127.0.0.1:8300/', timeout=5)" in health['test'][3]
            assert health['test'][3] in (ROOT / 'docs/node.md').read_text()
