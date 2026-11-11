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
