"""docs-verify against temporary git repositories and a fake decisions API."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import copy
import json
import subprocess
import threading

import pytest

from cplane import cli, docs_verify, run_platform


def git(path, *args):
    subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True)


def make_repo(path, claims, files=None):
    path.mkdir()
    git(path, 'init', '-q')
    git(path, 'config', 'user.email', 'test@example.test')
    git(path, 'config', 'user.name', 'Test')
    for name, text in (files or FILES).items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
    (path / 'docs').mkdir(exist_ok=True)
    (path / 'docs/claims.json').write_text(json.dumps(claims))
    git(path, 'add', '-A')
    git(path, 'commit', '-q', '-m', 'docs')
    return path


FILES = {
    'ARCHITECTURE.md': 'Parts\nThe api serves runs.\nThe worker reads queue.\n',
    'docs/contracts.md': '# Contracts\nqueue v1: rows in table jobs.\n',
    'api.py': 'def serve():\n    return "runs"\n',
    'worker.py': 'def work():\n    return read("jobs")\n',
}


def base_claims():
    return {
        'version': 1, 'repository': 'acme/app',
        'parts': [{'name': 'api', 'doc': 'ARCHITECTURE.md', 'doc_lines': [2, 2], 'standalone': False},
                  {'name': 'worker', 'doc': 'ARCHITECTURE.md', 'doc_lines': [3, 3], 'standalone': False}],
        'claims': [{'id': 'C1', 'doc': 'ARCHITECTURE.md', 'doc_lines': [2, 2], 'text': 'The api serves runs.',
                    'sources': [{'path': 'api.py', 'lines': [1, 2]}]}],
        'relations': [{'id': 'R1', 'from': 'worker', 'to': 'api', 'how': 'table', 'contract': 'queue',
                       'text': 'The worker reads jobs.',
                       'provider_sources': [{'path': 'api.py', 'lines': [2, 2]}],
                       'user_sources': [{'path': 'worker.py', 'lines': [2, 2]}]}],
        'contracts': [{'name': 'queue', 'version': '1', 'provider': 'acme/app', 'users': ['acme/app'],
                       'doc': 'docs/contracts.md', 'doc_lines': [2, 2]}],
    }


def answer(choice='supported', confidence=0.95, choices=None):
    choices = choices or [choice] * 3
    return {'provider': 'prov', 'model': 'm1',
            'questions': {'support': {'choice': choice, 'probabilities': {choice: 1.0}, 'confidence': confidence,
                                      'agreement': 1.0,
                                      'answers': [{'choice': c, 'confidence': confidence, 'probabilities': {c: 1.0}}
                                                  for c in choices]}},
            'usage': {'input_tokens': 10, 'output_tokens': 2}}


@pytest.fixture
def api(monkeypatch, tmp_path):
    import secrets

    key = secrets.token_urlsafe(32)
    key_file = tmp_path / 'credential'
    key_file.write_text(key + '\n')
    monkeypatch.setenv('CPLANE_EVAL_TASK_KEY_FILE', str(key_file))
    calls, replies = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            assert self.headers['Authorization'] == 'Bearer ' + key
            calls.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            status, response = replies.pop(0) if replies else (200, answer())
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('CPLANE_EVAL_TASK_URL', f'http://127.0.0.1:{http.server_port}')
    yield calls, replies
    http.shutdown()
    thread.join()
    http.server_close()


@pytest.fixture
def no_api(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('no API call expected')
    monkeypatch.setattr(run_platform.Decisions, 'decide', refuse)


def run(tmp_path, claims, *extra, files=None, name='repo'):
    repo = make_repo(tmp_path / name, claims, files)
    out = tmp_path / f'{name}-record.json'
    code = cli.main(['docs-verify', str(repo), '--out', str(out), *extra])
    return code, json.loads(out.read_text())


# Schema and citations


@pytest.mark.parametrize('mutate, message', [
    (lambda c: c.pop('contracts'), 'fails required'),
    (lambda c: c.update(version=2), '$.version: fails const'),
    (lambda c: c['claims'][0].update(extra=1), 'fails additionalProperties'),
    (lambda c: c['relations'][0].update(how='rpc'), '$.relations[0].how: fails enum'),
    (lambda c: c['claims'][0].update(doc_lines=[0, 1]), 'fails minimum'),
    (lambda c: c['claims'][0].update(sources=[]), 'fails minItems'),
    (lambda c: c['contracts'][0].update(doc='CONTRACTS.md'), 'fails const'),
])
def test_schema_errors_fail_before_any_call(tmp_path, no_api, capsys, mutate, message):
    claims = base_claims()
    mutate(claims)
    code, record = run(tmp_path, claims)
    assert code == 1
    assert any(message in e for e in record['errors'])
    assert record['items'] == [] and record['graph'] == []
    assert 'error:' in capsys.readouterr().out


@pytest.mark.parametrize('mutate, message', [
    (lambda c: c['claims'][0]['sources'][0].update(path='missing.py'), 'missing.py does not exist'),
    (lambda c: c['claims'][0]['sources'][0].update(lines=[1, 3]), 'exceed its 2 lines'),
    (lambda c: c['claims'][0].update(doc_lines=[3, 2]), 'reversed'),
    (lambda c: c['relations'][0].update(contract='other'), "'other' is not in contracts"),
    (lambda c: c['claims'].append(copy.deepcopy(c['claims'][0])), "duplicate id 'C1'"),
    (lambda c: c['parts'].append(copy.deepcopy(c['parts'][0])), "duplicate name 'api'"),
    (lambda c: c['relations'][0].update(provider_sources=[], user_sources=[]), 'cites no lines'),
])
def test_citation_errors_fail_before_any_call(tmp_path, no_api, mutate, message):
    claims = base_claims()
    mutate(claims)
    code, record = run(tmp_path, claims)
    assert code == 1
    assert any(message in e for e in record['errors']), record['errors']


def test_missing_claims_file(tmp_path, no_api):
    repo = make_repo(tmp_path / 'repo', base_claims())
    git(repo, 'rm', '-q', 'docs/claims.json')
    git(repo, 'commit', '-q', '-m', 'drop')
    out = tmp_path / 'r.json'
    assert cli.main(['docs-verify', str(repo), '--out', str(out)]) == 1
    assert 'missing' in json.loads(out.read_text())['errors'][0]


def test_reads_the_given_revision_not_the_worktree(tmp_path, api):
    claims = base_claims()
    repo = make_repo(tmp_path / 'repo', claims)
    first = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=False).stdout.strip()
    (repo / 'api.py').write_text('x\n')
    git(repo, 'commit', '-q', '-am', 'shrink')
    (repo / 'api.py').unlink()
    out = tmp_path / 'r.json'
    assert cli.main(['docs-verify', str(repo), '--out', str(out)]) == 1
    assert any('exceed' in e for e in json.loads(out.read_text())['errors'])
    assert cli.main(['docs-verify', str(repo), '--rev', first, '--out', str(out)]) == 0
    record = json.loads(out.read_text())
    assert record['revision'] == first
    assert subprocess.run(['git', '-C', str(repo), 'status', '--porcelain'],
                          capture_output=True, text=True, check=False).stdout == ' D api.py\n'


# Assembly


def test_assembly_exact_text(tmp_path):
    claims = base_claims()
    revision = docs_verify.Revision(make_repo(tmp_path / 'repo', claims))
    assert docs_verify.assemble('claim', claims['claims'][0], claims, revision) == {
        'claim': 'The api serves runs.',
        'document': 'ARCHITECTURE.md:2: The api serves runs.',
        'source_1': 'api.py:1: def serve():\napi.py:2:     return "runs"',
    }
    assert docs_verify.assemble('relation', claims['relations'][0], claims, revision) == {
        'relation': 'from: worker\nto: api\nhow: table\ncontract: queue\ntext: The worker reads jobs.',
        'provider': 'api.py:2:     return "runs"',
        'user': 'worker.py:2:     return read("jobs")',
        'contract': 'docs/contracts.md:2: queue v1: rows in table jobs.',
    }
    relation = dict(claims['relations'][0], contract=None)
    assert 'contract' not in docs_verify.assemble('relation', relation, claims, revision)
    assert docs_verify.assemble('relation', relation, claims, revision)['relation'].splitlines()[3] == 'contract: none'


def test_request_shape(tmp_path, api):
    calls, _ = api
    code, _ = run(tmp_path, base_claims())
    assert code == 0
    assert [c[0] for c in calls] == ['/v1/decisions', '/v1/decisions']
    claim, relation = calls[0][1], calls[1][1]
    assert set(claim) == {'text', 'questions', 'repeats'} and claim['repeats'] == 3
    assert claim['questions'] == {'support': {
        'instructions': 'Decide whether the cited code and text fully support the claim. Judge only from the given lines.',
        'choices': {'supported': 'every part of the claim is shown by the given lines',
                    'partly': 'some part is shown, some part is missing or different',
                    'not_supported': 'the lines do not show the claim, or contradict it'}}}
    assert relation['questions']['support']['instructions'] == (
        "Decide whether the provider's lines and the user's lines show this connection, "
        'through the named contract when one is given.')
    assert relation['questions']['support']['choices'] == claim['questions']['support']['choices']
    assert set(relation['text']) == {'relation', 'provider', 'user', 'contract'}


# Verdicts


def test_pass_record(tmp_path, api, capsys):
    code, record = run(tmp_path, base_claims())
    assert code == 0
    assert record['repository'] == 'acme/app' and len(record['revision']) == 40
    assert len(record['claims_sha256']) == 64 and record['started_at'] and record['ended_at']
    assert record['model'] == 'prov/m1'
    assert record['usage'] == {'input_tokens': 20, 'output_tokens': 4}
    assert [(i['id'], i['kind'], i['verdict']) for i in record['items']] == [('C1', 'claim', 'pass'),
                                                                            ('R1', 'relation', 'pass')]
    assert len(record['items'][0]['answers']) == 3
    assert record['summary']['pass'] == 2 and record['summary']['graph_failed'] == 0
    # No source text in the record.
    text = json.dumps(record)
    assert 'return' not in text and 'serves runs' not in text
    assert '2 pass, 0 flagged' in capsys.readouterr().out


@pytest.mark.parametrize('reply', [
    answer(choices=['supported', 'supported', 'partly']),
    answer('not_supported'),
    answer(confidence=0.89),
])
def test_flagged(tmp_path, api, capsys, reply):
    _, replies = api
    replies.append((200, reply))
    code, record = run(tmp_path, base_claims())
    assert code == 1
    item = record['items'][0]
    assert item['verdict'] == 'flagged' and len(item['answers']) == 3
    assert [a['choice'] for a in item['answers']] == [a['choice'] for a in reply['questions']['support']['answers']]
    assert 'flagged: C1' in capsys.readouterr().out


def test_too_large_from_api(tmp_path, api):
    calls, replies = api
    replies.append((413, {'error': 'decisions_input_too_large'}))
    code, record = run(tmp_path, base_claims())
    assert code == 1 and len(calls) == 2
    assert record['items'][0]['verdict'] == 'too_large'
    assert record['items'][1]['verdict'] == 'pass'


def test_too_large_locally_makes_no_call(tmp_path, api):
    calls, _ = api
    files = dict(FILES, **{'api.py': 'x' * 81_000 + '\n' + 'y\n'})
    code, record = run(tmp_path, base_claims(), files=files)
    assert code == 1
    assert record['items'][0] == {'id': 'C1', 'kind': 'claim', 'verdict': 'too_large', 'error': 'text_limit'}
    assert len(calls) == 1


def test_502_retried_then_error(tmp_path, api):
    calls, replies = api
    replies += [(502, {'error': 'decisions_provider_error'})] * 2
    code, record = run(tmp_path, base_claims())
    assert code == 1 and len(calls) == 3
    assert record['items'][0] == {'id': 'C1', 'kind': 'claim', 'verdict': 'error',
                                  'error': 'decisions_provider_error', 'attempts': 2}


def test_502_retried_then_pass(tmp_path, api):
    calls, replies = api
    replies.append((502, {'error': 'decisions_provider_error'}))
    code, record = run(tmp_path, base_claims())
    assert code == 0 and len(calls) == 3 and record['items'][0]['attempts'] == 2


def test_422_is_error_without_retry(tmp_path, api):
    calls, replies = api
    replies.append((422, {'error': 'decisions_refused'}))
    code, record = run(tmp_path, base_claims())
    assert code == 1 and len(calls) == 2
    assert record['items'][0]['verdict'] == 'error'


@pytest.mark.parametrize('status, reason', [(429, 'decisions_budget_reached'), (503, 'decisions_unavailable')])
def test_stop_writes_partial_record(tmp_path, api, capsys, status, reason):
    calls, replies = api
    replies += [(200, answer()), (status, {'error': reason})]
    claims = base_claims()
    claims['claims'].append(dict(claims['claims'][0], id='C2'))
    code, record = run(tmp_path, claims)
    assert code == 2 and len(calls) == 2
    assert record['stopped'] == reason
    assert [i['verdict'] for i in record['items']] == ['pass', 'not_checked', 'not_checked']
    assert record['ended_at'] and record['summary']['not_checked'] == 2
    assert f'stopped: {reason}' in capsys.readouterr().out


def test_missing_platform_settings_stop(tmp_path, monkeypatch):
    monkeypatch.delenv('CPLANE_EVAL_TASK_URL', raising=False)
    code, record = run(tmp_path, base_claims())
    assert code == 2 and record['stopped'] == 'platform_unavailable'


# Graph


def checks(record, rule):
    return {c['subject']: c['passed'] for c in record['graph'] if c['rule'] == rule}


def test_graph_only_makes_no_call(tmp_path, no_api):
    code, record = run(tmp_path, base_claims(), '--graph-only')
    assert code == 0 and record['items'] == [] and record['graph_only']
    assert checks(record, 'part_connected') == {'api': True, 'worker': True}


def test_part_needs_a_passing_relation_or_standalone(tmp_path, api):
    _, replies = api
    replies += [(200, answer()), (200, answer('partly'))]
    claims = base_claims()
    claims['parts'].append({'name': 'cli', 'doc': 'ARCHITECTURE.md', 'doc_lines': [1, 1], 'standalone': True})
    code, record = run(tmp_path, claims)
    assert code == 1
    assert checks(record, 'part_connected') == {'api': False, 'worker': False, 'cli': True}


def test_part_without_relation_fails_graph_only(tmp_path, no_api):
    claims = base_claims()
    claims['parts'].append({'name': 'cli', 'doc': 'ARCHITECTURE.md', 'doc_lines': [1, 1], 'standalone': False})
    code, record = run(tmp_path, claims, '--graph-only')
    assert code == 1 and checks(record, 'part_connected')['cli'] is False


def test_relation_endpoints_must_be_parts(tmp_path, no_api):
    claims = base_claims()
    claims['relations'][0]['to'] = 'nowhere'
    code, record = run(tmp_path, claims, '--graph-only')
    assert code == 1 and checks(record, 'relation_parts') == {'R1': False}


def test_relation_contract_rule():
    claims = base_claims()
    claims['contracts'] = []
    result = docs_verify.graph(claims, [], {}, graph_only=True)
    assert {c['subject']: c['passed'] for c in result if c['rule'] == 'relation_contract'} == {'R1': False}


@pytest.mark.parametrize('field, value', [('provider', ''), ('users', [])])
def test_contract_needs_provider_and_user(tmp_path, no_api, field, value):
    claims = base_claims()
    claims['contracts'][0][field] = value
    code, record = run(tmp_path, claims, '--graph-only')
    assert code == 1 and checks(record, 'contract_parties') == {'queue': False}


def other_claims(version='1', part='store'):
    return {'version': 1, 'repository': 'acme/db',
            'parts': [{'name': part, 'doc': 'ARCHITECTURE.md', 'doc_lines': [1, 1], 'standalone': True}],
            'claims': [], 'relations': [],
            'contracts': [{'name': 'queue', 'version': version, 'provider': 'acme/app', 'users': ['acme/db'],
                           'doc': 'docs/contracts.md', 'doc_lines': [1, 1]}]}


def cross(tmp_path, other, target='acme/db:store'):
    claims = base_claims()
    claims['relations'].append(dict(claims['relations'][0], id='R2', to=target))
    other_repo = make_repo(tmp_path / 'db', other)
    return run(tmp_path, claims, '--graph-only', '--with', str(other_repo))


def test_cross_repository_pass(tmp_path, no_api):
    code, record = cross(tmp_path, other_claims())
    assert code == 0
    assert checks(record, 'contract_version') == {'queue (acme/app, acme/db)': True}
    assert checks(record, 'remote_part') == {'R2': True}


def test_cross_repository_version_mismatch(tmp_path, no_api):
    code, record = cross(tmp_path, other_claims(version='2'))
    assert code == 1 and checks(record, 'contract_version') == {'queue (acme/app, acme/db)': False}


def test_cross_repository_missing_part(tmp_path, no_api, capsys):
    code, record = cross(tmp_path, other_claims(part='other'))
    assert code == 1 and checks(record, 'remote_part') == {'R2': False}
    assert 'graph remote_part R2' in capsys.readouterr().out


def test_remote_target_without_with_is_unchecked(tmp_path, no_api):
    claims = base_claims()
    claims['relations'].append(dict(claims['relations'][0], id='R2', to='acme/db:store'))
    code, record = run(tmp_path, claims, '--graph-only')
    assert code == 0 and checks(record, 'remote_part') == {'R2': None}
    assert record['summary']['graph_unchecked'] == 1


def test_invalid_with_repository_fails(tmp_path, no_api):
    other = other_claims()
    other['version'] = 3
    code, record = cross(tmp_path, other)
    assert code == 1 and any(e.startswith('--with') for e in record['errors'])


def test_unknown_revision_is_an_error(tmp_path, capsys):
    repo = make_repo(tmp_path / 'repo', base_claims())
    assert cli.main(['docs-verify', str(repo), '--rev', 'nope', '--out', str(tmp_path / 'r.json')]) == 1
    assert 'cannot resolve revision' in capsys.readouterr().err


def test_decisions_client_keeps_status_and_code(api):
    _, replies = api
    replies.append((429, {'error': 'decisions_budget_reached', 'detail': 'secret'}))
    with pytest.raises(run_platform.DecisionsError) as raised:
        run_platform.Decisions().decide({'text': {}, 'questions': {}, 'repeats': 1})
    assert (raised.value.status, raised.value.code) == (429, 'decisions_budget_reached')
