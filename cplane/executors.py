"""Executor adapters and detached turn supervisor; no shell interpretation."""
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import time

from . import fence
from .text_bounds import TAIL_LIMIT, cut, failure_tail

FINAL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["kind", "body"],
    "properties": {"kind": {"type": "string", "enum": ["handover", "question", "escalation", "waiting"]},
                   "body": {"type": "string"}},
}
FENCE_PARAGRAPH = '\n\nGitHub steps: there is no GitHub credential in this container and nothing can be pushed from inside. Commit your work on the assigned branch and end with kind "waiting". Its body must begin with a fenced JSON block containing {"branch": "your branch", "title": "PR title", "body": "PR description", "node_steps": null}. Set node_steps to text instead of null if work on the owner node is needed after merging. The runner opens the PR, checks CI, obtains any required merge approval, and merges it. It resumes you with "merged as <sha>"; then write your handover.'


def fenced():
    return os.environ.get('CPLANE_FENCE') == '1'


def read_output(path):
    """Read one untrusted output file without following links or opening devices."""
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'r', errors='replace') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError('executor output must be a regular file with one link')
            return stream.read()
    finally:
        os.close(directory)


def atomic_json(path, data):
    temp = path.with_suffix('.tmp')
    with temp.open('w') as stream:
        os.chmod(temp, 0o600)
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def command(job):
    folder = Path(job['run'])
    if job['tool'] == 'codex':
        args = ['codex', 'exec', '-m', job['model'], '-c',
                f'model_reasoning_effort="{job.get("effort", "medium")}"',
                '--output-schema', '/run/factory/schema.json', '--json',
                '-o', '/run/factory/last.json']
        if job.get('resume'):
            args += ['resume', job['resume']]
    else:
        args = ['claude', '-p', '--model', job['model'], '--effort', job.get('effort', 'medium'), '--output-format', 'json',
                '--json-schema', json.dumps(FINAL_SCHEMA)]
        if job.get('resume'):
            args += ['--resume', job['resume']]
    identity = []
    if job.get('eval_attempt'):
        identity = (['--run-id', job['container_id']] if fence.socket_enabled() else
                    ['--session-turn', str(job['cleanup_turn'])])
    return [*fence.fence_command(), 'run', *identity, '--tool', job['tool'], '--repo', job['repo'],
            '--run', str(folder / 'io'), '--', *args, '--', job['prompt']]


class Processes:
    def start(self, job):
        job['fence'] = True
        folder = Path(job['run'])
        output = folder / 'io'
        output.mkdir(mode=0o750)
        output.chmod(0o750)
        atomic_json(output / 'schema.json', FINAL_SCHEMA)
        os.chmod(output / 'schema.json', 0o444)
        fence.own(output, 'run')
        atomic_json(folder / 'request.json', job)
        # The supervisor is outside the CLI process group and closes all terminal FDs.
        with (folder / 'supervisor.log').open('ab') as log:
            os.fchmod(log.fileno(), 0o600)
            options = {'env': {k: os.environ[k] for k in ('PATH', 'LANG', 'PYTHONPATH', 'CPLANE_FENCE_COMMAND', 'CPLANE_LAUNCHER_SOCKET')
                               if k in os.environ}}
            proc = subprocess.Popen([sys.executable, '-m', 'cplane.executors', str(folder)],
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                    start_new_session=True, close_fds=True, **options)
        job['pid'] = proc.pid
        return proc.pid

    def stop(self, job):
        cleanup = (['stop', job['container_id']] if fence.socket_enabled() else
                   ['session-cleanup', str(job['cleanup_turn'])])
        subprocess.run([*fence.fence_command(), *cleanup], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env=fence.host_environment())

    def poll(self, job):
        if job.get('eval_attempt'):
            folder = Path(job['run'])
            done = (folder / 'exit.json').exists()
            if not done and job.get('pid'):
                try:
                    os.killpg(job['pid'], 0)
                except ProcessLookupError:
                    done = True
                except PermissionError:
                    pass
            return done, '', None, ''
        folder = Path(job['run'])
        session = job.get('session', '')
        final = None
        if job['tool'] == 'codex':
            logfile = folder / 'turn.jsonl'
            if logfile.exists():
                for line in logfile.read_text(errors='replace').splitlines():
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict) and event.get('type') == 'thread.started':
                            session = event['thread_id']
                    except (ValueError, KeyError):
                        continue
            last = folder / 'io/last.json'
            if last.exists() and last.stat().st_mtime_ns > job['started_ns']:
                try:
                    final = json.loads(read_output(last))
                except ValueError:
                    pass
        else:
            logfile = folder / 'claude.json'
            if logfile.exists() and logfile.stat().st_mtime_ns > job['started_ns']:
                try:
                    reply = json.loads(logfile.read_text())
                    if isinstance(reply, dict):
                        session = reply.get('session_id', session)
                        final = reply.get('structured_output')
                except ValueError:
                    pass
        done = (folder / 'exit.json').exists()
        if not done:
            # Detect a killed supervisor without confusing a reused PID for our process.
            pid = job.get('pid')
            if not pid and (folder / 'supervisor.json').exists():
                pid = json.loads((folder / 'supervisor.json').read_text())['pid']
            if pid:
                # A killed supervisor can leave its executor alive in this process group.
                # Reserving capacity for an ambiguous/reused group is safer than a duplicate.
                try:
                    os.killpg(pid, 0)
                except ProcessLookupError:
                    done = True
                except PermissionError:
                    pass
        valid = (isinstance(final, dict) and set(final) == {'kind', 'body'}
                 and final['kind'] in FINAL_SCHEMA['properties']['kind']['enum']
                 and isinstance(final['body'], str))
        lines = logfile.read_text(errors='replace').splitlines() if logfile.exists() else []
        errors = folder / 'stderr.log'
        if errors.exists():
            lines += errors.read_text(errors='replace').splitlines()
        output_tail = '\n'.join(lines[-40:])
        if done:
            exit_file = folder / 'exit.json'
            if exit_file.exists():
                try:
                    code = json.loads(exit_file.read_text()).get('code', 1)
                except (ValueError, OSError, AttributeError):
                    code = 1
                error_lines = errors.read_text(errors='replace').splitlines() if errors.exists() else []
                first_error = next((line.strip() for line in error_lines if line.strip()), 'no stderr output')
                tool = 'codex' if job['tool'] == 'codex' else 'claude'
                summary = f'{tool} exec exited {code}: {first_error}'
                tail = failure_tail(summary, output_tail)
            else:
                tail = cut(output_tail, TAIL_LIMIT)
        else:
            tail = cut(output_tail, TAIL_LIMIT)
        return done, session, final if valid else None, tail


def supervise(folder):
    job = json.loads((folder / 'request.json').read_text())
    logfile = folder / ('turn.jsonl' if job['tool'] == 'codex' else 'claude.json')
    atomic_json(folder / 'supervisor.json', {'pid': os.getpid()})
    code = 1
    timed_out = False
    stopped = True
    try:
        with logfile.open('ab') as log, (folder / 'stderr.log').open('ab') as errors:
            os.fchmod(log.fileno(), 0o600)
            os.fchmod(errors.fileno(), 0o600)
            code = subprocess.run(command(job), cwd=str(folder), stdin=subprocess.DEVNULL,
                                  stdout=log, stderr=errors, close_fds=True,
                                  **({'timeout': job['timeout_seconds']} if job.get('eval_attempt') else {})).returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        stopped = False
        cleanup = (['stop', job['container_id']] if fence.socket_enabled() else
                   ['session-cleanup', str(job['cleanup_turn'])])
        # Do not announce completion until the container is confirmed stopped.
        subprocess.run([*fence.fence_command(), *cleanup], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env=fence.host_environment())
        stopped = True
    except Exception as error:
        with logfile.open('a') as log:
            log.write(str(error) + '\n')
    finally:
        if stopped:
            atomic_json(folder / 'exit.json', {'code': code, 'at': time.time(), **({'timeout': True} if timed_out else {})})


if __name__ == '__main__':
    supervise(Path(sys.argv[1]))
