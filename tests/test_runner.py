import json
import os
import subprocess
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from cplane import state
from cplane.cli import main
from cplane.executors import Processes, command
from cplane.runner import GitHub, Runner
from cplane.text_bounds import TAIL_LIMIT

NOW = datetime(2026, 10, 16, 10, tzinfo=timezone.utc)


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


def test_show_run_folder_and_final(tmp_path, make_state, monkeypatch, capsys):
    path = make_state()
    runs = tmp_path / 'runs'
    monkeypatch.setenv('CPLANE_RUNS', str(runs))
    import hashlib

    from cplane.cli import main as cli_main
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


WEEKLY = ('You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit '
          'https://chatgpt.com/settings/usage to purchase more credits or try again at Nov 6th, 2026 10:57 AM.')
FIVE_HOUR = WEEKLY.split(' try again')[0] + ' try again at 2:56 PM.'
NO_TIME = 'You’ve hit your usage limit. Upgrade to Pro.'


def test_detached_starter_closes_stdin_and_writes_config(tmp_path, monkeypatch):
    from cplane.executors import FINAL_SCHEMA
    popen = Mock(return_value=Mock(pid=123))
    monkeypatch.setattr('cplane.executors.os.chown', lambda *args: None)
    # This fixture substitutes direct ownership; real privilege checks have separate coverage.
    monkeypatch.setattr('cplane.fence.require_ownership_support', lambda: None)
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
    # This fixture substitutes direct ownership; real privilege checks have separate coverage.
    monkeypatch.setattr('cplane.fence.require_ownership_support', lambda: None)
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


def test_github_open_and_merge_are_recoverable():
    gh = GitHub()
    gh.call = Mock(return_value='[{"number":12}]')
    request = {'branch': 'feat/example', 'title': 'title', 'body': 'body'}
    assert gh.open('owner/repo', request) == 12
    assert gh.call.call_args_list[1].args == ('owner/repo', 'pr', 'edit', '12', '--title', 'title', '--body', 'body')
    gh.call = Mock(side_effect=['[]', 'https://github.com/owner/repo/pull/12'])
    assert gh.open('owner/repo', request) == 12
    gh.call = Mock(return_value='{"state":"MERGED","mergeCommit":{"oid":"sha"}}')
    assert gh.merge('owner/repo', 12) == 'sha'
    assert gh.call.call_count == 1
    gh.call = Mock(side_effect=['{"state":"OPEN","title":"Example","mergeCommit":null}', '', '{"state":"MERGED","mergeCommit":{"oid":"sha"}}'])
    assert gh.merge('owner/repo', 12) == 'sha'
    assert gh.call.call_count == 3


def test_existing_pr_edit_allows_later_merge_check():
    from cplane.runner import check_merge_info
    gh = GitHub()
    info = {'state': 'OPEN', 'title': 'Old', 'body': 'DO NOT MERGE'}

    def call(repo, *args):
        if args[:2] == ('pr', 'list'):
            return '[{"number":12}]'
        assert args == ('pr', 'edit', '12', '--title', 'New', '--body', 'Ready')
        info.update(title=args[4], body=args[6])
        return ''

    gh.call = Mock(side_effect=call)
    assert gh.open('owner/repo', {'branch': 'feature', 'title': 'New', 'body': 'Ready'}) == 12
    check_merge_info(info)


def test_existing_pr_edit_failure_is_identified():
    gh = GitHub()
    gh.call = Mock(side_effect=['[{"number":12}]', state.StateError('gh operation failed')])
    with pytest.raises(state.StateError, match='PR edit failed'):
        gh.open('owner/repo', {'branch': 'feature', 'title': 'New', 'body': 'Ready'})


def test_live_process_group_reserves_capacity_after_supervisor_dies(tmp_path, monkeypatch):
    monkeypatch.setattr('cplane.executors.os.killpg', Mock())
    job = {'tool': 'codex', 'run': str(tmp_path), 'started_ns': 0, 'pid': 123}
    assert Processes().poll(job)[0] is False


def test_supervisor_writes_exit_marker_and_closes_executor_stdin(tmp_path, monkeypatch):
    import subprocess

    from cplane.executors import supervise
    job = {'tool': 'codex', 'run': str(tmp_path), 'repo': str(tmp_path), 'model': 'model', 'prompt': 'prompt'}
    (tmp_path / 'request.json').write_text(json.dumps(job))
    run = Mock(return_value=subprocess.CompletedProcess([], 7))
    monkeypatch.setattr('cplane.executors.subprocess.run', run)
    supervise(tmp_path)
    assert run.call_args.kwargs['stdin'] == subprocess.DEVNULL
    assert run.call_args.kwargs['cwd'] == str(tmp_path)
    assert json.loads((tmp_path / 'exit.json').read_text())['code'] == 7


@pytest.mark.parametrize('pr_state,expected', [('OPEN', True), ('CLOSED', False), ('MERGED', False)])
def test_github_is_open(pr_state, expected):
    gh = GitHub()
    gh.call = Mock(return_value=json.dumps({'state': pr_state}))
    assert gh.is_open('owner/repo', 12) is expected
    gh.call.assert_called_once_with('owner/repo', 'pr', 'view', '12', '--json', 'state')


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


def accept_with_running_job(r, p):
    r.run()
    edit(r, lambda s: s.update(state='accepted'))


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


def test_github_update_branch_polls_for_new_head(monkeypatch):
    gh = GitHub()
    gh.call = Mock(return_value='')
    gh.merge_info = Mock(side_effect=[{'headRefOid': 'old'}, {'headRefOid': 'old'},
                                      {'headRefOid': 'new'}])
    sleep = Mock()
    monkeypatch.setattr('cplane.runner.time.sleep', sleep)
    assert gh.update_branch('example/repo', 12, 'old') == 'new'
    gh.call.assert_called_once_with('example/repo', 'api', '-X', 'PUT',
                                    'repos/example/repo/pulls/12/update-branch',
                                    '-f', 'expected_head_sha=old')
    assert gh.merge_info.call_count == 3
    assert sleep.call_count == 2
    sleep.assert_called_with(5)


def test_github_update_branch_times_out(monkeypatch):
    gh = GitHub()
    gh.call = Mock(return_value='')
    gh.merge_info = Mock(return_value={'headRefOid': 'old'})
    clock = [0]
    monkeypatch.setattr('cplane.runner.time.monotonic', lambda: clock[0])
    monkeypatch.setattr('cplane.runner.time.sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    with pytest.raises(state.StateError, match='^gh operation failed$'):
        gh.update_branch('example/repo', 12, 'old')
    assert clock[0] == 120
    assert gh.merge_info.call_count == 25


@pytest.mark.parametrize(('error', 'exception'), [
    ('HTTP 422: merge conflict', 'conflict'),
    ('HTTP 422: expected head does not match', 'failure'),
    ('HTTP 500: merge conflict', 'failure'),
])
def test_github_update_branch_classifies_failures(monkeypatch, error, exception):
    from cplane.runner import BranchConflict
    monkeypatch.setattr('cplane.fence.github_environment', lambda _: {})
    run = Mock(return_value=subprocess.CompletedProcess([], 1, '', error))
    monkeypatch.setattr(subprocess, 'run', run)
    expected_type = BranchConflict if exception == 'conflict' else state.StateError
    message = 'PR conflicts with main; needs a new slice from main' if exception == 'conflict' else 'gh operation failed'
    with pytest.raises(expected_type, match='^' + message + '$'):
        GitHub().update_branch('example/repo', 12, 'old')
    assert run.call_count == 1
    assert run.call_args.args[0] == ['gh', 'api', '-X', 'PUT',
                                     'repos/example/repo/pulls/12/update-branch',
                                     '-f', 'expected_head_sha=old']


@pytest.mark.parametrize('reviews,expected', [
    ([(2, 'TelesforoAleix', 'APPROVED', 'tip')], 2),
    ([(2, 'TelesforoAleix', 'APPROVED', 'old')], None),
    ([(9, 'TelesforoAleix', 'CHANGES_REQUESTED', 'old'),
      (2, 'TelesforoAleix', 'APPROVED', 'tip')], None),
    ([(2, 'TelesforoAleix', 'APPROVED', 'tip'),
      (9, 'TelesforoAleix', 'DISMISSED', 'tip')], None),
    ([(2, 'other', 'APPROVED', 'tip')], None),
    ([(2, 'TelesforoAleix', 'APPROVED', 'tip'),
      (9, 'other', 'CHANGES_REQUESTED', 'tip'),
      (10, 'TelesforoAleix', 'COMMENTED', 'old')], 2),
    ([], None),
])
def test_owner_github_approval_uses_newest_deciding_review_across_pages(reviews, expected):
    gh = GitHub()
    records = [{'id': id, 'user': {'login': login}, 'state': state, 'commit_id': tip}
               for id, login, state, tip in reviews]
    gh.call = Mock(return_value=json.dumps([records[:1], records[1:]]))
    assert gh.owner_approval('example/repo', 12, 'tip') == expected
    gh.call.assert_called_once_with(
        'example/repo', 'api', 'repos/example/repo/pulls/12/reviews?per_page=100',
        '--paginate', '--slurp')


# Shared API fixtures for planner, scheduling and installation integration tests.
from test_run_api_runner import NOW, edit, pr_reply, setup  # noqa: F401,F811


def item(runner):
    return state.load(runner.path)['slices'][0]


def assert_prompt(job, text):
    goal = job.get('prompt') or job['requests'][job['active']]['request']['work']['goal']
    assert goal.startswith(text)


# --- review kept when a repair changes only tests ---

OLD, NEW = 'a' * 40, 'b' * 40


def review_fixture(files):
    runner = Runner.__new__(Runner)
    runner.github = Mock()
    if isinstance(files, Exception):
        runner.github.compare_files.side_effect = files
    else:
        runner.github.compare_files.return_value = files
    runner.log = lambda item, event, *a, **k: item['log'].append({'event': event})
    runner.cancel_entry = Mock()
    runner.clear_review_attention = Mock()
    item = {'repo': 'example/repo', 'log': []}
    entry = {'request': {'base_commit': OLD}}
    job = {'tip': OLD, 'review_tip': OLD, 'pr_review': 'review-1', 'requests': {'review-1': entry},
           'review_verdict': 'fix', 'review_findings': ['x'], 'review_requested_at': 1}
    return runner, item, job, entry


def f(name, **extra):
    return {'filename': name, 'status': 'modified', **extra}


@pytest.mark.parametrize('names', [
    ['tests/test_a.py', 'tests/data/x.json'], ['pkg/test_a.py'], ['pkg/a_test.py'],
    ['web/a.test.js'], ['web/a.test.jsx'], ['web/a.test.ts'], ['web/a.test.tsx'],
])
def test_tests_only_repair_keeps_review(names):
    runner, item, job, entry = review_fixture([f(n) for n in names] + [{'filename': 'tests/gone.py', 'status': 'removed'}])
    runner.review_head(item, job, NEW)
    runner.github.compare_files.assert_called_once_with('example/repo', OLD, NEW)
    assert job['tip'] == job['review_tip'] == NEW
    assert job['pr_review'] == 'review-1'
    assert job['review_verdict'] == 'fix' and job['review_findings'] == ['x']
    runner.cancel_entry.assert_not_called()
    assert [log['event'] for log in item['log']] == [f'review: kept review-1 on {NEW} (tests only)']
    runner.review_head(item, job, NEW)
    assert len(item['log']) == 1


@pytest.mark.parametrize('result', [
    [f('tests/test_a.py'), f('cplane/runner.py')],
    [f('src/testing.py')],
    [f('contest/a.py')],
    [f('tests/test_a.py', status='renamed', previous_filename='tests/test_b.py')],
    [f('tests/test_a.py', status='renamed', previous_filename='cplane/x.py')],
    [{'filename': 'cplane/x.py', 'status': 'removed'}],
    [f('tests/test_a.py')] * 300,
    [],
    RuntimeError('compare failed'),
])
def test_other_moves_and_failed_compare_retire_review(result):
    runner, item, job, entry = review_fixture(result)
    runner.review_head(item, job, NEW)
    assert job['tip'] == NEW and job['review_tip'] == OLD
    for key in ('pr_review', 'review_verdict', 'review_findings', 'review_requested_at'):
        assert key not in job
    assert entry['cancel_pending'] is True
    runner.cancel_entry.assert_called_once_with(job, entry)
    assert item['log'] == [{'event': f'review: superseded review-1 on {OLD} by {NEW}'}]
