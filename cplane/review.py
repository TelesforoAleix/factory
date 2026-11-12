"""Slice review validation and fresh copies, using only the clean clone for Git."""
from importlib.resources import files
import json
import os

from jsonschema import Draft202012Validator

from . import cut, fence
from .state import StateError


VALIDATOR = Draft202012Validator(
    json.loads(files('schema').joinpath('review.schema.json').read_text()))


def validate(answer, *, store=None, job=None):
    if not VALIDATOR.is_valid(answer):
        raise StateError('invalid review: expected pass with title/body or fix with tickets/test_files')
    if answer['verdict'] == 'fix':
        cut.validate_plan({key: answer[key] for key in ('tickets', 'test_files')})

    if store is not None and job is not None:
        from .run_records import outcome
        outcome(store, job, verdict=answer['verdict'])


def prepare(adapter, previous, copy_id):
    clean = adapter.clean(previous['repository'])
    branch = previous['branch']
    adapter.git(clean, 'fetch', '--prune', 'origin',
                '+refs/heads/*:refs/remotes/origin/*', auth=True)
    tip = adapter.git(clean, 'rev-parse', '--verify',
                      f'refs/remotes/origin/{branch}^{{commit}}').stdout.strip()
    if adapter.git(clean, 'merge-base', '--is-ancestor', previous['base'], tip,
                   allow_failure=True).returncode:
        raise StateError('review branch does not descend from the slice base')
    adapter.git(clean, 'update-ref', f'refs/heads/{branch}', tip)
    fence.trusted_directory(fence.WORK_ROOT)
    copy = fence.WORK_ROOT / copy_id
    if copy.exists() or copy.is_symlink():
        raise StateError('review copy already exists')
    adapter.git(clean, 'clone', '--no-hardlinks', '--template=', '--single-branch',
                '--branch', branch, '--config', 'core.hooksPath=/dev/null',
                '--config', 'user.name=Factory', '--config', 'user.email=factory@localhost',
                str(clean), str(copy))
    copy.chmod(0o700)
    for directory, folders, paths in os.walk(copy, followlinks=False):
        for name in [*folders, *paths]:
            os.chown(os.path.join(directory, name), fence.CLI_UID, fence.CLI_GID,
                     follow_symlinks=False)
    os.chown(copy, fence.CLI_UID, fence.CLI_GID)
    return {**{key: previous[key] for key in ('repository', 'branch', 'base', 'default')},
            'repo': str(copy), 'tip': tip}


def planner_change(args):
    """Keep accounting and the planner review on the same atomic update path."""
    from . import planner, state
    change = planner.change_for(args)

    def apply(item, data, at):
        result = change(item, data, at)
        if state.postgres():
            # Existing free-text reviews remain accepted reviews. The explicit
            # corrected verdict labels work that needed correction.
            verdict = 'corrected' if args.verdict == 'corrected' else 'accepted'
            state.store(None).slice_outcome(item['id'], verdict=verdict)
        return result
    return apply
