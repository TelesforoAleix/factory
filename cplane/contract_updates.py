"""Discover contract users from pins and deliver bounded, CI-checked pin updates."""

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

from contracts import canonical, pins

from . import planner, state, times
from .executors import atomic_json
from .text_bounds import ATTENTION_LIMIT, cut

CONTRACT = re.compile(pins.PATTERNS['contract'])
SCHEMA_PATH = re.compile(r'contracts/[a-z0-9]+(?:-[a-z0-9]+)*/openapi\.json')


class InvalidPin(state.StateError):
    """A readable branch does not hold a valid canonical pin."""


def projects(path):
    """Use the same project records as `cplane project list`; NEW has no repo."""
    if not state.postgres():
        return {}
    result = {}
    for project in state.store(path).library_projects():
        if not project['active']:
            continue
        repo = project['repository']
        if not repo and project['key'] == 'NEW':
            continue
        if isinstance(repo, str) and '/' not in repo:
            repo = 'TelesforoAleix/' + repo
        if not isinstance(repo, str) or not re.fullmatch(pins.PATTERNS['provider'], repo):
            raise state.StateError('Active project has no resolved repository')
        result[repo] = project['key']
    return result


class GitData:
    """Small Git Data adapter; every write is an explicit JSON request via the App."""

    def __init__(self, github):
        self.github = github

    def read(self, repo, resource):
        return json.loads(self.github.call(repo, 'api', f'repos/{repo}/{resource}'))

    def pages(self, repo, resource):
        pages = json.loads(self.github.call(
            repo, 'api', f'repos/{repo}/{resource}', '--paginate', '--slurp'))
        return [entry for page in pages for entry in page]

    def write(self, repo, resource, payload, method='POST'):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'request.json'
            path.write_text(canonical.dumps(payload), encoding='utf-8')
            return json.loads(self.github.call(
                repo, 'api', '--method', method, f'repos/{repo}/{resource}',
                '--input', str(path)))

    def branch(self, repo, contract):
        branch = 'contracts/' + contract
        refs = self.read(repo, 'git/matching-refs/heads/' + quote(branch, safe='/'))
        return next((r['object']['sha'] for r in refs
                     if r['ref'] == 'refs/heads/' + branch), None)

    def commit(self, repo, contract, base, files, message):
        if not CONTRACT.fullmatch(contract) or set(files) != set(pin_paths(contract)):
            raise state.StateError('Refusing contract update outside the two pin files')
        parent = self.read(repo, 'git/commits/' + base)
        entries = []
        for path, content in files.items():
            blob = self.write(repo, 'git/blobs', dict(content=content, encoding='utf-8'))
            entries.append(dict(path=path, mode='100644', type='blob', sha=blob['sha']))
        tree = self.write(repo, 'git/trees', dict(base_tree=parent['tree']['sha'], tree=entries))
        return self.write(repo, 'git/commits', dict(
            message=message, parents=[base], tree=tree['sha']))['sha']

    def point(self, repo, contract, sha, exists):
        if not CONTRACT.fullmatch(contract):
            raise state.StateError('Refusing non-contract ref')
        branch = 'contracts/' + contract
        if exists:
            self.write(repo, 'git/refs/heads/' + quote(branch, safe='/'),
                       dict(sha=sha, force=True), 'PATCH')
        else:
            self.write(repo, 'git/refs', dict(ref='refs/heads/' + branch, sha=sha))


def pin_paths(contract):
    return [f'pins/{contract}/schema.json', f'pins/{contract}/pin.json']


def read_pin(snapshot, contract):
    schema_path, pin_path = pin_paths(contract)
    raw, schema = snapshot.read(pin_path), snapshot.read(schema_path)
    if raw is None:
        raise InvalidPin('Contract pin unavailable')
    record = canonical.parse(raw, pin_path)
    errors = pins._check(record)
    if errors or record['contract'] != contract or schema is None:
        raise InvalidPin('Invalid contract pin')
    if (raw != canonical.dumps(record)
            or schema != canonical.dumps(canonical.parse(schema, schema_path))
            or hashlib.sha256(schema.encode()).hexdigest() != record['sha256']):
        raise InvalidPin('Invalid contract pin form or hash')
    return record


class Catalog:
    def __init__(self, github, repositories):
        self.github, self.repositories = github, repositories
        self.tips, self.schemas = {}, {}

    def build(self):
        contracts = {}
        snapshots = {}

        def snapshot(repo):
            if repo not in snapshots:
                self.tips[repo] = self.github.default_tip(repo)
                snapshots[repo] = self.github.snapshot(repo, self.tips[repo])
            return snapshots[repo]

        for repo in sorted(self.repositories):
            try:
                user = snapshot(repo)
            except Exception:
                # Its pins cannot be discovered; readable users can still name
                # this repository as an unavailable provider.
                continue
            for path in sorted(user.paths):
                match = re.fullmatch(r'pins/([a-z0-9]+(?:-[a-z0-9]+)*)/pin\.json', path)
                if not match:
                    continue
                contract = match[1]
                pin = read_pin(user, contract)
                key = (contract, pin['provider'])
                if key not in contracts:
                    entry = dict(contract=contract, provider=pin['provider'],
                                 provider_commit=None, sha256=None, users=[])
                    try:
                        provider = snapshot(pin['provider'])
                        raw = provider.read(f'contracts/{contract}/openapi.json')
                        if raw is None:
                            raise state.StateError('Provider schema unavailable')
                        text = canonical.dumps(canonical.parse(raw, 'provider schema'))
                        self.schemas[key] = text
                        entry.update(provider_commit=self.tips[pin['provider']],
                                     sha256=hashlib.sha256(text.encode()).hexdigest())
                    except Exception:  # An unreadable provider remains visible, without an update.
                        pass
                    contracts[key] = entry
                entry = contracts[key]
                entry['users'].append(dict(repository=repo, commit=pin['commit'],
                                           sha256=pin['sha256'],
                                           current=pin['sha256'] == entry['sha256']))
        return [contracts[key] for key in sorted(contracts)]


def record_attention(path, repo, contract, number, head, body, pin=None):
    """One durable notice per head, using the store's validated mutation path."""
    short = pin['commit'][:7] if pin else f'pr-{number}'
    identifier = f"{repo.split('/')[-1]}/pin-{contract}-{short}"
    event = f'contract PR #{number} head {head}'
    with state.locked(path):
        existing = next((s for s in state.load(path)['slices'] if s['id'] == identifier), None)
        if existing and any(log['event'] == event for log in existing['log']):
            return

        def change(item, data, at):
            if existing is None:
                title = (f"Adapt to the {contract} change from {pin['provider']}@{short}"
                         if pin else f'Review the {contract} update PR #{number}')
                item.update(repo=repo, feature='Contracts', title=title, pr=number,
                            no_feature='Contract pin update needs planner adaptation')
            item['attention'] = dict(kind='contract-change', body=cut(body, ATTENTION_LIMIT),
                                     since=at, answer=None, approved=False, **{'for': 'planner'})
            return f'Needs planner attention: {body}', None

        state.update_locked(path, identifier, 'contract-change', 'runner', change,
                            create=(lambda: planner.new_slice(identifier)) if existing is None else None,
                            event=event)


class Job:
    def __init__(self, runner):
        self.runner, self.github = runner, runner.github
        self.api = GitData(self.github)

    def guard(self, repo, listed):
        number = listed['number']
        pr = self.api.read(repo, f'pulls/{number}')
        branch = pr['head']['ref']
        contract = branch.removeprefix('contracts/')
        if not branch.startswith('contracts/') or not CONTRACT.fullmatch(contract):
            raise state.StateError('Invalid contract branch')
        if (pr['state'] != 'open' or pr['head']['repo']['full_name'] != repo
                or pr['base']['repo']['full_name'] != repo):
            raise state.StateError('Contract PR repository or state differs')
        issue = self.api.read(repo, f'issues/{number}')
        app = issue.get('performed_via_github_app') or {}
        if (str(app.get('id')) != os.environ.get('CPLANE_GITHUB_APP_ID')
                or not app.get('slug') or pr['user'].get('type') != 'Bot'
                or pr['user'].get('login') != app['slug'] + '[bot]'):
            raise state.StateError('Contract PR author is not Factory App')
        files = self.api.pages(repo, f'pulls/{number}/files?per_page=100')
        if (len(files) != 2 or {f['filename'] for f in files} != set(pin_paths(contract))
                or any(f.get('previous_filename') or f['status'] not in ('added', 'modified')
                       for f in files)):
            raise state.StateError('Contract PR changes other paths')
        head = self.github.branch_tip(repo, branch)
        if pr['head']['sha'] != head:
            raise state.StateError('Contract PR head differs from branch')
        pin = read_pin(self.github.snapshot(repo, head), contract)
        self.github.merge_info(repo, number, expected=head)
        return contract, head, pin

    def check(self, repo, pr):
        from .github_app import GitHubAppTransientError
        from .runner import GitHubReadError

        branch, number = pr['head']['ref'], pr['number']
        try:
            contract, head, pin = self.guard(repo, pr)
        except (GitHubReadError, GitHubAppTransientError):
            raise
        except (state.StateError, canonical.ContractError, KeyError, TypeError) as error:
            contract = branch.removeprefix('contracts/')
            contract = contract if CONTRACT.fullmatch(contract) else 'unknown'
            record_attention(self.runner.path, repo, contract, number, pr['head']['sha'],
                             f'Planner: review https://github.com/{repo}/pull/{number}: '
                             f'contract update guard failed ({type(error).__name__})')
            return False
        status, failed = self.github.checks(repo, number, expected=head)
        if status == 'green':
            # Re-read all guard evidence after CI; merge itself also matches the head.
            try:
                checked_contract, checked_head, _ = self.guard(repo, pr)
                if checked_contract != contract or checked_head != head:
                    raise state.StateError('Contract PR changed during CI check')
            except (GitHubReadError, GitHubAppTransientError):
                raise
            except (state.StateError, canonical.ContractError, KeyError, TypeError):
                record_attention(self.runner.path, repo, contract, number, head,
                                 f'Planner: review https://github.com/{repo}/pull/{number}: '
                                 'contract update changed during CI check')
                return False
            self.github.merge(repo, number, expected=head)
        elif status == 'red':
            record_attention(self.runner.path, repo, contract, number, head,
                             f'Planner: adapt to https://github.com/{repo}/pull/{number}; '
                             f'failed checks: {failed}', pin)
        return True

    def update(self, catalog, entry, user):
        contract, provider = entry['contract'], entry['provider']
        repo, commit = user['repository'], entry['provider_commit']
        branch = 'contracts/' + contract
        tip = self.api.branch(repo, contract)
        if tip:
            try:
                pin = read_pin(self.github.snapshot(repo, tip), contract)
            except (InvalidPin, canonical.ContractError):
                pin = None
            if (pin and pin['commit'] == commit and pin['sha256'] == entry['sha256']
                    and pin['provider'] == provider):
                return
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema = root / 'provider.json'
            schema.write_text(catalog.schemas[(contract, provider)], encoding='utf-8')
            folder = root / 'pin'
            pins.write(contract, provider, commit, schema, folder)
            files = {f'pins/{contract}/{path.name}': path.read_text(encoding='utf-8')
                     for path in sorted(folder.iterdir())}
        message = f"Update the {contract} pin to {provider.split('/')[-1]}@{commit[:7]}"
        head = self.api.commit(repo, contract, catalog.tips[repo], files, message)
        self.api.point(repo, contract, head, tip is not None)
        self.runner.open_pr(repo, dict(
            branch=branch, title=message,
            body=f"Provider commit: {provider}@{commit}\n\n"
                 f"Old SHA-256: {user['sha256']}\nNew SHA-256: {entry['sha256']}\n",
            node_steps=None, contract_changes=None))


def _run_locked(runner):
    """Check open updates every pass; scan daily after 03:45 or after schema merges."""
    with state.locked(runner.path):
        repositories = projects(runner.path)
        if not repositories:
            return
        job = Job(runner)
        blocked, errors = set(), []
        for repo in sorted(repositories):
            try:
                prs = job.api.pages(repo, 'pulls?state=open&per_page=100')
            except Exception as error:
                errors.append(error)
                blocked.add((repo, None))
                continue
            for pr in prs:
                branch = pr['head']['ref']
                if not branch.startswith('contracts/'):
                    continue
                try:
                    if not job.check(repo, pr):
                        blocked.add((repo, branch))
                except Exception as error:
                    errors.append(error)
                    blocked.add((repo, branch))
        path = runner.path.parent / 'contracts-state.json'
        saved = json.loads(path.read_text()) if path.exists() else {}
        observed = dict(saved.get('merges', {}))
        schema_merge = False
        for identifier, merged in getattr(runner, 'jobs', {}).items():
            sha = merged.get('sha')
            if not sha or observed.get(identifier) == sha:
                continue
            files = runner.github.compare_files(merged['repository'], merged['base'], sha)
            if len(files) >= 300:
                raise state.StateError('Schema merge comparison may be truncated')
            schema_merge |= any(SCHEMA_PATH.fullmatch(name) for f in files
                                for name in (f['filename'], f.get('previous_filename', '')))
            observed[identifier] = sha
        local = runner.clock().astimezone(times.LOCAL)
        today = local.date().isoformat()
        daily = (local.hour, local.minute) >= (3, 45) and saved.get('daily_date') != today
        if daily or schema_merge:
            catalog = Catalog(runner.github, repositories)
            entries = catalog.build()
            atomic_json(runner.path.parent / 'contracts-catalog.json', entries)
            for entry in entries:
                if entry['provider_commit'] is None:
                    continue
                for user in entry['users']:
                    repo = user['repository']
                    if (not user['current'] and (repo, None) not in blocked
                            and (repo, 'contracts/' + entry['contract']) not in blocked):
                        job.update(catalog, entry, user)
            saved['date'] = today
            if daily:
                saved['daily_date'] = today
        if errors:
            raise state.StateError('Contract PR checks unavailable')
        saved['merges'] = observed
        atomic_json(path, saved)


def run(runner):
    """Keep completed planner writes even if a later GitHub operation fails."""
    failure = None
    with state.locked(runner.path):
        try:
            _run_locked(runner)
        except Exception as error:
            # Raise only after committing successful, validated slice updates.
            # Failed mutations have their own savepoint in state.update_locked.
            failure = error
    if failure is not None:
        raise failure
