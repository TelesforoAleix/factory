#!/usr/bin/env python3.13
"""No credentials: check CONNECT allow/deny and direct egress from the internal net."""
import subprocess
import time

BASE = ['docker', 'run', '--rm', '--pull', 'never', '--user', '21000:21000',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--read-only',
        '--memory', '4g', '--memory-swap', '4g', '--cpus', '2', '--pids-limit', '256',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=512m',
        '--tmpfs', '/home/agent:rw,nosuid,nodev,size=512m,uid=21000,gid=21000,mode=0700',
        '--log-driver', 'none', '--network', 'factory-cli', 'factory-cli:1',
        'curl', '--silent', '--show-error', '--connect-timeout', '5', '--max-time', '15']


def curl(*args):
    return subprocess.run([*BASE, *args], capture_output=True, text=True, check=False)


for attempt in range(10):
    allowed = curl('--proxy', 'http://cli-proxy:8888', '--fail',
                   '--output', '/dev/null', 'https://api.github.com')
    if allowed.returncode == 0:
        break
    time.sleep(1)
else:
    raise SystemExit('FAIL: allowed host did not answer through proxy')
print('PASS: api.github.com:443 answers through proxy')
packages = curl('--proxy', 'http://cli-proxy:8888', '--fail',
                '--output', '/dev/null', 'https://pypi.org')
assert packages.returncode == 0, 'PyPI did not answer through proxy'
print('PASS: pypi.org:443 answers through proxy')
denied = curl('--proxy', 'http://cli-proxy:8888', 'https://example.com')
assert denied.returncode != 0 and '403' in denied.stderr, 'deny must be a proxy 403'
print('PASS: example.com:443 refused with 403')
direct = curl('--noproxy', '*', 'https://1.1.1.1')
assert direct.returncode != 0, 'direct HTTPS unexpectedly succeeded'
print('PASS: direct HTTPS without proxy fails')
