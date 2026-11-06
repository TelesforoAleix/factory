import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import plistlib
import subprocess
from unittest.mock import Mock

import pytest

from cplane import agent, state
from cplane.cli import main
from cplane.executors import CLAUDE_PARAGRAPH, Processes, command
from cplane.runner import Runner, Git, GitHub
from cplane.text_bounds import TAIL_LIMIT

NOW = datetime(2026, 10, 16, 10, tzinfo=timezone.utc)


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


@pytest.fixture
def setup(tmp_path, slice_data, make_state):
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
    assert p.started[0]['prompt'] == 'The exact prompt.\n'
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
    assert r.git.mock_calls[-1][0] == 'tidy'
    assert r.git.commit.call_count == 3
    assert len(p.started) == 1
    assert r.github.find_pr.call_count == 1
    r.run()
    assert item(r)['state'] == 'in review'


def test_tidy_skips_busy_repository_and_failure_does_not_fail_pass(setup, capsys):
    r, _, _ = setup
    r.run()
    r.git.tidy.assert_not_called()
    for job_file in r.runs.glob('*/job.json'):
        job_file.unlink()
    edit(r, lambda s: s.update(state='planned', slot=None, session={'tool': 'codex', 'id': '', 'folder': ''}))
    r.git.tidy.side_effect = OSError('simulated git failure')
    r.run()
    assert 'repo: tidy failed: simulated git failure' in capsys.readouterr().err


def test_tidy_skips_missing_repository_folder(setup, capsys):
    r, _, _ = setup
    repo = r.repos / 'repo'
    (repo / '.git').rmdir()
    repo.rmdir()
    edit(r, lambda s: s.update(state='planned', slot=None))
    r.git = Git()
    r.git.pull = Mock()
    r.git.commit = Mock()

    r.run()

    assert capsys.readouterr().err == ''


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
    assert p.started[0]['prompt'].startswith('The exact prompt.\n' + CLAUDE_PARAGRAPH)


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


def test_paused_issued_slice_does_not_block(setup):
    r, p, _ = setup
    data = state.load(r.path)
    parked = copy.deepcopy(data['slices'][0])
    parked.update(id='example/parked', state='issued', paused=True)
    data['slices'].append(parked)
    state.save(r.path, data)

    r.run()

    assert len(p.started) == 1
    assert item(r)['state'] == 'issued'


def test_paused_running_job_does_not_count_or_make_repository_busy(setup):
    r, _, _ = setup
    r.data = state.load(r.path)
    parked = copy.deepcopy(r.data['slices'][0])
    parked.update(id='example/parked', state='issued', paused=True)
    r.data['slices'].append(parked)
    r.jobs = {
        parked['id']: {
            'id': parked['id'], 'repo': str(r.repos / 'repo'), 'phase': 'running'
        }
    }

    assert r.room(r.data['slices'][0]) is None


def test_deferrals_name_blocker_and_log_identical_reason_once(setup):
    r, _, _ = setup
    r.data = state.load(r.path)
    candidate = r.data['slices'][0]
    r.at = NOW.isoformat()
    r.jobs = {
        f'example/W{i}': {
            'id': f'example/W{i}', 'repo': str(r.repos / f'repo{i}'), 'phase': 'running'
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
            'id': 'example/W0', 'repo': str(r.repos / 'repo'), 'phase': 'running'
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
    a = item(r)['attention']
    assert (a['kind'] if a else None) == attention
    if kind is None:
        assert a['body'].startswith('the run ended without a final message')
        assert a['body'].count('line') == 40
    elif a:
        assert a['body'] == 'body'


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
    assert p.started[-1]['prompt'] == 'exact answer'
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
    gh.merge.assert_called_once_with('example/repo', 12)
    assert p.started[-1]['prompt'] == 'merged as abc123'
    assert p.started[-1]['resume'] == 'session-1'
    assert p.started[-1]['tool'] == 'claude'
    p.finish()
    r.run()
    assert item(r)['state'] == 'in review'


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
    assert p.started[-1]['prompt'] == 'The owner approves the merge.'
    gh.merge.assert_not_called()


def test_resume_obeys_repository_limit(setup):
    r, p, _ = setup
    r.run()
    p.finish('question')
    r.run()
    data = state.load(r.path)
    second = copy.deepcopy(data['slices'][0])
    second.update(id='example/W2', state='ready', session=None, attention=None)
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


@pytest.mark.parametrize(('commit', 'extra'), [(False, []), (True, ['--commit'])])
def test_plist(commit, extra):
    data = plistlib.loads(plistlib.dumps(agent.render('/tmp/state.json', commit=commit, home='/tmp/owner', python='/python', environment={})))
    assert data['AbandonProcessGroup'] is True
    assert data['StartInterval'] == 300
    assert data['StandardOutPath'] == '/tmp/owner/Library/Logs/cplane/runner.log'
    assert data['StandardErrorPath'] == '/tmp/owner/Library/Logs/cplane/runner-error.log'
    assert data['ProgramArguments'] == ['/python', '-m', 'cplane.cli', '--state', '/tmp/state.json', *extra, '--actor', 'runner', 'run']


def test_agent_install_uninstall_only_fake_launchctl(tmp_path, monkeypatch):
    monkeypatch.setattr(agent.Path, 'home', lambda: tmp_path)
    call = Mock()
    monkeypatch.setattr(agent, 'launchctl', call)
    agent.install(tmp_path / 'state.json')
    plist = tmp_path / 'Library/LaunchAgents/com.cplane.runner.plist'
    assert plist.exists()
    assert call.call_args.args[0] == 'bootstrap'
    agent.uninstall()
    assert not plist.exists()
    assert call.call_args.args[0] == 'bootout'


def test_agent_replace_waits_for_launchd_before_bootstrap(tmp_path, monkeypatch):
    monkeypatch.setattr(agent.Path, 'home', lambda: tmp_path)
    target = tmp_path / 'Library/LaunchAgents/com.cplane.runner.plist'
    target.parent.mkdir(parents=True)
    target.write_text('old')
    listed = iter([0, 0, 113])
    calls = []

    def launchctl(*args, **kwargs):
        calls.append(args)
        if args[0] == 'list':
            return Mock(returncode=next(listed))
        return Mock(returncode=0)

    monkeypatch.setattr(agent, 'launchctl', launchctl)
    monkeypatch.setattr(agent.time, 'sleep', lambda _: calls.append(('sleep',)))
    agent.install(tmp_path / 'state.json')
    assert calls == [
        ('bootout', f'gui/{os.getuid()}', str(target)),
        ('list', agent.LABEL), ('sleep',), ('list', agent.LABEL), ('sleep',), ('list', agent.LABEL),
        ('bootstrap', f'gui/{os.getuid()}', str(target)),
    ]


def test_install_agent_passes_commit_flag(make_state, monkeypatch):
    path = make_state()
    install = Mock()
    monkeypatch.setattr(agent, 'install', install)
    assert main(['--state', str(path), '--commit', 'install-agent']) == 0
    install.assert_called_once_with(path.resolve(), commit=True)


@pytest.mark.parametrize('tool', ['codex', 'claude'])
@pytest.mark.parametrize('resume', [None, 'session'])
def test_executor_arguments(tool, resume, tmp_path):
    job = {'tool': tool, 'run': str(tmp_path), 'repo': '/tmp/repo', 'model': 'model', 'prompt': '-literal prompt', 'resume': resume}
    args = command(job)
    assert args[-2:] == ['--', job['prompt']]
    if resume:
        assert 'session' in args
    if tool == 'codex':
        assert 'sandbox_mode="workspace-write"' in args
        assert 'sandbox_workspace_write.network_access=true' in args
        from cplane.executors import cache_roots
        expected_roots = ['/tmp/repo/.git', *cache_roots()]
        assert args[args.index('-c', args.index('sandbox_workspace_write.network_access=true') + 1) + 1] == (
            'sandbox_workspace_write.writable_roots=' + json.dumps(expected_roots))
    else:
        assert args[args.index('--allowedTools') + 1] == 'Bash'
        assert args[args.index('--permission-mode') + 1] == 'acceptEdits'


def test_codex_exact_arguments_and_missing_cache_skipped(tmp_path, monkeypatch):
    from cplane import executors
    home = tmp_path / 'home'
    (home / '.cache/uv').mkdir(parents=True)
    monkeypatch.setattr(executors.Path, 'home', classmethod(lambda cls: home))
    run = tmp_path / 'run'
    job = {'tool': 'codex', 'run': str(run), 'repo': '/tmp/repo', 'model': 'model',
           'prompt': '-literal prompt', 'resume': 'session'}
    assert command(job) == [
        'codex', 'exec', '-m', 'model', '-c', 'sandbox_mode="workspace-write"',
        '-c', 'model_reasoning_effort="medium"',
        '-c', 'sandbox_workspace_write.network_access=true', '-c',
        'sandbox_workspace_write.writable_roots=' + json.dumps(
            ['/tmp/repo/.git', str((home / '.cache/uv').resolve())]),
        '--output-schema', str(run / 'schema.json'), '--json', '-o', str(run / 'last.json'),
        'resume', 'session', '--', '-literal prompt']


@pytest.mark.parametrize('model,effort', [('gpt-6-luna', 'low'), ('gpt-6.1-terra', 'medium')])
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
        last = tmp_path / 'last.json'
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


@pytest.mark.parametrize('remote,expected', [
    ('https://github.com/TelesforoAleix/control-plane.git', 'TelesforoAleix/control-plane'),
    ('git@github.com:TelesforoAleix/control-plane.git', 'TelesforoAleix/control-plane'),
    ('ssh://git@github.com/TelesforoAleix/control-plane.git', 'TelesforoAleix/control-plane'),
])
def test_github_repository_parses_origin(tmp_path, remote, expected):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', '-C', str(repo), 'init'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin', remote], check=True)
    assert GitHub().repository(repo) == expected


def test_github_repository_missing_origin_is_state_error(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', '-C', str(repo), 'init'], check=True, capture_output=True)
    with pytest.raises(state.StateError, match='missing GitHub origin'):
        GitHub().repository(repo)


def test_gh_arguments_include_full_repository_for_pr_calls(monkeypatch):
    calls = []
    responses = iter([
        '[{"number":12}]',  # lookup
        '[]',  # open lookup
        'https://github.com/owner/repo/pull/12',  # create
        '{"statusCheckRollup":[]}',  # checks
        '{"state":"OPEN","mergeCommit":null}',  # merge view
        '',  # merge
        '{"state":"MERGED","mergeCommit":{"oid":"abc"}}',  # merge confirmation
    ])
    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, next(responses), '')
    monkeypatch.setattr('cplane.runner.subprocess.run', fake_run)
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
    r.github.repository = Mock(side_effect=state.StateError('missing GitHub origin'))
    r.run()
    result = state.load(r.path)['slices']
    assert result[0]['attention']['kind'] == 'escalation'
    assert result[0]['attention']['body'].startswith('collect/deliver failed:')
    assert 'missing GitHub origin' in result[0]['attention']['body']
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
    weekly = {'used_percent': 100.0, 'resets_at': NOW.timestamp() + 90000}
    assert cut(r, p, NO_TIME, [primary, weekly], monkeypatch)['reset_at'] == weekly['resets_at']


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
    assert p.started[0]['prompt'] == '- begin with an option-like line\n' + (CLAUDE_PARAGRAPH if tool == 'claude' else '')
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


def test_runner_real_git_pull_does_not_commit_unchanged_state(tmp_path, slice_data, monkeypatch):
    import subprocess
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    for role in ('AUTHOR', 'COMMITTER'):
        monkeypatch.setenv(f'GIT_{role}_NAME', 'Fixture')
        monkeypatch.setenv(f'GIT_{role}_EMAIL', 'fixture@example.invalid')
    def git(*args):
        return subprocess.run(['git', *map(str, args)], capture_output=True, text=True, check=True).stdout.strip()
    remote, local = tmp_path / 'state.git', tmp_path / 'state'
    git('init', '--bare', '--initial-branch=main', remote)
    git('clone', remote, local)
    path = local / 'state.json'
    path.write_text(json.dumps({'version': 1, 'slices': [slice_data]}))
    (local / '.gitignore').write_text('*.lock\n')
    git('-C', local, 'add', '.')
    git('-C', local, 'commit', '-m', 'fixture')
    initial = git('-C', local, 'rev-parse', 'HEAD')
    git('-C', local, 'push', '-u', 'origin', 'main')
    r = Runner(path, processes=FakeProcesses(), clock=lambda: NOW, runs=tmp_path / 'runs')
    r.run()
    assert git('-C', remote, 'rev-parse', 'main') == git('-C', local, 'rev-parse', 'HEAD')
    assert git('-C', local, 'rev-parse', 'HEAD') == initial
    events = [entry['event'] for entry in json.loads(
        git('-C', remote, 'show', 'main:state.json'))['slices'][0]['log']]
    assert events == []


def test_detached_starter_closes_stdin_and_writes_config(tmp_path, monkeypatch):
    from cplane.executors import FINAL_SCHEMA, claude_settings
    popen = Mock(return_value=Mock(pid=123))
    monkeypatch.setattr('cplane.executors.subprocess.Popen', popen)
    job = {'tool': 'codex', 'run': str(tmp_path), 'repo': '/tmp/repo', 'model': 'm', 'prompt': 'brief'}
    assert Processes().start(job) == 123
    kwargs = popen.call_args.kwargs
    import subprocess
    assert kwargs['stdin'] == subprocess.DEVNULL
    assert kwargs['start_new_session'] is True
    assert kwargs['close_fds'] is True
    assert json.loads((tmp_path / 'schema.json').read_text()) == FINAL_SCHEMA
    assert json.loads((tmp_path / 'sandbox.json').read_text()) == claude_settings()
    assert (tmp_path / 'request.json').stat().st_mode & 0o777 == 0o600


def test_detached_supervisor_runs_as_importable_module(tmp_path, monkeypatch):
    import time

    run = tmp_path / 'run'
    run.mkdir()
    repo = tmp_path / 'repo'
    repo.mkdir()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    codex = bin_dir / 'codex'
    codex.write_text('#!/bin/sh\nexit 0\n')
    codex.chmod(0o755)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
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


def test_uninstall_cli_without_state(monkeypatch):
    uninstall = Mock()
    monkeypatch.setattr(agent, 'uninstall', uninstall)
    monkeypatch.delenv('CPLANE_STATE', raising=False)
    assert main(['uninstall-agent']) == 0
    uninstall.assert_called_once()


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
    assert p.started[-1]['prompt'] == (
        'Your turn was cut by the usage limit. Your uncommitted work is in your working tree. '
        'Continue the slice.')
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
    assert p.started[-1]['prompt'] == 'answer'


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
    gh.call = Mock(side_effect=['{"state":"OPEN","mergeCommit":null}', '', '{"state":"MERGED","mergeCommit":{"oid":"sha"}}'])
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
    assert p.started[0]['prompt'].encode('utf-8') == raw


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


@pytest.mark.parametrize('status,stop,expected', [
    ('red', False, 'escalation'),
    ('pending', False, None),
    ('green', True, 'merge'),
    ('green', False, None),
])
@pytest.mark.parametrize('source', ['branch', 'url', 'number'])
def test_codex_waiting_ci_outcomes(setup, status, stop, expected, source):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=stop))
    r.run()
    if source == 'branch':
        gh.find_pr.return_value = 12
    body = {'branch': 'Waiting for CI', 'url': 'CI: https://github.com/example/repo/pull/12',
            'number': 'Waiting on PR #12'}[source]
    p.finish('waiting', body)
    r.run()
    assert item(r)['pr'] == 12
    assert item(r)['attention'] is None
    assert r.jobs['voice/W1']['phase'] == 'pr'
    gh.checks.assert_not_called()
    gh.is_open.assert_called_once_with('example/repo', 12)
    gh.checks.return_value = status, 'test' if status == 'red' else ''
    r.run()
    a = item(r)['attention']
    assert (a['kind'] if a else None) == expected
    if expected == 'escalation':
        assert item(r)['state'] == 'escalated'
        assert a['body'] == 'failing check: test'
    elif expected == 'merge':
        assert a['body'] == 'Approve PR #12'
        assert not a['approved']
        assert 'review' not in a
    if status == 'green' and not stop:
        assert len(p.started) == 2
        assert p.started[-1]['prompt'] == 'CI is green on PR #12; merge it and continue.'
        assert p.started[-1]['resume'] == 'session-1'
        assert p.started[-1]['tool'] == 'codex'
    else:
        assert len(p.started) == 1
    # A further pass neither resumes twice nor replaces an existing attention.
    r.run()
    assert item(r)['attention'] == a
    assert len(p.started) == (2 if status == 'green' and not stop else 1)
    gh.merge.assert_not_called()
    gh.open.assert_not_called()


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


@pytest.mark.parametrize('stop,status', [(True, 'green'), (False, 'red'), (False, 'pending'), (False, 'green')])
def test_codex_ci_watch_recovers_state_save_failures(setup, monkeypatch, stop, status):
    r, p, gh = setup
    edit(r, lambda s: s.update(stop_before_merge=stop))
    r.run()
    gh.find_pr.return_value = 12
    p.finish('waiting', 'Waiting on CI')
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
    p.finish('waiting', 'CI pending')
    r.run()
    gh.checks.return_value = 'green', ''
    r.codex_reader = lambda: 100
    r.run()
    assert len(p.started) == 1
    assert r.jobs['voice/W1']['phase'] == 'pr'
    assert item(r)['attention'] is None
    r.codex_reader = lambda: 0
    r.run()
    r.run()
    assert len(p.started) == 2


def test_codex_ci_merge_attention_review_approval(setup):
    r, p, gh = setup
    r.run()
    gh.find_pr.return_value = 12
    p.finish('waiting', 'CI pending')
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
    assert p.started[-1]['prompt'] == 'The owner approves the merge.'
    gh.merge.assert_not_called()


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
    assert p.started[-1]['prompt'] == 'node step done'
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


def test_pull_uses_autostash(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr('cplane.runner.state.git', lambda root, *args: calls.append(args))
    path = tmp_path / 'slices.json'
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    Git().pull(path)
    assert calls == [('pull', '--rebase', '--autostash')]


def test_pull_with_unstaged_outbox_line(tmp_path):
    def g(cwd, *a):
        subprocess.run(['git', '-C', str(cwd), *a], check=True, capture_output=True)
    remote, local = tmp_path / 'remote.git', tmp_path / 'local'
    g(tmp_path, 'init', '-q', '--bare', str(remote))
    g(tmp_path, 'clone', '-q', str(remote), str(local))
    for key, value in (('user.email', 'a@example.com'), ('user.name', 'a')):
        g(local, 'config', key, value)
    (local / 'slices.json.outbox.jsonl').write_text('{}\n')
    (local / 'slices.json').write_text('{}\n')
    g(local, 'add', '.')
    g(local, 'commit', '-qm', 'one')
    g(local, 'push', '-q', 'origin', 'HEAD')
    (local / 'slices.json.outbox.jsonl').write_text('{}\n{}\n')
    Git().pull(local / 'slices.json')
    assert (local / 'slices.json.outbox.jsonl').read_text() == '{}\n{}\n'


def test_failing_pull_still_raises_and_never_launches_autostash(setup):
    r, p, _ = setup
    r.git.pull.side_effect = state.StateError('pull failed')
    with pytest.raises(state.StateError):
        r.run()
    assert not p.started


@pytest.mark.parametrize('model,expected', [
    ('opus', 'opus'), ('sonnet', 'sonnet'), ('gpt-6.1-sol', 'opus'),
    ('Some-SOL', 'opus'), ('other', 'sonnet'), ('Opus', 'sonnet'),
])
def test_claude_model_mapping(setup, model, expected):
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
