"""Host side of fenced delivery. Agent copies are data, never Git working directories."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys

from .state import StateError
from . import deny

ROOT_UID = 0
CLI_UID = CLI_GID = 21000
WORK_ROOT = Path('/srv/factory/work')
CLEAN_ROOT = Path('/srv/factory/clean')
LOGIN_ROOT = Path('/srv/factory/logins')
TOKEN = Path('/etc/factory/github-token')


def fence_command():
    return os.environ.get('CPLANE_FENCE_COMMAND', 'factory-cli')


def host_environment():
    # A credential is added only for the one authenticated git/gh call.
    return {**{key: os.environ[key] for key in ('PATH', 'LANG', 'PYTHONPATH') if key in os.environ},
            'HOME': '/nonexistent', 'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}


def github_environment(repositories=None):
    env = host_environment()
    auth = os.environ.get('CPLANE_GITHUB_AUTH', 'token')
    if auth == 'app':
        from . import github_app
        if not repositories:
            raise StateError('GitHub App needs the repository of the call')
        env['GH_TOKEN'] = github_app.installation_token(repositories)
        return env
    if auth != 'token':
        raise StateError('CPLANE_GITHUB_AUTH must be token or app')
    fd = os.open(TOKEN, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise StateError('GitHub token must be a root-owned regular file with mode 0600')
        token = stream.read().strip()
    if not token or any(c.isspace() for c in token):
        raise StateError('GitHub token is missing or invalid')
    env['GH_TOKEN'] = token
    return env


def git_options():
    helper = '!' + shlex.join([sys.executable, '-m', 'cplane.fence', 'credential'])
    return ['-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
            '-c', 'core.sshCommand=/bin/false', '-c', 'credential.helper=',
            '-c', 'credential.helper=' + helper, '-c', 'protocol.ext.allow=never',
            '-c', 'transfer.fsckObjects=true']


def trusted_directory(path):
    """Only root-managed ancestors; do not resolve through an agent-planted link."""
    for part in [*reversed(path.parents), path]:
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise StateError('trusted directory contains a link or non-directory')
        # Sticky system temporary roots are needed by synthetic fixtures only.
        if part != path and info.st_mode & stat.S_ISVTX and info.st_uid == 0:
            continue
        if info.st_uid not in (0, ROOT_UID) or info.st_mode & 0o022:
            raise StateError('trusted directory must be root-owned and not writable by others')
    return path


def snapshot_bundle(folder):
    """Snapshot offline export data without following agent-owned links."""
    # Snapshot an untrusted regular file before giving it to Git. No symlink,
    # FIFO, hardlink or later path replacement can redirect the host's read.
    directory = os.open(folder / 'io', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open('branch.bundle', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as source, (folder / 'export.bundle').open('wb') as target:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise StateError('bundle export must be a regular file with one link')
            shutil.copyfileobj(source, target)
    finally:
        os.close(directory)
    bundle = folder / 'export.bundle'
    bundle.chmod(0o600)
    return bundle


class Fence:
    def __init__(self):
        self.begin_pass()

    def begin_pass(self):
        self.visibility = {}

    def is_public(self, repo):
        if repo not in self.visibility:
            public = True
            try:
                result = subprocess.run(
                    ['gh', 'api', f'repos/{repo}'], cwd='/', capture_output=True,
                    text=True, env=github_environment([repo]), timeout=30)
                if result.returncode == 0:
                    public = json.loads(result.stdout).get('private') is not True
            except Exception:
                # Authentication, network and malformed responses all fail closed.
                pass
            self.visibility[repo] = public
        return self.visibility[repo]

    def check_request(self, repo, request):
        if self.is_public(repo):
            deny.Check().request(request)

    def resume(self, previous, session):
        if not previous or not previous.get('fence'):
            raise StateError('fenced resume metadata unavailable; needs attention')
        if not session or not re.fullmatch(r'[A-Za-z0-9-]+', session):
            raise StateError('fenced resume session unavailable; needs attention')
        copy = Path(previous['repo'])
        if (copy.parent != WORK_ROOT or copy.is_symlink() or not copy.is_dir()):
            raise StateError('fenced resume copy unavailable; needs attention')
        tool = previous['tool']
        if tool == 'codex':
            found = any((path.name.endswith('-' + session + '.jsonl') or path.name == session + '.jsonl')
                        and path.is_file() and not path.is_symlink()
                        for path in (LOGIN_ROOT / 'codex/sessions').rglob('*.jsonl'))
        else:
            path = LOGIN_ROOT / 'claude/projects/-work' / (session + '.jsonl')
            found = path.is_file() and not path.is_symlink()
        if not found:
            raise StateError('fenced resume cannot find its session; needs attention')
        return {key: previous[key] for key in ('repo', 'repository', 'branch', 'base', 'default')}

    def clean(self, repo):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) or any(
                part in ('.', '..') for part in repo.split('/')):
            raise StateError('invalid GitHub repository')
        trusted_directory(CLEAN_ROOT)
        owner, name = repo.split('/')
        parent = CLEAN_ROOT / owner
        parent.mkdir(mode=0o700, exist_ok=True)
        trusted_directory(parent)
        return parent / (name + '.git')

    def git(self, clean, *args, auth=False, allow_failure=False):
        # This is the only host Git entry point for delivery. Never accept a work copy.
        if not clean.is_relative_to(CLEAN_ROOT) or clean == CLEAN_ROOT:
            raise StateError('host Git refused outside clean clones')
        trusted_directory(clean)
        repo = clean.parent.name + '/' + clean.name.removesuffix('.git')
        command = ['git', '-C', str(clean), *git_options(),
                   '-c', 'protocol.file.allow=always', *map(str, args)]
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    encoding='utf-8', errors='surrogateescape',
                                    env=github_environment([repo]) if auth else host_environment())
        except OSError:
            raise StateError('fenced Git could not run') from None
        if result.returncode and not allow_failure:
            # Like the DB adapter, suppress diagnostics, which can echo credentials.
            raise StateError('fenced Git operation failed')
        return result

    def prepare(self, repo, branch, copy_id):
        clean = self.clean(repo)
        if not clean.exists():
            clean.mkdir(mode=0o700)
            self.git(clean, 'init', '--bare', '--template=')
            self.git(clean, 'remote', 'add', 'origin', f'https://github.com/{repo}.git')
        self.git(clean, 'check-ref-format', 'refs/heads/' + branch)
        self.git(clean, 'fetch', '--prune', 'origin', '+refs/heads/*:refs/remotes/origin/*', auth=True)
        head = self.git(clean, 'ls-remote', '--symref', 'origin', 'HEAD', auth=True).stdout
        match = re.search(r'^ref: refs/heads/([^\s]+)\s+HEAD$', head, re.M)
        if not match:
            raise StateError('GitHub default branch unavailable')
        default = match[1]
        if branch == default:
            raise StateError('slice branch must not be the default branch')
        base = self.git(clean, 'rev-parse', '--verify', f'refs/remotes/origin/{default}^{{commit}}').stdout.strip()
        self.git(clean, 'update-ref', f'refs/heads/{branch}', base)
        trusted_directory(WORK_ROOT)
        copy = WORK_ROOT / copy_id
        if copy.exists() or copy.is_symlink():
            raise StateError('work copy already exists')
        # All Git executes in the clean clone. Destination has no hooks, templates,
        # global config, hardlinks, or credentialed URL, and is not yet agent-owned.
        self.git(clean, 'clone', '--no-hardlinks', '--template=', '--single-branch',
                 '--branch', branch, '--config', 'core.hooksPath=/dev/null',
                 '--config', 'user.name=Factory', '--config', 'user.email=factory@localhost',
                 str(clean), str(copy))
        copy.chmod(0o700)
        for directory, folders, files in os.walk(copy, followlinks=False):
            for name in [*folders, *files]:
                os.chown(Path(directory) / name, CLI_UID, CLI_GID, follow_symlinks=False)
        os.chown(copy, CLI_UID, CLI_GID)
        return {'repo': str(copy), 'repository': repo, 'branch': branch,
                'base': base, 'default': default}

    def publish(self, job, request):
        if request['branch'] != job['branch'] or job['branch'] == job['default']:
            raise StateError('bundle refused: branch is not the slice branch or is the default branch')
        clean = self.clean(job['repository'])
        folder = trusted_directory(Path(job['run']))
        result = subprocess.run([fence_command(), 'bundle', '--repo', job['repo'],
                                 '--run', str(folder / 'io'), '--branch', job['branch']],
                                cwd=folder, capture_output=True, env=host_environment())
        if result.returncode:
            raise StateError('fenced bundle export failed')
        bundle = snapshot_bundle(folder)
        heads = self.git(clean, 'bundle', 'list-heads', bundle).stdout.splitlines()
        refs = dict(line.split(' ', 1)[::-1] for line in heads)
        expected = 'refs/heads/' + job['branch']
        if set(refs) != {'HEAD', expected} or refs['HEAD'] != refs[expected]:
            raise StateError('bundle refused: wrong branch or HEAD')
        self.git(clean, 'bundle', 'verify', bundle)
        imported = 'refs/factory/import/' + folder.name
        self.git(clean, 'fetch', '--no-tags', '--no-write-fetch-head', bundle, f'+{expected}:{imported}')
        tip = self.git(clean, 'rev-parse', '--verify', imported + '^{commit}').stdout.strip()
        if self.git(clean, 'merge-base', '--is-ancestor', job['base'], tip, allow_failure=True).returncode:
            raise StateError('bundle refused: branch does not descend from the base commit')
        # Recheck the current remote default before any push, too.
        head = self.git(clean, 'ls-remote', '--symref', 'origin', 'HEAD', auth=True).stdout
        match = re.search(r'^ref: refs/heads/([^\s]+)\s+HEAD$', head, re.M)
        if not match:
            raise StateError('GitHub default branch unavailable')
        if match[1] == job['branch']:
            raise StateError('bundle refused: slice branch is now the default branch')
        if self.is_public(job['repository']):
            check = deny.Check()
            check.request(request)
            check.commits(lambda *args: self.git(clean, *args), job['base'], tip)
        result = self.git(clean, 'push', '--porcelain', 'origin', f'{tip}:{expected}',
                          auth=True, allow_failure=True)
        if result.returncode:
            if re.search(r'\[rejected\].*(?:non-fast-forward|fetch first)', result.stdout):
                raise StateError('branch was rewritten; merge main instead of rebasing')
            raise StateError('fenced Git operation failed')
        return tip


if __name__ == '__main__':
    # Git's helper protocol: the token is returned only to Git, never persisted.
    if sys.argv[1:] == ['credential', 'get']:
        print('username=x-access-token')
        print('password=' + os.environ['GH_TOKEN'])
