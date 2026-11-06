"""Synthetic host directories only; never read installed CLI logins."""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import re
import subprocess

import pytest


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'node/bin/factory-cli'
    loader = importlib.machinery.SourceFileLoader('factory_cli', str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module, 'UID', os.getuid())
    monkeypatch.setattr(module, 'GID', os.getgid())
    # macOS /var can itself be a symlink; use the canonical temporary root.
    tmp_path = tmp_path.resolve()
    for name, attr in [('work', 'WORK_ROOT'), ('runs', 'RUN_ROOT'), ('logins', 'LOGIN_ROOT')]:
        root = tmp_path / name
        root.mkdir()
        monkeypatch.setattr(module, attr, root)
    for tool in module.TOOLS:
        (module.LOGIN_ROOT / tool).mkdir(mode=0o700)
    (module.WORK_ROOT / 'repo').mkdir()
    (module.RUN_ROOT / 'turn').mkdir()
    return module


def values(args, flag):
    return [args[i + 1] for i, value in enumerate(args[:-1]) if value == flag]


def build(module, tool='codex', **kwargs):
    return module.docker_arguments(tool, repo=module.WORK_ROOT / 'repo',
                                   run=module.RUN_ROOT / 'turn',
                                   command=[tool, 'exec' if tool == 'codex' else '-p', '--', 'synthetic'],
                                   **kwargs)


@pytest.mark.parametrize('tool', ['claude', 'codex'])
@pytest.mark.parametrize('login', [False, True])
def test_sealed_argument_list(launcher, tool, login):
    args = launcher.docker_arguments(tool, login=True) if login else build(launcher, tool)
    assert args[:3] == ['docker', 'run', '--rm']
    for flag, value in {'--pull': 'never', '--user': f'{os.getuid()}:{os.getgid()}',
                        '--cap-drop': 'ALL', '--security-opt': 'no-new-privileges',
                        '--memory': '4g', '--memory-swap': '4g', '--cpus': '2',
                        '--pids-limit': '256', '--log-driver': 'none',
                        '--network': 'factory-cli'}.items():
        assert values(args, flag) == [value]
    assert '--read-only' in args and '--init' in args
    assert values(args, '--tmpfs') == [
        '/tmp:rw,exec,nosuid,nodev,size=512m,mode=1777',
        f'/home/agent:rw,exec,nosuid,nodev,size=512m,uid={os.getuid()},gid={os.getgid()},mode=0700']
    mounts = values(args, '--mount')
    expected = [f'type=bind,src={launcher.LOGIN_ROOT / tool},dst=/login']
    if not login:
        expected += [f'type=bind,src={launcher.WORK_ROOT / "repo"},dst=/work',
                     f'type=bind,src={launcher.RUN_ROOT / "turn"},dst=/run/factory']
    assert mounts == expected
    assert not any('docker.sock' in a or '/srv/homelab' in a for a in args)
    assert not {'--privileged', '--cap-add', '--publish', '-p', '--env-file', '--pid', '--device'} & set(args[:args.index(launcher.IMAGE)])
    assert ('--interactive' in args) == login
    assert ('--tty' in args) == login
    env = dict(value.split('=', 1) for value in values(args, '--env'))
    assert env['HTTPS_PROXY'] == 'http://cli-proxy:8888'
    assert env['NO_PROXY'] == env['no_proxy'] == ''
    selected = 'CODEX_HOME' if tool == 'codex' else 'CLAUDE_CONFIG_DIR'
    other = 'CLAUDE_CONFIG_DIR' if tool == 'codex' else 'CODEX_HOME'
    assert env[selected] == '/login' and other not in env
    assert not any('KEY' in key or 'TOKEN' in key for key in env)
    command = args[args.index(launcher.IMAGE) + 1:]
    if not login:
        if tool == 'codex':
            assert '--dangerously-bypass-approvals-and-sandbox' in command
        else:
            assert '--dangerously-skip-permissions' in command
            assert '{"sandbox":{"enabled":false}}' in command
    elif tool == 'codex':
        assert command == ['codex', '-c', 'cli_auth_credentials_store="file"', 'login', '--device-auth']
    else:
        assert command == ['claude', 'auth', 'login']


@pytest.mark.parametrize('which', ['repo', 'run'])
@pytest.mark.parametrize('case', ['outside', 'prefix', 'root', 'symlink', 'ancestor', 'missing', 'relative', 'dotdot', 'comma', 'file'])
def test_refuse_unsafe_path(launcher, tmp_path, which, case):
    root = launcher.WORK_ROOT if which == 'repo' else launcher.RUN_ROOT
    target = root / ('repo' if which == 'repo' else 'turn')
    if case == 'outside':
        target = tmp_path.resolve()
    elif case == 'prefix':
        target = root.with_name(root.name + '-other')
        target.mkdir()
    elif case == 'root':
        target = root
    elif case == 'symlink':
        link = root / 'link'
        link.symlink_to(target, target_is_directory=True)
        target = link
    elif case == 'ancestor':
        (target / 'child').mkdir()
        link = root / 'link'
        link.symlink_to(target, target_is_directory=True)
        target = link / 'child'
    elif case == 'missing':
        target = root / 'absent'
    elif case == 'relative':
        target = Path('relative')
    elif case == 'dotdot':
        target = target / '..' / target.name
    elif case == 'comma':
        target = root / 'repo,src=/srv/homelab'
    else:
        target = root / 'file'
        target.touch()
    kwargs = dict(repo=launcher.WORK_ROOT / 'repo', run=launcher.RUN_ROOT / 'turn')
    kwargs[which] = target
    with pytest.raises((ValueError, OSError)):
        launcher.docker_arguments('codex', command=['codex', 'exec', 'synthetic'], **kwargs)


@pytest.mark.parametrize('case', ['mode', 'owner', 'symlink'])
def test_refuse_unsafe_login(launcher, monkeypatch, case):
    folder = launcher.LOGIN_ROOT / 'codex'
    if case == 'mode':
        folder.chmod(0o755)
    elif case == 'owner':
        monkeypatch.setattr(launcher, 'UID', os.getuid() + 1)
    else:
        folder.rmdir()
        folder.symlink_to(launcher.LOGIN_ROOT / 'claude', target_is_directory=True)
    with pytest.raises(ValueError):
        build(launcher)


@pytest.mark.parametrize('tool,command', [('claude', ['codex', 'exec']), ('codex', ['codex']),
                                          ('claude', ['claude', '--', '-p'])])
def test_refuse_interactive_or_wrong_tool(launcher, tool, command):
    with pytest.raises(ValueError):
        launcher.docker_arguments(tool, repo=launcher.WORK_ROOT / 'repo',
                                  run=launcher.RUN_ROOT / 'turn', command=command)


def test_run_closes_stdin_and_preserves_literal_prompt(launcher, monkeypatch, capsys):
    calls = []
    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 17)
    monkeypatch.setattr(launcher.subprocess, 'run', fake_run)
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-do-not-forward')
    prompt = '$(touch /tmp/unwanted); `env`'
    assert launcher.main(['run', '--tool', 'codex', '--repo', str(launcher.WORK_ROOT / 'repo'),
                          '--run', str(launcher.RUN_ROOT / 'turn'), '--', 'codex', 'exec', '--', prompt]) == 17
    args, kwargs = calls[0]
    assert args[-1] == prompt
    assert kwargs == {'stdin': subprocess.DEVNULL, 'check': False}
    assert 'synthetic-do-not-forward' not in str(args)
    assert capsys.readouterr() == ('', '')


def test_login_requires_terminal(launcher, monkeypatch):
    monkeypatch.setattr(launcher.sys.stdin, 'isatty', lambda: False)
    assert launcher.main(['login', 'claude']) == 2


def test_bundle_is_offline_and_mounts_no_login(launcher, monkeypatch):
    monkeypatch.setenv('GH_TOKEN', 'synthetic-secret-never-forward')
    args = launcher.bundle_arguments(repo=launcher.WORK_ROOT / 'repo',
                                     run=launcher.RUN_ROOT / 'turn', branch='slice/W1')
    assert values(args, '--network') == ['none']
    assert values(args, '--mount') == [
        f'type=bind,src={launcher.WORK_ROOT / "repo"},dst=/work,readonly',
        f'type=bind,src={launcher.RUN_ROOT / "turn"},dst=/run/factory']
    assert '--read-only' in args and '--init' in args
    assert values(args, '--cap-drop') == ['ALL']
    assert values(args, '--security-opt') == ['no-new-privileges']
    assert values(args, '--log-driver') == ['none']
    assert not any('/login' in value or 'synthetic-secret' in value for value in args)
    assert 'core.hooksPath=/dev/null' in args and 'core.fsmonitor=false' in args
    assert 'core.sshCommand=/bin/false' in args and 'protocol.allow=never' in args
    assert args[-5:] == ['bundle', 'create', '/run/factory/branch.bundle', 'HEAD', 'refs/heads/slice/W1']
    calls = []
    monkeypatch.setattr(launcher.subprocess, 'run', lambda cmd, **kw:
                        calls.append((cmd, kw)) or subprocess.CompletedProcess(cmd, 0))
    assert launcher.main(['bundle', '--repo', str(launcher.WORK_ROOT / 'repo'),
                          '--run', str(launcher.RUN_ROOT / 'turn'), '--branch', 'slice/W1']) == 0
    assert calls == [(args, {'stdin': subprocess.DEVNULL, 'check': False})]


@pytest.mark.parametrize('branch', ['--all', '../main', 'x/../main', '/main', 'x..y',
                                  'x.lock', 'x/.hidden', 'x//y', 'x\nmain', 'x;id'])
def test_bundle_refuses_ambiguous_branch(launcher, branch):
    with pytest.raises(ValueError):
        launcher.bundle_arguments(repo=launcher.WORK_ROOT / 'repo',
                                  run=launcher.RUN_ROOT / 'turn', branch=branch)


@pytest.mark.parametrize('which', ['repo', 'run'])
def test_bundle_refuses_linked_mount(launcher, which):
    root = launcher.WORK_ROOT if which == 'repo' else launcher.RUN_ROOT
    link = root / 'linked'
    link.symlink_to(root / ('repo' if which == 'repo' else 'turn'), target_is_directory=True)
    kwargs = dict(repo=launcher.WORK_ROOT / 'repo', run=launcher.RUN_ROOT / 'turn', branch='slice/W1')
    kwargs[which] = link
    with pytest.raises(ValueError):
        launcher.bundle_arguments(**kwargs)


def test_filter_exact_hosts_and_ports():
    root = Path(__file__).resolve().parents[1]
    rules = (root / 'node/proxy/allowed-hosts').read_text().splitlines()
    for rule in rules:
        assert re.fullmatch(r'\^[a-z0-9-]+(?:\\\.[a-z0-9-]+)+:443\$', rule)
    patterns = [re.compile(rule, re.I) for rule in rules]
    def allowed(value):
        return any(pattern.search(value) for pattern in patterns)
    assert allowed('api.openai.com:443') and allowed('api.anthropic.com:443')
    assert allowed('github.com:443')
    for host in ['pypi.org', 'files.pythonhosted.org', 'registry.npmjs.org']:
        assert allowed(f'{host}:443')
    for value in ['example.com:443', 'github.com:80', 'evil.github.com:443',
                  'api.openai.com.evil.test:443', 'http://github.com/', '127.0.0.1:443',
                  'evil.pypi.org:443', 'pypi.org:80', 'pypi.org.evil.com:443']:
        assert not allowed(value)
