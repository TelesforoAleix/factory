"""The factory-contracts tool on synthetic schemas, pins and a fake oasdiff."""
import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from contracts import cli, compat, pins, sender
from contracts.canonical import dumps
from contracts.practices import CHECKS

ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'a' * 40


def document(item_properties, item_required=('name',)):
    """A synthetic OpenAPI 3.1 document in the shape FastAPI generates."""
    return {
        'openapi': '3.1.0',
        'info': {'title': 'Synthetic', 'version': '0.1.0'},
        'paths': {
            '/v1/items': {'post': {
                'operationId': 'create_item',
                'requestBody': {'required': True, 'content': {'application/json': {
                    'schema': {'$ref': '#/components/schemas/Item'}}}},
                'responses': {'200': {'description': 'ok'}}}},
            '/v1/items/{item_id}/notes': {'post': {
                'requestBody': {'content': {'application/json': {'schema': {
                    'type': 'object', 'properties': {'text': {'type': 'string'}},
                    'required': ['text']}}}},
                'responses': {'200': {'description': 'ok'}}}},
        },
        'components': {'schemas': {
            'Item': {'type': 'object', 'title': 'Item', 'required': list(item_required),
                     'properties': item_properties},
            'Owner': {'type': 'object', 'title': 'Owner', 'required': ['login'],
                      'properties': {'login': {'type': 'string'},
                                     'labels': {'type': 'object', 'additionalProperties': {'type': 'string'}}}},
        }},
    }


ITEM = {
    'name': {'type': 'string'},
    'size': {'type': 'integer', 'default': 1},
    'owner': {'anyOf': [{'$ref': '#/components/schemas/Owner'}, {'type': 'null'}]},
    'tags': {'type': 'array', 'items': {'$ref': '#/components/schemas/Owner'}},
    'extra': {'type': 'object'},
}


def write(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


@pytest.fixture
def pin(tmp_path):
    schema = write(tmp_path / 'openapi.json', document(ITEM))
    pins.write('run-api', 'TelesforoAleix/homelab-v2', COMMIT, schema, tmp_path / 'pin')
    return tmp_path / 'pin'


def test_canonical_form(tmp_path, capsys):
    source = write(tmp_path / 'a.json', {'b': [1, {'z': 'é', 'a': None}], 'a': 'x'})
    assert cli.main(['canonical', str(source)]) == 0
    out = capsys.readouterr().out
    assert out == '{\n  "a": "x",\n  "b": [\n    1,\n    {\n      "a": null,\n      "z": "é"\n    }\n  ]\n}\n'
    assert out == json.dumps(json.loads(out), indent=2, sort_keys=True, ensure_ascii=False) + '\n'
    assert cli.main(['canonical', '--check', str(source)]) == 1
    (tmp_path / 'b.json').write_text(out, encoding='utf-8')
    assert cli.main(['canonical', '--check', str(tmp_path / 'b.json')]) == 0
    (tmp_path / 'bad.json').write_text('{', encoding='utf-8')
    assert cli.main(['canonical', str(tmp_path / 'bad.json')]) == 2


def test_generated_equal_and_different(tmp_path, capsys):
    value = document(ITEM)
    generator = write(tmp_path / 'generator-output.json', value)
    command = f'{sys.executable} -c "import sys; sys.stdout.write(open(sys.argv[1]).read())" {generator}'
    committed = tmp_path / 'openapi.json'
    committed.write_text(dumps(value), encoding='utf-8')
    assert cli.main(['generated', '--command', command, '--file', str(committed)]) == 0
    capsys.readouterr()
    changed = document({**ITEM, 'note': {'type': 'string', 'default': ''}})
    write(generator, changed)
    assert cli.main(['generated', '--command', command, '--file', str(committed)]) == 1
    err = capsys.readouterr().err
    assert 'differs from the generator' in err and '+' in err and '"note"' in err
    committed.write_text(json.dumps(changed), encoding='utf-8')  # Same value, not canonical.
    assert cli.main(['generated', '--command', command, '--file', str(committed)]) == 1
    assert cli.main(['generated', '--command', 'exit 3', '--file', str(committed)]) == 2


def test_pin_write_verify_and_tamper(tmp_path, capsys):
    schema = write(tmp_path / 'openapi.json', document(ITEM))
    out = tmp_path / 'pins' / 'run-api'
    assert cli.main(['pin', 'write', '--contract', 'run-api', '--provider', 'TelesforoAleix/homelab-v2',
                     '--commit', COMMIT, '--schema', str(schema), '--out', str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ['pin.json', 'schema.json']
    record = json.loads((out / 'pin.json').read_text())
    assert record == {'contract': 'run-api', 'provider': 'TelesforoAleix/homelab-v2', 'commit': COMMIT,
                      'sha256': hashlib.sha256((out / 'schema.json').read_bytes()).hexdigest()}
    assert (out / 'pin.json').read_text() == dumps(record)
    assert (out / 'schema.json').read_text() == dumps(document(ITEM))
    assert cli.main(['pin', 'verify', str(out)]) == 0
    capsys.readouterr()

    tampered = document({**ITEM, 'size': {'type': 'string'}})
    (out / 'schema.json').write_text(dumps(tampered), encoding='utf-8')
    assert cli.main(['pin', 'verify', str(out)]) == 1
    assert 'does not match the sha256' in capsys.readouterr().err
    with pytest.raises(Exception, match='sha256'):
        sender.check(out, 'POST', '/v1/items', {'name': 'x'})

    for bad in (['--commit', 'abc'], ['--provider', 'homelab-v2'], ['--contract', 'Run API']):
        arguments = dict(zip(['--contract', '--provider', '--commit'], ['run-api', 'o/n', COMMIT]))
        arguments.update(dict([bad]))
        argv = ['pin', 'write', *sum(arguments.items(), ()), '--schema', str(schema), '--out', str(tmp_path / 'x')]
        assert cli.main(argv) == 2
    write(out / 'pin.json', {**record, 'version': 2})
    assert 'exactly the keys' in pins.verify(out)[0]


def test_sender_unknown_top_level_field(pin):
    errors = sender.check(pin, 'POST', '/v1/items', {'name': 'x', 'colour': 'red'})
    assert errors == ['POST /v1/items: $.colour: field not defined by the pinned schema']


def test_sender_unknown_nested_field_through_ref(pin):
    body = {'name': 'x', 'owner': {'login': 'a', 'email': 'e'},
            'tags': [{'login': 'b'}, {'login': 'c', 'team': 't'}]}
    errors = sender.check(pin, 'post', '/v1/items', body)
    assert errors == ['POST /v1/items: $.owner.email: field not defined by the pinned schema',
                      'POST /v1/items: $.tags[1].team: field not defined by the pinned schema']


def test_sender_wrong_type(pin):
    errors = sender.check(pin, 'POST', '/v1/items', {'name': 'x', 'size': 'big', 'owner': {'login': 3}})
    assert any(e.startswith('POST /v1/items: $.size: ') and "'integer'" in e for e in errors)
    assert any(e.startswith('POST /v1/items: $.owner: ') for e in errors)
    assert sender.check(pin, 'POST', '/v1/items', {'size': 2}) == [
        "POST /v1/items: $: 'name' is a required property"]


def test_sender_valid_body_and_operations(pin, tmp_path, capsys):
    body = {'name': 'x', 'size': 2, 'owner': None, 'tags': [{'login': 'b', 'labels': {'any-key': 'v'}}],
            'extra': {'free': {'form': True}}}
    assert sender.check(pin, 'POST', '/v1/items', body) == []
    assert sender.check(pin, 'POST', '/v1/items/42/notes', {'text': 'n'}) == []
    assert sender.check(pin, 'POST', '/v1/items/42/notes', {'text': 'n', 'at': 1}) == [
        'POST /v1/items/42/notes: $.at: field not defined by the pinned schema']
    assert sender.check(pin, 'GET', '/v1/items', {}) == ['GET /v1/items: the pinned schema has no such operation']
    path = write(tmp_path / 'body.json', body)
    assert cli.main(['sender', '--pin', str(pin), '--method', 'POST', '--path', '/v1/items', '--body', str(path)]) == 0
    write(path, {**body, 'colour': 'red'})
    assert cli.main(['sender', '--pin', str(pin), '--method', 'POST', '--path', '/v1/items', '--body', str(path)]) == 1
    assert '$.colour' in capsys.readouterr().err


def test_sender_composition_and_refused_refs():
    doc = document({'name': {'type': 'string'}})
    doc['components']['schemas']['Item'] = {'allOf': [
        {'$ref': '#/components/schemas/Owner'}, {'properties': {'name': {'type': 'string'}}}]}
    assert sender.check_document(doc, 'POST', '/v1/items', {'login': 'a', 'name': 'n'}) == []
    assert sender.check_document(doc, 'POST', '/v1/items', {'login': 'a', 'x': 1}) == [
        'POST /v1/items: $.x: field not defined by the pinned schema']
    doc['components']['schemas']['Item'] = {'$ref': 'https://example.test/item.json'}
    with pytest.raises(Exception, match='unsupported'):
        sender.check_document(doc, 'POST', '/v1/items', {'name': 'n'})


FAKE = '''#!{python}
import json, os, sys
with open(os.environ['FAKE_OASDIFF_LOG'], 'a') as log:
    log.write(json.dumps({{'argv': sys.argv[1:], 'first': json.load(open(sys.argv[2]))}}) + '\\n')
direction = 'forward' if os.path.basename(sys.argv[2]) == 'base.json' else 'backward'
if direction in os.environ.get('FAKE_OASDIFF_FAIL', '').split(','):
    print(json.dumps([{{'id': direction + '-rule', 'level': 3, 'operation': 'POST', 'path': '/v1/items',
                       'text': 'synthetic break'}}]))
    sys.exit(1)
print('[]')
'''


@pytest.fixture
def fake_oasdiff(tmp_path, monkeypatch):
    script = tmp_path / 'bin' / 'oasdiff'
    script.parent.mkdir()
    script.write_text(FAKE.format(python=sys.executable))
    script.chmod(0o755)
    log = tmp_path / 'oasdiff.log'
    monkeypatch.setenv('FAKE_OASDIFF_LOG', str(log))
    monkeypatch.delenv('OASDIFF', raising=False)
    return script, log


@pytest.mark.parametrize('fail,code', [('', 0), ('forward', 1), ('backward', 1), ('forward,backward', 1)])
def test_compat_runs_both_directions(tmp_path, fake_oasdiff, monkeypatch, capsys, fail, code):
    script, log = fake_oasdiff
    monkeypatch.setenv('FAKE_OASDIFF_FAIL', fail)
    base = write(tmp_path / 'old.json', document(ITEM))
    revision = write(tmp_path / 'new.json', document({**ITEM, 'note': {'type': 'string', 'default': ''}}))
    assert cli.main(['compat', '--base', str(base), '--revision', str(revision), '--oasdiff', str(script)]) == code
    calls = [json.loads(line)['argv'] for line in log.read_text().splitlines()]
    assert [[Path(c[1]).name, Path(c[2]).name] for c in calls] == [['base.json', 'revision.json'],
                                                                     ['revision.json', 'base.json']]
    assert all(c[0] == 'breaking' and c[3:5] == ['--fail-on', 'ERR'] for c in calls)
    out = capsys.readouterr().out
    for direction, name in (('forward', 'base -> revision'), ('backward', 'revision -> base')):
        if direction in fail:
            assert f'{name}: breaking' in out and f'[{direction}-rule]' in out
        else:
            assert f'{name}: compatible' in out and f'[{direction}-rule]' not in out


def test_compat_reads_git_base_and_finds_oasdiff(tmp_path, fake_oasdiff, monkeypatch, capsys):
    script, log = fake_oasdiff
    repo = tmp_path / 'repo'
    repo.mkdir()
    def git(*args):
        subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
    git('init', '-q')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.test')
    write(repo / 'openapi.json', document(ITEM))
    git('add', '.')
    git('commit', '-qm', 'schema')
    write(repo / 'openapi.json', document({'name': {'type': 'string'}}))
    monkeypatch.chdir(repo)
    monkeypatch.setenv('PATH', str(script.parent) + os.pathsep + os.environ['PATH'])
    assert cli.main(['compat', '--base', 'git:HEAD:openapi.json', '--revision', 'openapi.json']) == 0
    assert json.loads(log.read_text().splitlines()[0])['first'] == document(ITEM)
    assert cli.main(['compat', '--base', 'git:HEAD:missing.json', '--revision', 'openapi.json']) == 2
    assert 'git show failed' in capsys.readouterr().err
    monkeypatch.setattr(compat.shutil, 'which', lambda name: None)
    assert cli.main(['compat', '--base', 'git:HEAD:openapi.json', '--revision', 'openapi.json']) == 2
    assert 'oasdiff v1.37.0' in capsys.readouterr().err
    monkeypatch.setenv('OASDIFF', str(script))
    assert cli.main(['compat', '--base', 'git:HEAD:openapi.json', '--revision', 'openapi.json']) == 0


@pytest.mark.skipif(not os.environ.get('OASDIFF'), reason='set OASDIFF to an oasdiff v1.37.0 binary')
def test_compat_with_real_oasdiff(tmp_path, capsys):
    base = write(tmp_path / 'base.json', document(ITEM, ('name', 'size')))
    optional = write(tmp_path / 'optional.json', document({**ITEM, 'note': {'type': 'string', 'default': ''}},
                                                          ('name', 'size')))
    reduced = {k: v for k, v in ITEM.items() if k != 'size'}
    removed = write(tmp_path / 'removed.json', document(reduced))
    assert cli.main(['compat', '--base', str(base), '--revision', str(optional)]) == 0
    capsys.readouterr()
    assert cli.main(['compat', '--base', str(base), '--revision', str(removed)]) == 1
    out = capsys.readouterr().out
    # Without a response schema, removing a request field breaks only old senders.
    assert 'revision -> base: breaking' in out and 'not fully compatible' in out


def test_practice_registry_names_existing_skills():
    commands = cli.parser()._subparsers._group_actions[0].choices
    pin_actions = commands['pin']._subparsers._group_actions[0].choices
    writers = {'pin write', 'practices'}
    assert set(CHECKS) == {*commands, *(f'pin {a}' for a in pin_actions)} - {'pin'} - writers
    skills = {p.stem for p in (ROOT / 'skills').glob('*.md')}
    for check, skill in CHECKS.items():
        assert skill in skills, f'{check} names missing skill {skill}'
    assert set(CHECKS.values()) == {'expand-contract'}
    text = (ROOT / 'skills' / 'expand-contract.md').read_text()
    assert len(text.splitlines()) < 80
    for check in CHECKS:
        assert f'factory-contracts {check}' in text


def test_package_imports_only_stdlib_and_jsonschema():
    for path in (ROOT / 'contracts').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ''] if isinstance(node, ast.ImportFrom) and not node.level else [])
            for name in names:
                top = name.split('.')[0]
                assert top in sys.stdlib_module_names or top == 'jsonschema', f'{path.name}: {name}'
    script = ("import sys\nfor name in ('cplane', 'factory_ui', 'flask', 'psycopg', 'waitress'):\n"
              "    sys.modules[name] = None\nfrom contracts import cli\nsys.exit(cli.main(['practices']))")
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert 'sender' in result.stdout
