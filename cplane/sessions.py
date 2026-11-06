"""Root-only, database-driven fenced conversation turns. No web execution path."""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import io
import json
import logging
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import time

from .fence import Fence, trusted_directory, host_environment, WORK_ROOT
from .state import StateError
from .stores import PostgresStore, REPOSITORY

BRIEFS = Path('/srv/factory/briefs')
RUNS = Path('/srv/factory/runs')
LOG = logging.getLogger(__name__)


def export_tree(clone, destination, ref):
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
            members.append(member)
        destination.mkdir(mode=0o700)
        archive.extractall(destination, members=members, filter='data')


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
        export_tree(BRIEFS, folder / 'planning', 'HEAD')
        repos = folder / 'repos'
        repos.mkdir(mode=0o755)
        repos.chmod(0o755)
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
    return [*args, '--', *command, '--', turn['text']]


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
    except CleanupError:
        raise
    except Exception:
        LOG.exception('Session turn %s failed', turn['id'])
        store.finish_session_turn(turn, 'Turn failed. Create a new session.', failed=True)
        return
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
            while True:
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
