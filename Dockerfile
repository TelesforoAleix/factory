# Build without credentials, secret mounts, or private state.
FROM node:22.23.5-bookworm-slim AS ui
WORKDIR /build/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.13.18-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates git openssh-client libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 21010 factory-runner \
    && useradd --uid 21010 --gid 21010 --no-create-home --no-log-init \
        --home-dir /tmp --shell /usr/sbin/nologin factory-runner \
    && groupadd --gid 21011 factory-sessions \
    && useradd --uid 21011 --gid 21011 --no-create-home --no-log-init \
        --home-dir /tmp --shell /usr/sbin/nologin factory-sessions

# Keep both the release version and its official SHA256 sums in the recipe.
# Only the gh executable is retained, not the archive or a download utility.
RUN python - <<'PY'
import hashlib
import io
import shutil
import subprocess
import tarfile
import urllib.request

version = '2.103.3'
checksums = {
    'amd64': '4c806978ffce1cec70853302a56d70ac6da4f19bae7adca4e1a8ab00633dd91d',
    'arm64': 'ee32df2323c8847f5fac6cb6b4b69ca75828e9329a8f22f677021f7b3306ce63',
}
arch = subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip()
expected = checksums[arch]  # Refuse architectures without a reviewed checksum.
name = f'gh_{version}_linux_{arch}'
url = f'https://github.com/cli/cli/releases/download/v{version}/{name}.tar.gz'
with urllib.request.urlopen(url, timeout=120) as response:
    archive = response.read()
if hashlib.sha256(archive).hexdigest() != expected:
    raise SystemExit('gh release checksum mismatch')
with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as release:
    with release.extractfile(f'{name}/bin/gh') as source:
        with open('/usr/local/bin/gh', 'wb') as target:
            shutil.copyfileobj(source, target)
PY
RUN chmod 0755 /usr/local/bin/gh \
    && pip install --no-cache-dir uv==0.11.18

ENV PATH="/opt/factory/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    XDG_CONFIG_HOME=/tmp/.config \
    UV_CACHE_DIR=/tmp/.cache/uv \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /opt/factory
COPY pyproject.toml uv.lock ./
COPY cplane/ cplane/
COPY schema/ schema/
COPY skills/ skills/
COPY factory_ui/ factory_ui/
RUN uv sync --frozen --no-dev --no-cache \
    && chmod -R a+rX /opt/factory
COPY --from=ui /build/ui/dist/ ui/dist/
USER 65534:65534
CMD ["cplane", "--help"]
