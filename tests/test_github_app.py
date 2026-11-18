"""Synthetic App keys and HTTP responses; no GitHub credential or network."""
import base64
from datetime import datetime, timezone
import io
import json
import os
import subprocess
import urllib.error
from unittest.mock import Mock

import pytest

from cplane import github_app as app, state

NOW = 1800000000
REPOS = ('example/one', 'example/two')


@pytest.fixture
def key(tmp_path, monkeypatch):
    monkeypatch.delenv('CPLANE_GITHUB_READ_ONLY', raising=False)
    monkeypatch.setattr(app, '_TOKENS', {})
    path = tmp_path / 'fake-app.pem'
    subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt',
                    'rsa_keygen_bits:2048', '-out', str(path)], check=True, capture_output=True)
    path.chmod(0o600)
    monkeypatch.setattr(app, 'KEY', path)
    monkeypatch.setattr(app, 'ROOT_UID', os.getuid())
    monkeypatch.setenv('CPLANE_GITHUB_APP_ID', '123')
    monkeypatch.setenv('CPLANE_GITHUB_INSTALLATION_ID', '456')
    monkeypatch.setattr(app.time, 'time', lambda: NOW)
    return path


def unbase(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def test_jwt_claims_and_real_rs256_signature(key, tmp_path):
    with key.open('rb') as source:
        assertion = app.jwt(source.fileno(), '123', NOW)
    header, payload, signature = assertion.split('.')
    assert json.loads(unbase(header)) == {'alg': 'RS256', 'typ': 'JWT'}
    assert json.loads(unbase(payload)) == {'iat': NOW - 60, 'exp': NOW + 540, 'iss': '123'}
    public = subprocess.run(['openssl', 'pkey', '-in', str(key), '-pubout'],
                            capture_output=True, check=True).stdout
    (tmp_path / 'public.pem').write_bytes(public)
    (tmp_path / 'signature').write_bytes(unbase(signature))
    result = subprocess.run(['openssl', 'dgst', '-sha256', '-verify', str(tmp_path / 'public.pem'),
                             '-signature', str(tmp_path / 'signature')],
                            input=(header + '.' + payload).encode(), capture_output=True)
    assert result.returncode == 0


def response(token='synthetic-token', expiry=NOW + 3600, repos=REPOS, permissions=None):
    return io.BytesIO(json.dumps(dict(token=token,
        expires_at=datetime.fromtimestamp(expiry, timezone.utc).isoformat(),
        repositories=[{'full_name': repo} for repo in repos], permissions=permissions)).encode())


def test_token_request_only_given_repositories(key, monkeypatch):
    opener = Mock()
    opener.open.return_value = response()
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    assert app.installation_token(['example/two', 'Example/one', 'example/one']) == 'synthetic-token'
    request = opener.open.call_args.args[0]
    assert request.full_url == 'https://api.github.com/app/installations/456/access_tokens'
    assert request.method == 'POST'
    assert json.loads(request.data) == {'repositories': ['one', 'two']}
    assert request.get_header('Authorization').startswith('Bearer ')
    assert opener.open.call_args.kwargs == {'timeout': 30}


def test_read_only_request_is_scoped_to_repository_and_contents(key, monkeypatch):
    monkeypatch.setenv('CPLANE_GITHUB_READ_ONLY', '1')
    opener = Mock()
    opener.open.return_value = response(
        repos=['example/one'], permissions={'contents': 'read', 'metadata': 'read'})
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    assert app.installation_token(['example/one']) == 'synthetic-token'
    assert json.loads(opener.open.call_args.args[0].data) == {
        'repositories': ['one'], 'permissions': {'contents': 'read'}}


@pytest.mark.parametrize('permissions', [
    {'contents': 'read', 'metadata': 'read'}, {'contents': 'read'}])
def test_read_only_accepts_contents_with_optional_metadata(key, monkeypatch, permissions):
    monkeypatch.setenv('CPLANE_GITHUB_READ_ONLY', '1')
    opener = Mock()
    opener.open.return_value = response(permissions=permissions)
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    assert app.installation_token(REPOS) == 'synthetic-token'


@pytest.mark.parametrize('permissions', [None, {}, {'contents': 'write'},
    {'contents': 'write', 'metadata': 'read'},
    {'contents': 'read', 'pull_requests': 'write'},
    {'contents': 'read', 'metadata': 'read', 'pull_requests': 'write'},
    {'contents': 'read', 'issues': 'read'}, {'metadata': 'read'},
    {'contents': 'read', 'metadata': 'write'}, {'contents': 'read', 'metadata': None},
    ['contents'], 'read'])
def test_read_only_refuses_any_other_permissions(key, monkeypatch, permissions):
    monkeypatch.setenv('CPLANE_GITHUB_READ_ONLY', '1')
    opener = Mock()
    opener.open.return_value = response(permissions=permissions)
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    with pytest.raises(state.StateError, match='response is invalid'):
        app.installation_token(REPOS)
    assert not app._TOKENS


def test_read_only_and_write_caches_are_separate(key, monkeypatch):
    opener = Mock()
    opener.open.side_effect = [
        response('write'), response('read', permissions={'contents': 'read', 'metadata': 'read'})]
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    assert app.installation_token(REPOS) == 'write'
    monkeypatch.setenv('CPLANE_GITHUB_READ_ONLY', '1')
    assert app.installation_token(REPOS) == 'read'
    assert app.installation_token(REPOS) == 'read'
    monkeypatch.setenv('CPLANE_GITHUB_READ_ONLY', '0')
    assert app.installation_token(REPOS) == 'write'
    assert opener.open.call_count == 2
    assert len(app._TOKENS) == 2


def test_direct_mint_also_honors_process_read_only_mode(key, monkeypatch):
    monkeypatch.setenv('CPLANE_GITHUB_READ_ONLY', '1')
    opener = Mock()
    opener.open.return_value = response(permissions={'contents': 'read', 'metadata': 'read'})
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    with key.open('rb') as source:
        assert app.mint(source.fileno(), '123', '456', REPOS, NOW)[0] == 'synthetic-token'
    assert json.loads(opener.open.call_args.args[0].data)['permissions'] == {'contents': 'read'}


@pytest.mark.parametrize('kind', ['owner', 'mode', 'directory', 'fifo', 'symlink'])
def test_key_refuses_wrong_owner_mode_or_type(key, monkeypatch, kind):
    if kind == 'owner':
        monkeypatch.setattr(app, 'ROOT_UID', os.getuid() + 1)
    elif kind == 'mode':
        key.chmod(0o640)
    else:
        key.unlink()
        if kind == 'directory':
            key.mkdir(mode=0o600)
        elif kind == 'fifo':
            os.mkfifo(key, 0o600)
        else:
            key.symlink_to(key.parent / 'missing')
    mint = Mock()
    monkeypatch.setattr(app, 'mint', mint)
    with pytest.raises(state.StateError):
        app.installation_token(REPOS)
    mint.assert_not_called()


@pytest.mark.parametrize('repos', [[], ['bad'], ['x/..'], ['x/one', 'y/two']])
def test_refuse_empty_invalid_or_mixed_owner_scope(key, monkeypatch, repos):
    mint = Mock()
    monkeypatch.setattr(app, 'mint', mint)
    with pytest.raises(state.StateError):
        app.installation_token(repos)
    mint.assert_not_called()


def test_failures_do_not_expose_credentials(key, monkeypatch, capsys):
    monkeypatch.setattr(app, 'mint', Mock(side_effect=ValueError('synthetic-secret')))
    with pytest.raises(state.StateError) as error:
        app.installation_token(REPOS)
    assert str(error.value) == 'GitHub App authentication failed'
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('status', [401, 403, 404, 422])
def test_refused_token_request_names_repository_without_http_details(key, monkeypatch, capsys, status):
    opener = Mock()
    opener.open.side_effect = urllib.error.HTTPError(
        'https://api.github.com/synthetic-secret', status, 'synthetic-secret',
        {'Authorization': 'synthetic-secret'}, io.BytesIO(b'synthetic-secret'))
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    with pytest.raises(state.StateError) as error:
        app.installation_token(['example/uninstalled'])
    assert str(error.value) == (
        'GitHub App token request refused for example/uninstalled; '
        'the App may not be installed there')
    assert error.value.__suppress_context__
    assert not app._TOKENS
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('changes', [dict(token='bad token'), dict(expiry=NOW),
                                    dict(repos=['other/one', 'other/two'])])
def test_refuse_invalid_response(key, monkeypatch, changes):
    opener = Mock()
    opener.open.return_value = response(**changes)
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    with pytest.raises(state.StateError, match='response is invalid'):
        app.installation_token(REPOS)


def test_token_reused_until_five_minutes_remain(key, monkeypatch):
    opener = Mock()
    opener.open.side_effect = [response(), response('renewed-token', NOW + 6900)]
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    assert app.installation_token(REPOS) == 'synthetic-token'
    for elapsed in (0, 60, 3000, 3299):
        monkeypatch.setattr(app.time, 'time', lambda: NOW + elapsed)
        assert app.installation_token(reversed(REPOS)) == 'synthetic-token'
    assert opener.open.call_count == 1
    monkeypatch.setattr(app.time, 'time', lambda: NOW + 3300)
    assert app.installation_token(REPOS) == 'renewed-token'
    assert app.installation_token(REPOS) == 'renewed-token'
    assert opener.open.call_count == 2


@pytest.mark.parametrize('elapsed', [3301, 3601])
def test_renew_after_idle_time_near_or_past_expiry(key, monkeypatch, elapsed):
    mint = Mock(side_effect=[('first', NOW + 3600), ('renewed', NOW + elapsed + 3600)])
    monkeypatch.setattr(app, 'mint', mint)
    assert app.installation_token(REPOS) == 'first'
    monkeypatch.setattr(app.time, 'time', lambda: NOW + elapsed)
    assert app.installation_token(REPOS) == 'renewed'
    assert mint.call_count == 2


def test_cache_does_not_expand_or_mix_repository_scopes(key, monkeypatch):
    mint = Mock(side_effect=[('both-repos', NOW + 3600), ('one-repo', NOW + 3600)])
    monkeypatch.setattr(app, 'mint', mint)
    assert app.installation_token(REPOS) == 'both-repos'
    assert app.installation_token(['example/one']) == 'one-repo'
    assert app.installation_token(REPOS) == 'both-repos'
    assert mint.call_count == 2
    assert mint.call_args.args[3] == ('example/one',)


@pytest.mark.parametrize('changed', ['app_id', 'installation_id', 'key', 'process'])
def test_changed_auth_context_mints_separately(key, monkeypatch, changed):
    mint = Mock(side_effect=[('first', NOW + 3600), ('new-context', NOW + 3600)])
    monkeypatch.setattr(app, 'mint', mint)
    assert app.installation_token(REPOS) == 'first'
    if changed == 'app_id':
        monkeypatch.setenv('CPLANE_GITHUB_APP_ID', '789')
    elif changed == 'installation_id':
        monkeypatch.setenv('CPLANE_GITHUB_INSTALLATION_ID', '789')
    elif changed == 'key':
        replacement = key.with_suffix('.replacement')
        replacement.write_bytes(key.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(key)
    else:
        pid = os.getpid()
        monkeypatch.setattr(app.os, 'getpid', lambda: pid + 1)
    assert app.installation_token(REPOS) == 'new-context'
    assert mint.call_count == 2


def test_key_check_still_applies_to_cached_token(key, monkeypatch):
    mint = Mock(return_value=('first', NOW + 3600))
    monkeypatch.setattr(app, 'mint', mint)
    assert app.installation_token(REPOS) == 'first'
    key.chmod(0o644)
    with pytest.raises(state.StateError, match='mode 0600'):
        app.installation_token(REPOS)
    assert mint.call_count == 1


def test_failed_renewal_does_not_return_old_token_or_cache_error(key, monkeypatch, capsys):
    mint = Mock(side_effect=[('first', NOW + 3600), ValueError('synthetic-secret'),
                             ('renewed', NOW + 6900)])
    monkeypatch.setattr(app, 'mint', mint)
    assert app.installation_token(REPOS) == 'first'
    monkeypatch.setattr(app.time, 'time', lambda: NOW + 3300)
    with pytest.raises(state.StateError, match='GitHub App authentication failed') as error:
        app.installation_token(REPOS)
    assert 'synthetic-secret' not in str(error.value)
    assert app.installation_token(REPOS) == 'renewed'
    assert mint.call_count == 3
    assert capsys.readouterr() == ('', '')


def test_concurrent_calls_share_one_mint(key, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    mint = Mock(return_value=('shared', NOW + 3600))
    monkeypatch.setattr(app, 'mint', mint)
    barrier = Barrier(4)

    def fetch(_):
        barrier.wait(timeout=10)
        return app.installation_token(REPOS)

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(fetch, range(4))) == ['shared'] * 4
    mint.assert_called_once()


@pytest.mark.parametrize(('owner', 'mode', 'accepted'), [
    (0, 0o600, True), (21000, 0o400, True), (21000, 0o600, False),
    (21000, 0o440, False), (21000, 0o444, False), (21001, 0o400, False),
    (0, 0o400, False), (0, 0o640, False), (21000, 0o1400, False),
])
def test_key_owner_mode_contract(key, monkeypatch, owner, mode, accepted):
    from types import SimpleNamespace
    info = os.stat(key)
    monkeypatch.setattr(app, 'ROOT_UID', 0)
    monkeypatch.setattr(app.os, 'geteuid', lambda: 21000)
    monkeypatch.setattr(app.os, 'fstat', lambda fd: SimpleNamespace(
        st_uid=owner, st_mode=0o100000 | mode, st_dev=info.st_dev, st_ino=info.st_ino,
        st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns))
    mint = Mock(return_value=('synthetic', NOW + 3600))
    monkeypatch.setattr(app, 'mint', mint)
    if accepted:
        assert app.installation_token(REPOS) == 'synthetic'
    else:
        with pytest.raises(state.StateError, match='root-owned regular file with mode 0600'):
            app.installation_token(REPOS)
        mint.assert_not_called()


@pytest.mark.parametrize('override', [False, True])
def test_key_path_setting(key, monkeypatch, override):
    configured = key.with_name('mounted-key')
    configured.write_bytes(key.read_bytes())
    configured.chmod(0o400)
    monkeypatch.delenv('CPLANE_GITHUB_APP_KEY', raising=False)
    if override:
        monkeypatch.setenv('CPLANE_GITHUB_APP_KEY', str(configured))
    real_open = os.open
    opened = []
    def record(path, flags):
        opened.append(path)
        return real_open(path, flags)
    monkeypatch.setattr(app.os, 'open', record)
    monkeypatch.setattr(app, 'mint', Mock(return_value=('synthetic', NOW + 3600)))
    assert app.installation_token(REPOS) == 'synthetic'
    assert opened == [str(configured) if override else key]


def test_default_key_path():
    assert str(app.KEY) == '/etc/factory/github-app.pem'


def test_override_key_link_refused(key, monkeypatch):
    key.chmod(0o400)
    link = key.with_name('link')
    link.symlink_to(key)
    monkeypatch.setenv('CPLANE_GITHUB_APP_KEY', str(link))
    mint = Mock()
    monkeypatch.setattr(app, 'mint', mint)
    with pytest.raises(state.StateError, match='GitHub App authentication failed'):
        app.installation_token(REPOS)
    mint.assert_not_called()


@pytest.mark.parametrize('failure', [urllib.error.URLError('synthetic-secret'), TimeoutError('synthetic-secret'),
                                    urllib.error.HTTPError('secret', 503, 'secret', {}, None)])
def test_transient_token_request_failure_is_safe(key, monkeypatch, failure):
    opener = Mock()
    opener.open.side_effect = failure
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    with pytest.raises(app.GitHubAppTransientError) as error:
        app.installation_token(REPOS)
    assert str(error.value) == 'GitHub App login failed'
    assert error.value.__suppress_context__
    assert not app._TOKENS


def test_signing_exception_is_not_transient(key, monkeypatch):
    monkeypatch.setattr(app, 'jwt', Mock(side_effect=TimeoutError('synthetic-secret')))
    with pytest.raises(state.StateError) as error:
        app.installation_token(REPOS)
    assert type(error.value) is state.StateError
    assert str(error.value) == 'GitHub App authentication failed'


def test_failure_reading_response_is_not_transient(key, monkeypatch):
    reply = Mock()
    reply.__enter__ = Mock(return_value=reply)
    reply.__exit__ = Mock(return_value=False)
    reply.read.side_effect = TimeoutError('synthetic-secret')
    opener = Mock()
    opener.open.return_value = reply
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    with pytest.raises(state.StateError) as error:
        app.installation_token(REPOS)
    assert type(error.value) is state.StateError
    assert str(error.value) == 'GitHub App authentication failed'


def test_case_reader_token_is_read_only_and_repo_scoped(key, monkeypatch):
    opener = Mock()
    opener.open.return_value = response(repos=['example/one'], permissions={
        'contents': 'read', 'pull_requests': 'read', 'metadata': 'read'})
    monkeypatch.setattr(app.urllib.request, 'build_opener', Mock(return_value=opener))
    assert app.installation_token(['example/one'], read_only=True, pull_requests=True) == 'synthetic-token'
    assert json.loads(opener.open.call_args.args[0].data) == {
        'repositories': ['one'], 'permissions': {'contents': 'read', 'pull_requests': 'read'}}
