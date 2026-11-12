"""Synthetic path policies; no executor content or private state."""
import pytest

from cplane import classes


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
