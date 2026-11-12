"""Synthetic deny-list fixtures; never read the node's private list."""
import os
import subprocess
from unittest.mock import Mock

import pytest

from cplane import deny, fence
from cplane.runner import Runner


@pytest.fixture
def deny_list(tmp_path, monkeypatch):
    path = tmp_path / 'deny-list'
    path.write_text('# ignored\n\nPrivate Example\n')
    path.chmod(0o600)
    monkeypatch.setattr(deny, 'DENY_LIST', path)
    monkeypatch.setattr(deny, 'ROOT_UID', os.getuid())
    return path


@pytest.mark.parametrize(('field', 'location'), [
    ('branch', 'branch name'), ('title', 'PR title'), ('body', 'PR body')])
def test_metadata_matches_substrings_without_disclosing_content(deny_list, field, location):
    with pytest.raises(deny.Denied) as caught:
        deny.Check().request({field: 'prefix PRIVATE EXAMPLE suffix'})
    assert str(caught.value) == 'private-content check: ' + location
    assert 'private example' not in str(caught.value).casefold()


def test_canary_is_checked_with_an_empty_list(deny_list):
    deny_list.write_text('')
    with pytest.raises(deny.Denied, match='PR body'):
        deny.Check().request({'body': deny.CANARY.lower()})


def test_blank_and_comment_lines_are_ignored_and_spaces_are_literal(deny_list):
    deny_list.write_text('\n  \n# ignored\n spaced \n')
    check = deny.Check()
    check.request({'title': '# ignored spaced'})
    with pytest.raises(deny.Denied):
        check.request({'title': 'a spaced value'})


@pytest.mark.parametrize('kind', ['missing', 'permissions', 'owner', 'link', 'directory', 'fifo', 'encoding'])
def test_list_must_be_readable_root_owned_regular_0600(deny_list, monkeypatch, kind):
    if kind == 'missing':
        deny_list.unlink()
    elif kind == 'permissions':
        deny_list.chmod(0o644)
    elif kind == 'owner':
        monkeypatch.setattr(deny, 'ROOT_UID', os.getuid() + 1)
    elif kind == 'link':
        target = deny_list.with_name('target')
        deny_list.rename(target)
        deny_list.symlink_to(target)
    elif kind == 'directory':
        deny_list.unlink()
        deny_list.mkdir()
    elif kind == 'fifo':
        deny_list.unlink()
        os.mkfifo(deny_list)
    elif kind == 'encoding':
        deny_list.write_bytes(b'\xff')
    with pytest.raises(deny.Denied, match='deny-list unavailable or invalid'):
        deny.Check()


@pytest.mark.parametrize(('reply', 'expected'), [
    ('{"private": true}', False), ('{"private": false}', True),
    ('{}', True), ('{"private": "true"}', True), ('invalid', True), ('[]', True)])
def test_visibility_uses_runner_token_and_caches_one_pass(monkeypatch, reply, expected):
    environment = Mock(return_value={'GH_TOKEN': 'synthetic-token'})
    monkeypatch.setattr(fence, 'github_environment', environment)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, reply, ''))
    monkeypatch.setattr(subprocess, 'run', run)
    adapter = fence.Fence()
    assert adapter.is_public('example/repo') is expected
    assert adapter.is_public('example/repo') is expected
    assert run.call_count == 1
    environment.assert_called_once_with(['example/repo'])
    assert run.call_args.args[0] == ['gh', 'api', 'repos/example/repo']
    assert run.call_args.kwargs['env'] == {'GH_TOKEN': 'synthetic-token'}
    adapter.begin_pass()
    assert adapter.is_public('example/repo') is expected
    assert run.call_count == 2


@pytest.mark.parametrize('failure', ['network', 'auth', 'refused'])
def test_unknown_visibility_is_public(monkeypatch, failure):
    monkeypatch.setattr(fence, 'github_environment', Mock(return_value={}))
    run = Mock(return_value=subprocess.CompletedProcess([], 1, '', 'private details'))
    if failure == 'network':
        run.side_effect = OSError('private details')
    elif failure == 'auth':
        monkeypatch.setattr(fence, 'github_environment', Mock(side_effect=RuntimeError('private details')))
    monkeypatch.setattr(subprocess, 'run', run)
    assert fence.Fence().is_public('example/repo') is True


def test_pr_send_checks_metadata_before_any_github_write(deny_list, tmp_path):
    adapter = fence.Fence()
    adapter.is_public = Mock(return_value=True)
    runner = Runner(tmp_path / 'state.json', github=Mock())
    runner.fence = adapter
    with pytest.raises(deny.Denied, match='PR body'):
        runner.open_pr('example/repo', {'branch': 'slice/test', 'title': 'title', 'body': 'PRIVATE EXAMPLE'})
    runner.github.open.assert_not_called()


@pytest.mark.parametrize(('owner', 'mode', 'accepted'), [
    (0, 0o600, True), (21000, 0o400, True), (21000, 0o600, False),
    (21000, 0o440, False), (21000, 0o444, False), (21001, 0o400, False),
    (0, 0o400, False), (0, 0o640, False), (21000, 0o1400, False),
])
def test_deny_owner_mode_contract(deny_list, monkeypatch, owner, mode, accepted):
    from types import SimpleNamespace
    monkeypatch.setattr(deny, 'ROOT_UID', 0)
    monkeypatch.setattr(deny.os, 'geteuid', lambda: 21000)
    monkeypatch.setattr(deny.os, 'fstat', lambda fd: SimpleNamespace(
        st_uid=owner, st_mode=0o100000 | mode))
    if accepted:
        assert deny.patterns() == (deny.CANARY.casefold(), 'private example')
    else:
        with pytest.raises(deny.Denied, match='deny-list unavailable or invalid'):
            deny.patterns()


@pytest.mark.parametrize('override', [False, True])
def test_deny_path_setting(deny_list, monkeypatch, override):
    configured = deny_list.with_name('mounted-list')
    configured.write_text('Mounted Synthetic\n')
    configured.chmod(0o400)
    monkeypatch.delenv('CPLANE_DENY_LIST', raising=False)
    if override:
        monkeypatch.setenv('CPLANE_DENY_LIST', str(configured))
    assert deny.patterns() == (deny.CANARY.casefold(),
                              'mounted synthetic' if override else 'private example')


def test_default_deny_path():
    assert str(deny.DENY_LIST) == '/etc/homelab/deny-list'


def test_override_deny_link_refused(deny_list, monkeypatch):
    deny_list.chmod(0o400)
    link = deny_list.with_name('link')
    link.symlink_to(deny_list)
    monkeypatch.setenv('CPLANE_DENY_LIST', str(link))
    with pytest.raises(deny.Denied, match='deny-list unavailable or invalid'):
        deny.patterns()
