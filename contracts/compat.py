"""Full compatibility: `oasdiff breaking` in both directions must report no error."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .canonical import ContractError, dumps, load, parse

OASDIFF_VERSION = '1.37.0'
LEVELS = {3: 'error', 2: 'warning', 1: 'info'}
# Level 3 findings that `compare` accepts, by direction (first, second), with the reader
# rule that makes each one safe. The same ids in the other direction stay breaking.
TOLERATED = {
    # A new operation: a user treats a 404 from a new endpoint as "not available yet".
    ('revision', 'base'): {'api-path-removed-without-deprecation', 'api-removed-without-deprecation'},
    # A new response enum value: a reader maps an unknown value to its fallback.
    ('base', 'revision'): {'response-property-enum-value-added'},
}


def find_oasdiff(explicit=None):
    """`--oasdiff`, then `OASDIFF`, then `PATH`."""
    candidate = explicit or os.environ.get('OASDIFF') or shutil.which('oasdiff')
    if not candidate or not (Path(candidate).is_file() or shutil.which(candidate)):
        raise ContractError(
            f'oasdiff not found: install oasdiff v{OASDIFF_VERSION} (github.com/oasdiff/oasdiff) '
            'and pass --oasdiff, set OASDIFF, or put it on PATH')
    return candidate


def read_base(spec):
    """A file path, or `git:REF:PATH` read with `git show` in the current repository."""
    if not spec.startswith('git:'):
        return load(spec)
    ref, separator, path = spec[4:].partition(':')
    if not separator or not ref or not path:
        raise ContractError(f'{spec}: expected git:REF:PATH')
    try:
        result = subprocess.run(['git', 'show', '--end-of-options', f'{ref}:{path}'],
                                capture_output=True, text=True)
    except OSError as error:
        raise ContractError(f'{spec}: {error}') from None
    if result.returncode:
        raise ContractError(f'{spec}: git show failed: {result.stderr.strip()}')
    return parse(result.stdout, spec)


def _breaking(oasdiff, first, second, folder):
    command = [oasdiff, 'breaking', str(first), str(second), '--fail-on', 'ERR',
               '--format', 'json', '--allow-external-refs=false']
    try:
        # A temporary folder and no OASDIFF_CONFIG: no local configuration can relax the rules.
        environment = {k: v for k, v in os.environ.items() if k != 'OASDIFF_CONFIG'}
        result = subprocess.run(command, capture_output=True, text=True, cwd=folder, env=environment)
    except OSError as error:
        raise ContractError(f'cannot run oasdiff: {error}') from None
    try:
        changes = json.loads(result.stdout) if result.stdout.strip() else []
        if not isinstance(changes, list):
            raise ValueError()
    except ValueError:
        changes = None
    failed = result.returncode == 1
    if (result.returncode not in (0, 1) or changes is None
            or failed and not any(isinstance(c, dict) and c.get('level') == 3 for c in changes)):
        raise ContractError(f'oasdiff failed (exit {result.returncode}): '
                            f'{(result.stderr or result.stdout).strip()[:2000]}')
    return changes


def compare(base, revision, oasdiff):
    """(passed, report lines) for two OpenAPI documents."""
    lines, passed = [], True
    with tempfile.TemporaryDirectory(prefix='factory-contracts-') as folder:
        files = {}
        for name, value in (('base', base), ('revision', revision)):
            files[name] = Path(folder) / f'{name}.json'
            files[name].write_text(dumps(value), encoding='utf-8')
        for first, second in (('base', 'revision'), ('revision', 'base')):
            changes = _breaking(oasdiff, files[first], files[second], folder)
            direction = f'{first} -> {second}'
            counted = [c for c in changes if isinstance(c, dict)]
            allowed = TOLERATED[(first, second)]
            tolerated = [c.get('level') == 3 and c.get('id') in allowed for c in counted]
            failed = any(c.get('level') == 3 and not ok for c, ok in zip(counted, tolerated))
            passed = passed and not failed
            lines.append(f'{direction}: {"breaking" if failed else "compatible"}')
            for change, ok in zip(counted, tolerated):
                level = 'tolerated' if ok else LEVELS.get(change.get('level'), str(change.get('level')))
                where = ' '.join(str(change.get(k)) for k in ('operation', 'path') if change.get(k))
                lines.append(f'  {level} [{change.get("id")}] {where}: {change.get("text", "")}'.rstrip())
    return passed, lines
