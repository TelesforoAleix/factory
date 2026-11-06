# Factory CLI containers

Factory's independent Docker stack fences each CLI run in one container. It copies
Home Lab's sealed-task and two-network proxy pattern without modifying Home Lab.
Nothing here wires it into `cplane`; runner integration is a later slice. The host
prepares a credential-free repository copy and pushes changes after the run.
The image contains Claude Code **2.1.318**, codex-cli **0.162.1**, git, Python 3.13
and uv 0.11.18. CLI versions are fixed; base-image tags and OS packages update on
rebuild. No secret belongs in either build context or image layer.

## Install after merge

The orchestrator runs these commands on Ubuntu from a reviewed Factory checkout.
Docker Engine, Compose, git and Python 3 must already be installed. Reserve
UID/GID **21000** exclusively for Factory data. Stop if either is already assigned
to another account. The proxy uses numeric UID/GID 21001 internally, without host
files or a host account.

```sh
getent passwd 21000
getent group 21000
# Both lookups should have no result on first install.
sudo groupadd --gid 21000 factory-cli
sudo useradd --uid 21000 --gid 21000 --no-create-home \
  --home-dir /nonexistent --shell /usr/sbin/nologin factory-cli
sudo install -d -o root -g root -m 0755 /srv/factory
sudo install -d -o root -g root -m 0711 /srv/factory/logins
sudo install -d -o 21000 -g 21000 -m 0700 \
  /srv/factory/logins/claude /srv/factory/logins/codex
sudo install -d -o root -g root -m 0711 /srv/factory/work /srv/factory/runs
sudo install -d -o root -g root -m 0755 /opt/factory/node
sudo cp -R node/cli node/proxy /opt/factory/node/
sudo install -o root -g root -m 0644 node/compose.yaml /opt/factory/node/compose.yaml
sudo install -o root -g root -m 0755 node/bin/factory-cli /usr/local/bin/factory-cli
sudo install -o root -g root -m 0755 node/check-fence.py /opt/factory/node/check-fence.py
sudo docker build -t factory-cli:1 /opt/factory/node/cli
sudo docker compose -f /opt/factory/node/compose.yaml build
sudo docker compose -f /opt/factory/node/compose.yaml up -d --no-build
sudo python3 /opt/factory/node/check-fence.py
```

Keep the launcher, installed stack and parent folders root-owned and unwritable
by containers. Each repository copy below `/srv/factory/work` and each run folder
below `/srv/factory/runs` is owned by 21000:21000, mode 0700. Login directories
must have that exact ownership and mode. The launcher accepts only absolute,
existing descendant directories; it rejects roots themselves, `..`, mount-option
delimiters and every symlink component. It never creates a missing mount. Host
management must not replace or rename paths during launch: validation and Docker
binding are separate operations, not protection against a hostile host process.

Prepare a fresh repository copy without secrets, credential helpers, authenticated
remote URLs, private git configuration or hooks. Do not bind a host clone carrying
credentials. A linked worktree pointing outside the copy cannot work inside.
For a public synthetic example:

```sh
sudo install -d -o 21000 -g 21000 -m 0700 \
  /srv/factory/work/fence-demo /srv/factory/runs/fence-demo
sudo -u factory-cli git -c credential.helper= clone \
  https://github.com/octocat/Hello-World.git /srv/factory/work/fence-demo
sudo factory-cli run --tool codex --repo /srv/factory/work/fence-demo \
  --run /srv/factory/runs/fence-demo -- codex exec -- 'Inspect the README'
sudo factory-cli run --tool claude --repo /srv/factory/work/fence-demo \
  --run /srv/factory/runs/fence-demo -- claude -p -- 'Inspect the README'
```

Container paths are `/work`, `/run/factory` and `/login`; use container paths for
CLI output arguments. Run closes stdin, has no TTY, and requires `codex exec` or
`claude -p`/`--print`. The launcher adds sandbox/approval bypass flags and disables
Claude's inner sandbox: the sealed container supplies the sandbox. It does not
rewrite runner commands. `docker_arguments()` exposes the argument list to tests.
The host launcher needs Docker access, which itself confers administrator power.
It invokes no shell, forwards no host environment into the container, captures no
CLI output, disables Docker logging and propagates the process exit code.

## Owner login and revocation

From the owner's real terminal (never pipe, record, tee or redirect login output):

```sh
sudo factory-cli login claude
sudo factory-cli login codex
```

Follow the CLI's printed URL in the owner's browser. Claude uses `claude auth
login`; choose a claude.ai account. Codex uses device-code login; enable it in the
ChatGPT account if requested. No callback port is published. Login uses the same
image, network, limits and sealing flags, with no repository or run mount. Only
`/login` persists; home and `/tmp` are tmpfs. The launcher prints the CLI's own
output and saves nothing. Never supply tokens through arguments or environment.

Both modes mount only `/srv/factory/logins/<selected-tool>` at `/login`, writable
for token refresh. The other tool's login is absent. `CODEX_HOME=/login` and
`cli_auth_credentials_store="file"` select Codex file storage.
`CLAUDE_CONFIG_DIR=/login` selects Claude's config/credentials;
`XDG_CONFIG_HOME=/login/xdg` covers Linux configuration fallback. Use claude.ai
login: Console sign-in without an API key has different storage semantics in the
current Claude documentation and is not the prescribed login here. Coordinate
same-tool runs and login/revocation on the host to avoid simultaneous refreshes.

To revoke, first identify that tool's running containers by image and mounts with
`sudo docker ps` / `sudo docker inspect <container-id>`, then stop them with
`sudo docker stop <container-id>`. Revoke the session in the provider account's
security settings; revoke any API key in its provider console. Removing local
files alone does not revoke credentials copied elsewhere. Then discard only the
selected tool's local folder:

```sh
# Choose ONE tool; never print the files' contents.
sudo rm -rf -- /srv/factory/logins/claude
sudo install -d -o 21000 -g 21000 -m 0700 /srv/factory/logins/claude
# For Codex, use /srv/factory/logins/codex in both commands instead.
```

## Network policy and sources

Tinyproxy joins `factory-cli` (internal) and `factory-egress` (outbound). CLI
containers join only `factory-cli`. No ports are published. Tinyproxy permits
CONNECT to port 443 only. `node/proxy/allowed-hosts` contains anchored exact
`host:443` regexes; ordinary HTTP is refused. There are no wildcard domains or
package registry allowances. Claude auto-updates, nonessential traffic and
claude.ai connectors are disabled. Prepare dependencies outside the fence;
downloads inside a run may fail. Do not widen the list to work around a failure.

Sources used for the initial allowlist and configuration:

- [Claude network configuration](https://code.claude.com/docs/en/network-config)
  documents proxy variables and model/authentication hosts: `api.anthropic.com`,
  `claude.ai`, `claude.com`, `platform.claude.com`. The last handles OAuth exchange
  and refresh. Optional telemetry, updater and connector hosts are omitted.
- [Claude authentication](https://code.claude.com/docs/en/authentication) and
  [settings](https://code.claude.com/docs/en/settings) describe
  `CLAUDE_CONFIG_DIR`. The published **2.1.318** Linux x64 npm package was inspected
  for that variable, `.credentials.json`, OAuth hosts and flags. No real login
  was read or copied.
- [Official OpenAI authentication documentation](https://developers.openai.com/codex/auth/)
  describes `CODEX_HOME`, file credentials and device login. The
  [pinned 0.162.1 source](https://github.com/openai/codex/tree/rust-v0.162.1/codex-rs)
  confirms these settings, proxy support for HTTPS/WebSockets,
  `auth.openai.com` for login/refresh, `chatgpt.com` for subscription model calls,
  and `api.openai.com` for API calls. Only those three exact OpenAI hosts are used.
- [GitHub communication requirements](https://docs.github.com/en/actions/reference/runners/self-hosted-runners#requirements-for-communication-with-github)
  and [connectivity guidance](https://docs.github.com/en/get-started/using-github/troubleshooting-connectivity-problems)
  inform the HTTPS-only GitHub selection: `github.com`, `api.github.com`,
  `raw.githubusercontent.com`, `codeload.github.com`,
  `objects.githubusercontent.com`, `release-assets.githubusercontent.com`.
  Other dynamic asset hosts are deliberately omitted.
- Home Lab's [container function](https://github.com/TelesforoAleix/homelab-v2/blob/main/node/usr/local/sbin/homelab-task-run),
  [package proxy](https://github.com/TelesforoAleix/homelab-v2/tree/main/node/opt/homelab-package-proxy)
  and [compose networks](https://github.com/TelesforoAleix/homelab-v2/blob/main/compose.yaml)
  supply the task sealing and two-network pattern.

## Fence limits

Each CLI container drops all capabilities, prohibits gaining privileges, has a
read-only root, tmpfs home and `/tmp`, 4 GiB memory including swap, 2 CPUs,
256 PIDs and `--pull never`. It has no Docker socket, host network,
`/srv/homelab`, deploy key or GitHub credential. Only its selected login,
repository and run folder are mounted. Login mounts only its selected login.
Docker logging is disabled for both proxy and CLI containers.

An agent **can read and copy its own run's login**, change mounted data and use
its provider account. GitHub HTTPS is **a way out**: this is a destination
allowlist, not data-loss prevention or URL/API filtering. CONNECT is not
TLS-inspected. The internal bridge is not a per-run firewall: peers on the bridge
and host bridge services may be reachable. Docker's embedded DNS is not a DNS
exfiltration filter. Do not attach public apps or trusted services to these
networks. Containers share the host kernel; this does not prevent kernel/runtime
exploits. Same-tool containers share a login. The host directory manager and
Docker administrators remain trusted. Limits apply per run, not to total host use.

## Validation

```sh
uv run pytest
sudo docker compose -f /opt/factory/node/compose.yaml config --quiet
sudo python3 /opt/factory/node/check-fence.py
```

The network check uses no credentials. Under sealing flags on the internal net,
it checks that an allowed GitHub host answers, `example.com` returns a proxy 403,
and direct HTTPS to a public IP fails. CI builds both images, prints both CLI
versions under sealing flags, and runs the network check. No real model call or
login is tested. After merge the orchestrator repeats the fence check on the node
and the owner logs in; neither step is performed by this slice.
