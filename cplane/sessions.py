"""Database-driven fenced conversation turns. No web execution path."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import ctypes
from datetime import datetime, timezone
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

from .fence import Fence, trusted_directory, host_environment, WORK_ROOT, own
from . import prompts, run_records, skills
from .workshop import WorkshopServer, KINDS as WORKSHOP_KINDS
from factory_ui.documents import Documents
from .planning import Planning, sessions_clean_root
from . import fence
from .state import StateError, database_url
from .stores import PostgresStore, REPOSITORY

PLANNING_EXPORT = 'factory-planning-export'
BRIEFS = Path('/srv/factory/briefs')
RUNS = Path(os.environ.get('CPLANE_SESSION_RUNS', '/srv/factory/runs'))
LOCK = Path(os.environ.get('CPLANE_SESSIONS_LOCK', '/run/factory-sessions.lock'))
LOG = logging.getLogger(__name__)


def _briefs_owner_uid():
    setting = os.environ.get('CPLANE_BRIEFS_OWNER_UID')
    if setting is not None and (not setting.isascii() or not setting.isdecimal()):
        raise StateError('Invalid CPLANE_BRIEFS_OWNER_UID')
    return int(setting) if setting is not None else None


def _trusted_export_clone(clone, owner_uid):
    if owner_uid is None:
        return trusted_directory(clone)
    # Only the clone itself may have this additional owner; ancestors retain
    # their usual checks. This exception is used only for the briefs clone.
    trusted_directory(clone.parent)
    info = clone.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid(), owner_uid)
            or info.st_mode & 0o022):
        raise StateError('Untrusted document clone directory')
    return clone


def export_tree(clone, destination, ref, *, markdown_only=False, owner_uid=None):
    """Only trusted clone Git; omit links and reject unsafe archive entries."""
    _trusted_export_clone(clone, owner_uid)
    safe = ['-c', f'safe.directory={clone}'] if owner_uid is not None else []
    result = subprocess.run(['git', '-C', str(clone), *safe, '-c', 'core.hooksPath=/dev/null',
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
        return archive.pax_headers.get('comment')


UI_DOCS = Path(os.environ.get('CPLANE_UI_DOCS', '/var/lib/factory/ui-docs'))


class DocumentExporter:
    """Publish committed Markdown only; no Git pull and no agent-owned inputs."""

    def __init__(self, clone=BRIEFS, destination=UI_DOCS):
        self.clone, self.destination = clone, destination
        self.head = None

    def refresh(self):
        owner_uid = _briefs_owner_uid()
        _trusted_export_clone(self.clone, owner_uid)
        head = subprocess.run(
            ['git', '-C', str(self.clone), '-c', f'safe.directory={self.clone}',
             '-c', 'core.hooksPath=/dev/null',
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
                export_tree(self.clone, tree, head, markdown_only=True, owner_uid=owner_uid)
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


def session_directory(info):
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and info.st_gid == fence.CLI_GID and stat.S_IMODE(info.st_mode) == 0o1770)


def repository_fence():
    return Fence(clean_root=sessions_clean_root())


def workspace(session):
    repositories = session['repositories']
    if (not isinstance(repositories, list) or any(
            not isinstance(repository, str) or not REPOSITORY.fullmatch(repository)
            for repository in repositories)):
        raise StateError('Invalid session repository')
    if any(r.split('/')[1].lower() == PLANNING_EXPORT for r in repositories):
        raise StateError('Repository collides with planning export')
    trusted_directory(WORK_ROOT)
    folder = WORK_ROOT / f'session-{session["id"]}'
    # Older first-turn failures may have a complete workspace but no resume ID.
    # Reuse only through the same ownership/mode/export checks as provider rollover.
    exists = os.path.lexists(folder)
    retry_workspace = session.get('_restart') and exists
    if exists and not session.get('cli_session_id'):
        info = folder.lstat()
        reusable = (retry_workspace or session.get('workspace_ready')) and session_directory(info)
        if reusable:
            components = [folder / 'repos', *(folder / 'repos' / r.split('/')[1] for r in repositories)]
            if session.get('area') != 'homelab':
                components.append(folder / 'repos' / PLANNING_EXPORT)
            try:
                for component in components:
                    info = component.lstat()
                    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
                        reusable = False
                        break
            except OSError:
                reusable = False
        if not reusable:
            fence.remove(folder, 'work')
            retry_workspace = False
            session['workspace_ready'] = False
    if session['cli_session_id'] or session.get('workspace_ready') or retry_workspace:
        # Never refresh or walk the workspace on resume. Only Factory-owned
        # installed instructions may have their read modes repaired.
        info = folder.lstat()
        if not session_directory(info):
            raise StateError('Workspace unavailable')
        skills.ensure_readable(folder, session.get('skill_names'))
    else:
        # mkdir is exclusive: an interrupted or planted workspace is never reused.
        fence.require_ownership_support()
        folder.mkdir(mode=0o700)
        repos = folder / 'repos'
        repos.mkdir(mode=0o755)
        repos.chmod(0o755)
        if session.get('area') == 'homelab':
            Planning(session).prepare(folder / 'planning')
        else:
            # Reuse the existing read-only repository mount contract. Repository
            # The reserved export name is rejected in repository lists.
            export_tree(BRIEFS, repos / PLANNING_EXPORT, 'HEAD', owner_uid=_briefs_owner_uid())
            (repos / PLANNING_EXPORT).chmod(0o755)
            (folder / 'planning').symlink_to('repos/' + PLANNING_EXPORT)
        adapter = repository_fence() if session['repositories'] else None
        for repository in session['repositories']:
            _, name = repository.split('/')
            with adapter.locked_clean(repository) as clean:
                head = adapter.git(clean, 'ls-remote', '--symref', 'origin', 'HEAD', auth=True).stdout
                match = re.search(r'^ref: refs/heads/([^\s]+)\s+HEAD$', head, re.M)
                if not match:
                    raise StateError('GitHub default branch unavailable')
                commit = export_tree(clean, repos / name, f'refs/remotes/origin/{match[1]}')
                if len(repositories) == 1:
                    session['_starting_commit'] = commit
                (repos / name).chmod(0o755)
        skills.install(folder, session.get('skill_names') if session.get('skill_names') is not None else sorted(skills.DEFAULTS))
        # Transfer planning only while the session is still private to Factory.
        if session.get('area') == 'homelab':
            own(folder / 'planning', 'work', recursive=True)
        os.chown(folder, -1, fence.CLI_GID)
        folder.chmod(0o1770)
    paths = []
    for repository in session['repositories']:
        path = folder / 'repos' / repository.split('/')[1]
        # Reject any agent replacement, including an ancestor symlink. No recursion.
        for component in (folder / 'repos', path):
            info = component.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
                raise StateError('Repository export replaced')
        paths.append(path)
    if session.get('area') != 'homelab':
        readonly = folder / 'repos' / PLANNING_EXPORT
        for component in (folder / 'repos', readonly):
            info = component.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o022:
                raise StateError('Planning export replaced')
        paths.append(readonly)
    return folder, paths


def turn_command(turn, folder, paths, run, *, accounting=None):
    session = turn['session']
    tool = session['tool']
    args = [*fence.fence_command(), 'run', '--tool', tool, '--repo', str(folder), '--run', str(run),
            '--session-turn', str(turn['id'])]
    for path in paths:
        args += ['--read-only-path', str(path)]
    if tool == 'codex':
        command = ['codex', 'exec', '--skip-git-repo-check', '--json', '-m', session['model'],
                   '-c', f'model_reasoning_effort="{session["effort"]}"']
        if session.get('kind') in WORKSHOP_KINDS:
            command += ['-c', 'mcp_servers.workshop.command="python3"',
                        '-c', 'mcp_servers.workshop.args=["/run/factory/workshop_mcp.py"]']
        if session['cli_session_id']:
            command += ['resume', session['cli_session_id']]
    else:
        command = ['claude', '-p', '--output-format', 'json', '--model', session['model'], '--effort', session['effort']]
        if session.get('kind') in WORKSHOP_KINDS:
            command += ['--mcp-config', '/run/factory/workshop-mcp.json']
        if session['cli_session_id']:
            command += ['--resume', session['cli_session_id']]
    prompt = ('Workshop event: ' if turn.get('role') == 'system' else '') + turn['text']
    if turn.get('context'):
        prompt = turn['context'] + '\n\nCurrent message:\n' + prompt
    loaded_prompts = []
    if session.get('kind') in WORKSHOP_KINDS:
        prompt += f'\n\nCurrent message ID: {turn["id"]}'
        name = 'secretary' if session.get('kind') == 'secretary' else 'chat'
        prompt += '\n\n' + prompts.text(name)
        loaded_prompts.append(name)
    if session.get('area') == 'homelab':
        prompt += '\n\n' + prompts.text('homelab')
        loaded_prompts.append('homelab')
    if accounting is not None:
        accounting['context'] = run_records.chat_context(folder, session, loaded_prompts)
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
    accounting = {}
    try:
        return _execute_turn(turn, store, accounting)
    finally:
        if 'started' in accounting:
            run_records.chat_record(store, turn, accounting)


def _execute_turn(turn, store, accounting):
    reason = 'Workspace could not be prepared.'
    try:
        session = turn['session']
        if session.get('cli_session_id'):
            trusted_directory(WORK_ROOT)
            folder = WORK_ROOT / f'session-{session["id"]}'
            try:
                valid = session_directory(folder.lstat())
            except FileNotFoundError:
                valid = False
            if not valid:
                if os.path.lexists(folder):
                    fence.remove(folder, 'work')
                store.reset_session_context(session['id'])
                session.update(cli_session_id=None, workspace_ready=False)
        folder, paths = workspace(session)
        reason = 'The model tool could not complete the turn.'
        trusted_directory(RUNS)
        run = RUNS / f'session-turn-{turn["id"]}'
        run.mkdir(mode=0o700)  # Factory-owned; no agent output files to follow
        command = turn_command(turn, folder, paths, run, accounting=accounting)
        run_records.save_context(run, accounting['context'])
        accounting['started'] = time.time()
        workshop = (WorkshopServer(run, PostgresStore(store._url), turn['session']['id'],
                                   Documents(UI_DOCS))
                    if turn['session'].get('kind') in WORKSHOP_KINDS else nullcontext())
        with workshop:
            result = subprocess.run(command,
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                    env=host_environment())
        accounting['output'] = result.stdout
        accounting['ended'] = time.time()
        if result.returncode == 125:
            # Do not free capacity while Docker cleanup is uncertain.
            raise CleanupError('Container cleanup failed')
        if result.returncode:
            LOG.error('Session turn %s exited %s', turn['id'], result.returncode)
            reply = 'Turn timed out after 20 minutes.' if result.returncode == 124 else 'The model tool exited with an error.'
            store.finish_session_turn(turn, reply, failed=True)
            return
        cli_id, reply = parse_reply(turn['session']['tool'], result.stdout)
        accounting['outcome'] = 'completed'
        commits = []
        if turn['session'].get('area') == 'homelab':
            io_folder = run / 'io'
            io_folder.mkdir(mode=0o750)
            io_folder.chmod(0o750)
            fence.own(io_folder, 'run')
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
    except Exception:
        LOG.error('Session turn %s failed', turn['id'])
        store.finish_session_turn(turn, reason, failed=True)
        return
    if commits:
        store.finish_session_turn(turn, reply, cli_id, planning_commits=commits)
    else:
        store.finish_session_turn(turn, reply, cli_id)


def cleanup_interrupted_turn(turn):
    subprocess.run([*fence.fence_command(), 'session-cleanup', str(turn['id'])], check=True,
                   stdout=subprocess.DEVNULL)
    run = RUNS / f'session-turn-{turn["id"]}'
    if run.exists():
        # Service termination closes the listener but can leave its directory
        # entry. Only traverse the host-owned run tree after container cleanup.
        trusted_directory(run)
        (run / 'workshop.sock').unlink(missing_ok=True)


def reap_turns(active, store):
    for future in list(active):
        if future.done():
            turn = active.pop(future)
            try:
                future.result()
            except Exception:
                LOG.error('Session turn %s failed unexpectedly', turn['id'])
                try:
                    store.finish_session_turn(turn, 'Turn failed unexpectedly.', failed=True)
                except Exception:
                    LOG.exception('Could not record session turn %s failure', turn['id'])


def main():
    # Enforce this before any recovery, model probe or worker can contact GitHub.
    os.environ['CPLANE_GITHUB_READ_ONLY'] = '1'
    if os.environ.get('CPLANE_GITHUB_AUTH', 'token') != 'app':
        raise StateError('Sessions requires CPLANE_GITHUB_AUTH=app; '
                         'token mode cannot be narrowed to read-only')
    logging.basicConfig(level=logging.INFO)
    url = database_url()
    # One supervisor on the node; DB claims additionally serialize capacity checks.
    with open(LOCK, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        store = PostgresStore(url)
        from .models import recover_catalog_runs
        recover_catalog_runs()
        store.models_recover()
        for turn in store.interrupted_session_turns():
            try:
                cleanup_interrupted_turn(turn)
                run_records.chat_record(store, turn, {
                    'outcome': 'interrupted',
                    'context': run_records.saved_context(RUNS / f'session-turn-{turn["id"]}')})
                store.finish_session_turn(turn, 'Turn interrupted. Send a message to start a new session.', failed=True)
            except Exception:
                LOG.exception('Session turn %s cleanup failed', turn['id'])
                try:
                    store.finish_session_turn(turn, 'Turn cleanup failed.', failed=True)
                except Exception:
                    LOG.error('Could not record session turn %s failure', turn['id'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            active = {}
            exporter = DocumentExporter()
            next_export = 0
            while True:
                if not active:
                    store.models_process_one()
                if time.monotonic() >= next_export:
                    try:
                        exporter.refresh()
                    except Exception:
                        LOG.exception('Document export failed; keeping previous export')
                    next_export = time.monotonic() + 60
                reap_turns(active, store)
                while len(active) < 2:
                    turn = store.claim_session_turn()
                    if turn is None:
                        break
                    active[pool.submit(execute_turn, turn, PostgresStore(url))] = turn
                time.sleep(2)


if __name__ == '__main__':
    main()
