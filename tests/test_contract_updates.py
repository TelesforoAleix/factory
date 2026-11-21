"""Synthetic pins and a Git Data API double; no live repositories or private state."""

import copy
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from test_stores import pg_store

from contracts import canonical, pins
from cplane import contract_updates as updates, state
from cplane.cli import main
from cplane.docs_verify import Snapshot
from cplane.runner import GitHub, Runner

USER = 'TelesforoAleix/factory'
PROVIDER = 'TelesforoAleix/homelab-v2'
BASE, OLD, NEW = 'a' * 40, 'b' * 40, 'c' * 40
OLD_SCHEMA = {'openapi': '3.1.0', 'paths': {}}
NEW_SCHEMA = {'openapi': '3.1.0', 'paths': {'/new': {'get': {}}}}
NOW = datetime(2026, 11, 21, 4, tzinfo=UTC)
BRANCH = 'contracts/run-api'
REAL_PROJECTS = updates.projects


def pin_files(schema=OLD_SCHEMA, commit=OLD):
    text = canonical.dumps(schema)
    record = dict(contract='run-api', provider=PROVIDER, commit=commit,
                  sha256=hashlib.sha256(text.encode()).hexdigest())
    return {'pins/run-api/schema.json': text, 'pins/run-api/pin.json': canonical.dumps(record)}


class FakeGitHub:
    def __init__(self):
        self.tips = {USER: BASE, PROVIDER: NEW}
        self.files = {(USER, BASE): {**pin_files(), 'untouched.txt': 'keep'},
                      (PROVIDER, NEW): {'contracts/run-api/openapi.json': canonical.dumps(NEW_SCHEMA)}}
        self.refs, self.prs, self.blobs, self.trees = {}, {}, {}, {}
        self.writes, self.opens, self.merges, self.checked, self.compares = [], [], [], [], []
        self.status = 'pending'
        self.changed = []
        self.app = dict(id=123, slug='factory')
        self.extra_files = []
        self.public = False
        self.next_sha = 1

    def default_tip(self, repo):
        return self.tips[repo]

    def branch_tip(self, repo, branch):
        return self.refs[(repo, branch)]

    def snapshot(self, repo, sha):
        files = self.files[(repo, sha)]
        snapshot = Snapshot(sha, files.get)
        snapshot.paths = tuple(files)
        return snapshot

    def is_public(self, repo):
        return self.public

    def open(self, repo, request):
        self.opens.append((repo, request))
        number = 1
        self.prs[repo, number] = dict(
            number=number, state='open', user=dict(type='Bot', login='factory[bot]'),
            base=dict(repo=dict(full_name=repo)),
            head=dict(ref=request['branch'], sha=self.refs[repo, request['branch']],
                      repo=dict(full_name=repo)))
        return number

    def merge_info(self, repo, number, expected=None):
        assert self.prs[repo, number]['head']['sha'] == expected
        return dict(state='OPEN', headRefOid=expected)

    def checks(self, repo, number, expected=None):
        self.checked.append((repo, number, expected))
        assert self.prs[repo, number]['head']['sha'] == expected
        return self.status, 'test' if self.status == 'red' else ''

    def merge(self, repo, number, expected=None):
        assert self.refs[repo, BRANCH] == expected
        self.merges.append((repo, number, expected))
        self.prs[repo, number]['state'] = 'closed'
        self.tips[repo] = expected
        return expected

    def compare_files(self, repo, base, sha):
        self.compares.append((repo, base, sha))
        return self.changed

    def call(self, repo, *args):
        assert args[0] == 'api'
        method = args[args.index('--method') + 1] if '--method' in args else 'GET'
        resource = next(a for a in args if a.startswith('repos/'))[len(f'repos/{repo}/'):]
        if method != 'GET':
            payload = json.loads(Path(args[args.index('--input') + 1]).read_text())
            self.writes.append((repo, method, resource, payload))
            sha = f'{self.next_sha:040x}'
            self.next_sha += 1
            if resource == 'git/blobs':
                self.blobs[sha] = payload['content']
            elif resource == 'git/trees':
                self.trees[sha] = payload
            elif resource == 'git/commits':
                tree = self.trees[payload['tree']]
                files = dict(self.files[repo, payload['parents'][0]])
                files.update({entry['path']: self.blobs[entry['sha']] for entry in tree['tree']})
                self.files[repo, sha] = files
            elif resource == 'git/refs':
                self.refs[repo, payload['ref'].removeprefix('refs/heads/')] = payload['sha']
            elif resource.startswith('git/refs/heads/'):
                self.refs[repo, resource.removeprefix('git/refs/heads/')] = payload['sha']
                for (pr_repo, _), pr in self.prs.items():
                    if pr_repo == repo and pr['head']['ref'] == BRANCH:
                        pr['head']['sha'] = payload['sha']
            else:
                raise AssertionError(resource)
            return json.dumps(dict(sha=sha))
        if resource.startswith('git/matching-refs/heads/'):
            branch = resource.removeprefix('git/matching-refs/heads/')
            sha = self.refs.get((repo, branch))
            return json.dumps([dict(ref='refs/heads/' + branch, object=dict(sha=sha))] if sha else [])
        if resource.startswith('git/commits/'):
            return json.dumps(dict(tree=dict(sha='base-tree')))
        if resource.startswith('issues/'):
            return json.dumps(dict(performed_via_github_app=self.app))
        if resource.startswith('pulls?'):
            prs = [pr for (pr_repo, _), pr in self.prs.items() if pr_repo == repo and pr['state'] == 'open']
            return json.dumps([prs])
        if resource.startswith('pulls/'):
            number = int(resource.split('/')[1])
            if '/files?' in resource:
                files = [dict(filename=p, status='modified') for p in updates.pin_paths('run-api')]
                return json.dumps([files + self.extra_files])
            return json.dumps(self.prs[repo, number])
        raise AssertionError(resource)


@pytest.fixture
def context(make_state, monkeypatch):
    path = make_state([])
    github = FakeGitHub()
    runner = Runner(path, github=github, clock=lambda: NOW)
    runner.jobs = {}
    monkeypatch.setattr(updates, 'projects', lambda path: {USER: 'FAC', PROVIDER: 'LAB'})
    monkeypatch.setattr(updates.times, 'LOCAL', UTC)
    monkeypatch.setenv('CPLANE_GITHUB_APP_ID', '123')
    monkeypatch.setenv('CPLANE_GITHUB_INSTALLATION_ID', '456')
    return runner, github


def build_catalog(github):
    catalog = updates.Catalog(github, {USER: 'FAC', PROVIDER: 'LAB'})
    return catalog, catalog.build()


def open_update(context):
    runner, github = context
    catalog, entries = build_catalog(github)
    updates.Job(runner).update(catalog, entries[0], entries[0]['users'][0])
    return github.prs[USER, 1]


def test_catalog_from_two_repositories_and_canonical_provider(context):
    _, github = context
    github.files[PROVIDER, NEW].update(pin_files())
    github.files[PROVIDER, NEW]['contracts/run-api/openapi.json'] = json.dumps(NEW_SCHEMA)
    _, entries = build_catalog(github)
    assert entries == [dict(
        contract='run-api', provider=PROVIDER, provider_commit=NEW,
        sha256=hashlib.sha256(canonical.dumps(NEW_SCHEMA).encode()).hexdigest(),
        users=[dict(repository=USER, commit=OLD,
                    sha256=json.loads(pin_files()['pins/run-api/pin.json'])['sha256'], current=False),
               dict(repository=PROVIDER, commit=OLD,
                    sha256=json.loads(pin_files()['pins/run-api/pin.json'])['sha256'], current=False)])]


@pytest.mark.parametrize('failure', ['missing', 'unreadable'])
def test_unreadable_provider_stays_in_catalog_and_has_no_pr(context, failure, monkeypatch):
    runner, github = context
    if failure == 'missing':
        github.files[PROVIDER, NEW] = {}
    else:
        original = github.snapshot
        def unavailable(repo, sha):
            if repo == PROVIDER:
                raise state.StateError('unavailable')
            return original(repo, sha)
        monkeypatch.setattr(github, 'snapshot', unavailable)
    catalog = updates.Catalog(github, {USER: 'FAC'})
    entry, = catalog.build()
    assert entry['provider_commit'] is None and entry['sha256'] is None
    assert entry['users'][0]['current'] is False
    updates.run(runner)
    assert github.opens == github.writes == []


def test_equal_hash_raises_no_pr_even_at_new_provider_commit(context):
    runner, github = context
    github.files[PROVIDER, NEW]['contracts/run-api/openapi.json'] = canonical.dumps(OLD_SCHEMA)
    updates.run(runner)
    assert github.opens == github.writes == []
    entry, = json.loads((runner.path.parent / 'contracts-catalog.json').read_text())
    assert entry['users'][0]['current'] is True


def test_update_writes_exact_pin_format_and_preserves_tree(context, tmp_path):
    runner, github = context
    open_update(context)
    sha = github.refs[USER, BRANCH]
    actual = github.files[USER, sha]
    schema = tmp_path / 'schema.json'
    schema.write_text(canonical.dumps(NEW_SCHEMA))
    pins.write('run-api', PROVIDER, NEW, schema, tmp_path / 'expected')
    for name in ('pin.json', 'schema.json'):
        assert actual['pins/run-api/' + name] == (tmp_path / 'expected' / name).read_text()
    assert actual['untouched.txt'] == 'keep'
    tree = next(payload for _, _, resource, payload in github.writes if resource == 'git/trees')
    assert tree['base_tree'] == 'base-tree'
    assert {f['path'] for f in tree['tree']} == set(updates.pin_paths('run-api'))
    commit = next(payload for _, _, resource, payload in github.writes if resource == 'git/commits')
    assert commit['parents'] == [BASE]
    assert commit['message'] == 'Update the run-api pin to homelab-v2@ccccccc'
    repo, request = github.opens[0]
    assert repo == USER and request['title'] == commit['message']
    assert NEW in request['body']
    assert all(e in request['body'] for e in [json.loads(pin_files()['pins/run-api/pin.json'])['sha256'],
                                            json.loads(actual['pins/run-api/pin.json'])['sha256']])
    assert not state.load(runner.path)['slices']


def test_up_to_date_branch_changes_nothing(context):
    runner, github = context
    open_update(context)
    before = copy.deepcopy((github.writes, github.opens))
    catalog, entries = build_catalog(github)
    updates.Job(runner).update(catalog, entries[0], entries[0]['users'][0])
    assert (github.writes, github.opens) == before


def test_outdated_branch_is_force_updated_from_default(context):
    runner, github = context
    github.refs[USER, BRANCH] = OLD
    github.files[USER, OLD] = pin_files()
    open_update(context)
    ref = github.writes[-1]
    assert ref[1:3] == ('PATCH', 'git/refs/heads/contracts/run-api')
    assert ref[3]['force'] is True


def test_green_merges_at_expected_head_without_review(context):
    runner, github = context
    open_update(context)
    head = github.refs[USER, BRANCH]
    github.status = 'green'
    updates.run(runner)
    assert github.checked == [(USER, 1, head)]
    assert github.merges == [(USER, 1, head)]
    assert not state.load(runner.path)['slices']


def test_red_records_planned_slice_and_planner_attention_once_per_head(context):
    runner, github = context
    open_update(context)
    github.status = 'red'
    updates.run(runner)
    first = state.load(runner.path)
    item, = first['slices']
    assert item['id'] == 'factory/pin-run-api-ccccccc'
    assert item['title'] == f'Adapt to the run-api change from {PROVIDER}@ccccccc'
    assert item['repo'] == USER and item['pr'] == 1
    assert item['state'] == 'planned' and item['brief'] is None
    assert item['attention']['kind'] == 'contract-change'
    assert item['attention']['for'] == 'planner'
    assert 'pull/1' in item['attention']['body'] and 'test' in item['attention']['body']
    notices = state.store(runner.path).notices()
    assert len(notices) == 1
    updates.run(runner)
    assert state.load(runner.path) == first
    assert state.store(runner.path).notices() == notices
    # A new head for the same provider creates a new notice, without replacing planner work.
    old_head = github.refs[USER, BRANCH]
    new_head = 'd' * 40
    github.files[USER, new_head] = github.files[USER, old_head]
    github.refs[USER, BRANCH] = new_head
    github.prs[USER, 1]['head']['sha'] = new_head
    updates.run(runner)
    assert len(state.load(runner.path)['slices']) == 1
    assert len(state.store(runner.path).notices()) == 2
    assert not github.merges


def test_pending_waits_and_checks_again_without_daily_scan(context):
    runner, github = context
    open_update(context)
    updates.run(runner)
    saved = (runner.path.parent / 'contracts-catalog.json').stat().st_mtime_ns
    updates.run(runner)
    assert len(github.checked) == 2 and not github.merges
    assert (runner.path.parent / 'contracts-catalog.json').stat().st_mtime_ns == saved
    assert not state.load(runner.path)['slices']


@pytest.mark.parametrize('violation', ['author', 'app', 'files', 'rename', 'head', 'fork', 'branch', 'pin'])
def test_guard_failure_never_merges_or_rewrites_and_raises_attention(context, violation):
    runner, github = context
    pr = open_update(context)
    head = github.refs[USER, BRANCH]
    if violation == 'author':
        pr['user']['login'] = 'other[bot]'
    elif violation == 'app':
        github.app['id'] = 999
    elif violation == 'files':
        github.extra_files = [dict(filename='other.txt', status='modified')]
    elif violation == 'rename':
        github.extra_files = [dict(filename='pins/run-api/schema.json', status='renamed', previous_filename='secret')]
    elif violation == 'head':
        pr['head']['sha'] = 'd' * 40
    elif violation == 'fork':
        pr['head']['repo']['full_name'] = 'other/repo'
    elif violation == 'branch':
        pr['head']['ref'] = 'contracts/bad/branch'
    else:
        github.files[USER, head]['pins/run-api/pin.json'] = '{}'
    writes = copy.deepcopy(github.writes)
    updates.run(runner)
    assert github.merges == [] and github.writes == writes
    item, = state.load(runner.path)['slices']
    assert item['attention']['kind'] == 'contract-change'
    assert 'pull/1' in item['attention']['body']
    notices = state.store(runner.path).notices()
    updates.run(runner)
    assert state.store(runner.path).notices() == notices


def test_guard_rechecked_after_ci(context):
    runner, github = context
    pr = open_update(context)
    github.status = 'green'
    check = github.checks
    def moved(*args, **kwargs):
        result = check(*args, **kwargs)
        pr['user']['login'] = 'another[bot]'
        return result
    github.checks = moved
    updates.run(runner)
    assert not github.merges
    assert state.load(runner.path)['slices'][0]['attention']['kind'] == 'contract-change'


def test_runner_pass_survives_job_error_and_exports(context, monkeypatch, capsys):
    runner, _ = context
    runner._run_pass = Mock()
    monkeypatch.setattr(updates, 'run', Mock(side_effect=RuntimeError('secret multiline\nvalue')))
    export = Mock()
    monkeypatch.setattr('cplane.runner.export_bot', export)
    runner.run()
    runner._run_pass.assert_called_once()
    export.assert_called_once_with(runner.path)
    assert capsys.readouterr().err.splitlines() == ['cplane: contract updates failed: RuntimeError']


def test_daily_trigger_uses_local_time_once_per_day(context, monkeypatch):
    runner, github = context
    monkeypatch.setattr(updates.times, 'LOCAL', ZoneInfo('Europe/Madrid'))
    runner.clock = lambda: datetime(2026, 11, 21, 2, 44, tzinfo=UTC)
    updates.run(runner)
    assert not github.opens
    runner.clock = lambda: datetime(2026, 11, 21, 2, 45, tzinfo=UTC)
    updates.run(runner)
    assert len(github.opens) == 1
    path = runner.path.parent / 'contracts-state.json'
    assert json.loads(path.read_text())['date'] == '2026-11-21'
    # Observe scans without altering the catalog instance binding.
    original = updates.Catalog.build
    scans = []
    monkeypatch.setattr(updates.Catalog, 'build', lambda self: (scans.append(1), original(self))[1])
    updates.run(runner)
    assert not scans
    runner.clock = lambda: datetime(2026, 11, 22, 2, 45, tzinfo=UTC)
    updates.run(runner)
    assert scans == [1]


@pytest.mark.parametrize('changed,scan', [('contracts/run-api/openapi.json', True), ('cplane/other.py', False)])
def test_schema_merge_triggers_full_scan_before_daily_time(context, changed, scan, monkeypatch):
    runner, github = context
    runner.clock = lambda: datetime(2026, 11, 21, 1, tzinfo=UTC)
    runner.jobs = {'provider/slice': dict(repository=PROVIDER, base=OLD, sha=NEW,
                                        contract_scan_pending=True)}
    github.changed = [dict(filename=changed)]
    updates.run(runner)
    assert bool(github.opens) == scan
    assert github.compares == [(PROVIDER, OLD, NEW)]
    updates.run(runner)
    assert github.compares == [(PROVIDER, OLD, NEW)]
    # A schema-triggered scan does not consume the later daily scan.
    if scan:
        original = updates.Catalog.build
        scans = []
        monkeypatch.setattr(updates.Catalog, 'build', lambda self: (scans.append(1), original(self))[1])
        runner.clock = lambda: NOW
        updates.run(runner)
        assert scans == [1]


def test_projects_use_active_records_and_resolve_short_names(context, monkeypatch):
    runner, _ = context
    projects = REAL_PROJECTS
    monkeypatch.setattr(state, 'postgres', lambda: True)
    backend = Mock()
    backend.library_projects.return_value = [dict(key='FAC', repository='factory', active=True),
                                            dict(key='LAB', repository=PROVIDER, active=True),
                                            dict(key='OLD', repository='old', active=False),
                                            dict(key='NEW', repository=None, active=True)]
    monkeypatch.setattr(state, 'store', lambda path: backend)
    assert projects(runner.path) == {USER: 'FAC', PROVIDER: 'LAB'}
    backend.library_projects.return_value = [dict(key='BAD', repository=None, active=True)]
    assert projects(runner.path) == {}
    backend.library_projects.return_value = [dict(key='BAD', repository='invalid/repo/name', active=True)]
    with pytest.raises(state.StateError, match='repository'):
        projects(runner.path)


def test_catalog_cli_prints_json_without_writing(context, monkeypatch, capsys):
    _, github = context
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr('cplane.runner.GitHub', lambda: github)
    assert main(['contracts', 'catalog']) == 0
    assert json.loads(capsys.readouterr().out)[0]['users'][0]['current'] is False
    assert not github.writes


def test_public_pr_still_uses_runner_deny_check(context, monkeypatch):
    _, github = context
    github.public = True
    deny = Mock()
    monkeypatch.setattr('cplane.runner.deny.Check', lambda: deny)
    open_update(context)
    deny.request.assert_called_once_with(github.opens[0][1])


def test_git_data_ref_and_path_scope_is_enforced():
    api = updates.GitData(Mock())
    with pytest.raises(state.StateError):
        api.point(USER, '../main', NEW, False)
    with pytest.raises(state.StateError):
        api.commit(USER, 'run-api', BASE, {'other': 'unsafe'}, 'message')
    api.github.call.assert_not_called()


def test_git_data_mutation_is_not_retried_or_counted_as_read(monkeypatch):
    calls = []
    def failed(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, '', 'refused')
    monkeypatch.setattr('cplane.runner.fence.github_environment', lambda repos: {})
    monkeypatch.setattr('cplane.runner.subprocess.run', failed)
    github = GitHub()
    with pytest.raises(state.StateError):
        updates.GitData(github).write(USER, 'git/blobs', dict(content='x', encoding='utf-8'))
    assert len(calls) == 1
    assert github.successful_reads == 0


def test_complete_runner_pass_calls_contract_job(context):
    runner, github = context
    runner.run()
    assert len(github.opens) == 1
    assert (runner.path.parent / 'contracts-state.json').exists()


def test_failed_scan_retries_and_still_checks_open_prs(context, monkeypatch):
    runner, github = context
    open_update(context)
    original = updates.Catalog.build
    monkeypatch.setattr(updates.Catalog, 'build', Mock(side_effect=RuntimeError('unavailable')))
    with pytest.raises(RuntimeError):
        updates.run(runner)
    assert len(github.checked) == 1
    assert not (runner.path.parent / 'contracts-state.json').exists()
    monkeypatch.setattr(updates.Catalog, 'build', original)
    updates.run(runner)
    assert len(github.checked) == 2
    assert json.loads((runner.path.parent / 'contracts-state.json').read_text())['date'] == '2026-11-21'


def test_head_change_after_ci_is_not_merged(context, monkeypatch):
    runner, github = context
    pr = open_update(context)
    original = github.checks
    def moved(*args, **kwargs):
        result = original(*args, **kwargs)
        old_head = github.refs[USER, BRANCH]
        new_head = 'd' * 40
        github.files[USER, new_head] = github.files[USER, old_head]
        github.refs[USER, BRANCH] = pr['head']['sha'] = new_head
        return result
    github.status = 'green'
    monkeypatch.setattr(github, 'checks', moved)
    updates.run(runner)
    assert not github.merges
    assert state.load(runner.path)['slices'][0]['attention']['kind'] == 'contract-change'


def test_orphan_branch_without_pin_is_replaced_from_default(context):
    runner, github = context
    github.refs[USER, BRANCH] = OLD
    github.files[USER, OLD] = {'orphan.txt': 'not delivered'}
    updates.run(runner)
    head = github.refs[USER, BRANCH]
    assert 'orphan.txt' not in github.files[USER, head]
    assert github.writes[-1][1:3] == ('PATCH', 'git/refs/heads/contracts/run-api')
    assert len(github.opens) == 1


def test_transient_guard_read_failure_waits_without_false_planner_attention(context, monkeypatch):
    from cplane.runner import GitHubReadError
    runner, github = context
    open_update(context)
    original = github.call
    def unavailable(repo, *args):
        if any('/issues/' in arg for arg in args):
            raise GitHubReadError('unavailable')
        return original(repo, *args)
    monkeypatch.setattr(github, 'call', unavailable)
    with pytest.raises(state.StateError, match='checks unavailable'):
        updates.run(runner)
    assert not state.load(runner.path)['slices']
    assert not github.merges


def test_postgres_job_uses_project_records_and_atomically_records_red_once(context, pg_store, monkeypatch):
    runner, github = context
    with pg_store.locked():
        pg_store.connection.execute("UPDATE cplane_projects SET active = key IN ('FAC', 'LAB', 'NEW')")
    monkeypatch.setattr(updates, 'projects', REAL_PROJECTS)
    assert REAL_PROJECTS(runner.path) == {USER: 'FAC', PROVIDER: 'LAB'}
    open_update(context)
    github.status = 'red'
    original = github.call
    def unavailable(repo, *args):
        if repo == PROVIDER and any('/pulls?' in arg for arg in args):
            raise state.StateError('unavailable')
        return original(repo, *args)
    monkeypatch.setattr(github, 'call', unavailable)
    with pytest.raises(state.StateError, match='checks unavailable'):
        updates.run(runner)
    monkeypatch.setattr(github, 'call', original)
    first = pg_store.load()
    item, = first['slices']
    assert item['id'] == 'factory/pin-run-api-ccccccc'
    assert item['brief'] is None and item['state'] == 'planned'
    assert item['attention']['for'] == 'planner'
    assert len(pg_store.notices()) == 1
    updates.run(runner)
    assert pg_store.load() == first
    assert len(pg_store.notices()) == 1


def test_other_repository_error_keeps_completed_red_attention(context, monkeypatch):
    from cplane.runner import GitHubReadError
    runner, github = context
    open_update(context)
    github.status = 'red'
    original = github.call
    def unavailable(repo, *args):
        if repo == PROVIDER and any('/pulls?' in arg for arg in args):
            raise GitHubReadError('unavailable')
        return original(repo, *args)
    monkeypatch.setattr(github, 'call', unavailable)
    with pytest.raises(state.StateError, match='checks unavailable'):
        updates.run(runner)
    first = state.load(runner.path)
    assert len(first['slices']) == len(state.store(runner.path).notices()) == 1
    monkeypatch.setattr(github, 'call', original)
    updates.run(runner)
    assert state.load(runner.path) == first
    assert len(state.store(runner.path).notices()) == 1


def test_old_merged_ledger_does_not_block_first_daily_scan(context):
    runner, github = context
    runner.jobs = {'old/slice': dict(repository='unavailable/repo', base=OLD, sha=NEW)}
    updates.run(runner)
    assert github.compares == []
    assert len(github.opens) == 1


def test_after_merge_marks_new_merge_for_contract_scan_and_keeps_old_notice(context, monkeypatch):
    runner, _ = context
    monkeypatch.setattr(runner, 'graph_check', lambda item, job: None)
    monkeypatch.setattr(runner, 'save_job', Mock())
    changes = [dict(name='example-api', version='2', users=[USER])]
    job = dict(request=dict(contract_changes=changes))
    runner.after_merge({}, job)
    assert job['contract_scan_pending'] is True
    kind, body = job['pending_attention'][0]
    assert kind == 'contract-change'
    assert 'example-api 2' in body and USER in body
    runner.save_job.assert_called_once_with(job)


@pytest.mark.parametrize('missing', [
    ('CPLANE_GITHUB_APP_ID',),
    ('CPLANE_GITHUB_INSTALLATION_ID',),
    ('CPLANE_GITHUB_APP_ID', 'CPLANE_GITHUB_INSTALLATION_ID'),
])
def test_job_silent_without_app_configuration(context, monkeypatch, capsys, missing):
    runner, github = context
    runner._run_pass = Mock()
    for key in missing:
        monkeypatch.delenv(key, raising=False)
    store = Mock(side_effect=AssertionError('Store must not be opened'))
    monkeypatch.setattr(state, 'store', store)
    github.call = Mock(side_effect=AssertionError('GitHub must not be called'))
    runner.run()
    assert capsys.readouterr().err == ''
    runner._run_pass.assert_called_once()
    store.assert_not_called()
    github.call.assert_not_called()
    assert not (runner.path.parent / 'contracts-state.json').exists()
    assert not (runner.path.parent / 'contracts-catalog.json').exists()


@pytest.mark.parametrize('records', [
    [],
    [dict(key='FAC', repository=None, active=True)],
    [dict(key='FAC', repository='', active=True)],
    [dict(key='FAC', repository=USER, active=False)],
])
def test_job_silent_without_active_project_repository(context, monkeypatch, capsys, records):
    runner, github = context
    runner._run_pass = Mock()
    backend = state.store(runner.path)
    backend.library_projects = Mock(return_value=records)
    monkeypatch.setattr(state, 'store', lambda path: backend)
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(updates, 'projects', REAL_PROJECTS)
    github.call = Mock(side_effect=AssertionError('GitHub must not be called'))
    runner.run()
    assert capsys.readouterr().err == ''
    backend.library_projects.assert_called_once()
    github.call.assert_not_called()
    assert not (runner.path.parent / 'contracts-state.json').exists()
    assert not (runner.path.parent / 'contracts-catalog.json').exists()


def test_job_real_failure_with_inputs_logs_one_line(context, capsys):
    runner, github = context
    runner._run_pass = Mock()
    github.call = Mock(side_effect=state.StateError('private diagnostics\nsecond line'))
    runner.run()
    assert capsys.readouterr().err == 'cplane: contract updates failed: StateError\n'
    assert github.call.call_count == 2
