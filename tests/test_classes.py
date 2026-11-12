"""Synthetic path policies; no executor content or private state."""
import os
import subprocess

import pytest

from cplane import classes, fence


@pytest.mark.parametrize('path,expected', [
    ('source.py', 1), ('cplane/runner.py', 2), ('schema/item.json', 2),
    ('guard/key', 4), ('.github/workflows/test.yml', 4), ('.github/change-classes', 4),
])
def test_highest_matching_class_wins_without_last_rule_override(path, expected):
    table = '# policy\n4 /guard/**\n2 /guard/*\n2 /cplane/runner.py\n2 /schema/**\n'
    assert classes.classify([path], table) == (expected, [path] if expected == 4 else [])


@pytest.mark.parametrize('table', [None, 'not a rule', '4 /guard/**\n3 /src/**',
                                  '2', '4 /guard/**\n2 ', '2 /src/**\n4 !'])
@pytest.mark.parametrize('path,expected', [
    ('.github/checks/a', 4), ('node/cli/main.py', 4), ('Dockerfile', 4),
    ('nested/Dockerfile', 4), ('compose.yaml', 4), ('a/b/compose.yaml', 4),
    ('source.py', 2), ('anode/file', 2), ('src/Dockerfile.txt', 2),
])
def test_missing_or_malformed_table_defaults_for_entire_change(table, path, expected):
    assert classes.classify([path], table) == (expected, [path] if expected == 4 else [])


@pytest.mark.parametrize('path', [
    'migrations/001.py', 'a/migrations/new.txt', 'data.sql', 'a/query.sql',
    'pyproject.toml', 'uv.lock', 'a/uv.lock', 'package.json', 'ui/package-lock.json',
    'requirements.txt', 'tools/requirements-dev.txt',
])
def test_content_rules_raise_unmatched_paths_to_two(path):
    assert classes.classify([path], '') == (2, [])


@pytest.mark.parametrize('pattern,path,expected', [
    ('/node/**', 'node/a/b', 4), ('/node/**', 'other/node/a', 1),
    ('guard', 'src/guard/file', 4), ('/guard', 'src/guard/file', 1),
    ('a/b', 'src/a/b', 1), ('a/b', 'a/b/file', 4),
    ('**/Dockerfile', 'Dockerfile', 4), ('**/Dockerfile', 'a/b/Dockerfile', 4),
    ('a/**/b', 'a/b', 4), ('a/**/b', 'a/c/d/b', 4),
    ('a/*/b', 'a/c/d/b', 1), ('a/?/b', 'a/c/b', 4),
    ('guard/', 'guard', 1), ('guard/', 'nested/guard/file', 4),
    ('file[0-9].txt', 'nested/file7.txt', 4), ('file[!0-9]', 'filex', 4),
    (r'/literal\*.txt', 'literal*.txt', 4), (r'/literal\*.txt', 'literal1.txt', 1),
    (r'/space\ ', 'space ', 4), ('/trailing   ', 'trailing', 4),
    ('/[abc', '[abc', 4), ('**/', 'any/file', 4),
])
def test_gitignore_patterns(pattern, path, expected):
    assert classes.classify([path], '4 ' + pattern) == (expected, [path] if expected == 4 else [])


def test_github_cannot_be_lowered_by_a_table_and_guards_are_sorted_unique():
    assert classes.classify(['.github/z', 'src/a', '.github/a', '.github/z'], '1 /**') == (
        4, ['.github/a', '.github/z'])
    assert classes.classify([], None) == (1, [])
    assert classes.classify(['plain.py'], '# empty policy\n') == (1, [])


def test_deleted_files_keep_path_class_without_content_floor():
    assert classes.classify(['query.sql'], '', deleted=['query.sql']) == (1, [])
    assert classes.classify(['query.sql'], '2 /*.sql', deleted=['query.sql']) == (2, [])


def test_negation_cannot_cancel_another_lines_class():
    assert classes.classify(['guard/key'], '4 /guard/**\n2 !/guard/**') == (4, ['guard/key'])
    assert classes.classify(['plain.py'], '4 !/guard/**') == (1, [])


@pytest.fixture
def merged_pr(tmp_path, monkeypatch):
    """A real fenced clean clone with stale main and a PR that merged new main."""
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('CPLANE_GITHUB_AUTH', 'token')
    for role in ('AUTHOR', 'COMMITTER'):
        monkeypatch.setenv(f'GIT_{role}_NAME', 'Synthetic')
        monkeypatch.setenv(f'GIT_{role}_EMAIL', 'synthetic@example.invalid')
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
    root = tmp_path / 'clean'
    root.mkdir(mode=0o700)
    monkeypatch.setattr(fence, 'CLEAN_ROOT', root)
    token = tmp_path / 'token'
    token.write_text('synthetic-test-token')
    token.chmod(0o600)
    monkeypatch.setattr(fence, 'TOKEN', token)

    def git(repo, *args):
        return subprocess.run(['git', '-C', str(repo), *map(str, args)],
                              check=True, capture_output=True, text=True).stdout.strip()

    repo = tmp_path / 'remote'
    repo.mkdir()
    git(repo, 'init', '--initial-branch=main', '--template=')
    (repo / '.github').mkdir()
    (repo / '.github/change-classes').write_text('4 /guard/**\n')
    (repo / 'guard').mkdir()
    (repo / 'guard/main').write_text('base\n')
    (repo / 'guard/own').write_text('base\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'base policy and guards')
    base = git(repo, 'rev-parse', 'HEAD')
    adapter = fence.Fence()
    clean = adapter.clean('example/repo')
    git(tmp_path, 'clone', '--bare', repo, clean)
    adapter.git(clean, 'fetch', 'origin', '+refs/heads/*:refs/remotes/origin/*')

    git(repo, 'checkout', '-b', 'pr')
    (repo / 'feature.py').write_text('feature\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'PR feature')
    git(repo, 'checkout', 'main')
    (repo / 'guard/main').write_text('main change\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'another PR changes a guard')
    git(repo, 'checkout', 'pr')
    git(repo, 'merge', '--no-edit', 'main')
    job = dict(repository='example/repo', base=base)

    def import_tip():
        job['tip'] = git(repo, 'rev-parse', 'HEAD')
        adapter.git(clean, 'fetch', 'origin', 'refs/heads/pr')

    import_tip()
    assert git(clean, 'rev-parse', 'origin/main') == base
    return adapter, job, repo, clean, git, import_tip


def test_changes_exclude_guard_inherited_from_merged_main(merged_pr):
    adapter, job, _, _, _, _ = merged_pr
    assert classes.changes(adapter, job) == (1, [])


def test_changes_keep_pr_guard_and_policy_at_pinned_base(merged_pr):
    adapter, job, repo, _, git, import_tip = merged_pr
    (repo / 'guard/own').write_text('PR change\n')
    (repo / '.github/change-classes').unlink()
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'PR changes guard and removes policy')
    import_tip()
    assert classes.changes(adapter, job) == (4, ['.github/change-classes', 'guard/own'])


def test_changes_keep_guard_reverted_by_pr(merged_pr):
    adapter, job, repo, _, git, import_tip = merged_pr
    git(repo, 'checkout', job['base'], '--', 'guard/main')
    git(repo, 'commit', '-m', 'PR reverts main guard change')
    import_tip()
    assert classes.changes(adapter, job) == (4, ['guard/main'])


def test_changes_fall_back_to_base_when_fetch_fails(merged_pr, tmp_path):
    adapter, job, _, clean, git, _ = merged_pr
    # Even a cached current main must not be trusted after a failed fetch.
    adapter.git(clean, 'fetch', 'origin', '+refs/heads/*:refs/remotes/origin/*')
    git(clean, 'remote', 'set-url', 'origin', tmp_path / 'missing.git')
    assert classes.changes(adapter, job) == (4, ['guard/main'])


def test_changes_fall_back_to_base_when_fetch_credentials_are_unavailable(merged_pr):
    adapter, job, _, clean, _, _ = merged_pr
    adapter.git(clean, 'fetch', 'origin', '+refs/heads/*:refs/remotes/origin/*')
    fence.TOKEN.unlink()
    assert classes.changes(adapter, job) == (4, ['guard/main'])


def test_changes_fall_back_to_base_when_merge_base_is_unavailable(merged_pr):
    adapter, job, repo, _, git, _ = merged_pr
    git(repo, 'checkout', '--orphan', 'unrelated')
    git(repo, 'rm', '-rf', '.')
    (repo / 'unrelated.txt').write_text('unrelated main\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'unrelated history')
    git(repo, 'branch', '-f', 'main', 'HEAD')
    assert classes.changes(adapter, job) == (4, ['guard/main'])
