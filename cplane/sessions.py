"""Root-only, database-driven fenced conversation turns. No web execution path."""
from concurrent.futures import ThreadPoolExecutor
import ctypes
import fcntl
import io
import json
import logging
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import tarfile
import time

from .fence import Fence, trusted_directory, host_environment, WORK_ROOT
from .planning import Planning
from .state import StateError
from .stores import PostgresStore, REPOSITORY

BRIEFS = Path('/srv/factory/briefs')
RUNS = Path('/srv/factory/runs')
LOG = logging.getLogger(__name__)
HOMELAB_INSTRUCTION = (
    'A change to planning/ reaches main only when it is committed there with '
    'git add and git commit. Commit each agreed change in the turn that makes it, '
    'with a short message. Only unprotected Markdown files may change.'
)


def export_tree(clone, destination, ref, *, markdown_only=False):
    """Only trusted clone Git; omit links and reject unsafe archive entries."""
    trusted_directory(clone)
    result = subprocess.run(['git', '-C', str(clone), '-c', 'core.hooksPath=/dev/null',
                             '-c', 'core.fsmonitor=false', 'archive', '--format=tar', ref],
                            capture_output=True, check=True, env=host_environment())
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        members = []
        for member in archive.getmembers():
            path = Path(member.name)
            if path.is_absolute() or '..' in path.parts or '.git' in path.parts:
                raise StateError('Export contains unsafe entries')
            if member.issym() or member.islnk():
                continue
            if not (member.isfile() or member.isdir()):
                raise StateError('Export contains unsafe entries')
            if markdown_only and not (member.isfile() and path.suffix == '.md'):
                continue
            members.append(member)
        destination.mkdir(mode=0o700)
        archive.extractall(destination, members=members, filter='data')


UI_DOCS = Path('/var/lib/factory/ui-docs')


class DocumentExporter:
    """Publish committed Markdown only; no Git pull and no agent-owned inputs."""

    def __init__(self, clone=BRIEFS, destination=UI_DOCS):
        self.clone, self.destination = clone, destination
        self.head = None

    def refresh(self):
        trusted_directory(self.clone)
        head = subprocess.run(
            ['git', '-C', str(self.clone), '-c', 'core.hooksPath=/dev/null',
             '-c', 'core.fsmonitor=false', 'rev-parse', '--verify', 'HEAD^{commit}'],
            capture_output=True, check=True, text=True, env=host_environment()).stdout.strip()
        if head == self.head:
            return False
        parent = self.destination.parent
        trusted_directory(parent)
        # Shared reader lock prevents deleting an old generation during a read.
        lock_fd = os.open(parent / '.ui-docs.lock', os.O_CREAT | os.O_RDONLY | os.O_NOFOLLOW, 0o644)
        os.fchmod(lock_fd, 0o644)
        try:
            with tempfile.TemporaryDirectory(prefix='.ui-docs-', dir=parent) as staging:
                tree = Path(staging) / 'tree'
                export_tree(self.clone, tree, head, markdown_only=True)
                for directory, _, filenames in os.walk(tree):
                    Path(directory).chmod(0o755)
                    for name in filenames:
                        (Path(directory) / name).chmod(0o644)
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                if self.destination.is_symlink():
                    raise StateError('Invalid document export destination')
                if self.destination.exists():
                    if not self.destination.is_dir():
                        raise StateError('Invalid document export destination')
                    # Linux rename exchange leaves the public path present even
                    # across a process crash. Both trees are plain directories.
                    libc = ctypes.CDLL(None, use_errno=True)
                    if libc.renameat2(-100, os.fsencode(tree), -100,
                                      os.fsencode(self.destination), 2) != 0:
                        raise OSError(ctypes.get_errno(), 'Document exchange failed')
                else:
                    os.rename(tree, self.destination)
                self.head = head
                return True
        finally:
            os.close(lock_fd)


def workspace(session):
    repositories = session['repositories']
    if (not isinstance(repositories, list) or any(
            not isinstance(repository, str) or not REPOSITORY.fullmatch(repository)
            for repository in repositories)):
        raise StateError('Invalid session repository')
    trusted_directory(WORK_ROOT)
    folder = WORK_ROOT / f'session-{session["id"]}'
    if session['cli_session_id']:
        # Never repair, refresh, walk or write an agent-owned workspace on resume.
        info = folder.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 21000
                or stat.S_IMODE(info.st_mode) != 0o700):
            raise StateError('Workspace unavailable')
    else:
        # mkdir is exclusive: an interrupted or planted workspace is never reused.
        folder.mkdir(mode=0o700)
        repos = folder / 'repos'
        repos.mkdir(mode=0o755)
        repos.chmod(0o755)
        if session.get('area') == 'homelab':
            Planning(session).prepare(folder / 'planning')
        else:
            # Reuse the existing read-only repository mount contract. Repository
            # names cannot start with '.', so this reserved export cannot collide.
            export_tree(BRIEFS, repos / '.planning', 'HEAD')
            (repos / '.planning').chmod(0o755)
            (folder / 'planning').symlink_to('repos/.planning')
        fence = Fence()
        for repository in session['repositories']:
            _, name = repository.split('/')
            clean = fence.clean(repository)
            if not clean.exists():
                clean.mkdir(mode=0o700)
                fence.git(clean, 'init', '--bare', '--template=')
                fence.git(clean, 'remote', 'add', 'origin', f'https://github.com/{repository}.git')
            fence.git(clean, 'fetch', '--prune', 'origin', '+refs/heads/*:refs/remotes/origin/*', auth=True)
            head = fence.git(clean, 'ls-remote', '--symref', 'origin', 'HEAD', auth=True).stdout
            match = re.search(r'^ref: refs/heads/([^\s]+)\s+HEAD$', head, re.M)
            if not match:
                raise StateError('GitHub default branch unavailable')
            export_tree(clean, repos / name, f'refs/remotes/origin/{match[1]}')
            (repos / name).chmod(0o755)
        # Chown planning only, while workspace remains root-owned and inaccessible.
        if session.get('area') == 'homelab':
            for directory, folders, files in os.walk(folder / 'planning', followlinks=False):
                for name in [*folders, *files]:
                    os.chown(Path(directory) / name, 21000, 21000, follow_symlinks=False)
            os.chown(folder / 'planning', 21000, 21000)
        os.chown(folder, 21000, 21000)
    paths = []
    for repository in session['repositories']:
        path = folder / 'repos' / repository.split('/')[1]
        # Reject any agent replacement, including an ancestor symlink. No recursion.
        for component in (folder / 'repos', path):
            info = component.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise StateError('Repository export replaced')
        paths.append(path)
    if session.get('area') != 'homelab':
        readonly = folder / 'repos/.planning'
        for component in (folder / 'repos', readonly):
            info = component.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise StateError('Planning export replaced')
        paths.append(readonly)
    return folder, paths


def turn_command(turn, folder, paths, run):
    session = turn['session']
    tool = session['tool']
    args = ['factory-cli', 'run', '--tool', tool, '--repo', str(folder), '--run', str(run),
            '--session-turn', str(turn['id'])]
    for path in paths:
        args += ['--read-only-path', str(path)]
    if tool == 'codex':
        command = ['codex', 'exec', '--skip-git-repo-check', '--json', '-m', session['model'],
                   '-c', 'model_reasoning_effort="medium"']
        if session['cli_session_id']:
            command += ['resume', session['cli_session_id']]
    else:
        command = ['claude', '-p', '--output-format', 'json', '--model', session['model']]
        if session['cli_session_id']:
            command += ['--resume', session['cli_session_id']]
    prompt = turn['text']
    if session.get('area') == 'homelab':
        prompt += '\n\n' + HOMELAB_INSTRUCTION
    return [*args, '--', *command, '--', prompt]


def parse_reply(tool, output):
    if tool == 'claude':
        reply = json.loads(output)
        if reply.get('is_error'):
            raise StateError('CLI failed')
        cli_id, text = reply.get('session_id'), reply.get('result')
    else:
        cli_id, parts = None, []
        for line in output.splitlines():
            event = json.loads(line)
            if event.get('type') == 'thread.started':
                cli_id = event.get('thread_id')
            if event.get('type') == 'item.completed' and event.get('item', {}).get('type') == 'agent_message':
                parts.append(event['item']['text'])
        text = '\n\n'.join(parts)
    if not isinstance(cli_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,100}', cli_id) or not isinstance(text, str) or not text.strip():
        raise StateError('CLI returned no reply or resume id')
    return cli_id, text


class CleanupError(RuntimeError):
    pass


def execute_turn(turn, store):
    try:
        folder, paths = workspace(turn['session'])
        trusted_directory(RUNS)
        run = RUNS / f'session-turn-{turn["id"]}'
        run.mkdir(mode=0o700)  # root-owned; no agent output files to follow
        result = subprocess.run(turn_command(turn, folder, paths, run),
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                env=host_environment())
        if result.returncode == 125:
            # Do not free capacity while Docker cleanup is uncertain.
            raise CleanupError('Container cleanup failed')
        if result.returncode:
            LOG.error('Session turn %s exited %s: %s', turn['id'], result.returncode, result.stderr)
            reply = 'Turn timed out after 20 minutes.' if result.returncode == 124 else 'Turn failed. Create a new session.'
            store.finish_session_turn(turn, reply, failed=True)
            return
        cli_id, reply = parse_reply(turn['session']['tool'], result.stdout)
        commits = []
        if turn['session'].get('area') == 'homelab':
            io_folder = run / 'io'
            io_folder.mkdir(mode=0o700)
            os.chown(io_folder, 21000, 21000)
            try:
                commits = Planning(turn['session']).deliver(folder / 'planning', run)
            except (StateError, OSError) as error:
                # Only fixed messages from the delivery boundary reach the page;
                # Git diagnostics, arguments and environments are never logged.
                reply += '\n\nPlanning delivery stopped. See the delivery notice.'
                store.finish_session_turn(turn, reply, cli_id,
                                          delivery_notice=(str(error) if isinstance(error, StateError) else
                                                           'Planning delivery failed; nothing confirmed pushed.'))
                return
    except CleanupError:
        raise
    except Exception:
        LOG.exception('Session turn %s failed', turn['id'])
        store.finish_session_turn(turn, 'Turn failed. Create a new session.', failed=True)
        return
    if commits:
        store.finish_session_turn(turn, reply, cli_id, planning_commits=commits)
    else:
        store.finish_session_turn(turn, reply, cli_id)


def main():
    logging.basicConfig(level=logging.INFO)
    url = os.environ.get('CPLANE_DATABASE_URL')
    # One supervisor on the node; DB claims additionally serialize capacity checks.
    with open('/run/factory-sessions.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        store = PostgresStore(url)
        for turn in store.interrupted_session_turns():
            subprocess.run(['factory-cli', 'session-cleanup', str(turn['id'])], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            store.finish_session_turn(turn, 'Turn interrupted. Create a new session.', failed=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            active = []
            exporter = DocumentExporter()
            next_export = 0
            while True:
                if time.monotonic() >= next_export:
                    try:
                        exporter.refresh()
                    except Exception:
                        LOG.exception('Document export failed; keeping previous export')
                    next_export = time.monotonic() + 60
                for future in list(active):
                    if future.done():
                        future.result()  # database failures stop service; restart reconciles
                        active.remove(future)
                while len(active) < 2:
                    turn = store.claim_session_turn()
                    if turn is None:
                        break
                    active.append(pool.submit(execute_turn, turn, PostgresStore(url)))
                time.sleep(2)


if __name__ == '__main__':
    main()
