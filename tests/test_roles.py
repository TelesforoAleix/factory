import json
import os
import stat

import pytest

from cplane.cli import main
from cplane.state import load

ADD = ['add', '--id', 'new/W2', '--repo', 'example/repo', '--feature', 'f', '--title', 'T']
TABLE = {
    'cutter': [{'kind': 'litellm', 'purpose': 'x'}, {'kind': 'cli', 'tool': 'claude', 'model': 'opus', 'effort': 'high'},
               {'kind': 'cli', 'tool': 'codex', 'model': 'second'}],
    'plain': [{'kind': 'cli', 'tool': 'codex', 'model': 'some-model'}],
    'worker': [{'kind': 'litellm', 'purpose': 'task-worker'}],
}


@pytest.fixture
def roles(tmp_path, monkeypatch, make_state):
    monkeypatch.setenv('CPLANE_RUNS', str(tmp_path / 'runs'))
    path = make_state([])

    def install(script_body=None, command=None):
        if script_body is not None:
            script = tmp_path / 'table.py'
            script.write_text(script_body)
            command = f'python3 "{script}"'
        (tmp_path / 'roles-command').write_text(command)
    return path, install


def emit(table):
    return f'import json\nprint(json.dumps({table!r}))\n'


def added(path):
    return load(path)['slices'][0]['executor']


def run_add(path, *extra):
    return main(['--state', str(path), *ADD, *extra])


def test_default_role_first_cli_route(roles, capsys):
    path, install = roles
    install(emit(TABLE))
    assert run_add(path) == 0
    assert added(path) == {'tool': 'claude', 'model': 'opus', 'effort': 'high'}
    assert 'roles:' not in capsys.readouterr().err


def test_role_without_effort_and_named_role(roles):
    path, install = roles
    install(emit(TABLE))
    assert run_add(path, '--role', 'plain') == 0
    assert added(path) == {'tool': 'codex', 'model': 'some-model'}


def test_effort_flag_overrides(roles):
    path, install = roles
    install(emit(TABLE))
    assert run_add(path, '--effort', 'low') == 0
    assert added(path) == {'tool': 'claude', 'model': 'opus', 'effort': 'low'}


@pytest.mark.parametrize('flags', [['--tool', 'codex'], ['--model', 'm'], ['--tool', 'claude', '--model', 'm']])
def test_flags_skip_table(roles, tmp_path, flags):
    path, install = roles
    marker = tmp_path / 'ran'
    install(f'open({str(marker)!r}, "w").close()\nprint("{{}}")\n')
    assert run_add(path, *flags) == 0
    assert not marker.exists()
    executor = added(path)
    assert executor['tool'] == (flags[flags.index('--tool') + 1] if '--tool' in flags else 'codex')
    assert executor['model'] == (flags[flags.index('--model') + 1] if '--model' in flags else 'gpt-6.1-sol')
    assert 'effort' not in executor


def fallback(path, capsys, *extra):
    assert run_add(path, *extra) == 0
    assert added(path) == {'tool': 'codex', 'model': 'gpt-6.1-sol'}
    lines = [l for l in capsys.readouterr().err.splitlines() if l]
    assert len(lines) == 1 and lines[0].startswith('roles:')


def test_missing_file(roles, capsys):
    fallback(roles[0], capsys)


@pytest.mark.parametrize('command', ['', '  ', '/nonexistent/program', 'python3 -c "import sys; sys.exit(3)"',
                                     'python3 -c "print(1)"', "python3 -c 'print(\"[]\")'", 'python3 -c "print(\'x\')"',
                                     "unbalanced 'quote"])
def test_failing_or_invalid_command(roles, capsys, command):
    path, install = roles
    install(command=command)
    fallback(path, capsys)


def test_timeout(roles, capsys, monkeypatch):
    path, install = roles
    install('import time\ntime.sleep(60)\n')
    import cplane.roles as module
    real = module.subprocess.run
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: real(*a, **{**k, 'timeout': 0.5}))
    fallback(path, capsys)


def test_stdin_closed_and_no_shell(roles, capsys):
    path, install = roles
    install('import sys, json\nassert sys.stdin.read() == ""\nprint(json.dumps({"cutter": [{"kind": "cli", "tool": "codex", "model": "m"}]}))\n')
    assert run_add(path) == 0
    assert added(path)['model'] == 'm'


def test_command_is_not_run_by_a_shell(roles, capsys):
    path, install = roles
    install(command='echo ' + json.dumps(json.dumps(TABLE)) + ' ; true')
    fallback(path, capsys)


@pytest.mark.parametrize('table', [
    {}, {'cutter': []}, {'cutter': 'x'}, {'cutter': [{'kind': 'litellm'}]}, {'cutter': ['cli']},
    {'cutter': [{'kind': 'cli', 'tool': 'gemini', 'model': 'm'}]},
    {'cutter': [{'kind': 'cli', 'tool': 'codex'}]},
    {'cutter': [{'kind': 'cli', 'tool': 'codex', 'model': ''}]},
    {'cutter': [{'kind': 'cli', 'tool': 'codex', 'model': 5}]},
    {'cutter': [{'kind': 'cli', 'tool': 'codex', 'model': 'm', 'effort': 'extreme'}]},
    {'cutter': [{'kind': 'cli', 'tool': 'codex', 'model': 'm', 'effort': 3}]},
])
def test_invalid_table_falls_back(roles, capsys, table):
    path, install = roles
    install(emit(table))
    fallback(path, capsys)


def test_role_with_only_non_cli_routes(roles, capsys):
    path, install = roles
    install(emit(TABLE))
    fallback(path, capsys, '--role', 'worker')


def test_edit_does_not_read_table(roles, tmp_path):
    path, install = roles
    marker = tmp_path / 'ran'
    install(f'open({str(marker)!r}, "w").close()\n')
    assert run_add(path, '--tool', 'codex') == 0
    assert main(['--state', str(path), 'edit', 'new/W2', '--title', 'N']) == 0
    assert not marker.exists()
