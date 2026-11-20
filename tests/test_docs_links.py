"""The document map, relative links and anchors, and claims citations stay valid."""
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
CORE = ['AGENTS.md', 'ARCHITECTURE.md', 'DECISIONS.md', 'docs/contracts.md',
        'docs/operations.md', 'docs/migrations.md', 'docs/documentation.md']
DOCUMENTS = sorted({*CORE, 'README.md', *(str(p.relative_to(ROOT)) for p in (ROOT / 'docs').glob('*.md'))})
LINK = re.compile(r'\[(?:[^\]]*)\]\(([^)\s]+)\)|(?:src|srcset)="([^"]+)"')


def prose(path):
    """The document's lines outside fenced code blocks."""
    lines, fenced = [], False
    for line in (ROOT / path).read_text(encoding='utf-8').splitlines():
        if line.lstrip().startswith('```'):
            fenced = not fenced
            continue
        lines.append('' if fenced else line)
    return lines


def slug(heading):
    text = re.sub(r'[^\w\- ]', '', heading.strip().lower())
    return text.replace(' ', '-')


def anchors(path):
    found = set()
    for line in prose(path):
        match = re.match(r'#{1,6}\s+(.*)', line)
        if match:
            found.add(slug(match.group(1)))
    return found


def links(path):
    for number, line in enumerate(prose(path), 1):
        for match in LINK.finditer(line):
            target = match.group(1) or match.group(2)
            if not re.match(r'[a-z][a-z0-9+.-]*:', target):
                yield number, target


def test_document_map_names_existing_files():
    text = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
    section = text.split('## Document map', 1)[1].split('\n## ', 1)[0]
    named = [target for _, target in links('AGENTS.md') if target in section]
    assert len(named) >= 10
    for target in named:
        assert (ROOT / target.split('#')[0]).is_file(), target


def test_core_documents_exist():
    for name in CORE:
        assert (ROOT / name).is_file(), name


@pytest.mark.parametrize('document', DOCUMENTS)
def test_relative_links_and_anchors_resolve(document):
    for number, target in links(document):
        file, _, anchor = target.partition('#')
        resolved = ((ROOT / document).parent / file).resolve() if file else ROOT / document
        assert resolved.exists(), f'{document}:{number}: {target}'
        if anchor:
            assert resolved.suffix == '.md', f'{document}:{number}: {target}'
            assert anchor in anchors(resolved.relative_to(ROOT)), f'{document}:{number}: {target}'


def test_claims_are_valid_and_cite_existing_lines():
    claims = json.loads((ROOT / 'docs/claims.json').read_text(encoding='utf-8'))
    schema = json.loads((ROOT / 'schema/claims.schema.json').read_text(encoding='utf-8'))
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(claims)]
    assert not errors

    def cited(where, path, lines):
        file = ROOT / path
        assert file.is_file(), f'{where}: {path}'
        length = len(file.read_text(encoding='utf-8').splitlines())
        assert lines[0] <= lines[1] <= length, f'{where}: {path} {lines}'

    for kind, key in (('parts', 'name'), ('claims', 'id'), ('relations', 'id'), ('contracts', 'name')):
        names = [item[key] for item in claims[kind]]
        assert len(names) == len(set(names)), kind
    for item in claims['parts'] + claims['claims'] + claims['contracts']:
        cited(item.get('id') or item['name'], item['doc'], item['doc_lines'])
    for item in claims['claims']:
        for source in item['sources']:
            cited(item['id'], source['path'], source['lines'])
    for item in claims['relations']:
        assert item['provider_sources'] or item['user_sources'], item['id']
        for source in item['provider_sources'] + item['user_sources']:
            cited(item['id'], source['path'], source['lines'])
