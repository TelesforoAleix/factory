"""Start the Codex and Claude usage windows on a schedule, and install the launchd jobs for it."""
from datetime import datetime
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
import time

from .agent import launchctl

LABEL = 'com.cplane.primer'
WAKE_LABEL = 'com.cplane.primer-wake'
TIMEOUT = 120
TIMES = ((6, 0), (11, 0), (16, 0), (21, 0))
WAKE_TIMES = ('05:59', '10:59', '15:59', '20:59')
MAX_WAKE_AGE = 600
REQUESTS = (
    ('claude', ['claude', '-p', '--model', 'haiku', 'Reply with: ok']),
    ('codex', ['codex', 'exec', '-m', 'gpt-6-luna', '--skip-git-repo-check', '-s', 'read-only', 'Reply with: ok']),
)
USER_WAKES = re.compile(r'lid|power ?button|pwrb|hid|user|keyboard|trackpad|mouse|usb|bluetooth|ethernet|network|\bac\b|charger', re.I)
SCHEDULED_WAKES = re.compile(r'\bRTC\b|scheduled|repeating', re.I)


def stamp(now=None):
    return (now or datetime.now().astimezone()).strftime('%Y-%m-%d %H:%M:%S')


def should_sleep(now, wake, reason, idle):
    """Decide whether to sleep again. Times are epoch seconds; idle is seconds since the last input."""
    if wake is None or reason is None or idle is None:
        return False, 'wake time, reason or idle time unknown'
    since = now - wake
    if since < 0 or since >= MAX_WAKE_AGE:
        return False, f'last wake {int(since)}s ago'
    if USER_WAKES.search(reason) or not SCHEDULED_WAKES.search(reason):
        return False, 'last wake was not a scheduled one'
    if idle <= since:
        return False, 'user input since the wake'
    return True, 'scheduled wake, no user input since'


def wake_reason(log):
    """The reason of the newest Wake or DarkWake entry in `pmset -g log` output."""
    found = None
    for line in log.splitlines():
        if re.search(r'\s(?:Dark)?Wake\s', line):
            match = re.search(r'due to (.*)', line)
            found = match.group(1) if match else ''
    return found


def read(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def last_wake():
    out = read(['sysctl', '-n', 'kern.waketime'])
    match = out and re.search(r'sec\s*=\s*(\d+)', out)
    return int(match.group(1)) if match else None


def idle_seconds():
    out = read(['ioreg', '-c', 'IOHIDSystem'])
    match = out and re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
    return int(match.group(1)) / 1e9 if match else None


def request(name, args):
    with tempfile.TemporaryDirectory() as folder:
        try:
            result = subprocess.run(args, cwd=folder, stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return 'error timeout'
        except OSError:
            return 'error not runnable'
    return 'ok' if result.returncode == 0 else f'error exit {result.returncode}'


def prime(*, home=None, sleep=None, clock=time.time):
    """Send one request to each tool; return True when both succeeded."""
    log = Path(home or Path.home()) / 'Library/Logs/cplane/primer.log'
    log.parent.mkdir(parents=True, exist_ok=True)

    def note(text):
        with log.open('a') as stream:
            stream.write(f'{stamp()} {text}\n')

    awake = subprocess.Popen(['caffeinate', '-s', '-i', '-w', str(os.getpid())])
    try:
        outcomes = []
        for name, args in REQUESTS:
            outcome = request(name, args)
            outcomes.append(outcome)
            note(f'{name} {outcome}')
        reason = wake_reason(read(['pmset', '-g', 'log']) or '')
        go, why = should_sleep(clock(), last_wake(), reason, idle_seconds())
        note(f'sleep {"yes" if go else "no"}: {why}')
        if go:
            (sleep or (lambda: subprocess.run(['pmset', 'sleepnow'])))()
    finally:
        awake.terminate()
    return all(outcome == 'ok' for outcome in outcomes)


def render(*, home=None, python=None, environment=None):
    logs = Path(home or Path.home()) / 'Library/Logs/cplane'
    source = environment if environment is not None else os.environ
    # launchd does not inherit the terminal's PATH, so the binaries must be found on the captured one.
    path = source.get('PATH') or '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'
    return {
        'Label': LABEL,
        'ProgramArguments': [str(python or sys.executable), '-m', 'cplane.cli', 'prime'],
        'WorkingDirectory': str(Path(__file__).resolve().parent.parent),
        'EnvironmentVariables': {'PATH': path},
        'StartCalendarInterval': [{'Hour': hour, 'Minute': minute} for hour, minute in TIMES],
        'StandardOutPath': str(logs / 'primer.out.log'),
        'StandardErrorPath': str(logs / 'primer-error.log'),
    }


def target():
    return Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')


def install():
    path = target()
    path.parent.mkdir(parents=True, exist_ok=True)
    (Path.home() / 'Library/Logs/cplane').mkdir(parents=True, exist_ok=True)
    if path.exists():
        launchctl('bootout', f'gui/{os.getuid()}', str(path), missing_ok=True)
        while launchctl('list', LABEL, missing_ok=True).returncode == 0:
            time.sleep(0.1)
    path.write_bytes(plistlib.dumps(render()))
    launchctl('bootstrap', f'gui/{os.getuid()}', str(path))


def uninstall():
    path = target()
    if path.exists():
        launchctl('bootout', f'gui/{os.getuid()}', str(path), missing_ok=True)
        path.unlink()


# Self-contained: root runs only this text. Needs BSD date and pmset.
WAKE_SCRIPT = '''set -u
sched=$(pmset -g sched)
now=$(date +%y%m%d%H%M)
for d in 0 1; do
  key=$(date -v+${d}d +%y%m%d)
  day=$(date -v+${d}d +%m/%d/%Y)
  schedule_day=$(date -v+${d}d +%m/%d/%y)
  for t in ''' + ' '.join(WAKE_TIMES) + '''; do
    when="$day $t:00"
    schedule_when="$schedule_day $t:00"
    [ "$key${t%:*}${t#*:}" -gt "$now" ] || continue
    case "$sched" in *"$when"*) continue;; esac
    pmset schedule wake "$schedule_when"
  done
done
'''


def render_wake():
    return {
        'Label': WAKE_LABEL,
        'ProgramArguments': ['/bin/sh', '-c', WAKE_SCRIPT],
        'EnvironmentVariables': {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'},
        'RunAtLoad': True,
        'StartCalendarInterval': {'Hour': 0, 'Minute': 5},
        'StandardOutPath': '/var/log/cplane-primer-wake.log',
        'StandardErrorPath': '/var/log/cplane-primer-wake.log',
    }


def wake_plist():
    return plistlib.dumps(render_wake()).decode()
