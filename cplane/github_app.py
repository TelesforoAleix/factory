"""Host-only GitHub App authentication. Credentials stay in process memory."""
import base64
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.request

from .state import StateError

KEY = Path('/etc/factory/github-app.pem')
ROOT_UID = 0
_TOKENS = {}
_TOKEN_LOCK = threading.Lock()


class GitHubAppTransientError(StateError):
    """Token request failed before an HTTP answer or returned a server error."""


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def jwt(fd, app_id, now):
    message = '.'.join(encoded(json.dumps(value, separators=(',', ':')).encode()) for value in (
        {'alg': 'RS256', 'typ': 'JWT'},
        {'iat': int(now) - 60, 'exp': int(now) + 540, 'iss': app_id}))
    # Sign the checked descriptor, never reopen a path that could have changed.
    result = subprocess.run(
        ['openssl', 'dgst', '-sha256', '-sign', f'/proc/self/fd/{fd}'],
        input=message.encode('ascii'), capture_output=True, pass_fds=(fd,), timeout=30,
        env={'PATH': os.defpath, 'HOME': '/nonexistent'})
    if result.returncode:
        raise StateError('GitHub App signing failed')
    return message + '.' + encoded(result.stdout)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def mint(fd, app_id, installation_id, repositories, now, *, read_only=False):
    read_only = read_only or os.environ.get('CPLANE_GITHUB_READ_ONLY') == '1'
    assertion = jwt(fd, app_id, now)
    body = {'repositories': [repo.split('/')[1] for repo in repositories]}
    if read_only:
        body['permissions'] = {'contents': 'read'}
    request = urllib.request.Request(
        f'https://api.github.com/app/installations/{installation_id}/access_tokens',
        data=json.dumps(body).encode(),
        headers={'Authorization': 'Bearer ' + assertion,
                 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'factory-cplane'},
        method='POST')
    # No redirects or ambient proxy credentials for this credential exchange.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=30)
    except urllib.error.HTTPError as error:
        if 500 <= error.code < 600:
            raise GitHubAppTransientError('GitHub App login failed') from None
        raise
    except Exception:
        raise GitHubAppTransientError('GitHub App login failed') from None
    with response:
        data = json.load(response)
    token = data['token']
    expiry = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
    if (not isinstance(token, str) or not token or any(c.isspace() for c in token)
            or expiry.tzinfo is None or expiry.timestamp() <= now + 60
            or {r['full_name'].lower() for r in data['repositories']} != set(repositories)
            or (read_only and data.get('permissions') != {'contents': 'read'})):
        raise StateError('GitHub App token response is invalid')
    return token, expiry.timestamp()


def repositories_checked(repositories):
    repos = tuple(sorted({repo.lower() for repo in repositories}))
    if (not repos or len(repos) > 500 or any(
            not re.fullmatch(r'[a-z0-9_.-]+/[a-z0-9_.-]+', repo)
            or any(part in ('.', '..') for part in repo.split('/')) for repo in repos)
            or len({repo.split('/')[0] for repo in repos}) != 1):
        raise StateError('GitHub App requires repositories from one installation owner')
    return repos


def installation_token(repositories):
    """Reuse tokens in this process, renewing within five minutes of expiry."""
    try:
        repos = repositories_checked(repositories)
        read_only = os.environ.get('CPLANE_GITHUB_READ_ONLY') == '1'
        app_id = os.environ['CPLANE_GITHUB_APP_ID']
        installation_id = os.environ['CPLANE_GITHUB_INSTALLATION_ID']
        if not all(re.fullmatch(r'[1-9][0-9]*', value) for value in (app_id, installation_id)):
            raise StateError('GitHub App ids must be positive integers')
        fd = os.open(os.environ.get('CPLANE_GITHUB_APP_KEY', KEY), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as key:
            info = os.fstat(key.fileno())
            if (not stat.S_ISREG(info.st_mode) or not (
                    (info.st_uid == ROOT_UID and stat.S_IMODE(info.st_mode) == 0o600)
                    or (info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o400))):
                raise StateError('GitHub App key must be a root-owned regular file with mode 0600')
            # Keep distinct scopes, installations and key revisions isolated. A
            # fork must mint its own token rather than use its parent's cache.
            context = (os.getpid(), app_id, installation_id, repos, read_only, info.st_dev,
                       info.st_ino, info.st_mtime_ns, info.st_ctime_ns)
            with _TOKEN_LOCK:
                now = time.time()
                cached = _TOKENS.get(context)
                if cached is None or cached[1] <= now + 300:
                    cached = mint(key.fileno(), app_id, installation_id, repos, now,
                                  read_only=read_only)
                    _TOKENS[context] = cached
                return cached[0]
    except StateError:
        raise
    except urllib.error.HTTPError:
        raise StateError(f'GitHub App token request refused for {", ".join(repos)}; '
                         'the App may not be installed there') from None
    except Exception:
        # Neither HTTP bodies, OpenSSL diagnostics nor exception details are safe.
        raise StateError('GitHub App authentication failed') from None
