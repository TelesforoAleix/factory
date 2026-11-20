"""Check a repository's documentation claims, relations and part graph.

The input is ``docs/claims.json`` at a git revision. Requests to the decisions
API are assembled by code from cited lines only. The record never holds source
text; it keeps ids, verdicts, raw answers, usage and graph results.
"""

from datetime import datetime, timezone
import hashlib
from importlib.resources import files
import json
import subprocess

from jsonschema import Draft202012Validator

from . import run_platform
from .state import StateError

CLAIMS_PATH = 'docs/claims.json'
SCHEMA = json.loads(files('schema').joinpath('claims.schema.json').read_text())
TEXT_LIMIT = 80_000
REPEATS = 3
CHOICES = {
    'supported': 'every part of the claim is shown by the given lines',
    'partly': 'some part is shown, some part is missing or different',
    'not_supported': 'the lines do not show the claim, or contradict it',
}
INSTRUCTIONS = {
    'claim': 'Decide whether the cited code and text fully support the claim. Judge only from the given lines.',
    'relation': ("Decide whether the provider's lines and the user's lines show this connection, "
                 'through the named contract when one is given.'),
}
VERDICTS = ('pass', 'flagged', 'too_large', 'error', 'not_checked')
STOP = {429: 'decisions_budget_reached', 503: 'decisions_unavailable'}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Revision:
    """Read-only file access to one commit of a checked-out repository."""

    def __init__(self, path, rev='HEAD'):
        self.path = str(path)
        result = subprocess.run(['git', '-C', self.path, 'rev-parse', '--verify', '--quiet', '--end-of-options',
                                 rev + '^{commit}'], capture_output=True, text=True, check=False)
        if result.returncode != 0 or not result.stdout.strip():
            raise StateError(f'cannot resolve revision {rev!r} in {self.path}')
        self.sha = result.stdout.strip()
        self._cache = {}

    def read(self, path):
        """Return the file's text, or None when it does not exist at the revision."""
        if path not in self._cache:
            result = subprocess.run(['git', '-C', self.path, 'cat-file', 'blob', f'{self.sha}:{path}'],
                                    capture_output=True, check=False)
            text = None
            if result.returncode == 0:
                try:
                    text = result.stdout.decode('utf-8')
                except UnicodeError:
                    text = None
            self._cache[path] = text
        return self._cache[path]

    def lines(self, path):
        text = self.read(path)
        return None if text is None else text.splitlines()


class Snapshot(Revision):
    """The same read-only access over a ``fetch(path) -> text | None`` callable, with no checkout."""

    def __init__(self, sha, fetch):
        self.path, self.sha, self._fetch, self._cache = None, sha, fetch, {}

    def read(self, path):
        if path not in self._cache:
            text = self._fetch(path)
            self._cache[path] = text if isinstance(text, str) else None
        return self._cache[path]


def _where(error):
    return '$' + ''.join(f'[{p}]' if isinstance(p, int) else f'.{p}' for p in error.absolute_path)


def load(revision):
    """Return (claims, raw bytes, errors). Errors are structural, never source text."""
    raw = revision.read(CLAIMS_PATH)
    if raw is None:
        return None, None, [f'{CLAIMS_PATH} is missing or not UTF-8 at {revision.sha}']
    try:
        claims = json.loads(raw)
    except ValueError:
        return None, raw.encode(), [f'{CLAIMS_PATH} is not valid JSON']
    errors = [f'{_where(e)}: fails {e.validator}'
              for e in sorted(Draft202012Validator(SCHEMA).iter_errors(claims), key=lambda e: list(map(str, e.absolute_path)))]
    return (None if errors else claims), raw.encode(), errors


def citation_errors(claims, revision):
    errors = []
    for kind, key in (('parts', 'name'), ('claims', 'id'), ('relations', 'id'), ('contracts', 'name')):
        seen = set()
        for entry in claims[kind]:
            if entry[key] in seen:
                errors.append(f'{kind}: duplicate {key} {entry[key]!r}')
            seen.add(entry[key])

    def cite(where, path, span):
        a, b = span
        if a > b:
            errors.append(f'{where}: range {a}-{b} is reversed')
            return
        lines = revision.lines(path)
        if lines is None:
            errors.append(f'{where}: {path} does not exist at the revision')
        elif b > len(lines):
            errors.append(f'{where}: {path} lines {a}-{b} exceed its {len(lines)} lines')

    for kind in ('parts', 'claims', 'contracts'):
        for index, entry in enumerate(claims[kind]):
            cite(f'{kind}[{index}].doc_lines', entry['doc'], entry['doc_lines'])
    for index, claim in enumerate(claims['claims']):
        for n, source in enumerate(claim['sources']):
            cite(f'claims[{index}].sources[{n}]', source['path'], source['lines'])
    contracts = {c['name'] for c in claims['contracts']}
    for index, relation in enumerate(claims['relations']):
        for key in ('provider_sources', 'user_sources'):
            for n, source in enumerate(relation[key]):
                cite(f'relations[{index}].{key}[{n}]', source['path'], source['lines'])
        if not relation['provider_sources'] and not relation['user_sources']:
            errors.append(f'relations[{index}]: cites no lines')
        if relation['contract'] is not None and relation['contract'] not in contracts:
            errors.append(f'relations[{index}].contract: {relation["contract"]!r} is not in contracts')
    return errors


def excerpt(revision, path, span):
    lines = revision.lines(path)
    return '\n'.join(f'{path}:{n}: {lines[n - 1]}' for n in range(span[0], span[1] + 1))


def assemble(kind, item, claims, revision):
    """Build the request ``text`` deterministically from cited lines."""
    if kind == 'claim':
        text = {'claim': item['text'], 'document': excerpt(revision, item['doc'], item['doc_lines'])}
        for n, source in enumerate(item['sources'], 1):
            text[f'source_{n}'] = excerpt(revision, source['path'], source['lines'])
        return text
    text = {
        'relation': '\n'.join((f"from: {item['from']}", f"to: {item['to']}", f"how: {item['how']}",
                               f"contract: {item['contract'] or 'none'}", f"text: {item['text']}")),
        'provider': '\n'.join(excerpt(revision, s['path'], s['lines']) for s in item['provider_sources']),
        'user': '\n'.join(excerpt(revision, s['path'], s['lines']) for s in item['user_sources']),
    }
    if item['contract'] is not None:
        contract = next(c for c in claims['contracts'] if c['name'] == item['contract'])
        text['contract'] = excerpt(revision, contract['doc'], contract['doc_lines'])
    return text


def request(kind, text):
    return {'text': text,
            'questions': {'support': {'instructions': INSTRUCTIONS[kind], 'choices': dict(CHOICES)}},
            'repeats': REPEATS}


def _answers(value):
    """Return (question result, raw answers) from a 200 response, or raise ValueError."""
    question = (value.get('questions') or {}).get('support') if isinstance(value.get('questions'), dict) else None
    if not isinstance(question, dict) or not isinstance(question.get('answers'), list):
        raise ValueError
    answers = []
    for answer in question['answers']:
        if not isinstance(answer, dict) or not isinstance(answer.get('choice'), str):
            raise ValueError
        answers.append({k: answer.get(k) for k in ('choice', 'confidence', 'probabilities')})
    return question, answers


def judge(client, body):
    """Return (item fields, response or None, stop reason or None)."""
    for attempt in (1, 2):
        try:
            value = client.decide(body)
        except run_platform.DecisionsError as error:
            if error.status == 413:
                return {'verdict': 'too_large', 'error': error.code or 'decisions_input_too_large'}, None, None
            if error.status in STOP:
                return None, None, error.code or STOP[error.status]
            if error.status in (401, 403):
                return None, None, error.code or f'http_{error.status}'
            if error.status == 502 and attempt == 1:
                continue
            return {'verdict': 'error', 'error': error.code or f'http_{error.status}', 'attempts': attempt}, None, None
        except run_platform.Unavailable:
            return None, None, 'platform_unavailable'
        try:
            question, answers = _answers(value)
        except ValueError:
            return {'verdict': 'error', 'error': 'invalid_response', 'attempts': attempt}, value, None
        confidence = question.get('confidence')
        passed = len(answers) == REPEATS and all(a['choice'] == 'supported' for a in answers)
        return {'verdict': 'pass' if passed else 'flagged', 'choice': question.get('choice'),
                'confidence': confidence, 'agreement': question.get('agreement'),
                'answers': answers, 'attempts': attempt}, value, None


def _split(target):
    repository, separator, part = target.rpartition(':')
    return (repository, part) if separator else (None, target)


def graph(claims, items, others, *, graph_only):
    """Code-only graph rules. ``others`` maps owner/name to a valid claims document."""
    checks = []

    def check(rule, subject, passed, detail=None):
        checks.append({'rule': rule, 'subject': subject, 'passed': passed, **({'detail': detail} if detail else {})})

    parts = {p['name'] for p in claims['parts']}
    verdicts = {item['id']: item['verdict'] for item in items if item['kind'] == 'relation'}
    for relation in claims['relations']:
        repository, part = _split(relation['to'])
        missing = [end for end, name in (('from', relation['from']), ('to', None if repository else part))
                   if name is not None and name not in parts]
        check('relation_parts', relation['id'], not missing,
              'unknown ' + ' and '.join(missing) + ' part' if missing else None)
    for part in claims['parts']:
        if part['standalone']:
            check('part_connected', part['name'], True, 'standalone')
            continue
        linked = [r for r in claims['relations']
                  if r['from'] == part['name'] or (_split(r['to']) == (None, part['name']))]
        good = linked if graph_only else [r for r in linked if verdicts.get(r['id']) == 'pass']
        check('part_connected', part['name'], bool(good),
              None if good else ('no relation' if not linked else 'no passing relation'))
    contracts = {c['name'] for c in claims['contracts']}
    for relation in claims['relations']:
        if relation['contract'] is not None:
            check('relation_contract', relation['id'], relation['contract'] in contracts)
    for contract in claims['contracts']:
        missing = [k for k, ok in (('provider', bool(contract['provider'].strip())),
                                   ('user', any(u.strip() for u in contract['users']))) if not ok]
        check('contract_parties', contract['name'], not missing,
              'missing ' + ' and '.join(missing) if missing else None)

    documents = {claims['repository']: claims, **others}
    names = sorted(documents)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            theirs = {c['name']: c for c in documents[second]['contracts']}
            for contract in documents[first]['contracts']:
                other = theirs.get(contract['name'])
                if other is not None:
                    same = other['version'] == contract['version']
                    check('contract_version', f"{contract['name']} ({first}, {second})", same,
                          None if same else f"version {contract['version']} in {first}, {other['version']} in {second}")
    for name in names:
        for relation in documents[name]['relations']:
            repository, part = _split(relation['to'])
            if repository is None:
                continue
            subject = f"{name}:{relation['id']}" if name != claims['repository'] else relation['id']
            if repository not in documents:
                if name == claims['repository']:
                    check('remote_part', subject, None, f'{repository} not given with --with')
                continue
            found = part in {p['name'] for p in documents[repository]['parts']}
            check('remote_part', subject, found, None if found else f'{relation["to"]} does not exist')
    return checks


def verify(path, *, rev='HEAD', others=(), graph_only=False, client=None):
    """Return (record, exit code). Never writes to the checked repository."""
    started = _now()
    revision = path if isinstance(path, Revision) else Revision(path, rev)
    record = {'version': 1, 'repository': None, 'revision': revision.sha, 'claims_sha256': None,
              'started_at': started, 'ended_at': None, 'graph_only': graph_only, 'model': None,
              'usage': {'input_tokens': 0, 'output_tokens': 0}, 'errors': [], 'stopped': None,
              'items': [], 'graph': [], 'summary': None}

    def finish(code):
        record['ended_at'] = _now()
        counts = {v: sum(i['verdict'] == v for i in record['items']) for v in VERDICTS}
        record['summary'] = {**counts, 'graph_failed': sum(c['passed'] is False for c in record['graph']),
                             'graph_unchecked': sum(c['passed'] is None for c in record['graph']),
                             'errors': len(record['errors'])}
        return record, code

    claims, raw, errors = load(revision)
    if raw is not None:
        record['claims_sha256'] = hashlib.sha256(raw).hexdigest()
    if claims is not None:
        record['repository'] = claims['repository']
        errors = citation_errors(claims, revision)
    others_docs = {}
    for other_path in others:
        other = Revision(other_path)
        document, _, other_errors = load(other)
        errors += [f'--with {other_path}: {e}' for e in other_errors]
        if document is not None:
            if claims is not None and document['repository'] == claims['repository']:
                errors.append(f'--with {other_path}: names the checked repository')
            elif document['repository'] in others_docs:
                errors.append(f'--with {other_path}: repeats {document["repository"]}')
            else:
                others_docs[document['repository']] = document
    if errors:
        record['errors'] = errors
        return finish(1)

    work = [('claim', c) for c in claims['claims']] + [('relation', r) for r in claims['relations']]
    models = []
    if not graph_only and work:
        if client is None:
            try:
                client = run_platform.Decisions()
            except run_platform.Unavailable:
                record['stopped'] = 'platform_unavailable'
        for kind, item in work:
            entry = {'id': item['id'], 'kind': kind}
            record['items'].append(entry)
            if record['stopped']:
                entry['verdict'] = 'not_checked'
                continue
            text = assemble(kind, item, claims, revision)
            if sum(len(v) for v in text.values()) > TEXT_LIMIT:
                entry.update(verdict='too_large', error='text_limit')
                continue
            result, response, stop = judge(client, request(kind, text))
            if stop:
                record['stopped'] = stop
                entry['verdict'] = 'not_checked'
                continue
            entry.update(result)
            if response is not None:
                usage = response.get('usage') if isinstance(response.get('usage'), dict) else {}
                for key in ('input_tokens', 'output_tokens'):
                    if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool):
                        record['usage'][key] += usage[key]
                model = response.get('model')
                if isinstance(model, str):
                    provider = response.get('provider')
                    label = f'{provider}/{model}' if isinstance(provider, str) else model
                    if label not in models:
                        models.append(label)
    record['model'] = models[0] if len(models) == 1 else (models or None)
    record['graph'] = graph(claims, record['items'], others_docs, graph_only=graph_only)
    if record['stopped']:
        return finish(2)
    failing = (any(i['verdict'] != 'pass' for i in record['items'])
               or any(c['passed'] is False for c in record['graph']))
    return finish(1 if failing else 0)


def graph_check(revision):
    """The graph-only check on a Revision or Snapshot: (record, exit code, summary text)."""
    record, code = verify(revision, graph_only=True)
    return record, code, summary(record)


def summary(record):
    s = record['summary']
    lines = [f"docs-verify {record['repository'] or '?'} at {record['revision'][:12]}: "
             + ', '.join(f'{s[v]} {v}' for v in VERDICTS)
             + f"; graph {s['graph_failed']} failing, {s['graph_unchecked']} unchecked"]
    if record['stopped']:
        lines.append(f"stopped: {record['stopped']}")
    lines += [f'error: {e}' for e in record['errors']]
    for verdict in VERDICTS[1:]:
        ids = [i['id'] for i in record['items'] if i['verdict'] == verdict]
        if ids:
            lines.append(f'{verdict}: ' + ' '.join(ids))
    lines += [f"graph {c['rule']} {c['subject']}: {c.get('detail') or 'failed'}"
              for c in record['graph'] if c['passed'] is False]
    return '\n'.join(lines)


def command(args):
    record, code = verify(args.path, rev=args.rev, others=args.others or (), graph_only=args.graph_only)
    text = json.dumps(record, indent=2, ensure_ascii=False) + '\n'
    with open(args.out, 'w', encoding='utf-8') as handle:
        handle.write(text)
    print(summary(record))
    return code
