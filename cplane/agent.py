"""Render and manage the owner's five-minute launchd job."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

from .state import StateError

LABEL = 'com.cplane.runner'


def render(path, *, commit=False, home=None, python=None, environment=None):
    home = Path(home or Path.home())
    logs = home / 'Library/Logs/cplane'
    source = environment if environment is not None else os.environ
    # launchd does not inherit the terminal's environment or PATH.
    env = {key: source[key] for key in ('PATH', 'CPLANE_REPOS', 'CPLANE_RUNS') if key in source}
    env.setdefault('PATH', '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin')
    return {
        'Label': LABEL,
        'ProgramArguments': [str(python or sys.executable), '-m', 'cplane.cli', '--state', str(path),
                             *(('--commit',) if commit else ()), '--actor', 'runner', 'run'],
        'WorkingDirectory': str(Path(__file__).resolve().parent.parent),
        'EnvironmentVariables': env,
        'StartInterval': 300,
        'AbandonProcessGroup': True,
        'StandardOutPath': str(logs / 'runner.log'),
        'StandardErrorPath': str(logs / 'runner-error.log'),
    }


def launchctl(*args, missing_ok=False):
    result = subprocess.run(['launchctl', *args], capture_output=True, text=True)
    if result.returncode and not missing_ok:
        raise StateError('launchctl: ' + (result.stderr.strip() or result.stdout.strip()))
    return result


def install(path, *, commit=False):
    home = Path.home()
    target = home / 'Library/LaunchAgents' / (LABEL + '.plist')
    target.parent.mkdir(parents=True, exist_ok=True)
    (home / 'Library/Logs/cplane').mkdir(parents=True, exist_ok=True)
    if target.exists():
        launchctl('bootout', f'gui/{os.getuid()}', str(target), missing_ok=True)
        while launchctl('list', LABEL, missing_ok=True).returncode == 0:
            time.sleep(0.1)
    target.write_bytes(plistlib.dumps(render(path, commit=commit)))
    launchctl('bootstrap', f'gui/{os.getuid()}', str(target))


def uninstall():
    target = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    if target.exists():
        launchctl('bootout', f'gui/{os.getuid()}', str(target), missing_ok=True)
        target.unlink()
