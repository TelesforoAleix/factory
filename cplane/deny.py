"""Host-only private-content gate. Never include matched content in diagnostics."""
import os
from pathlib import Path
import re
import stat

from .state import StateError

DENY_LIST = Path('/etc/homelab/deny-list')
ROOT_UID = 0
# Public on purpose: the owner can plant this to verify the installed boundary.
CANARY = 'FACTORY-PUBLIC-DENY-CANARY-DL1'


class Denied(StateError):
    """A safe, content-free delivery escalation."""


def patterns():
    try:
        fd = os.open(os.environ.get('CPLANE_DENY_LIST', DENY_LIST), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or not (
                    (info.st_uid == ROOT_UID and stat.S_IMODE(info.st_mode) == 0o600)
                    or (info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o400))):
                raise ValueError
            lines = stream.read().splitlines()
    except (OSError, UnicodeError, ValueError):
        raise Denied('private-content check: deny-list unavailable or invalid') from None
    return tuple(s.casefold() for s in [CANARY, *lines] if s.strip() and not s.startswith('#'))


class Check:
    def __init__(self):
        self.patterns = patterns()

    def hit(self, text):
        folded = text.casefold()
        return any(value in folded for value in self.patterns)

    def text(self, text, location):
        if self.hit(text):
            raise Denied('private-content check: ' + location)

    def request(self, request):
        for key, location in [('branch', 'branch name'), ('title', 'PR title'), ('body', 'PR body')]:
            self.text(request.get(key, ''), location)

    def commits(self, git, base, tip):
        # Each commit is scanned independently, including merge resolutions. A
        # later removal must never erase evidence of an earlier addition.
        for commit in git('rev-list', f'{base}..{tip}').stdout.splitlines():
            self.text(git('log', '-1', '--format=%B', '--no-patch', commit).stdout,
                      'commit message (' + commit + ')')
            paths = git('diff-tree', '--root', '-m', '-r', '--no-commit-id',
                        '--no-renames', '--name-only', '-z', commit).stdout.split('\0')
            for path in dict.fromkeys(p for p in paths if p):
                patch = git('log', '-1', '-p', '--format=', '--root',
                            '--diff-merges=first-parent', '--no-ext-diff', '--no-textconv',
                            '--no-renames', '--text', '--unified=0', commit,
                            '--', ':(literal)' + path).stdout
                line_number = None
                for line in patch.split('\n'):
                    hunk = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
                    if hunk:
                        line_number = int(hunk[1])
                    elif line_number is not None and line.startswith('+'):
                        if self.hit(line[1:]):
                            # A filename can itself contain a denied string.
                            # In that case use a stable commit/file ordinal.
                            name = ('file ' + str(paths.index(path) + 1) if self.hit(path)
                                    else ascii(path))
                            raise Denied(f'private-content check: {name}:{line_number} (commit {commit})')
                        line_number += 1
                    elif line_number is not None and line.startswith(' '):
                        line_number += 1
