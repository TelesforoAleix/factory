"""Root entry point. Only recorded, allowlisted commits reachable from main run."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

from . import fence, installation, state
from .executors import atomic_json

INSTALL_ROOT = Path('/var/lib/factory/install')
OUTPUT_LIMIT = 8192


class InstallFailed(state.StateError):
    def __init__(self, sha, repository, result):
        super().__init__('Install failed; rollback attempted; migrations remain applied')
        self.record = dict(ok=False, commit=sha, repository=repository,
                           stderr=output_tail(result.stderr), stdout=output_tail(result.stdout))


def output_tail(output):
    return (output or '').encode('utf-8')[-OUTPUT_LIMIT:].decode('utf-8', errors='ignore')


def github(repo, path, *, output=None):
    result = subprocess.run(['gh', 'api', '--hostname', 'github.com', f'repos/{repo}/{path}'],
                            env=fence.github_environment(), stdout=output or subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    if result.returncode:
        raise state.StateError('Install download or verification failed')
    return json.loads(result.stdout) if output is None else None


def unpack(archive, target):
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if not members or any(not (m.isfile() or m.isdir()) for m in members):
            raise state.StateError('Install archive contains unsupported entries')
        roots = {Path(m.name).parts[0] for m in members if Path(m.name).parts}
        if len(roots) != 1 or any(Path(m.name).is_absolute() or '..' in Path(m.name).parts for m in members):
            raise state.StateError('Install archive contains invalid paths')
        source.extractall(target, filter='data')
        return target / roots.pop()


def install(slice_id, request=None):
    path = Path(os.environ['CPLANE_STATE']).expanduser().resolve()
    runs = installation.runs_path(path)
    with state.locked(path):
        data = state.load(path)
        item = next((s for s in data['slices'] if s['id'] == slice_id), None)
        if item is None:
            raise state.StateError('Unknown install slice')
        attention = item['attention']
        if not attention or attention['kind'] != 'node-step' or attention['answer'] is not None:
            raise state.StateError('Install requires an open node step')
        requests = [r for s, r in installation.pending(data) if s['id'] == slice_id]
        if request is not None and request not in requests:
            raise state.StateError('Install request is no longer pending')
        jobs = [(p, json.loads(p.read_text())) for p in runs.glob('*/job.json')]
        job_path, job = max(((p, j) for p, j in jobs if j['id'] == slice_id),
                            key=lambda pair: pair[1]['started_ns'], default=(None, {}))
        repo, sha = item['repo'], job.get('sha', '')
        if job.get('phase') != 'node-step' or job.get('repository', repo) != repo or not re.fullmatch('[0-9a-f]{40}', sha):
            raise state.StateError('Install requires recorded merge metadata')
        if repo not in os.environ.get('CPLANE_INSTALL_REPOS', '').split(',') or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise state.StateError('Install repository is not allowlisted')
        installation.check_commit(job, repo)
        # Pin the first attempt durably before any download or root execution.
        job.update(install_sha=sha, install_repository=repo)
        atomic_json(job_path, job)
    comparison = github(repo, f'compare/{sha}...main')
    if comparison.get('status') not in ('ahead', 'identical') or comparison.get('merge_base_commit', {}).get('sha') != sha:
        raise state.StateError('Install commit is not on main')
    with tempfile.TemporaryDirectory(prefix='stage-', dir=INSTALL_ROOT) as folder:
        folder = Path(folder)
        archive = folder / 'source.tar.gz'
        with archive.open('wb') as output:
            github(repo, f'tarball/{sha}', output=output)
        stage = unpack(archive, folder / 'source')
        script = stage / 'node/install'
        if not script.is_file():
            raise state.StateError('Commit has no node/install')
        # Never pass GitHub credentials to the installer or its build processes.
        env = {k: v for k, v in os.environ.items() if k.startswith('CPLANE_') or k in ('PATH', 'LANG')}
        env['HOME'] = '/root'
        result = subprocess.run(['/usr/bin/python3', str(script), str(stage), sha],
                                env=env, capture_output=True, text=True, errors='replace')
        if result.returncode:
            raise InstallFailed(sha, repo, result)
        answer = json.loads(result.stdout)
        return {'ok': True, 'commit': sha, 'manual': answer['manual']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('slice_id')
    parser.add_argument('--request')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('factory-install requires root')
    if args.request and not re.fullmatch('[0-9a-f]{32}', args.request):
        parser.error('invalid request')
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    fence.trusted_directory(INSTALL_ROOT)
    if args.request is None:
        try:
            path = Path(os.environ['CPLANE_STATE'])
            with state.locked(path):
                state.update_locked(path, args.slice_id, 'install', 'owner', installation.request_change('owner'))
                request = next(r for s, r in installation.pending(state.load(path)) if s['id'] == args.slice_id)
            if installation.start_unit(args.slice_id, request, installation.runs_path(path) / 'installs'):
                print('Install unit requested')
                return 0
        except Exception:
            pass
        print('Install could not be requested')
        return 1
    answer = {'ok': False}
    try:
        with (INSTALL_ROOT / 'lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print('An install is already running')
                return 1
            try:
                answer = install(args.slice_id, args.request)
            except InstallFailed as error:
                answer = error.record
            except Exception:
                # Download/service diagnostics can carry credentials; only script output is retained.
                print('Install failed; inspect the installation and services (migrations are not undone)')
            directory = installation.runs_path(os.environ['CPLANE_STATE']) / 'installs'
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_json(directory / (args.request + '.json'), answer)
    except Exception:
        print('Install could not be recorded')
        return 1
    print(json.dumps(answer))
    return 0 if answer['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
