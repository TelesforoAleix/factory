import os
import plistlib
import subprocess

import pytest

from cplane import primer
from cplane.cli import main

SECRET = 'SECRET-RESPONSE-TEXT'


def fake(folder, name, body):
    path = folder / name
    path.write_text('#!/bin/sh\n' + body)
    path.chmod(0o755)


@pytest.fixture
def bin(tmp_path, monkeypatch):
    folder = tmp_path / 'bin'
    folder.mkdir()
    fake(folder, 'caffeinate', 'exec sleep 30\n')
    fake(folder, 'claude', f'echo {SECRET}\n')
    fake(folder, 'codex', f'echo {SECRET}\n')
    fake(folder, 'sysctl', 'echo "{ sec = 1000, usec = 5 } Thu Jan  1"\n')
    fake(folder, 'ioreg', 'echo \'    | "HIDIdleTime" = 900000000000\'\n')
    fake(folder, 'pmset', 'echo "2026-01-01 00:16:40 +0000 Wake  Wake from Deep Idle [CDNVA] : due to RTC/Maintenance"\n')
    monkeypatch.setenv('PATH', str(folder) + os.pathsep + os.environ['PATH'])
    return folder


def lines(home):
    return (home / 'Library/Logs/cplane/primer.log').read_text().splitlines()


def test_both_ok_and_log_has_no_response(bin, tmp_path):
    assert primer.prime(home=tmp_path, sleep=lambda: None, clock=lambda: 1100)
    log = lines(tmp_path)
    assert log[0].endswith(' claude ok') and log[1].endswith(' codex ok')
    assert SECRET not in '\n'.join(log)


def test_one_fails_other_still_runs(bin, tmp_path):
    fake(bin, 'claude', f'echo {SECRET}; echo {SECRET} >&2; exit 3\n')
    assert not primer.prime(home=tmp_path, sleep=lambda: None, clock=lambda: 1100)
    log = lines(tmp_path)
    assert log[0].endswith(' claude error exit 3') and log[1].endswith(' codex ok')
    assert SECRET not in '\n'.join(log)


def test_timeout(bin, tmp_path, monkeypatch):
    monkeypatch.setattr(primer, 'TIMEOUT', 1)
    fake(bin, 'claude', 'exec sleep 20\n')
    assert not primer.prime(home=tmp_path, sleep=lambda: None, clock=lambda: 1100)
    log = lines(tmp_path)
    assert log[0].endswith(' claude error timeout') and log[1].endswith(' codex ok')


def test_runs_in_empty_dir_with_closed_stdin(bin, tmp_path):
    fake(bin, 'claude', 'test -z "$(ls -A)" && ! read x\n')
    assert primer.prime(home=tmp_path, sleep=lambda: None, clock=lambda: 1100)


def test_sleeps_after_scheduled_wake(bin, tmp_path):
    slept = []
    primer.prime(home=tmp_path, sleep=lambda: slept.append(1), clock=lambda: 1100)
    assert slept and lines(tmp_path)[-1].split(' ', 2)[2].startswith('sleep yes')


def test_user_wake_left_alone(bin, tmp_path):
    fake(bin, 'pmset', 'echo "2026-01-01 00:16:40 +0000 Wake  Wake from Deep Idle : due to EC.LidOpen/Lid Open"\n')
    slept = []
    primer.prime(home=tmp_path, sleep=lambda: slept.append(1), clock=lambda: 1100)
    assert not slept and 'sleep no' in lines(tmp_path)[-1]


def test_decision_function():
    scheduled = 'RTC (Alarm)'
    assert primer.should_sleep(1100, 1000, scheduled, 900)[0]
    assert not primer.should_sleep(1100, 1000, scheduled, 50)[0]
    assert not primer.should_sleep(1000 + 600, 1000, scheduled, 9999)[0]
    assert not primer.should_sleep(1100, 1000, 'EC.LidOpen/Lid Open', 900)[0]
    assert not primer.should_sleep(1100, 1000, 'PWRB (power button)', 900)[0]
    assert not primer.should_sleep(1100, 1000, None, 900)[0]
    assert not primer.should_sleep(1100, None, scheduled, 900)[0]


def test_wake_reason_takes_newest():
    log = ('x Wake  Wake from Deep Idle : due to EC.LidOpen/Lid Open\n'
           'x Sleep Entering Sleep\n'
           'x DarkWake DarkWake from Normal Sleep [CDN] : due to RTC/Maintenance\n')
    assert primer.wake_reason(log) == 'RTC/Maintenance'


def test_rendered_plist():
    plist = primer.render(home='/h', python='/py', environment={'PATH': '/x/bin:/y/bin'})
    assert plist['Label'] == 'com.cplane.primer'
    assert plist['ProgramArguments'] == ['/py', '-m', 'cplane.cli', 'prime']
    assert plist['EnvironmentVariables'] == {'PATH': '/x/bin:/y/bin'}
    assert plist['StartCalendarInterval'] == [{'Hour': h, 'Minute': 0} for h in (6, 11, 16, 21)]
    assert plist['StandardOutPath'].startswith('/h/Library/Logs/cplane/')
    assert plist['StandardErrorPath'].startswith('/h/Library/Logs/cplane/')


def test_wake_plist_command(capsys):
    assert main(['primer-wake-plist']) == 0
    plist = plistlib.loads(capsys.readouterr().out.encode())
    assert plist['Label'] == 'com.cplane.primer-wake' and plist['RunAtLoad'] is True
    assert plist['StartCalendarInterval'] == {'Hour': 0, 'Minute': 5}
    assert plist['ProgramArguments'][:2] == ['/bin/sh', '-c']


def run_wake(tmp_path, now, today, tomorrow, existing=''):
    folder = tmp_path / 'wakebin'
    folder.mkdir(exist_ok=True)
    calls = tmp_path / 'calls'
    calls.write_text('')
    sched = tmp_path / 'sched'
    sched.write_text(existing)
    fake(folder, 'pmset', f'if [ "$1" = -g ]; then cat {sched}; else echo "$@" >> {calls}; fi\n')
    fake(folder, 'date', f'''case "$*" in
  +%y%m%d%H%M) echo {now};;
  "-v+0d +%y%m%d") echo {today[0]};;
  "-v+0d +%m/%d/%Y") echo {today[1].replace("/26", "/2026")};;
  "-v+0d +%m/%d/%y") echo {today[1]};;
  "-v+1d +%y%m%d") echo {tomorrow[0]};;
  "-v+1d +%m/%d/%Y") echo {tomorrow[1].replace("/26", "/2026")};;
  "-v+1d +%m/%d/%y") echo {tomorrow[1]};;
  *) exit 1;;
esac
''')
    script = primer.render_wake()['ProgramArguments'][2]
    subprocess.run(['/bin/sh', '-c', script], env={'PATH': str(folder) + ':/usr/bin:/bin'}, check=True)
    return calls.read_text().splitlines() if calls.exists() else []


DAYS = (('261028', '10/28/26'), ('261029', '10/29/26'))


def test_wake_schedules_remaining_and_tomorrow(tmp_path):
    calls = run_wake(tmp_path, '2610281200', *DAYS)
    assert calls == [f'schedule wake {d} {t}:00' for d, t in
                     [('10/28/26', '15:59'), ('10/28/26', '20:59')] + [('10/29/26', t) for t in primer.WAKE_TIMES]]


def test_wake_skips_existing_and_past(tmp_path):
    existing = ' wake at 10/28/2026 15:59:00 by pmset\\n wake at 10/29/2026 05:59:00 by pmset'
    calls = run_wake(tmp_path, '2610280005', *DAYS, existing=existing)
    wanted = ['10/28/26 05:59:00', '10/28/26 10:59:00', '10/28/26 20:59:00',
              '10/29/26 10:59:00', '10/29/26 15:59:00', '10/29/26 20:59:00']
    assert calls == ['schedule wake ' + w for w in wanted]


def test_wake_second_run_skips_four_digit_year_schedule(tmp_path):
    first = run_wake(tmp_path, '2610280005', *DAYS)
    scheduled = '\n'.join(' wake at ' + line.removeprefix('schedule wake ').replace('/26 ', '/2026 ') + ' by pmset'
                            for line in first)
    second = run_wake(tmp_path, '2610280005', *DAYS, existing=scheduled)
    assert second == []
