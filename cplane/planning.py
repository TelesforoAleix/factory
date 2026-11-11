"""Planning delivery: untrusted bundles in, fast-forward Markdown commits out."""
import os
from pathlib import Path
import re
import subprocess

from . import fence
from .state import StateError

READ_KEY = Path('/etc/factory/briefs-key/id_ed25519')
WRITE_KEY = Path('/etc/factory/planning-write-key/id_ed25519')
KNOWN_HOSTS = Path('/etc/factory/briefs-key/known_hosts')
START = 'refs/factory/start'
DELIVERED = 'refs/factory/delivered'


class Planning:
    def __init__(self, session):
        self.session = session
        self.branch = f'session-{session["id"]}'
        root = fence.trusted_directory(fence.CLEAN_ROOT)
        parent = root / 'planning-sessions'
        parent.mkdir(mode=0o700, exist_ok=True)
        fence.trusted_directory(parent)
        self.clean = parent / self.branch

    def git(self, *args, network=None, allow_failure=False):
        if self.clean == fence.CLEAN_ROOT or not self.clean.is_relative_to(fence.CLEAN_ROOT):
            raise StateError('Planning host Git refused outside clean clones.')
        fence.trusted_directory(self.clean)
        env = fence.host_environment()
        if network:
            # Only the push receives the write identity, in its private environment.
            key = WRITE_KEY if network == 'push' else READ_KEY
            env['GIT_SSH_COMMAND'] = (
                f'ssh -F /dev/null -i {key} -o IdentitiesOnly=yes -o BatchMode=yes '
                f'-o StrictHostKeyChecking=yes -o UserKnownHostsFile={KNOWN_HOSTS}')
        result = subprocess.run(
            ['git', '-C', str(self.clean), *fence.git_options(),
             '-c', 'protocol.file.allow=always', '-c', 'user.name=Factory',
             '-c', 'user.email=factory@localhost', *map(str, args)],
            capture_output=True, text=True, env=env)
        if result.returncode and not allow_failure:
            message = {
                'fetch': 'Planning fetch failed; no delivery confirmed.',
                'push': 'Planning push failed; no delivery confirmed.',
            }.get(network, 'Planning Git operation failed; no delivery confirmed.')
            raise StateError(message)
        return result

    def prepare(self, destination):
        remote = os.environ.get('CPLANE_PLANNING_REMOTE', '')
        if not re.fullmatch(r'git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', remote):
            raise StateError('Planning SSH remote unavailable or invalid.')
        self.clean.mkdir(mode=0o700)  # never reuse interrupted preparations
        self.git('init', '--template=')
        self.git('remote', 'add', 'origin', remote)
        self.git('fetch', '--no-tags', 'origin', 'refs/heads/main:refs/remotes/origin/main', network='fetch')
        base = self.git('rev-parse', 'refs/remotes/origin/main^{commit}').stdout.strip()
        self.git('update-ref', START, base)
        self.git('update-ref', DELIVERED, base)
        self.git('checkout', '-b', self.branch, base)
        self.git('clone', '--no-hardlinks', '--template=', '--single-branch', '--branch', self.branch,
                 '--config', 'core.hooksPath=/dev/null', '--config', 'user.name=Factory',
                 '--config', 'user.email=factory@localhost', self.clean, destination)
        destination.chmod(0o700)

    def deliver(self, copy, run):
        if self.session['area'] != 'homelab':
            return []
        # The supervisor permits just one active turn per session. This clone is
        # dedicated to that session, so other sessions cannot alter its refs/index.
        result = subprocess.run([fence.fence_command(), 'bundle', '--repo', str(copy),
                                 '--run', str(run / 'io'), '--branch', self.branch],
                                cwd=run, capture_output=True, env=fence.host_environment())
        if result.returncode:
            raise StateError('Planning bundle export refused; nothing pushed.')
        bundle = fence.snapshot_bundle(run)
        heads = self.git('bundle', 'list-heads', bundle).stdout.splitlines()
        expected = 'refs/heads/' + self.branch
        if (len(heads) != 2 or len(set(heads)) != 2
                or {line.split(' ', 1)[1] for line in heads} != {'HEAD', expected}
                or len({line.split(' ', 1)[0] for line in heads}) != 1):
            raise StateError('Planning bundle refused: wrong branch or HEAD.')
        self.git('bundle', 'verify', bundle)
        imported = 'refs/factory/import'
        self.git('fetch', '--no-tags', '--no-write-fetch-head', bundle, f'+{expected}:{imported}')
        tip = self.git('rev-parse', imported + '^{commit}').stdout.strip()
        for base in (START, DELIVERED):
            if self.git('merge-base', '--is-ancestor', base, tip, allow_failure=True).returncode:
                raise StateError('Planning bundle refused: commits do not descend from the session start or last delivery.')
        previous = self.git('rev-parse', DELIVERED).stdout.strip()
        if previous == tip:
            return []
        # Inspect every commit, including each merge parent and transient changes
        # later reverted. A forbidden commit refuses the entire delivery.
        commits = self.git('rev-list', f'{START}..{tip}').stdout.splitlines()
        for commit in commits:
            paths = self.git('diff-tree', '--root', '-m', '--no-commit-id', '--name-only',
                             '--no-renames', '-r', '-z', commit).stdout.split('\0')
            for name in filter(None, paths):
                path = Path(name)
                if (path.suffix != '.md' or any(part in ('.github', '.claude', '.agents', 'AGENTS.md')
                                              for part in path.parts)):
                    raise StateError('Planning commit refused: only unprotected *.md files may change; nothing pushed.')
            # Markdown symlinks and submodules must not smuggle non-document data.
            entries = self.git('ls-tree', '-r', '-z', commit).stdout.split('\0')
            for entry in filter(None, entries):
                mode, rest = entry.split(' ', 1)
                name = rest.split('\t', 1)[1]
                if Path(name).suffix == '.md' and mode not in ('100644', '100755'):
                    raise StateError('Planning commit refused: Markdown must be regular files; nothing pushed.')
        self.git('fetch', '--no-tags', 'origin', '+refs/heads/main:refs/remotes/origin/main', network='fetch')
        latest = self.git('rev-parse', 'refs/remotes/origin/main').stdout.strip()
        self.git('checkout', '-B', 'delivery', tip)
        rebased = self.git('rebase', '--onto', latest, previous, allow_failure=True)
        if rebased.returncode:
            self.git('rebase', '--abort', allow_failure=True)
            raise StateError('Planning rebase failed, possibly due to a conflict with main: nothing pushed. Resolve the conflicting changes in this session and try again.')
        head = self.git('rev-parse', 'HEAD').stdout.strip()
        if self.git('merge-base', '--is-ancestor', latest, head, allow_failure=True).returncode:
            raise StateError('Planning delivery refused: push would not fast-forward.')
        pushed = self.git('rev-list', '--reverse', f'{latest}..{head}').stdout.splitlines()
        self.git('push', 'origin', f'{head}:refs/heads/main', network='push')
        self.git('update-ref', DELIVERED, tip)
        return pushed
