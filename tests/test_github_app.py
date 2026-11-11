"""Synthetic App keys and HTTP responses; no GitHub credential or network."""
import base64
from datetime import datetime, timezone
import io
import json
import os
import subprocess
from unittest.mock import Mock

import pytest

from cplane import github_app as app, state

NOW = 1800000000
REPOS = ('example/one', 'example/two')


@pytest.fixture
def key(tmp_path, monkeypatch):
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


def response(token='synthetic-token', expiry=NOW + 3600, repos=REPOS):
    return io.BytesIO(json.dumps(dict(token=token,
        expires_at=datetime.fromtimestamp(expiry, timezone.utc).isoformat(),
        repositories=[{'full_name': repo} for repo in repos])).encode())


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
