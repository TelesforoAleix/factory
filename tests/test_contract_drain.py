"""The drain check with a fake usage endpoint, fake slices and a synthetic catalog."""

import json
from datetime import UTC, datetime

import pytest

from cplane import contract_drain, run_platform, state
from cplane.cli import main
from cplane.eligibility import eligibility

NOW = datetime(2026, 11, 21, 12, tzinfo=UTC)
USER = 'TelesforoAleix/factory'
PROVIDER = 'TelesforoAleix/homelab-v2'
MERGED_AT = '2026-11-01T10:00:00+00:00'
STEP = dict(contract='run-api', shape='base', expand='factory/expand')


def usage(*shapes, unknown=(), contract='run-api', since='2026-10-22'):
    return dict(contract=contract, schema='0' * 64, since=since,
                shapes=[dict(application='factory', operation='POST /v1/runs', shape=shape,
                             day=day, count=count) for shape, day, count in shapes],
                unknown_fields=[dict(application=a, operation=o, field=f, first_seen='2026-11-01',
                                     last_seen='2026-11-20', count=3) for a, o, f in unknown])


class FakeEndpoint:
    def __init__(self, monkeypatch):
        self.value, self.error, self.calls = usage(), None, 0
        endpoint = self

        class Connection:
            def request(self, path):
                assert path == '/v1/contracts/usage'
                endpoint.calls += 1
                if endpoint.error:
                    raise run_platform.Unavailable(endpoint.error)
                return endpoint.value

        monkeypatch.setattr(run_platform, 'Connection', Connection)


@pytest.fixture
def endpoint(monkeypatch):
    return FakeEndpoint(monkeypatch)


def log(at, text='add'):
    return dict(at=at, actor='planner', event=text)


def make(slice_data, identifier, *, repo=USER, created='2026-11-05T00:00:00+00:00', **fields):
    return dict(slice_data, id=identifier, repo=repo, state=fields.pop('state', 'planned'),
                log=[log(created)] + fields.pop('log', []), **fields)


@pytest.fixture
def world(tmp_path, slice_data):
    (tmp_path / 'contracts-catalog.json').write_text(json.dumps([dict(
        contract='run-api', provider=PROVIDER, provider_commit='a' * 40, sha256='0' * 64,
        users=[dict(repository=USER, commit='a' * 40, sha256='0' * 64, current=True)])]))
    expand = make(slice_data, 'factory/expand', created='2026-10-01T00:00:00+00:00',
                  state='in review', log=[log(MERGED_AT, 'merged: ' + 'f' * 40)])
    step = make(slice_data, 'factory/contract', created='2026-10-02T00:00:00+00:00',
                state='ready', contract_step=dict(STEP))
    return tmp_path, expand, step


def data(world, *extra, jobs=None, cache=None):
    path, expand, step = world
    return dict(version=1, slices=[expand, step, *extra], _eligibility=dict(
        jobs=jobs or {}, now=NOW, state_path=path / 'slices.json', usage_cache=cache))


def test_pass(world, endpoint):
    endpoint.value = usage(('base', '2026-11-10', 4), ('new', '2026-11-20', 9))
    result = contract_drain.drain(world[2], data(world))
    assert result == dict(passed=True, expand_merged_at=MERGED_AT, shape_last_seen='2026-11-10',
                          open_work=[], reason='drained')


@pytest.mark.parametrize('day, passed', [('2026-11-15', False), ('2026-11-14', True)])
def test_count_inside_and_just_outside_window(world, endpoint, day, passed):
    endpoint.value = usage(('base', day, 1), ('base', '2026-11-20', 0))
    result = contract_drain.drain(world[2], data(world))
    assert result['passed'] is passed and result['shape_last_seen'] == day
    if not passed:
        assert result['reason'] == 'old shape used within the last 7 days'


def test_quiet_days_and_counter_coverage(world, endpoint):
    world[2]['contract_step']['quiet_days'] = 1
    endpoint.value = usage(('base', '2026-11-20', 2), since='2026-11-21')
    assert contract_drain.drain(world[2], data(world))['passed']
    world[2]['contract_step']['quiet_days'] = 3
    endpoint.value = usage(since='2026-11-20')
    assert contract_drain.drain(world[2], data(world))['reason'] == 'usage counter covers fewer than 3 days'


def test_expand_not_merged(world, endpoint):
    world[1]['log'] = [log('2026-10-01T00:00:00+00:00'), log(MERGED_AT, 'merged: ')]
    result = contract_drain.drain(world[2], data(world))
    assert result['passed'] is False and result['expand_merged_at'] is None
    assert result['reason'] == 'expand slice has not merged'
    assert endpoint.calls == 0


def test_old_open_work_in_user_repository_not_in_unrelated(world, endpoint, slice_data):
    old_user = make(slice_data, 'factory/old', created='2026-10-20T00:00:00+00:00')
    old_provider = make(slice_data, 'homelab-v2/old', repo=PROVIDER.lower(),
                        created='2026-10-20T00:00:00+00:00', state='issued')
    unrelated = make(slice_data, 'other/old', repo='TelesforoAleix/other',
                     created='2026-10-20T00:00:00+00:00')
    closed = make(slice_data, 'factory/done', created='2026-10-20T00:00:00+00:00', state='accepted')
    dropped = make(slice_data, 'factory/gone', created='2026-10-20T00:00:00+00:00', state='dropped')
    new = make(slice_data, 'factory/new', created='2026-11-02T00:00:00+00:00')
    result = contract_drain.drain(world[2], data(world, old_user, old_provider, unrelated, closed, dropped, new))
    assert result['passed'] is False
    assert result['open_work'] == ['factory/old', 'homelab-v2/old']
    assert result['reason'] == 'work created before the expand change is still open'
    assert contract_drain.drain(world[2], data(world, unrelated, closed, dropped, new))['passed']


def test_old_running_job(world, endpoint):
    merged_ns = int(datetime.fromisoformat(MERGED_AT).timestamp() * 1e9)
    old = dict(id='other/job', phase='running', started_ns=merged_ns - 1, requests={})
    waiting = dict(id='other/wait', phase='pr', started_ns=merged_ns - 1,
                   requests={'r': dict(record=dict(status='waiting'))})
    finished = dict(id='other/finished', phase='merged', started_ns=merged_ns - 1,
                    requests={'r': dict(record=dict(status='done'))})
    later = dict(id='other/later', phase='running', started_ns=merged_ns + 1, requests={})
    jobs = {job['id']: job for job in (old, waiting, finished, later)}
    result = contract_drain.drain(world[2], data(world, jobs=jobs))
    assert result['open_work'] == ['other/job', 'other/wait'] and not result['passed']
    assert contract_drain.drain(world[2], data(world, jobs={'other/later': later}))['passed']


@pytest.mark.parametrize('error, value, reason', [
    ('Platform run response unavailable', None, 'usage endpoint unavailable'),
    ('Platform run settings unavailable', None, 'run platform not configured'),
    ('Platform run HTTP 404', None, 'usage endpoint not served (HTTP 404)'),
    ('Platform run HTTP 503', None, 'usage endpoint answered HTTP 503'),
    (None, usage(contract='other'), 'usage answer is for another contract or unreadable'),
    (None, dict(usage(), shapes=[dict(shape='base', day='yesterday', count=1)]), 'usage answer unreadable'),
    (None, ['not', 'an', 'object'], 'usage answer unreadable'),
])
def test_endpoint_errors_fail_closed(world, endpoint, error, value, reason):
    endpoint.error, endpoint.value = error, value
    result = contract_drain.drain(world[2], data(world))
    assert result['passed'] is False and result['reason'] == reason


@pytest.mark.parametrize('catalog, reason', [
    (None, 'contract catalog unreadable'), ('{', 'contract catalog unreadable'),
    ('[]', 'contract not in the catalog')])
def test_unreadable_catalog_fails_closed(world, endpoint, catalog, reason):
    file = world[0] / 'contracts-catalog.json'
    file.unlink() if catalog is None else file.write_text(catalog)
    assert contract_drain.drain(world[2], data(world))['reason'] == reason


def test_eligibility_blocks_then_unblocks_with_one_read_per_pass(world, endpoint, slice_data):
    endpoint.value = usage(('base', '2026-11-20', 1))
    cache = {}
    snapshot = data(world, cache=cache)
    blocked = dict(status='blocked', reason='drain', detail='old shape used within the last 7 days')
    assert eligibility(world[2], snapshot) == blocked
    assert eligibility(world[2], snapshot) == blocked
    assert endpoint.calls == 1
    endpoint.value = usage(('base', '2026-11-01', 1))
    assert eligibility(world[2], data(world, cache={})) == dict(status='ready')
    assert endpoint.calls == 2
    plain = make(slice_data, 'factory/plain', state='ready')
    assert eligibility(plain, data(world, cache={})) == dict(status='ready')
    assert endpoint.calls == 2


def test_cli_add_edit_and_drain(world, endpoint, capsys, monkeypatch):
    path = world[0] / 'slices.json'
    path.write_text(json.dumps(dict(version=1, slices=[world[1]])))
    monkeypatch.setattr(contract_drain, 'datetime', type('Clock', (datetime,), {
        'now': classmethod(lambda cls, tz=None: NOW)}))
    args = ['--state', str(path), '--actor', 'planner']
    assert main([*args, 'add', '--id', 'factory/step', '--repo', USER, '--feature', 'Contracts',
                 '--title', 'Remove base', '--no-feature', 'Contract step',
                 '--contract-step', 'contract=run-api,shape=base,expand=factory/expand']) == 0
    assert state.load(path)['slices'][1]['contract_step'] == STEP
    assert main([*args, 'edit', 'factory/step', '--contract-step',
                 'contract=run-api,shape=base,expand=factory/expand,quiet_days=3']) == 0
    assert state.load(path)['slices'][1]['contract_step'] == dict(STEP, quiet_days=3)
    capsys.readouterr()
    endpoint.value = usage(('base', '2026-11-17', 2))
    assert main([*args, 'contracts', 'drain', 'factory/step']) == 0
    assert json.loads(capsys.readouterr().out) == dict(
        passed=True, expand_merged_at=MERGED_AT, shape_last_seen='2026-11-17', open_work=[], reason='drained')
    endpoint.error = 'Platform run HTTP 404'
    assert main([*args, 'contracts', 'drain', 'factory/step']) == 0
    assert json.loads(capsys.readouterr().out)['passed'] is False
    assert main([*args, 'contracts', 'drain', 'factory/expand']) == 1
    before = path.read_bytes()
    for bad in ('contract=run-api,shape=base', 'contract=run-api,shape=base,expand=x,quiet_days=0',
                'contract=run-api,shape=base,expand=x,colour=red'):
        with pytest.raises(SystemExit):
            main([*args, 'edit', 'factory/step', '--contract-step', bad])
    assert path.read_bytes() == before


def test_schema_refuses_other_step_keys(world):
    step = world[2]
    for value in (dict(STEP, extra='x'), dict(STEP, quiet_days=0), {'contract': 'run-api'}):
        with pytest.raises(Exception):
            state.validate(dict(version=1, slices=[dict(step, contract_step=value)]))
    state.validate(dict(version=1, slices=[dict(step, contract_step=dict(STEP, quiet_days=2))]))


class FakeRunner:
    def __init__(self, path):
        self.path, self.usage_cache = path, {}


def test_unknown_field_notices_once_each_none_on_first_run(world, endpoint, capsys):
    path = world[0] / 'slices.json'
    path.write_text(json.dumps(dict(version=1, slices=[])))
    endpoint.value = usage(unknown=[('factory', 'POST /v1/runs', 'old_field')])
    contract_drain.findings(FakeRunner(path))
    assert state.load(path)['slices'] == []
    endpoint.value = usage(unknown=[('factory', 'POST /v1/runs', 'old_field'),
                                    ('factory', 'POST /v1/runs', 'extra'),
                                    ('factory', 'POST /v1/runs', 'extra')])
    for _ in range(3):
        contract_drain.findings(FakeRunner(path))
    slices = state.load(path)['slices']
    assert len(slices) == 1
    item = slices[0]
    assert item['repo'] == PROVIDER and item['id'].startswith('homelab-v2/contract-run-api-field-')
    attention = item['attention']
    assert attention['kind'] == 'contract-change' and attention['for'] == 'planner'
    for name in ('run-api', 'factory', 'POST /v1/runs', 'extra'):
        assert name in attention['body']
    assert '3' not in attention['body'] and '2026' not in attention['body']
    notices = [n for _, n in state.store(path).notices()]
    assert len(notices) == 1 and notices[0]['event'] == 'contract-change'
    assert capsys.readouterr().err == ''


def test_unknown_field_errors_log_one_line(world, endpoint, capsys):
    path = world[0] / 'slices.json'
    path.write_text(json.dumps(dict(version=1, slices=[])))
    endpoint.error = 'Platform run settings unavailable'
    contract_drain.findings(FakeRunner(path))
    assert capsys.readouterr().err == ''
    endpoint.error = 'Platform run HTTP 503'
    contract_drain.findings(FakeRunner(path))
    assert capsys.readouterr().err.count('\n') == 1
    endpoint.error = None
    endpoint.value = dict(usage(), unknown_fields='broken')
    contract_drain.findings(FakeRunner(path))
    assert capsys.readouterr().err.count('\n') == 1
    assert state.load(path)['slices'] == []


def test_runner_reads_usage_once_and_findings_survive_update_failure(world, endpoint, monkeypatch):
    from cplane import contract_updates, runner as runner_module

    calls = []
    monkeypatch.setattr(runner_module.Runner, '_run_pass', lambda self: setattr(self, 'usage_cache', {}))
    monkeypatch.setattr(contract_updates, 'run', lambda r: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(runner_module, 'export_bot', lambda path: calls.append('export'))
    monkeypatch.setattr(contract_drain, 'findings', lambda r: calls.append('findings'))
    runner = runner_module.Runner.__new__(runner_module.Runner)
    runner.path = world[0] / 'slices.json'
    runner.run()
    assert calls == ['findings', 'export']
