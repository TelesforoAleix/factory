import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import plistlib
import subprocess
from unittest.mock import Mock

import pytest

from cplane import state
from cplane.cli import main
from cplane.executors import FENCE_PARAGRAPH, Processes, command
from cplane.runner import Runner, Git, GitHub
from cplane.text_bounds import ATTENTION_LIMIT, TAIL_LIMIT, cut as cut_text

NOW = datetime(2026, 10, 16, 10, tzinfo=timezone.utc)


def assert_prompt(job, text):
    assert job['prompt'] == (text + f"\n\nRunner assignment: use branch {job['branch']}. "
                             "This assigned branch overrides any branch named in the brief. "
                             f"The pinned base commit is {job['base']}." + FENCE_PARAGRAPH)


class FakeProcesses:
    def __init__(self):
        self.started = []
        self.results = {}

    def start(self, job):
        self.started.append(copy.deepcopy(job))
        return len(self.started)

    def poll(self, job):
        return self.results.get(job['run'], (False, 'session-1', None, ''))

    def finish(self, kind='handover', body='done', session='session-1'):
        job = self.started[-1]
        self.results[job['run']] = (True, session, {'kind': kind, 'body': body} if kind else None, 'line\n' * 40)


class FakeGitHub:
    def __init__(self):
        self.repository = Mock(return_value='example/repo')
        self.open = Mock(return_value=12)
        self.find_pr = Mock(return_value=None)
        self.is_open = Mock(return_value=True)
        self.checks = Mock(return_value=('pending', ''))
        self.merge = Mock(return_value='abc123')
        self.merge_info = Mock(return_value={})
        self.update_branch = Mock(return_value='c' * 40)


@pytest.fixture
def setup(tmp_path, slice_data, make_state, monkeypatch):
    slice_data['slot'] = (NOW - timedelta(minutes=1)).isoformat()
    path = make_state()
    (tmp_path / 'briefs').mkdir()
    (tmp_path / 'briefs/W1.md').write_text('The exact prompt.\n')
    (tmp_path / 'repos/repo').mkdir(parents=True)
    (tmp_path / 'repos/repo/.git').mkdir()
    processes, github = FakeProcesses(), FakeGitHub()
    runner = Runner(path, processes=processes, github=github, git=Mock(), clock=lambda: NOW,
                    codex_reader=lambda: 10, claude_reader=lambda: None,
                    runs=tmp_path / 'runs', repos=tmp_path / 'repos')
    from cplane import fence
    trusted = fence.trusted_directory
    monkeypatch.setattr(fence, 'trusted_directory', lambda path: None if Path(path) == runner.runs else trusted(path))
    monkeypatch.setattr('cplane.classes.changes', lambda *args: (1, []))
    def prepare(repository, branch, token):
        return {'repo': str(tmp_path / 'repos' / repository.split('/')[-1]),
                'branch': branch, 'base': 'a' * 40, 'repository': repository}
    runner.fence = Mock()
    runner.fence.prepare.side_effect = prepare
    runner.fence.resume.side_effect = lambda previous, session: {
        key: previous[key] for key in ('repo', 'branch', 'base', 'repository')}
    runner.fence.publish.return_value = 'b' * 40
    return runner, processes, github


def item(runner):
    return state.load(runner.path)['slices'][0]


def edit(runner, change):
    data = state.load(runner.path)
    change(data['slices'][0])
    state.save(runner.path, data)


def test_pass_order_prompt_session_and_notices(setup):
    r, p, _ = setup
    r.run()
    assert_prompt(p.started[0], 'The exact prompt.\n')
    assert p.started[0]['tool'] == 'codex'
    assert r.git.commit.call_count == 1
    assert item(r)['state'] == 'issued'
    r.run()
    assert item(r)['session'] == {'tool': 'codex', 'id': 'session-1', 'folder': str(r.repos / 'repo')}
    p.finish()
    r.run()
    assert item(r)['state'] == 'in review'
    assert [n['event'] for n in map(json.loads, Path(str(r.path) + '.outbox.jsonl').read_text().splitlines())] == ['started', 'finished']
    assert all(e['actor'] == 'runner' for e in item(r)['log'])
    assert r.git.mock_calls[0][0] == 'pull'
    assert 'commit' in [call[0] for call in r.git.mock_calls]
    r.git.tidy.assert_not_called()
    assert r.git.commit.call_count == 3
    assert len(p.started) == 1
    r.github.find_pr.assert_not_called()
    r.run()
    assert item(r)['state'] == 'in review'






@pytest.mark.parametrize('field,value', [('state', 'planned'), ('paused', True), ('slot', None),
    ('slot', (NOW + timedelta(seconds=1)).isoformat()), ('depends_on', ['missing/W1'])])
def test_not_due(setup, field, value):
    r, p, _ = setup
    edit(r, lambda s: s.update({field: value}))
    before = r.path.read_bytes()
    r.run()
    assert not p.started
    assert r.path.read_bytes() == before
    r.git.commit.assert_not_called()


def test_dependency_accepted(setup):
    r, p, _ = setup
    data = state.load(r.path)
    dep = copy.deepcopy(data['slices'][0])
    dep.update(id='example/W0', state='accepted')
    data['slices'][0]['depends_on'] = [dep['id']]
    data['slices'].append(dep)
    state.save(r.path, data)
    r.run()
    assert len(p.started) == 1


@pytest.mark.parametrize('used', [0, 98.9, None, 99, 99.9, 100])
def test_codex_capacity_never_falls_back_to_claude(setup, used):
    r, p, _ = setup
    r.codex_reader = lambda: used
    r.claude_reader = lambda: {'at': NOW.timestamp(), 'rate_limits': {'five_hour': {'used_percentage': 1}}}
    r.run()
    if isinstance(used, (int, float)) and 0 <= used < 99:
        assert len(p.started) == 1
        assert p.started[0]['tool'] == 'codex'
        assert p.started[0]['model'] == 'example-model'
    else:
        assert not p.started
        assert item(r)['state'] == 'ready'


def test_explicit_claude_slice_starts_on_claude(setup):
    r, p, _ = setup
    edit(r, lambda s: s['executor'].update(tool='claude', model='sonnet'))
    r.claude_reader = lambda: {'at': NOW.timestamp(), 'rate_limits': {'five_hour': {'used_percentage': 1}}}
    r.run()
    assert p.started[0]['tool'] == 'claude'
    assert p.started[0]['model'] == 'sonnet'
    assert_prompt(p.started[0], 'The exact prompt.\n')


def test_missing_capacity_defers(setup):
    r, p, _ = setup
    r.codex_reader = lambda: None
    r.run()
    assert not p.started


def test_capacity_unavailable_deferral_is_logged_once(setup):
    r, _, _ = setup
    r.codex_reader = lambda: None
    r.claude_reader = lambda: None
    r.at = NOW.isoformat()
    candidate = item(r)
    r.data = state.load(r.path)
    candidate = r.data['slices'][0]
    r.jobs = {}
    r.instant = NOW
    r.launch(candidate, 'prompt')
    r.launch(candidate, 'prompt')
    assert [entry['event'] for entry in candidate['log']] == ['deferred: capacity unavailable']


@pytest.mark.parametrize('repos,count', [(['repo', 'repo', 'third'], 2), (['repo', 'second', 'third'], 2)])
def test_running_limits(setup, repos, count):
    r, p, _ = setup
    data = state.load(r.path)
    base = data['slices'][0]
    data['slices'] = []
    for i, repo in enumerate(repos):
        (r.repos / repo).mkdir(exist_ok=True)
        s = copy.deepcopy(base)
        s.update(id=f'example/W{i}', repo='example/' + repo)
        data['slices'].append(s)
    state.save(r.path, data)
    r.run()
    assert len(p.started) == count
    assert len({j['repo'] for j in p.started}) == count
    r.run()
    assert len(p.started) == count
    p.results[p.started[0]['run']] = (True, 'session-1', {'kind': 'handover', 'body': 'done'}, '')
    r.run()
    assert len(p.started) == 3


def test_paused_issued_slice_still_blocks_repository(setup):
    r, p, _ = setup
    data = state.load(r.path)
    parked = copy.deepcopy(data['slices'][0])
    parked.update(id='example/parked', state='issued', paused=True)
    data['slices'].append(parked)
    state.save(r.path, data)

    r.run()

    assert not p.started
    assert item(r)['state'] == 'ready'


def test_paused_running_job_still_makes_repository_busy(setup):
    r, _, _ = setup
    r.data = state.load(r.path)
    parked = copy.deepcopy(r.data['slices'][0])
    parked.update(id='example/parked', state='issued', paused=True)
    r.data['slices'].append(parked)
    r.jobs = {
        parked['id']: {
            'id': parked['id'], 'repo': str(r.repos / 'repo'), 'repository': 'example/repo', 'phase': 'running'
        }
    }

    assert r.room(r.data['slices'][0]) == 'deferred: repository busy (example/parked)'


def test_deferrals_name_blocker_and_log_identical_reason_once(setup):
    r, _, _ = setup
    r.data = state.load(r.path)
    candidate = r.data['slices'][0]
    r.at = NOW.isoformat()
    r.jobs = {
        f'example/W{i}': {
            'id': f'example/W{i}', 'repo': str(r.repos / f'repo{i}'), 'repository': f'example/repo{i}', 'phase': 'running'
        }
        for i in range(2)
    }

    assert r.room(candidate) == 'deferred: executor limit (running: example/W0, example/W1)'
    r.launch(candidate, 'prompt')
    r.launch(candidate, 'prompt')
    assert [entry['event'] for entry in candidate['log']] == [
        'deferred: executor limit (running: example/W0, example/W1)'
    ]

    r.jobs = {
        'example/W0': {
            'id': 'example/W0', 'repo': str(r.repos / 'repo'), 'repository': 'example/repo', 'phase': 'running'
        }
    }
    assert r.room(candidate) == 'deferred: repository busy (example/W0)'
    r.launch(candidate, 'prompt')
    assert candidate['log'][-1]['event'] == 'deferred: repository busy (example/W0)'


@pytest.mark.parametrize('kind,expected_state,attention', [
    ('handover', 'in review', None), ('question', 'issued', 'question'),
    ('escalation', 'escalated', 'escalation'), ('waiting', 'issued', 'node-step'),
    (None, 'escalated', 'escalation'),
])
def test_collect(setup, kind, expected_state, attention):
    r, p, _ = setup
    r.run()
    p.finish(kind, 'body')
    r.run()
    assert item(r)['state'] == expected_state
    assert item(r).get('final') == (dict(kind=kind, body='body', at=NOW.isoformat()) if kind else None)
    a = item(r)['attention']
    assert (a['kind'] if a else None) == attention
    if kind is None:
        assert a['body'].startswith('the run ended without a final message')
        assert a['body'].count('line') == 40
    elif a:
        assert a['body'] == 'body'


def test_collected_final_replaces_previous_and_bounds_body(setup):
    r, p, _ = setup
    edit(r, lambda s: s.update(final={'kind': 'waiting', 'body': 'old', 'at': NOW.isoformat()}))
    r.run()
    body = 'x' * (ATTENTION_LIMIT + 100)
    p.finish('question', body)
    r.run()
    assert item(r)['final'] == {'kind': 'question', 'body': cut_text(body, ATTENTION_LIMIT), 'at': NOW.isoformat()}
    assert len(item(r)['final']['body']) <= ATTENTION_LIMIT


@pytest.mark.parametrize('kind', ['question', 'escalation'])
def test_answer_resumes_and_capacity_defers(setup, kind):
    r, p, _ = setup
    r.run()
    p.finish(kind)
    r.run()
    edit(r, lambda s: s['attention'].update(answer='exact answer'))
    r.codex_reader = lambda: 100
    r.run()
    assert len(p.started) == 1
    assert item(r)['attention']['answer'] == 'exact answer'
    r.codex_reader = lambda: 1
    r.run()
    assert len(p.started) == 2
    assert_prompt(p.started[-1], 'exact answer')
    assert p.started[-1]['resume'] == 'session-1'
    assert item(r)['attention'] is None
    p.finish()
    r.run()
    assert item(r)['state'] == 'in review'


def claude_start(r):
    r.codex_reader = lambda: 100
    edit(r, lambda s: s['executor'].update(tool='claude', model='sonnet'))
    r.claude_reader = lambda: {'at': NOW.timestamp(), 'rate_limits': {'five_hour': {'used_percentage': 1}}}
    r.run()


def pr_reply(node_steps=None):
    return '```json\n' + json.dumps({'branch': 'feat/example', 'title': 'Example', 'body': 'Change README', 'node_steps': node_steps}) + '\n```\nDetails'


def test_claude_pr_red(setup):
    r, p, gh = setup
    claude_start(r)
    p.finish('waiting', pr_reply())
    r.run()
    assert item(r)['pr'] == 12
    gh.checks.return_value = 'red', 'test'
    r.run()
    assert item(r)['attention']['kind'] == 'escalation'
    assert 'test' in item(r)['attention']['body']
    gh.merge.assert_not_called()


def test_claude_auto_merge_resume_handover(setup):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=False))
    claude_start(r)
    p.finish('waiting', pr_reply())
    r.run()
    gh.checks.return_value = 'green', ''
    r.run()
    gh.merge.assert_called_once_with('example/repo', 12, expected='b' * 40)
    assert_prompt(p.started[-1], 'merged as abc123')
    assert p.started[-1]['resume'] == 'session-1'
    assert p.started[-1]['tool'] == 'claude'
    p.finish()
    r.run()
    assert item(r)['state'] == 'in review'


@pytest.mark.parametrize('body', ['', ' \n', pr_reply(None), pr_reply('')])
def test_post_merge_waiting_without_node_steps_finishes(setup, body):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=False))
    claude_start(r)
    p.finish('waiting', pr_reply())
    r.run()
    gh.checks.return_value = 'green', ''
    r.run()
    assert p.started[-1]['sha'] == 'abc123'
    p.finish('waiting', body)
    r.run()
    assert item(r)['state'] == 'in review'
    assert item(r)['attention'] is None
    assert any(e['event'] == 'finished' for e in item(r)['log'])
    assert r.jobs['voice/W1']['phase'] == 'collected'
    r.run()
    assert len(p.started) == 2
    gh.open.assert_called_once()
    gh.merge.assert_called_once()


def test_post_merge_node_step_replays_after_state_save_failure(setup, monkeypatch):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=False))
    claude_start(r)
    p.finish('waiting', pr_reply(None))
    r.run()
    gh.merge.return_value = 'a' * 40
    gh.checks.return_value = 'green', ''
    r.run()
    p.finish('waiting', pr_reply('Install the merged commit'))
    with monkeypatch.context() as patch:
        patch.setattr(state, 'save', Mock(side_effect=OSError('synthetic disk failure')))
        with pytest.raises(OSError, match='synthetic disk failure'):
            r.run()
    assert r.jobs['voice/W1']['phase'] == 'node-step'
    assert item(r)['attention'] is None
    r.run()
    assert item(r)['attention']['kind'] == 'node-step'
    assert item(r)['attention']['body'] == 'Install the merged commit'
    assert r.jobs['voice/W1']['sha'] == 'a' * 40
    r.run()
    assert len(p.started) == 2
    gh.open.assert_called_once()
    gh.merge.assert_called_once()


@pytest.mark.parametrize('title', ['[Blocked] needs input', '[bLoCkEd] needs input',
                                  'Blocked: needs input', 'BLOCKED: needs input',
                                  'Draft: input', '[Draft] input', 'x DO NOT MERGE',
                                  'x merge blocker'])
@pytest.mark.parametrize('approved', [False, True])
def test_blocked_live_pr_title_is_not_merged(setup, title, approved):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=approved))
    claude_start(r)
    p.finish('waiting', pr_reply())  # The live title can differ from the request.
    r.run()
    real_github = GitHub()
    real_github.call = Mock(return_value=json.dumps(
        {'state': 'OPEN', 'title': title, 'mergeCommit': None, 'headRefOid': 'b' * 40}))
    gh.merge.side_effect = real_github.merge
    gh.merge_info.side_effect = real_github.merge_info
    gh.checks.return_value = 'green', ''
    r.run()
    assert item(r)['attention']['kind'] == 'escalation'
    assert item(r)['attention']['body'] == 'PR marked not for merging'
    assert r.jobs['voice/W1']['phase'] == 'pr'
    assert 'sha' not in r.jobs['voice/W1']
    real_github.call.assert_called_once_with('example/repo', 'pr', 'view', '12',
                                             '--json', 'state,mergeCommit,title,body,isDraft,headRefOid,mergeStateStatus,mergeable')
    assert len(p.started) == 1


@pytest.mark.parametrize('node_steps', [None, 'Run migration on owner node'])
def test_claude_approval_and_node_steps(setup, node_steps):
    r, p, gh = setup
    claude_start(r)
    p.finish('waiting', pr_reply(node_steps))
    r.run()
    gh.checks.return_value = 'green', ''
    r.run()
    assert item(r)['attention']['kind'] == 'merge'
    gh.merge.assert_not_called()
    edit(r, lambda s: s['attention'].update(approved=True))
    r.run()
    gh.merge.assert_called_once()
    if node_steps:
        assert len(p.started) == 1
        assert item(r)['attention']['kind'] == 'node-step'
        assert item(r)['attention']['body'] == node_steps
    else:
        assert len(p.started) == 2
        assert item(r)['attention'] is None


def test_claude_resume_waits_for_capacity_after_merge(setup):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=False))
    claude_start(r)
    p.finish('waiting', pr_reply())
    r.run()
    gh.checks.return_value = 'green', ''
    r.claude_reader = lambda: None
    r.run()
    gh.merge.assert_called_once()
    assert len(p.started) == 1
    r.claude_reader = lambda: {'at': NOW.timestamp(), 'rate_limits': {'five_hour': {'used_percentage': 1}}}
    r.run()
    assert len(p.started) == 2


@pytest.mark.parametrize('body', [ '```json\n{}\n```', '```json\nnot json\n```'])
def test_claude_invalid_pr(setup, body):
    r, p, gh = setup
    claude_start(r)
    p.finish('waiting', body)
    r.run()
    assert item(r)['attention']['kind'] == 'escalation'
    gh.open.assert_not_called()


def test_codex_merge_approval(setup):
    r, p, gh = setup
    r.run()
    p.finish('question')
    r.run()
    edit(r, lambda s: s['attention'].update(kind='merge', approved=True))
    r.run()
    assert len(p.started) == 1
    assert item(r)['attention']['kind'] == 'merge'
    gh.merge.assert_not_called()


def test_resume_obeys_repository_limit(setup):
    r, p, _ = setup
    edit(r, lambda s: s.update(allowed_files=['first/**']))
    r.run()
    p.finish('question')
    r.run()
    data = state.load(r.path)
    second = copy.deepcopy(data['slices'][0])
    second.update(id='example/W2', state='ready', session=None, attention=None, allowed_files=['second/**'])
    data['slices'].append(second)
    state.save(r.path, data)
    r.run()
    edit(r, lambda s: s['attention'].update(answer='answer'))
    r.run()
    assert len(p.started) == 2
    assert item(r)['attention']['answer'] == 'answer'


def test_launch_failure_collected(setup):
    r, p, _ = setup
    p.start = Mock(side_effect=OSError('missing executable'))
    r.run()
    job = r.jobs[item(r)['id']]
    p.results[job['run']] = True, '', None, 'missing executable'
    r.run()
    assert item(r)['state'] == 'escalated'


def test_pull_failure_never_launches(setup):
    r, p, _ = setup
    r.git.pull.side_effect = state.StateError('pull failed')
    with pytest.raises(state.StateError, match='pull failed'):
        r.run()
    assert not p.started


def test_runner_cli_uses_default_commit(make_state, monkeypatch):
    path = make_state()
    fake = Mock()
    monkeypatch.setattr('cplane.runner.Runner', fake)
    assert main(['run', '--state', str(path)]) == 0
    fake.assert_called_once_with(path)
    fake.return_value.run.assert_called_once()


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('resume', [None, 'session'])
def test_executor_arguments(tool, resume, tmp_path):
    job = {'tool': tool, 'run': str(tmp_path), 'repo': '/tmp/repo', 'model': 'model', 'prompt': '-literal prompt', 'resume': resume}
    args = command(job)
    assert args[-2:] == ['--', job['prompt']]
    if resume:
        assert 'session' in args
    assert args[:3] == ['factory-cli', 'run', '--tool']
    assert args[args.index('--repo') + 1] == '/tmp/repo'
    if tool == 'codex':
        assert '/run/factory/schema.json' in args
        assert '/run/factory/last.json' in args
    else:
        assert '--json-schema' in args





@pytest.mark.parametrize('model,effort', [('gpt-6-luna', 'medium'), ('gpt-6.1-terra', 'medium')])
def test_codex_effort_defaults_and_explicit_levels(tmp_path, model, effort):
    job = {'tool': 'codex', 'run': str(tmp_path), 'repo': '/tmp/repo', 'model': model, 'prompt': 'brief'}
    args = command(job)
    assert args[args.index('model_reasoning_effort="' + effort + '"') - 1] == '-c'
    job['effort'] = 'xhigh'
    assert 'model_reasoning_effort="xhigh"' in command(job)


def test_runner_effort_applies_to_resume_and_old_state(setup):
    r, p, _ = setup
    edit(r, lambda s: s['executor'].pop('effort', None))
    r.run()
    assert p.started[-1]['effort'] == 'medium'
    assert 'model_reasoning_effort="medium"' in command(p.started[-1])
    p.finish('question')
    r.run()
    edit(r, lambda s: s['attention'].update(answer='continue'))
    edit(r, lambda s: s['executor'].update(effort='xhigh'))
    r.run()
    assert p.started[-1]['resume'] == 'session-1'
    assert p.started[-1]['effort'] == 'xhigh'
    assert 'model_reasoning_effort="xhigh"' in command(p.started[-1])


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('fresh', [True, False])
def test_process_final_freshness(tmp_path, tool, fresh):
    import os
    start = 1_700_000_000_000_000_000
    job = {'tool': tool, 'run': str(tmp_path), 'started_ns': start, 'session': ''}
    final = {'kind': 'handover', 'body': 'done'}
    if tool == 'codex':
        (tmp_path / 'io').mkdir()
        last = tmp_path / 'io/last.json'
        last.write_text(json.dumps(final))
        (tmp_path / 'turn.jsonl').write_text('{"type":"thread.started","thread_id":"session"}\n')
    else:
        last = tmp_path / 'claude.json'
        last.write_text(json.dumps({'structured_output': final, 'session_id': 'session'}))
    os.utime(last, ns=(start + (1 if fresh else -1),) * 2)
    (tmp_path / 'exit.json').write_text('{}')
    done, session, result, _ = Processes().poll(job)
    assert done
    assert result == (final if fresh else None)
    if fresh:
        assert session == 'session'


def test_process_records_codex_session_before_exit(tmp_path):
    job = {'tool': 'codex', 'run': str(tmp_path), 'started_ns': 0, 'session': ''}
    (tmp_path / 'turn.jsonl').write_text('{"type":"thread.started","thread_id":"early-session"}\n')
    done, session, final, _ = Processes().poll(job)
    assert not done and final is None
    assert session == 'early-session'


def test_codex_pr_lookup_uses_newest_matching_pr():
    gh = GitHub()
    gh.call = Mock(return_value=json.dumps([
        {'number': 10, 'createdAt': '2026-10-01T00:00:00Z'},
        {'number': 11, 'createdAt': '2026-10-10T00:00:00Z'},
    ]))
    assert gh.find_pr('owner/repo', 'feature') == 11
    gh.call.assert_called_once_with('owner/repo', 'pr', 'list', '--head', 'feature', '--state', 'all',
                                    '--json', 'number,createdAt')






def test_gh_arguments_include_full_repository_for_pr_calls(monkeypatch):
    calls = []
    responses = iter([
        '[{"number":12}]',  # lookup
        '[]',  # open lookup
        'https://github.com/owner/repo/pull/12',  # create
        '{"statusCheckRollup":[]}',  # checks
        '{"state":"OPEN","title":"Example","mergeCommit":null}',  # merge view
        '',  # merge
        '{"state":"MERGED","mergeCommit":{"oid":"abc"}}',  # merge confirmation
    ])
    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, next(responses), '')
    monkeypatch.setattr('cplane.runner.subprocess.run', fake_run)
    monkeypatch.setattr('cplane.fence.github_environment', lambda repositories=None: {})
    gh = GitHub()
    request = {'branch': 'feat/x', 'title': 'Title', 'body': 'Body'}
    assert gh.find_pr('owner/repo', 'feat/x') == 12
    assert gh.open('owner/repo', request) == 12
    assert gh.checks('owner/repo', 12) == ('green', '')
    assert gh.merge('owner/repo', 12) == 'abc'
    assert len(calls) == 7
    assert all(call[-2:] == ['-R', 'owner/repo'] for call in calls)
    assert calls[0][1:4] == ['pr', 'list', '--head']
    assert calls[1][1:4] == ['pr', 'list', '--head']
    assert calls[2][1:3] == ['pr', 'create']
    assert calls[3][1:3] == ['pr', 'view']
    assert calls[4][1:3] == ['pr', 'view']
    assert calls[5][1:3] == ['pr', 'merge']
    assert calls[6][1:3] == ['pr', 'view']


def test_slice_collection_failure_does_not_stop_healthy_slice_start(setup):
    r, p, _ = setup
    data = state.load(r.path)
    base = data['slices'][0]
    broken = copy.deepcopy(base)
    broken.update(id='example/broken', state='issued', repo='example/repo', session={'tool': 'codex', 'id': 's', 'folder': str(r.repos / 'repo')})
    healthy = copy.deepcopy(base)
    healthy.update(id='example/healthy', repo='example/healthy')
    (r.repos / 'healthy').mkdir()
    data['slices'] = [broken, healthy]
    state.save(r.path, data)
    run = r.runs / 'broken'
    run.mkdir(parents=True)
    job = {'id': broken['id'], 'repo': str(r.repos / 'repo'), 'run': str(run), 'tool': 'codex',
           'model': 'gpt-sol', 'started_ns': 1, 'session': 's', 'phase': 'running'}
    r.save_job(job)
    p.results[str(run)] = (True, 's', {'kind': 'handover', 'body': 'done'}, '')
    p.results[str(run)] = (True, 'bad session!', {'kind': 'handover', 'body': 'done'}, '')
    job['fence'] = True
    r.save_job(job)
    r.run()
    result = state.load(r.path)['slices']
    assert result[0]['attention']['kind'] == 'escalation'
    assert result[0]['attention']['body'].startswith('collect/deliver failed:')
    assert 'invalid session' in result[0]['attention']['body']
    assert [j['id'] for j in p.started] == ['example/healthy']
    r.git.commit.assert_called_once()


def test_missing_final_escalation_summarizes_tool_exit(setup, tmp_path):
    r, _, _ = setup
    r.at = NOW.isoformat()
    candidate = item(r)
    run = tmp_path / 'run'
    run.mkdir()
    r.apply_final(candidate, {'tool': 'codex', 'final': None,
                             'tail': 'codex exec exited 2: unexpected argument\nother output',
                             'run': str(run), 'phase': 'ended'})
    assert candidate['attention']['body'] == 'codex exec exited 2: unexpected argument\n\nother output'


def test_process_exit_summary_uses_first_stderr_line(tmp_path):
    (tmp_path / 'exit.json').write_text('{"code":2}')
    (tmp_path / 'stderr.log').write_text('unexpected argument --foo\nmore detail\n')
    (tmp_path / 'turn.jsonl').write_text('output\n')
    job = {'tool': 'codex', 'run': str(tmp_path), 'started_ns': 0, 'pid': 999999}
    done, _, _, tail = Processes().poll(job)
    assert done
    assert tail.startswith('codex exec exited 2: unexpected argument --foo\n')


def test_huge_process_tail_is_bounded_and_keeps_summary_and_output_end(tmp_path):
    (tmp_path / 'exit.json').write_text('{"code":2}')
    (tmp_path / 'stderr.log').write_text('usage limit reached\n')
    (tmp_path / 'turn.jsonl').write_text('FIRST OUTPUT LINE\n' + 'x' * 20_000 + '\nLAST OUTPUT LINE')
    job = {'tool': 'codex', 'run': str(tmp_path), 'started_ns': 0, 'pid': 999999}
    done, _, _, tail = Processes().poll(job)
    assert done
    assert len(tail) <= TAIL_LIMIT
    assert tail.startswith('codex exec exited 2: usage limit reached\n… [')
    assert 'full output in the run folder' in tail
    assert 'LAST OUTPUT LINE' in tail


def test_attention_log_is_one_bounded_line_and_body_is_bounded(setup):
    r, _, _ = setup
    r.at = NOW.isoformat()
    candidate = item(r)
    r.attention(candidate, 'escalation', 'first line\n' + 'x' * 20_000)
    assert len(candidate['attention']['body']) <= 8_000
    event = candidate['log'][-1]['event']
    assert len(event) <= 500
    assert '\n' not in event
    assert event.startswith('escalation: first line')


def test_show_run_folder_and_final(tmp_path, make_state, monkeypatch, capsys):
    path = make_state()
    runs = tmp_path / 'runs'
    monkeypatch.setenv('CPLANE_RUNS', str(runs))
    from cplane.cli import main as cli_main
    import hashlib
    folder = runs / hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:20] / 'run-1'
    folder.mkdir(parents=True)
    atomic = {'id': 'voice/W1', 'tool': 'codex', 'started_ns': 1,
              'final': {'kind': 'handover', 'body': 'Ready for review'}}
    (folder / 'job.json').write_text(json.dumps(atomic))
    assert cli_main(['--state', str(path), 'show', 'voice/W1']) == 0
    assert f'run: {folder}' in capsys.readouterr().out
    assert cli_main(['--state', str(path), 'show', 'voice/W1', '--final']) == 0
    assert capsys.readouterr().out == 'kind: handover\nbody: Ready for review\n'


@pytest.mark.parametrize('checks,expected', [
    ([{'name': 'test', 'conclusion': 'FAILURE'}], ('red', 'test')),
    ([{'context': 'external', 'state': 'ERROR'}], ('red', 'external')),
    ([{'name': 'test', 'conclusion': ''}], ('pending', '')),
    ([{'name': 'test', 'conclusion': 'SUCCESS'}], ('green', '')),
    ([], ('green', '')),
])
def test_github_check_states(checks, expected):
    gh = GitHub()
    gh.call = Mock(return_value=json.dumps({'statusCheckRollup': checks, 'mergeStateStatus': 'CLEAN'}))
    assert gh.checks('owner/repo', 1) == expected


def test_claude_plain_waiting_is_node_step(setup):
    r, p, gh = setup
    claude_start(r)
    p.finish('waiting', 'A long job is running; inspect its log after it ends.')
    r.run()
    assert item(r)['attention']['kind'] == 'node-step'
    gh.open.assert_not_called()


def test_checks_only_on_later_pass(setup):
    r, p, gh = setup
    claude_start(r)
    p.finish('waiting', pr_reply())
    r.run()
    gh.checks.assert_not_called()
    r.run()
    gh.checks.assert_called_once()


def test_approval_does_not_merge_newly_red_check(setup):
    r, p, gh = setup
    claude_start(r)
    p.finish('waiting', pr_reply())
    r.run()
    gh.checks.return_value = 'green', ''
    r.run()
    edit(r, lambda s: s['attention'].update(approved=True))
    gh.checks.return_value = 'red', 'test'
    r.run()
    gh.merge.assert_not_called()
    assert item(r)['attention']['kind'] == 'escalation'


def test_replays_collection_if_state_save_fails(setup, monkeypatch):
    r, p, _ = setup
    r.run()
    p.finish('question', 'Please answer')
    save = state.save
    monkeypatch.setattr(state, 'save', Mock(side_effect=OSError('disk unavailable')))
    with pytest.raises(OSError):
        r.run()
    monkeypatch.setattr(state, 'save', save)
    r.run()
    assert item(r)['attention']['body'] == 'Please answer'
    assert len(p.started) == 1


def test_missing_local_metadata_occupies_slot(setup):
    r, p, _ = setup
    data = state.load(r.path)
    lost = copy.deepcopy(data['slices'][0])
    lost.update(id='example/W0', state='issued', session={'tool': 'codex', 'id': 'lost', 'folder': '/tmp/repo'})
    data['slices'].append(lost)
    state.save(r.path, data)
    r.run()
    assert not p.started


def test_codex_usage_latest_nonnull_report(tmp_path, monkeypatch):
    from cplane.runner import codex_usage
    folder = tmp_path / '.codex/sessions'
    folder.mkdir(parents=True)
    (folder / 'new.jsonl').write_text('\n'.join([
        '{"payload":{"rate_limits":{"primary":{"used_percent":34}}}}',
        '{"payload":{"rate_limits":null}}', 'not json']))
    assert codex_usage(folder) == 34


def test_codex_usage_falls_back_to_older_session_with_report(tmp_path):
    from cplane.runner import codex_usage
    folder = tmp_path / 'sessions'
    folder.mkdir()
    older = folder / 'older.jsonl'
    newest = folder / 'newest.jsonl'
    older.write_text('{"payload":{"rate_limits":{"primary":{"used_percent":40}}}}')
    newest.write_text('{"payload":{"rate_limits":null}}')
    os.utime(older, (1, 1))
    os.utime(newest, (2, 2))
    assert codex_usage(folder) == 40


def test_codex_usage_prefers_newest_session_report(tmp_path):
    from cplane.runner import codex_usage
    folder = tmp_path / 'sessions'
    folder.mkdir()
    older = folder / 'older.jsonl'
    newest = folder / 'newest.jsonl'
    older.write_text('{"payload":{"rate_limits":{"primary":{"used_percent":40}}}}')
    newest.write_text('{"payload":{"rate_limits":{"primary":{"used_percent":17}}}}')
    os.utime(older, (1, 1))
    os.utime(newest, (2, 2))
    assert codex_usage(folder) == 17


def test_codex_usage_expired_window_is_free(tmp_path, monkeypatch):
    from cplane.runner import codex_usage
    folder = tmp_path / 'sessions'
    folder.mkdir()
    (folder / 'session.jsonl').write_text(json.dumps({'payload': {'rate_limits': {
        'primary': {'used_percent': 100, 'resets_at': NOW.timestamp() - 1}}}}))
    monkeypatch.setattr('cplane.runner.time.time', lambda: NOW.timestamp())
    assert codex_usage(folder) == 0


def report(folder, primary, secondary):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'session.jsonl').write_text(json.dumps(
        {'payload': {'rate_limits': {'primary': primary, 'secondary': secondary}}}))


def test_codex_usage_reads_both_windows(tmp_path, monkeypatch):
    from cplane.runner import codex_usage
    monkeypatch.setattr('cplane.runner.time.time', lambda: NOW.timestamp())
    ahead = NOW.timestamp() + 1000
    report(tmp_path, {'used_percent': 37.0, 'resets_at': ahead}, {'used_percent': 100.0, 'resets_at': ahead})
    assert codex_usage(tmp_path) == 100.0
    report(tmp_path, {'used_percent': 37.0, 'resets_at': ahead},
           {'used_percent': 100.0, 'resets_at': NOW.timestamp() - 1})
    assert codex_usage(tmp_path) == 37.0
    report(tmp_path, None, None)
    assert codex_usage(tmp_path) is None


WEEKLY = ('You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit '
          'https://chatgpt.com/settings/usage to purchase more credits or try again at Nov 6th, 2026 10:57 AM.')
FIVE_HOUR = WEEKLY.split(' try again')[0] + ' try again at 2:56 PM.'
NO_TIME = 'You’ve hit your usage limit. Upgrade to Pro.'


def cut(r, p, message, limits=None, monkeypatch=None):
    monkeypatch.setattr('cplane.runner.codex_limits', lambda: limits)
    failure = {'type': 'turn.failed', 'error': {'message': message}}
    p.results[p.started[-1]['run']] = (True, 'session-1', None, json.dumps(failure))
    r.run()
    return r.jobs[item(r)['id']]


def at(r, **delta):
    r.clock = lambda: NOW + timedelta(**delta)
    r.codex_reader = lambda: 0


def test_weekly_message_sets_date_and_time(setup, monkeypatch):
    r, p, _ = setup
    r.run()
    job = cut(r, p, WEEKLY, None, monkeypatch)
    assert job['reset_at'] == datetime(2026, 11, 6, 10, 57, tzinfo=timezone.utc).timestamp()
    assert 'resumes after Nov 06 10:57' in item(r)['log'][-2]['event']
    at(r, days=1)
    r.run()
    assert len(p.started) == 1
    at(r, days=21, hours=1)
    r.run()
    assert len(p.started) == 2


@pytest.mark.parametrize('message, expected', [
    (FIVE_HOUR, datetime(2026, 10, 16, 14, 56, tzinfo=timezone.utc)),
    ('Error running remote compact task: ' + FIVE_HOUR, datetime(2026, 10, 16, 14, 56, tzinfo=timezone.utc)),
    ('Error running remote compact task: ' + WEEKLY, datetime(2026, 11, 6, 10, 57, tzinfo=timezone.utc)),
])
def test_other_usage_limit_messages_parse(setup, monkeypatch, message, expected):
    r, p, _ = setup
    r.run()
    assert cut(r, p, message, None, monkeypatch)['reset_at'] == expected.timestamp()


@pytest.mark.parametrize('message, expected', [
    ('try again at 11:19 PM.', datetime(2026, 11, 12, 0, 19, tzinfo=timezone(timedelta(hours=1)))),
    ('try again at Nov 13th, 2026 11:19 PM.', datetime(2026, 11, 14, 0, 19, tzinfo=timezone(timedelta(hours=1)))),
    ('try again at 10:00 PM.', datetime(2026, 11, 12, 23, 0, tzinfo=timezone(timedelta(hours=1)))),
])
def test_message_clock_is_utc_with_local_instant(setup, monkeypatch, message, expected):
    r, p, _ = setup
    r.clock = lambda: datetime(2026, 11, 12, 0, 10, tzinfo=timezone(timedelta(hours=1)))
    r.run()
    assert cut(r, p, NO_TIME + ' ' + message, None, monkeypatch)['reset_at'] == expected.timestamp()


def test_stale_reset_without_time_waits_sixty_minutes(setup, monkeypatch):
    r, p, _ = setup
    r.run()
    stale = [{'used_percent': 100, 'resets_at': NOW.timestamp() - 3600}]
    job = cut(r, p, NO_TIME, stale, monkeypatch)
    assert job['reset_at'] == NOW.timestamp() + 3600
    at(r, minutes=5)
    r.run()
    at(r, minutes=59)
    r.run()
    assert len(p.started) == 1
    at(r, minutes=60)
    r.run()
    assert len(p.started) == 2


def test_report_at_99_percent_names_the_reset(setup, monkeypatch):
    r, p, _ = setup
    r.run()
    primary = {'used_percent': 37.0, 'resets_at': NOW.timestamp() + 600}
    weekly = {'used_percent': 99.0, 'resets_at': NOW.timestamp() + 90000}
    assert cut(r, p, FIVE_HOUR, [primary, weekly], monkeypatch)['reset_at'] == weekly['resets_at']


def test_null_limits_with_and_without_message_time(setup, monkeypatch):
    r, p, _ = setup
    r.run()
    assert cut(r, p, FIVE_HOUR, None, monkeypatch)['reset_at'] == datetime(2026, 10, 16, 14, 56, tzinfo=timezone.utc).timestamp()
    at(r, hours=5)
    r.run()
    assert cut(r, p, NO_TIME, None, monkeypatch)['reset_at'] == (NOW + timedelta(hours=6)).timestamp()


def test_waiting_job_holds_new_codex_slice(setup, monkeypatch):
    r, p, _ = setup
    r.run()
    cut(r, p, FIVE_HOUR, None, monkeypatch)
    data = state.load(r.path)
    (r.repos / 'other').mkdir()
    new = copy.deepcopy(data['slices'][0])
    new.update(id='example/other', repo='example/other', state='ready', attention=None, session=None)
    data['slices'].append(new)
    state.save(r.path, data)
    r.codex_reader = lambda: 0
    r.run()
    assert len(p.started) == 1
    at(r, hours=5)
    r.run()
    assert len(p.started) == 3


def test_repeated_limit_gives_one_notice(setup, monkeypatch):
    r, p, _ = setup
    r.run()
    cut(r, p, WEEKLY, None, monkeypatch)
    assert len(r.notices) == 1

    def resume_and_cut(message):
        # The wait is cut short so the resume runs, as if the limit's reset had moved.
        job = r.jobs[item(r)['id']]
        job['reset_at'] = NOW.timestamp()
        r.save_job(job)
        at(r, minutes=1)
        r.run()
        cut(r, p, message, None, monkeypatch)
        return [n for n in r.notices if 'cut by' in n['text']]

    assert resume_and_cut(WEEKLY) == []
    assert len(resume_and_cut(WEEKLY)) == 0
    assert len(resume_and_cut(WEEKLY.replace('Nov 6th', 'Nov 13th'))) == 1
    assert resume_and_cut(WEEKLY.replace('Nov 6th', 'Nov 13th')) == []
    assert sum('cut by Codex' in e['event'] for e in item(r)['log']) == 5
    assert len(p.started) == 5


def test_repeated_fixed_wait_gives_one_notice(setup, monkeypatch):
    r, p, _ = setup
    r.run()
    cut(r, p, NO_TIME, None, monkeypatch)
    assert len(r.notices) == 1
    at(r, hours=2)
    r.run()
    cut(r, p, NO_TIME, None, monkeypatch)
    assert not any('cut by' in n['text'] for n in r.notices)


def test_paused_waiting_slice_does_not_resume(setup, monkeypatch):
    r, p, _ = setup
    r.run()
    cut(r, p, FIVE_HOUR, None, monkeypatch)
    edit(r, lambda s: s.update(paused=True))
    at(r, hours=6)
    r.run()
    assert len(p.started) == 1
    edit(r, lambda s: s.update(paused=False))
    r.run()
    assert len(p.started) == 2
    r.run()
    assert len(p.started) == 2


@pytest.mark.parametrize('tool', ['codex', 'claude'])
def test_brief_frontmatter_and_option_like_prompt_are_passed_after_separator(setup, tool):
    r, p, _ = setup
    (r.path.parent / 'briefs/W1.md').write_text('---\nstatus: ready\n---\n- begin with an option-like line\n')
    if tool == 'claude':
        edit(r, lambda s: s['executor'].update(tool='claude', model='sonnet'))
        r.claude_reader = lambda: {'at': NOW.timestamp(), 'rate_limits': {'five_hour': {'used_percentage': 1}}}
    r.run()
    assert_prompt(p.started[0], '- begin with an option-like line\n')
    from cplane.executors import command
    args = command(p.started[0])
    assert args[-2:] == ['--', p.started[0]['prompt']]
    assert args[-2] == '--'


def test_null_claude_percentage_is_unknown(setup):
    r, p, _ = setup
    r.codex_reader = lambda: 100
    r.claude_reader = lambda: {'at': NOW.timestamp(), 'rate_limits': {'five_hour': {'used_percentage': None}}}
    r.run()
    assert not p.started


def test_expired_claude_window_is_free_even_with_old_usage_file(setup):
    r, p, _ = setup
    r.codex_reader = lambda: 100
    edit(r, lambda s: s['executor'].update(tool='claude', model='sonnet'))
    r.claude_reader = lambda: {'at': NOW.timestamp() - 7200, 'rate_limits': {'five_hour': {
        'used_percentage': 100, 'resets_at': NOW.timestamp() - 1}}}
    r.run()
    assert len(p.started) == 1
    assert p.started[0]['tool'] == 'claude'


def test_usage_unavailable_or_malformed(tmp_path, monkeypatch):
    from cplane.runner import codex_usage, claude_usage
    assert codex_usage(tmp_path / '.codex/sessions') is None
    assert claude_usage(tmp_path / '.claude/usage-now.json') is None
    (tmp_path / '.claude').mkdir()
    (tmp_path / '.claude/usage-now.json').write_text('invalid')
    assert claude_usage(tmp_path / '.claude/usage-now.json') is None




def test_detached_starter_closes_stdin_and_writes_config(tmp_path, monkeypatch):
    from cplane.executors import FINAL_SCHEMA
    popen = Mock(return_value=Mock(pid=123))
    monkeypatch.setattr('cplane.executors.os.chown', lambda *args: None)
    monkeypatch.setattr('cplane.executors.subprocess.Popen', popen)
    job = {'tool': 'codex', 'run': str(tmp_path), 'repo': '/tmp/repo', 'model': 'm', 'prompt': 'brief'}
    assert Processes().start(job) == 123
    kwargs = popen.call_args.kwargs
    import subprocess
    assert kwargs['stdin'] == subprocess.DEVNULL
    assert kwargs['start_new_session'] is True
    assert kwargs['close_fds'] is True
    assert json.loads((tmp_path / 'io/schema.json').read_text()) == FINAL_SCHEMA
    assert (tmp_path / 'request.json').stat().st_mode & 0o777 == 0o600


def test_detached_supervisor_runs_as_importable_module(tmp_path, monkeypatch):
    import time

    run = tmp_path / 'run'
    run.mkdir()
    repo = tmp_path / 'repo'
    repo.mkdir()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    codex = bin_dir / 'factory-cli'
    codex.write_text('#!/bin/sh\nexit 0\n')
    codex.chmod(0o755)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    monkeypatch.setattr('cplane.executors.os.chown', lambda *args: None)
    job = {'tool': 'codex', 'run': str(run), 'repo': str(repo), 'model': 'stub', 'prompt': 'test'}

    Processes().start(job)

    deadline = time.monotonic() + 5
    while not (run / 'exit.json').exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert (run / 'exit.json').exists()
    assert json.loads((run / 'exit.json').read_text())['code'] == 0
    assert 'Traceback' not in (run / 'supervisor.log').read_text()


@pytest.mark.parametrize('reply', ['{', '{"kind":"unknown","body":"x"}', '{"kind":"handover","body":1}'])
def test_invalid_final_escalates_not_handover(tmp_path, reply):
    import time
    job = {'tool': 'codex', 'run': str(tmp_path), 'started_ns': time.time_ns() - 1_000_000_000}
    (tmp_path / 'last.json').write_text(reply)
    (tmp_path / 'exit.json').write_text('{}')
    done, _, final, _ = Processes().poll(job)
    assert done and final is None


def test_killed_supervisor_and_log_tail(tmp_path, monkeypatch):
    monkeypatch.setattr('cplane.executors.os.killpg', Mock(side_effect=ProcessLookupError))
    (tmp_path / 'turn.jsonl').write_text('\n'.join(str(i) for i in range(80)))
    job = {'tool': 'codex', 'run': str(tmp_path), 'started_ns': 0, 'pid': 123}
    done, _, final, tail = Processes().poll(job)
    assert done and final is None
    assert tail.splitlines() == [str(i) for i in range(40, 80)]


def test_explicit_claude_keeps_configured_tool_and_model(setup):
    r, p, _ = setup
    edit(r, lambda s: s['executor'].update(tool='claude', model='sonnet'))
    original = item(r)['executor']
    r.claude_reader = lambda: {'at': NOW.timestamp(), 'rate_limits': {'five_hour': {'used_percentage': 1}}}
    r.run()
    assert item(r)['executor'] == original
    assert item(r)['session']['tool'] == 'claude'


def test_codex_usage_limit_waits_then_resumes_once(setup, monkeypatch):
    r, p, _ = setup
    r.run()
    run = p.started[0]['run']
    retry_at = NOW.timestamp() + 60
    monkeypatch.setattr('cplane.runner.codex_limits', lambda: [{'resets_at': retry_at}])
    failure = {'type': 'turn.failed', 'error': {'message': 'You’ve hit your usage limit. Try again at 10:01 AM.'}}
    p.results[run] = (True, 'session-1', None, json.dumps(failure))

    r.run()

    assert item(r)['state'] == 'issued'
    assert item(r)['attention'] is None
    assert len(p.started) == 1
    assert len(r.notices) == 1
    assert "cut by Codex's usage limit; resumes after 10:01" in r.notices[0]['text']
    assert r.jobs[item(r)['id']]['phase'] == 'usage-limit-wait'

    r.clock = lambda: NOW + timedelta(seconds=59)
    r.codex_reader = lambda: 99
    r.run()
    assert len(p.started) == 1

    r.clock = lambda: NOW + timedelta(seconds=60)
    r.codex_reader = lambda: 0
    r.run()
    assert len(p.started) == 2
    assert p.started[-1]['resume'] == 'session-1'
    assert_prompt(p.started[-1], 'Your turn was cut by the usage limit. Your uncommitted work is in your working tree. Continue the slice.')
    r.run()
    assert len(p.started) == 2


def test_non_limit_codex_failure_still_escalates(setup):
    r, p, _ = setup
    r.run()
    job = p.started[0]
    p.results[job['run']] = (True, 'session-1', None, 'codex exec exited 1: unexpected argument')
    r.run()
    assert item(r)['attention']['kind'] == 'escalation'
    assert all('cut by Codex' not in notice['text'] for notice in r.notices)


def test_claude_session_resumes_even_when_codex_capacity_returns(setup):
    r, p, _ = setup
    claude_start(r)
    p.finish('question')
    r.run()
    edit(r, lambda s: s['attention'].update(answer='answer'))
    r.codex_reader = lambda: 0
    r.run()
    assert p.started[-1]['tool'] == 'claude'
    assert_prompt(p.started[-1], 'answer')


def test_node_step_recovery_after_state_save_failure(setup, monkeypatch):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=False))
    claude_start(r)
    p.finish('waiting', pr_reply('Owner node work'))
    r.run()
    gh.checks.return_value = 'green', ''
    save = state.save
    monkeypatch.setattr(state, 'save', Mock(side_effect=OSError('disk unavailable')))
    with pytest.raises(OSError):
        r.run()
    monkeypatch.setattr(state, 'save', save)
    r.run()
    assert item(r)['attention']['kind'] == 'node-step'
    assert item(r)['attention']['body'] == 'Owner node work'
    assert len(p.started) == 1


def test_resume_cannot_exceed_two_running_turns(setup):
    r, p, _ = setup
    r.run()
    p.finish('question')
    r.run()
    data = state.load(r.path)
    base = data['slices'][0]
    for i in range(2):
        repo = f'other{i}'
        (r.repos / repo).mkdir()
        s = copy.deepcopy(base)
        s.update(id=f'example/other{i}', repo=f'example/{repo}', state='ready', attention=None, session=None)
        data['slices'].append(s)
    state.save(r.path, data)
    r.run()
    assert len(p.started) == 3  # one finished question, two running
    edit(r, lambda s: s['attention'].update(answer='answer'))
    r.run()
    assert len(p.started) == 3
    assert item(r)['attention']['answer'] == 'answer'


def test_github_open_and_merge_are_recoverable():
    gh = GitHub()
    gh.call = Mock(return_value='[{"number":12}]')
    request = {'branch': 'feat/example', 'title': 'title', 'body': 'body'}
    assert gh.open('owner/repo', request) == 12
    assert gh.call.call_count == 1
    gh.call = Mock(side_effect=['[]', 'https://github.com/owner/repo/pull/12'])
    assert gh.open('owner/repo', request) == 12
    gh.call = Mock(return_value='{"state":"MERGED","mergeCommit":{"oid":"sha"}}')
    assert gh.merge('owner/repo', 12) == 'sha'
    assert gh.call.call_count == 1
    gh.call = Mock(side_effect=['{"state":"OPEN","title":"Example","mergeCommit":null}', '', '{"state":"MERGED","mergeCommit":{"oid":"sha"}}'])
    assert gh.merge('owner/repo', 12) == 'sha'
    assert gh.call.call_count == 3


def test_live_process_group_reserves_capacity_after_supervisor_dies(tmp_path, monkeypatch):
    monkeypatch.setattr('cplane.executors.os.killpg', Mock())
    job = {'tool': 'codex', 'run': str(tmp_path), 'started_ns': 0, 'pid': 123}
    assert Processes().poll(job)[0] is False


def test_supervisor_writes_exit_marker_and_closes_executor_stdin(tmp_path, monkeypatch):
    from cplane.executors import supervise
    import subprocess
    job = {'tool': 'codex', 'run': str(tmp_path), 'repo': str(tmp_path), 'model': 'model', 'prompt': 'prompt'}
    (tmp_path / 'request.json').write_text(json.dumps(job))
    run = Mock(return_value=subprocess.CompletedProcess([], 7))
    monkeypatch.setattr('cplane.executors.subprocess.run', run)
    supervise(tmp_path)
    assert run.call_args.kwargs['stdin'] == subprocess.DEVNULL
    assert run.call_args.kwargs['cwd'] == str(tmp_path)
    assert json.loads((tmp_path / 'exit.json').read_text())['code'] == 7


def test_approved_merge_with_pending_checks_waits(setup):
    r, p, gh = setup
    claude_start(r)
    p.finish('waiting', pr_reply())
    r.run()
    gh.checks.return_value = 'green', ''
    r.run()
    edit(r, lambda s: s['attention'].update(approved=True))
    gh.checks.return_value = 'pending', ''
    r.run()
    gh.merge.assert_not_called()
    assert item(r)['attention']['approved']


def test_prompt_preserves_crlf_and_trailing_whitespace(setup):
    r, p, _ = setup
    raw = b'Exact prompt\r\nwith whitespace  \r\n'
    (r.path.parent / 'briefs/W1.md').write_bytes(raw)
    r.run()
    assert_prompt(p.started[0], raw.decode('utf-8'))


def test_empty_state_is_successful_without_an_empty_git_commit(setup):
    r, p, _ = setup
    r.path.write_text('{"version":1,"slices":[]}\n')
    r.run()
    r.git.pull.assert_called_once_with(r.path)
    r.git.commit.assert_not_called()
    assert not p.started


@pytest.mark.parametrize('phase', [None, 'running', 'ended', 'collected', 'pr', 'merged', 'node-step'])
@pytest.mark.parametrize('attention_kind', [None, 'question', 'merge'])
@pytest.mark.parametrize('tool', ['codex', 'claude'])
def test_accepted_slices_do_not_change_or_log(setup, phase, attention_kind, tool):
    r, p, gh = setup
    attention = None if attention_kind is None else {
        'kind': attention_kind, 'body': 'Review this', 'since': NOW.isoformat(),
        'answer': 'An answer to deliver' if attention_kind == 'question' else None,
        'approved': attention_kind == 'merge',
    }
    edit(r, lambda s: s.update(
        state='accepted', session={'tool': tool, 'id': 'accepted-session', 'folder': str(r.repos / 'repo')},
        attention=attention, pr=12, stop_before_merge=False,
    ))
    job_path = None
    if phase is not None:
        run = r.runs / 'accepted-job'
        run.mkdir(parents=True)
        job = {
            'id': 'voice/W1', 'phase': phase, 'run': str(run), 'tool': tool,
            'repo': str(r.repos / 'repo'), 'session': 'stale-session',
            'model': 'example-model', 'started_ns': 1, 'sha': 'abc123',
            'request': {'branch': 'feat/example', 'title': 'Example', 'body': 'Change',
                        'node_steps': 'Owner node work'},
            'final': {'kind': 'waiting', 'body': pr_reply('Owner node work')}, 'tail': '',
        }
        r.save_job(job)
        job_path = run / 'job.json'
        job_before = job_path.read_bytes()
        p.results[str(run)] = (True, 'stale-session', {'kind': 'handover', 'body': 'done'}, '')
    p.start = Mock(wraps=p.start)
    p.poll = Mock(wraps=p.poll)
    gh.checks.return_value = 'green', ''
    before = item(r)
    state_before = r.path.read_bytes()
    for pass_number in (1, 2):
        r.run()
        after = item(r)
        assert {k: v for k, v in after.items() if k != 'log'} == {
            k: v for k, v in before.items() if k != 'log'
        }
        assert after['log'] == before['log']
        assert r.path.read_bytes() == state_before
        p.start.assert_not_called()
        # A running job's process is polled in memory only, so it can free its slot.
        assert p.poll.call_count == (pass_number if phase == 'running' else 0)
        gh.open.assert_not_called()
        gh.checks.assert_not_called()
        gh.merge.assert_not_called()
        assert not r.notices
        r.git.commit.assert_not_called()
        assert not Path(str(r.path) + '.outbox.jsonl').exists()
        if job_path:
            assert job_path.read_bytes() == job_before




@pytest.mark.parametrize('number,opened', [(None, True), (12, False)])
def test_codex_waiting_without_open_pr_keeps_node_step(setup, number, opened):
    r, p, gh = setup
    r.run()
    gh.find_pr.return_value = number
    gh.is_open.return_value = opened
    p.finish('waiting', 'Owner node work')
    r.run()
    r.run()
    assert item(r)['attention']['kind'] == 'node-step'
    assert item(r)['attention']['body'] == 'Owner node work'
    gh.checks.assert_not_called()
    assert len(p.started) == 1








@pytest.mark.parametrize('pr_state,expected', [('OPEN', True), ('CLOSED', False), ('MERGED', False)])
def test_github_is_open(pr_state, expected):
    gh = GitHub()
    gh.call = Mock(return_value=json.dumps({'state': pr_state}))
    assert gh.is_open('owner/repo', 12) is expected
    gh.call.assert_called_once_with('owner/repo', 'pr', 'view', '12', '--json', 'state')


def test_frontline_start_schedules_in_same_pass(setup):
    from cplane.orders import Collector
    r, processes, _ = setup
    edit(r, lambda s: s.update(slot=None))
    current = item(r)
    queued = dict(id='start-1', created=NOW.isoformat(), action='start', slice=current['id'],
                  argument=None, expect=dict(state='ready', paused=False, attention=None))
    client = Mock()
    client.request.side_effect = [{'orders': [queued]}, None]
    r.orders = Collector(client=client, tmux=Mock())
    # start uses the same real clock as the terminal command.
    r.clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=1)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('CPLANE_ORDERS_URL', 'http://127.0.0.1:1')
        r.run()
    assert len(processes.started) == 1
    assert item(r)['state'] == 'issued'
    assert item(r)['log'][0]['actor'] == 'frontline'


@pytest.mark.parametrize('failure', ['timeout', '503', 'connection', 'no-config'])
def test_frontline_unavailable_does_not_block_scheduling(setup, monkeypatch, failure, capsys):
    from urllib.error import HTTPError, URLError
    from cplane.orders import Collector
    r, processes, _ = setup
    client = Mock()
    if failure == 'no-config':
        monkeypatch.delenv('CPLANE_ORDERS_URL', raising=False)
    else:
        monkeypatch.setenv('CPLANE_ORDERS_URL', 'http://127.0.0.1:1')
        client.request.side_effect = {
            'timeout': TimeoutError('private address'),
            '503': HTTPError('private address', 503, 'locked', {}, None),
            'connection': URLError('private address'),
        }[failure]
    r.orders = Collector(client=client, tmux=Mock())
    r.run()
    assert len(processes.started) == 1
    assert 'private address' not in capsys.readouterr().err
    assert client.request.call_count == (0 if failure == 'no-config' else 1)


@pytest.mark.parametrize('checks,expected', [
    ([{'name': 'test', 'conclusion': 'CANCELLED'}, {'name': 'test', 'conclusion': 'SUCCESS'}], ('green', '')),
    ([{'name': 'test', 'conclusion': 'SUCCESS'}, {'name': 'test', 'conclusion': 'CANCELLED'}], ('green', '')),
    ([{'name': 'test', 'conclusion': 'CANCELLED'}], ('red', 'test')),
    ([{'name': 'test', 'conclusion': 'CANCELLED'}, {'name': 'lint', 'conclusion': 'SUCCESS'}], ('red', 'test')),
    ([{'name': 'test', 'conclusion': 'FAILURE'}, {'name': 'test', 'conclusion': 'SUCCESS'}], ('red', 'test')),
    ([{'name': 'test', 'conclusion': 'TIMED_OUT'}, {'name': 'test', 'conclusion': 'SUCCESS'}], ('red', 'test')),
    ([{'name': 'test', 'conclusion': 'CANCELLED'}, {'name': 'test', 'conclusion': 'SUCCESS'},
      {'name': 'lint', 'conclusion': 'ERROR'}], ('red', 'lint')),
])
def test_cancelled_check_is_not_red_when_same_name_succeeded(checks, expected):
    gh = GitHub()
    gh.call = Mock(return_value=json.dumps({'statusCheckRollup': checks}))
    assert gh.checks('owner/repo', 1) == expected


@pytest.mark.parametrize('tool', ['codex', 'claude'])
def test_answer_to_node_step_resumes_session(setup, tool):
    r, p, _ = setup
    if tool == 'claude':
        claude_start(r)
        p.finish('waiting', 'plain text')
    else:
        r.run()
        p.finish('waiting', 'plain text')
    r.run()
    assert item(r)['attention']['kind'] == 'node-step'
    r.run()
    assert len(p.started) == 1
    assert main(['--state', str(r.path), 'answer', 'voice/W1', 'node step done']) == 0
    r.run()
    assert len(p.started) == 2
    assert_prompt(p.started[-1], 'node step done')
    assert p.started[-1]['resume'] == 'session-1'
    assert item(r)['attention'] is None


def accept_with_running_job(r, p):
    r.run()
    edit(r, lambda s: s.update(state='accepted'))


def test_accepted_slice_with_ended_process_frees_slot_and_repository(setup, tmp_path, slice_data):
    r, p, _ = setup
    accept_with_running_job(r, p)
    p.finish()
    second = copy.deepcopy(item(r))
    second.update(id='voice/W2', state='ready', session=None, attention=None, log=[],
                  slot=(NOW - timedelta(minutes=1)).isoformat())
    data = state.load(r.path)
    data['slices'].append(second)
    state.save(r.path, data)
    r.run()
    assert len(p.started) == 2
    assert p.started[-1]['id'] == 'voice/W2'
    assert r.room(second) is None or 'W1' not in r.room(second)


def test_accepted_slice_with_live_process_still_counts(setup):
    r, p, _ = setup
    accept_with_running_job(r, p)
    second = copy.deepcopy(item(r))
    second.update(id='voice/W2', state='ready', session=None, attention=None, log=[],
                  slot=(NOW - timedelta(minutes=1)).isoformat())
    data = state.load(r.path)
    data['slices'].append(second)
    state.save(r.path, data)
    r.run()
    assert len(p.started) == 1
    assert 'repository busy (voice/W1)' in state.load(r.path)['slices'][1]['log'][-1]['event']






def test_failing_pull_still_raises_and_never_launches_autostash(setup):
    r, p, _ = setup
    r.git.pull.side_effect = state.StateError('pull failed')
    with pytest.raises(state.StateError):
        r.run()
    assert not p.started


@pytest.mark.parametrize('model,expected', [
    ('opus', 'opus'), ('sonnet', 'sonnet'), ('gpt-6.1-sol', 'gpt-6.1-sol'),
    ('Some-SOL', 'Some-SOL'), ('other', 'other'), ('Opus', 'Opus'),
])
def test_claude_model_choice_is_preserved(setup, model, expected):
    r, p, _ = setup
    r.codex_reader = lambda: 100
    edit(r, lambda s: s['executor'].update(tool='claude', model=model))
    r.claude_reader = lambda: {'at': NOW.timestamp(), 'rate_limits': {'five_hour': {'used_percentage': 1}}}
    r.run()
    assert p.started[0]['model'] == expected


def test_claude_resume_model_unchanged(setup):
    r, p, _ = setup
    claude_start(r)
    edit(r, lambda s: s['executor'].update(model='opus'))
    p.finish('question', 'q')
    r.run()
    edit(r, lambda s: s['attention'].update(answer='a'))
    r.run()
    assert p.started[-1]['model'] == 'sonnet'


def test_bot_export_after_pass(setup, tmp_path, monkeypatch):
    from cplane import fence
    r, _, _ = setup
    folder = tmp_path / 'bot'
    folder.mkdir()
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
    monkeypatch.setenv('CPLANE_BOT_EXPORT', str(folder))
    events = ['started', 'question', 'merge', 'submitted', 'escalation', 'owner-check', 'chat-paused']
    notices = [{'at': '2026-01-01', 'id': 'voice/W1', 'event': event, 'text': event}
               for event in events]
    state.store(r.path).append_notices(notices)
    r.run()
    exported = json.loads((folder / 'slices.json').read_text())
    assert len(exported['slices']) == 1
    assert 'log' not in exported['slices'][0]
    outbox = folder / 'slices.json.outbox.jsonl'
    previous = outbox.read_text()
    assert [json.loads(line)['event'] for line in previous.splitlines()] == [
        'question', 'merge', 'escalation', 'owner-check', 'chat-paused']
    for file in (folder / 'slices.json', outbox):
        assert file.stat().st_mode & 0o777 == 0o640
        assert file.stat().st_gid == folder.stat().st_gid
    state.store(r.path).append_notices([notices[1]])
    r.run()
    assert outbox.read_text() == previous + json.dumps(notices[1], ensure_ascii=False) + '\n'


def test_bot_export_projects_accepted_slices(tmp_path, make_state, slice_data, monkeypatch):
    from cplane import fence, runner
    accepted = dict(slice_data, id='voice/W0', state='accepted', paused=True,
                    attention={'kind': 'question', 'body': 'Follow up',
                               'since': '2026-01-01T00:00:00Z', 'answer': None, 'approved': False},
                    pr=1, log=[{'at': '2026-01-01T00:00:00Z', 'actor': 'test', 'event': 'done'}])
    active = dict(slice_data, state='planned',
                  log=[{'at': '2026-01-01T00:00:00Z', 'actor': 'test', 'event': 'created'}])
    path = make_state([accepted, active])
    original = json.loads(path.read_text())
    folder = tmp_path / 'bot'
    folder.mkdir()
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
    monkeypatch.setenv('CPLANE_BOT_EXPORT', str(folder))

    runner.export_bot(path)

    exported = json.loads((folder / 'slices.json').read_text())
    fields = {'id', 'repo', 'title', 'state', 'pr', 'feature', 'paused', 'attention'}
    assert exported['slices'][0] == {key: accepted[key] for key in fields}
    assert exported['slices'][1] == {key: value for key, value in active.items() if key != 'log'}
    assert json.loads(path.read_text()) == original


def test_bot_export_unset_and_empty_pass(tmp_path, make_state, monkeypatch):
    from cplane import fence
    path = make_state([])
    r = Runner(path, git=Mock(), runs=tmp_path / 'runs')
    monkeypatch.delenv('CPLANE_BOT_EXPORT', raising=False)
    r.run()
    assert not (tmp_path / 'bot').exists()
    folder = tmp_path / 'bot'
    folder.mkdir()
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
    monkeypatch.setenv('CPLANE_BOT_EXPORT', str(folder))
    r.run()
    assert json.loads((folder / 'slices.json').read_text())['slices'] == []
    assert (folder / 'slices.json.outbox.jsonl').read_text() == ''


def test_bot_export_untrusted_and_write_failure(setup, tmp_path, monkeypatch, capsys):
    from cplane import fence, runner
    r, _, _ = setup
    folder = tmp_path / 'bot'
    folder.mkdir(mode=0o777)
    folder.chmod(0o777)
    monkeypatch.setattr(fence, 'ROOT_UID', os.getuid())
    monkeypatch.setenv('CPLANE_BOT_EXPORT', str(folder))
    r.run()
    assert list(folder.iterdir()) == []
    assert capsys.readouterr().err == 'cplane: bot export failed\n'
    folder.chmod(0o750)
    replace = os.replace
    def fail(source, destination):
        if Path(destination).parent == folder:
            raise OSError('private text')
        return replace(source, destination)
    monkeypatch.setattr(runner.os, 'replace', fail)
    r.run()
    assert list(folder.iterdir()) == []
    assert capsys.readouterr().err == 'cplane: bot export failed\n'


def test_stuck_since_detects_idle_and_pending_checks():
    from datetime import datetime, timedelta, timezone
    from cplane.runner import stuck_since

    instant = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    def entry(minutes, event):
        return {'at': (instant - timedelta(minutes=minutes)).isoformat(),
                'actor': 'runner', 'event': event}
    item = {'state': 'issued', 'log': [entry(20, 'started')]}
    assert stuck_since(item, instant) == (instant - timedelta(minutes=20), 'no new log activity')
    item['log'] = [entry(11, 'checks: pending'), entry(1, 'checks: pending')]
    assert stuck_since(item, instant) == (instant - timedelta(minutes=11), 'checks pending')
    item['log'].insert(1, entry(5, 'checks: green'))
    assert stuck_since(item, instant) is None
    item['state'] = 'accepted'
    assert stuck_since(item, instant) is None


def test_ci_reads_record_both_heads_without_changing_delivery(setup, monkeypatch):
    r, _, _ = setup
    r.run()
    current = r.data['slices'][0]
    job = r.jobs[current['id']]
    job['phase'] = 'pr'
    current.update(pr=12, attention=None, stop_before_merge=True)
    store = Mock()
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(state, 'store', lambda _: store)
    job['tip'] = 'b' * 40
    github = Mock()
    github.checks.side_effect = [('red', 'test'), ('green', '')]
    r.github = github
    r.pr_checks(current, job)
    assert current['attention']['kind'] == 'escalation'
    current['attention'] = None
    r.pr_checks(current, job)
    assert current['attention']['kind'] == 'merge'
    assert all(call.kwargs['expected'] == 'b' * 40 for call in github.checks.call_args_list)
    observations = [call.kwargs['ci'] for call in store.run_record_outcome.call_args_list if 'ci' in call.kwargs]
    assert observations == [dict(sha='b' * 40, status='red', failing_job='test'),
                            dict(sha='b' * 40, status='green', failing_job=None)]
    assert job['phase'] == 'pr'


def test_pipeline_failure_diagnostic_survives_missing_cli_version(setup, monkeypatch, capsys):
    from cplane import run_records
    from conftest import SyntheticStore

    r, processes, _ = setup
    backend = SyntheticStore(r.path)
    backend.pipeline_step = Mock(side_effect=RuntimeError('PRIVATE pipeline failure'))
    backend.route_chat_events = Mock()
    backend.ordered_slices = lambda items: items
    backend.limit_show = lambda: dict(executors=2, repository_runs=1)
    backend.slice_executor = lambda item: dict(tool='codex', model='synthetic', effort='medium')
    backend.slice_policy = lambda identifier: None
    monkeypatch.setattr(state, 'postgres', lambda: True)
    monkeypatch.setattr(state, 'store', lambda _: backend)
    original = run_records.subprocess.run

    def missing_cli(args, **kwargs):
        if args[0] == 'codex':
            raise FileNotFoundError('PRIVATE missing CLI')
        return original(args, **kwargs)

    monkeypatch.setattr(run_records.subprocess, 'run', missing_cli)
    r.run()
    assert capsys.readouterr().err == 'pipeline step failed\n'
    assert len(processes.started) == 1
    assert item(r)['state'] == 'issued'


@pytest.mark.parametrize('stop,status', [(True, 'green'), (False, 'red'), (False, 'pending'), (False, 'green')])
def test_codex_ci_watch_recovers_state_save_failures(setup, monkeypatch, stop, status):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=stop))
    r.run()
    gh.find_pr.return_value = 12
    p.finish('waiting', pr_reply())
    save = state.save
    monkeypatch.setattr(state, 'save', Mock(side_effect=OSError('disk unavailable')))
    with pytest.raises(OSError):
        r.run()
    # On replay the branch might have changed. The saved PR number is authoritative.
    gh.find_pr.side_effect = AssertionError('must recover saved PR')
    monkeypatch.setattr(state, 'save', save)
    r.run()
    assert item(r)['pr'] == 12
    gh.checks.return_value = status, 'test'
    monkeypatch.setattr(state, 'save', Mock(side_effect=OSError('disk unavailable')))
    with pytest.raises(OSError):
        r.run()
    monkeypatch.setattr(state, 'save', save)
    r.run()
    r.run()
    if status == 'green' and not stop:
        assert len(p.started) == 2
        assert item(r)['attention'] is None
        assert item(r)['session']['id'] == 'session-1'
    else:
        assert len(p.started) == 1
        a = item(r)['attention']
        if status == 'pending':
            assert a is None
        else:
            assert a['kind'] == ('merge' if status == 'green' else 'escalation')


def test_codex_green_waits_for_capacity_then_resumes_once(setup):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=False))
    r.run()
    gh.find_pr.return_value = 12
    p.finish('waiting', pr_reply())
    r.run()
    gh.checks.return_value = 'green', ''
    r.codex_reader = lambda: 100
    r.run()
    assert len(p.started) == 1
    assert r.jobs['voice/W1']['phase'] == 'merged'
    assert item(r)['attention'] is None
    r.codex_reader = lambda: 0
    r.run()
    r.run()
    assert len(p.started) == 2


def test_codex_ci_merge_attention_review_approval(setup):
    r, p, gh = setup
    r.run()
    gh.find_pr.return_value = 12
    p.finish('waiting', pr_reply())
    r.run()
    gh.checks.return_value = 'green', ''
    r.run()
    args = ['--state', str(r.path)]
    assert main([*args, 'approve', 'voice/W1']) == 1
    assert main([*args, '--actor', 'planner', 'review', 'voice/W1', 'Ready']) == 0
    r.run()
    assert item(r)['attention']['review']['verdict'] == 'Ready'
    assert main([*args, 'approve', 'voice/W1']) == 0
    r.run()
    r.run()
    assert len(p.started) == 2
    assert_prompt(p.started[-1], 'merged as abc123')
    gh.merge.assert_called_once_with('example/repo', 12, expected='b' * 40)


@pytest.mark.parametrize('blocked_state', ['issued', 'escalated', 'awaiting handover'])
def test_ended_attention_allows_unrelated_scope_in_same_repository(setup, blocked_state):
    r, processes, _ = setup
    edit(r, lambda s: s.update(allowed_files=['first/**']))
    r.run()
    processes.finish('question', 'Synthetic decision')
    r.run()
    data = state.load(r.path)
    first = data['slices'][0]
    first['state'] = blocked_state
    second = dict(copy.deepcopy(first), id='voice/W2', state='ready', session=None,
                  attention=None, log=[], allowed_files=['second/**'])
    data['slices'].append(second)
    state.save(r.path, data)
    r.run()
    assert [job['id'] for job in processes.started] == ['voice/W1', 'voice/W2']
    assert item(r)['attention']['answer'] is None


def test_runner_dependency_waits_for_merge_and_install(setup, monkeypatch):
    r, processes, _ = setup
    monkeypatch.setenv('CPLANE_INSTALL_REPOS', 'example/repo')
    dependency = dict(copy.deepcopy(item(r)), id='voice/dependency', state='in review',
                      allowed_files=['dependency/**'])
    current = dict(item(r), depends_on=[dependency['id']], allowed_files=['work/**'])
    data = dict(version=1, slices=[current, dependency])
    state.save(r.path, data)
    r.run()
    assert not processes.started
    dependency['log'].append(dict(at=NOW.isoformat(), actor='runner', event='merged: abc123'))
    state.save(r.path, data)
    r.run()
    assert not processes.started
    dependency['log'].append(dict(at=NOW.isoformat(), actor='runner', event='Installed abc123'))
    state.save(r.path, data)
    r.run()
    assert [job['id'] for job in processes.started] == ['voice/W1']


@pytest.mark.parametrize('metadata', [dict(body='Please DO NOT MERGE this'),
                                       dict(body='merge blocker: waiting'), dict(isDraft=True)])
@pytest.mark.parametrize('stop', [False, True])
def test_not_for_merge_body_and_github_draft_never_get_cards(setup, metadata, stop):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=stop))
    r.run()
    p.finish('waiting', pr_reply())
    r.run()
    live = GitHub()
    live.call = Mock(return_value=json.dumps(dict(state='OPEN', title='Ordinary title',
                                                  headRefOid='b' * 40, **metadata)))
    gh.merge_info.side_effect = live.merge_info
    gh.checks.return_value = ('green', '')
    r.run()
    assert item(r)['attention']['body'] == 'PR marked not for merging'
    gh.merge.assert_not_called()
    assert not any(e['event'].startswith('merge:') for e in item(r)['log'])


def test_behind_branch_updates_once_then_waits_for_new_head_ci(setup):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=False))
    r.run()
    p.finish('waiting', pr_reply())
    r.run()
    gh.merge_info.return_value = dict(mergeStateStatus='BEHIND', mergeable='MERGEABLE')
    gh.checks.return_value = ('green', '')
    r.run()
    gh.update_branch.assert_called_once_with('example/repo', 12, 'b' * 40)
    gh.merge.assert_not_called()
    assert r.jobs['voice/W1']['tip'] == 'c' * 40
    gh.merge_info.return_value = dict(mergeStateStatus='CLEAN', mergeable='MERGEABLE')
    gh.checks.return_value = ('pending', '')
    r.run()
    gh.checks.assert_called_with('example/repo', 12, expected='c' * 40)
    gh.merge.assert_not_called()
    gh.checks.return_value = ('green', '')
    r.run()
    gh.merge.assert_called_once_with('example/repo', 12, expected='c' * 40)


def test_branch_update_conflict_has_fixed_reason(setup):
    from cplane.runner import BranchConflict
    r, p, gh = setup
    r.run()
    p.finish('waiting', pr_reply())
    r.run()
    gh.merge_info.return_value = dict(mergeStateStatus='BEHIND', mergeable='MERGEABLE')
    gh.update_branch.side_effect = BranchConflict('PR conflicts with main; needs a new slice from main')
    r.run()
    assert item(r)['attention']['body'] == 'PR conflicts with main; needs a new slice from main'
    gh.merge.assert_not_called()


def test_github_update_branch_uses_merge_and_classifies_conflict(monkeypatch):
    from cplane.runner import BranchConflict
    gh = GitHub()
    gh.call = Mock(side_effect=['', '{"state":"OPEN","title":"OK","headRefOid":"new"}'])
    assert gh.update_branch('example/repo', 12, 'old') == 'new'
    assert gh.call.call_args_list[0].args == (
        'example/repo', 'pr', 'update-branch', '12', '--expected-head-oid', 'old')
    monkeypatch.setattr('cplane.fence.github_environment', lambda _: {})
    monkeypatch.setattr(subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], 1, '', 'merge conflict')))
    with pytest.raises(BranchConflict, match='^PR conflicts with main; needs a new slice from main$'):
        GitHub().update_branch('example/repo', 12, 'old')


def test_rewritten_publish_escalates_once_and_answer_resumes_existing_copy(setup):
    r, p, gh = setup
    r.run()
    original = p.started[-1]
    p.finish('waiting', pr_reply())
    reason = 'branch was rewritten; merge main instead of rebasing'
    r.fence.publish.side_effect = state.StateError(reason)
    r.run()
    assert r.jobs['voice/W1']['phase'] == 'publish-blocked'
    for _ in range(3):
        r.run()
    r.fence.publish.assert_called_once()
    assert sum(e['event'] == 'escalation: ' + reason for e in item(r)['log']) == 1
    edit(r, lambda s: s['attention'].update(answer='Merge main and continue'))
    r.run()
    assert len(p.started) == 2
    assert p.started[-1]['repo'] == original['repo']
    assert p.started[-1]['resume'] == 'session-1'
    r.fence.publish.assert_called_once()
    gh.open.assert_not_called()


@pytest.mark.parametrize('with_job', [False, True])
def test_answer_without_session_restarts_from_brief(setup, with_job):
    r, p, _ = setup
    if with_job:
        r.run()
        p.results[p.started[-1]['run']] = (True, '', None, 'start failed')
        r.run()
    else:
        r.fence.prepare.side_effect = OSError('start failed')
        r.run()
        r.fence.prepare.side_effect = lambda repo, branch, token: dict(
            repo=str(r.repos / 'repo'), branch=branch, base='a' * 40, repository=repo)
    assert not item(r)['session'] or not item(r)['session']['id']
    edit(r, lambda s: s['attention'].update(answer='Try again'))
    r.run()
    assert len(p.started) == (2 if with_job else 1)
    assert p.started[-1]['resume'] is None
    assert_prompt(p.started[-1], 'The exact prompt.\n')
    assert item(r)['attention'] is None


@pytest.mark.parametrize('age,expected', [(1800, 0), (1801, 1)])
def test_usage_probe_refreshes_only_stale_full_usage(setup, monkeypatch, age, expected):
    r, p, _ = setup
    used = [99]
    r.codex_reader = lambda: used[0]
    monkeypatch.setattr('cplane.runner.codex_report', lambda: ([{'used_percent': 99}], NOW.timestamp() - age))
    probe = Mock(side_effect=lambda _: used.__setitem__(0, 0))
    monkeypatch.setattr('cplane.runner.probe_codex_usage', probe)
    r.run()
    assert probe.call_count == expected
    assert len(p.started) == expected


def test_usage_probe_hourly_limit_survives_runner_passes(setup, monkeypatch):
    r, p, _ = setup
    r.codex_reader = lambda: 99
    monkeypatch.setattr('cplane.runner.codex_report', lambda: ([{'used_percent': 99}], NOW.timestamp() - 7200))
    probe = Mock(side_effect=OSError('unavailable'))
    monkeypatch.setattr('cplane.runner.probe_codex_usage', probe)
    for minutes in (0, 1, 59, 60):
        r.clock = lambda: NOW + timedelta(minutes=minutes)
        r.run()
        assert probe.call_count == (2 if minutes == 60 else 1)
    assert not p.started


def test_unapproved_merge_card_is_replaced_when_pr_becomes_blocked(setup):
    from cplane.runner import BlockedPR
    r, p, gh = setup
    r.run()
    p.finish('waiting', pr_reply())
    r.run()
    gh.checks.return_value = ('green', '')
    r.run()
    assert item(r)['attention']['kind'] == 'merge'
    gh.merge_info.side_effect = BlockedPR('PR marked not for merging')
    r.run()
    assert item(r)['attention']['kind'] == 'escalation'
    assert item(r)['attention']['body'] == 'PR marked not for merging'
    gh.merge.assert_not_called()


def test_usage_report_age_comes_from_report_not_session_activity(tmp_path):
    from cplane.runner import codex_report
    report_time = NOW - timedelta(hours=2)
    log = tmp_path / 'session.jsonl'
    log.write_text(json.dumps(dict(timestamp=report_time.isoformat(),
        payload=dict(rate_limits=dict(primary=dict(used_percent=99))))) + '\n' +
        json.dumps(dict(timestamp=NOW.isoformat(), payload=dict(type='other activity'))) + '\n')
    assert codex_report(tmp_path)[1] == report_time.timestamp()


def test_usage_observation_outside_run_never_probes(setup, monkeypatch):
    r, _, _ = setup
    r.instant, r.jobs = NOW, {}
    r.codex_reader = lambda: 99
    probe = Mock(side_effect=AssertionError('read-only observations never start a CLI'))
    monkeypatch.setattr('cplane.runner.probe_codex_usage', probe)
    assert r.choose(item(r)) is None
    probe.assert_not_called()


@pytest.mark.parametrize('slice_state', ['planned', 'researching', 'in review'])
def test_answer_without_session_does_not_start_inactive_slice(setup, slice_state):
    r, p, _ = setup
    attention = dict(kind='question', body='Planning question', since=NOW.isoformat(),
                     answer='Answered', approved=False)
    edit(r, lambda s: s.update(state=slice_state, attention=attention))
    r.run()
    assert not p.started
    assert item(r)['state'] == slice_state
    assert item(r)['attention'] == attention


@pytest.mark.parametrize('metadata', [dict(title='Draft: wait'), dict(body='MERGE BLOCKER'),
                                       dict(isDraft=True)])
def test_check_head_read_also_guards_merge_cards(setup, metadata):
    r, _, _ = setup
    r.run()
    candidate = r.data['slices'][0]
    job = r.jobs[candidate['id']]
    tip = 'a' * 40
    candidate.update(pr=12, attention=None, stop_before_merge=True)
    job.update(phase='pr', tip=tip)
    gh = GitHub()
    live = dict(headRefOid=tip, state='OPEN', title='Ordinary PR', body='', isDraft=False,
                mergeStateStatus='CLEAN', mergeable='MERGEABLE')
    live.update(metadata)
    gh.call = Mock(side_effect=[json.dumps(live),
        json.dumps(dict(workflow_runs=[dict(id=1, status='completed')])),
        json.dumps(dict(jobs=[dict(name='test', status='completed', conclusion='success')]))])
    r.github = gh
    r.pr_checks(candidate, job)
    assert candidate['attention']['kind'] == 'escalation'
    assert candidate['attention']['body'] == 'PR marked not for merging'
    assert gh.call.call_count == 3
    fields = gh.call.call_args_list[0].args[-1].split(',')
    assert {'headRefOid', 'title', 'body', 'isDraft', 'mergeStateStatus', 'mergeable'} <= set(fields)
    assert not any(e['event'].startswith('merge:') for e in candidate['log'])


@pytest.mark.parametrize('stop', [True, False])
def test_guard_card_names_at_most_twenty_paths_and_approval_merges(setup, monkeypatch, stop):
    r, _, gh = setup
    r.run()
    current = r.data['slices'][0]
    job = r.jobs[current['id']]
    current.update(pr=12, attention=None, stop_before_merge=stop)
    job.update(phase='pr', tip='b' * 40, request=dict(node_steps=None))
    paths = [f'guard/{i:02d}' for i in range(23)]
    monkeypatch.setattr('cplane.classes.changes', lambda *args: (4, paths))
    gh.checks.return_value = ('green', '')
    r.pr_checks(current, job)
    card = current['attention']
    assert card['kind'] == 'merge'
    assert all(path in card['body'] for path in paths[:20])
    assert all(path not in card['body'] for path in paths[20:])
    assert '3 more class 4 paths' in card['body']
    gh.merge.assert_not_called()
    card['approved'] = True
    r.launch = Mock()
    r.deliver(current)
    gh.merge.assert_called_once_with('example/repo', 12, expected='b' * 40)


@pytest.mark.parametrize('enabled', [False, True])
def test_ticket_start_gate(setup, monkeypatch, enabled):
    r, processes, _ = setup
    monkeypatch.delenv('CPLANE_TASK_SUBMIT', raising=False)
    if enabled:
        monkeypatch.setenv('CPLANE_TASK_SUBMIT', '["synthetic-submit"]')
    edit(r, lambda s: s.update(flow='tickets'))
    launch = Mock()
    monkeypatch.setattr(r, 'launch', launch)
    r.run()
    assert launch.call_count == int(enabled)
    assert not processes.started


def test_ticket_resume_and_submission_gate(setup, monkeypatch):
    r, processes, _ = setup
    r.run()
    assert len(processes.started) == 1
    monkeypatch.delenv('CPLANE_TASK_SUBMIT', raising=False)
    edit(r, lambda s: s.update(flow='tickets'))
    collect, submit = Mock(), Mock()
    monkeypatch.setattr(r, 'collect', collect)
    monkeypatch.setattr(r, 'submit_tickets', submit)
    # A cut result must remain untouched while the host interface is off.
    job = r.jobs['voice/W1']
    job['phase'] = 'cut-ready'
    r.save_job(job)
    launch = Mock()
    monkeypatch.setattr(r, 'launch', launch)
    r.run()
    collect.assert_not_called()
    submit.assert_not_called()
    launch.assert_not_called()
