"""Lossless Markdown backlog tables; no Git or database access."""
import re

from .state import StateError

COLUMNS = ('Feature', 'Kind', 'Area', 'Repo', 'Horizon', 'Order', 'Slices', 'Readiness', 'Depends on')
HORIZONS = {'building': 'now', 'acceptance': 'now', 'testing': 'now', 'ready': 'next', 'next': 'next',
            'shortlist': 'next', 'grilling': 'next', 'parked': 'parked', 'done': 'done'}


def cells(line):
    """Split outside code spans and escaped pipes, retaining every cell byte."""
    text = line.rstrip('\r\n')
    cuts = []
    code = 0
    i = 0
    while i < len(text):
        char = text[i]
        if char == '\\':
            i += 2
            continue
        if char == '`':
            end = i + 1
            while end < len(text) and text[end] == '`':
                end += 1
            size = end - i
            if not code:
                code = size
            elif code == size:
                code = 0
            i = end
            continue
        if char == '|' and not code:
            cuts.append(i)
        i += 1
    bounds = [-1, *cuts, len(text)]
    parts = [text[a + 1:b] for a, b in zip(bounds, bounds[1:])]
    if cuts and not parts[0].strip():
        parts.pop(0)
    if cuts and not parts[-1].strip():
        parts.pop()
    return parts


def table(text):
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if tuple(c.strip() for c in cells(line)) == COLUMNS]
    if len(starts) != 1:
        raise StateError('Backlog must contain exactly one nine-column table')
    start = starts[0]
    if start + 1 >= len(lines) or len(cells(lines[start + 1])) != 9 or not all(
            re.fullmatch(r':?-{3,}:?', c.strip()) for c in cells(lines[start + 1])):
        raise StateError('Backlog table separator is invalid')
    end = start + 2
    while end < len(lines) and '|' in lines[end] and lines[end].strip():
        end += 1
    return lines, start, end


def stage_for(values):
    horizon = values[4].strip()
    if horizon == 'now':
        return 'building'
    if horizon == 'next':
        return 'ready' if values[7].strip().startswith('ready') else 'shortlist'
    if horizon in ('later', 'parked'):
        return 'parked'
    if horizon == 'done':
        return 'done'
    raise StateError('Unknown horizon')


def parse(text, projects):
    lines, start, end = table(text)
    repositories = {}
    for key, repository in projects:
        if repository:
            repositories.setdefault(repository, []).append(key)
    repositories['—'] = ['NEW']
    rows, errors, unknown, stages = [], [], set(), {}
    for order, line in enumerate(lines[start + 2:end]):
        values = cells(line)
        try:
            if len(values) != 9:
                raise StateError('Expected nine cells')
            stage = stage_for(values)
            from .features import bounded
            bounded(values[0].strip(), 'Title')
            if '\x00' in line:
                raise StateError('NUL in row')
        except StateError:
            errors.append(start + 3 + order)
            continue
        stages[stage] = stages.get(stage, 0) + 1
        repo = values[3].strip()
        keys = repositories.get(repo, [])
        if len(keys) != 1:
            unknown.add(repo)
        rows.append(dict(project=keys[0] if len(keys) == 1 else None,
                         title=values[0].strip(), stage=stage,
                         backlog=dict(cells=values, row=line, order=order, stage=stage)))
    report = dict(rows_found=end - start - 2, rows_per_stage=stages,
                  repositories_with_no_key=sorted(unknown), unparsed_rows=errors)
    return rows, report


def generated_table(text, features):
    lines, start, end = table(text)
    imported = sorted((f for f in features if f.get('backlog')), key=lambda f: f['backlog']['order'])
    other = sorted((f for f in features if not f.get('backlog')), key=lambda f: f['id'])
    newline = '\r\n' if lines[start].endswith('\r\n') else '\n'
    rendered = []
    for feature in imported:
        data = feature['backlog']
        row = data['row']
        values = data['cells']
        title = feature['title']
        changes = {}
        if title != values[0].strip():
            changes[0] = title.replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
        repository = feature.get('repository')
        if repository is not None and repository != values[3].strip():
            changes[3] = repository
        if feature['stage'] != data['stage']:
            changes[4] = HORIZONS[feature['stage']]
        prefix = row.find(values[0]) if values[0] else 1
        for index in sorted(changes, reverse=True):
            offset = prefix + sum(len(c) + 1 for c in values[:index])
            old = values[index]
            if old.strip():
                replacement = re.sub(r'\S.*\S|\S', lambda _: changes[index], old, count=1)
            else:
                replacement = old + changes[index]
            row = row[:offset] + replacement + row[offset + len(old):]
        rendered.append(row)
    for feature in other:
        title = feature['title'].replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
        rendered.append('| ' + ' | '.join((title, '', '', feature.get('repository', feature['project']), HORIZONS[feature['stage']], '', '', '', '')) + ' |' + newline)
    # A source table without a trailing newline still needs one between appended rows.
    for i in range(len(rendered) - 1):
        if not rendered[i].endswith('\n'):
            rendered[i] += newline
    return ''.join(lines[:start + 2] + rendered + lines[end:])
