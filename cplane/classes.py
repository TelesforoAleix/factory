"""Change policy from the target repository's pinned base, never executor content."""
import fnmatch
import re


DEFAULT = """4 /.github/**
4 /node/**
4 **/Dockerfile
4 **/compose.yaml
"""


def _pattern(pattern):
    """Compile root-relative gitignore wildcards without a runtime dependency.

    Every matching policy line contributes independently; there is no last-rule
    override.
    """
    if not pattern or pattern == '/':
        raise ValueError('invalid class pattern')
    anchored = pattern.startswith('/') or '/' in pattern.rstrip('/')
    directory = pattern.endswith('/')
    pattern = pattern.removeprefix('/').removesuffix('/')
    parts = pattern.split('/')
    if any(not part for part in parts):
        raise ValueError('invalid class pattern')
    result = '' if anchored else '(?:.*/)?'
    for index, part in enumerate(parts):
        if part == '**':
            result += '.*' if index == len(parts) - 1 else '(?:[^/]+/)*'
            continue
        offset = 0
        while offset < len(part):
            char = part[offset]
            if char == '\\':
                offset += 1
                if offset == len(part):
                    raise ValueError('invalid class escape')
                result += re.escape(part[offset])
            elif char == '*':
                result += '[^/]*'
            elif char == '?':
                result += '[^/]'
            elif char == '[':
                end = offset + 1
                if end < len(part) and part[end] in '!^':
                    end += 1
                if end < len(part) and part[end] == ']':
                    end += 1
                end = part.find(']', end)
                if end < 0:
                    result += r'\['
                else:
                    result += '(?!/)' + fnmatch.translate(part[offset:end + 1])[4:-3]
                    offset = end
            else:
                result += re.escape(char)
            offset += 1
        if index < len(parts) - 1:
            result += '/'
    # A matching directory also covers its descendants. A trailing slash only
    # matches directories, so require a descendant in our file-only diff.
    result += '/.*' if directory else '(?:/.*)?'
    return re.compile(result + r'\Z')


def parse(table):
    """Return all rules, or None if any non-comment line fails to parse."""
    if table is None:
        return None
    rules = []
    try:
        for line in table.splitlines():
            line = line.lstrip()
            if not line or line.startswith('#'):
                continue
            level, pattern = line.split(maxsplit=1)
            if level not in ('1', '2', '4'):
                return None
            # Gitignore ignores trailing spaces unless escaped.
            pattern = re.sub(r'(?<!\\) +$', '', pattern)
            negated = pattern.startswith('!')
            matcher = _pattern(pattern[1:] if negated else pattern)
            # An unignore line assigns no class. It cannot cancel a class from
            # another line: the table explicitly uses the highest match.
            if not negated:
                rules.append((int(level), matcher))
    except (ValueError, re.error):
        return None
    return rules


def classify(paths, table, *, deleted=()):
    """Return the highest path class and the sorted class 4 paths."""
    rules = parse(table)
    fallback = rules is None
    if fallback:
        rules = parse(DEFAULT)
    highest, guards = 1, []
    deleted = set(deleted)
    for path in sorted(set(paths)):
        if not path:
            continue
        level = max((number for number, pattern in rules if pattern.fullmatch(path)),
                    default=2 if fallback else 1)
        if path.startswith('.github/'):
            level = 4
        name = path.rsplit('/', 1)[-1]
        if path not in deleted and ('migrations' in path.split('/')[:-1] or name.endswith('.sql')
                or name in ('pyproject.toml', 'uv.lock', 'package.json', 'package-lock.json')
                or fnmatch.fnmatchcase(name, 'requirements*.txt')):
            level = max(level, 2)
        highest = max(highest, level)
        if level == 4:
            guards.append(path)
    return highest, guards


def changes(adapter, job):
    """Read only tracked names and the policy blob through the clean Git copy."""
    clean = adapter.clean(job['repository'])
    table = adapter.git(clean, 'show', f"{job['base']}:.github/change-classes",
                        allow_failure=True)
    entries = adapter.git(clean, 'diff', '--name-status', '-z', '--no-renames',
                          job['base'], job['tip'], '--').stdout.split('\0')
    changes = list(zip(entries[::2], entries[1::2]))
    return classify([path for _, path in changes],
                    table.stdout if table.returncode == 0 else None,
                    deleted=[path for status, path in changes if status == 'D'])
