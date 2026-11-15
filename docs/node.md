# Factory CLI containers

Factory's independent Docker stack fences each CLI run in one container. It copies
Home Lab's sealed-task and two-network proxy pattern without modifying Home Lab.
`CPLANE_FENCE=1` routes runner turns and usage warm-ups through `factory-cli run`.
With it unset, the Mac launchd runner keeps its existing commands and behaviour.
The host prepares a credential-free repository copy and pushes changes after the run.
The image contains Claude Code **2.1.318**, codex-cli **0.162.1**, git, Python 3.13
and uv 0.11.18. CLI versions are fixed; base-image tags and OS packages update on
rebuild. No secret belongs in either build context or image layer.

## Factory service image (build only)

The root `Dockerfile` builds one image for Workshop (`python -m factory_ui.serve`,
port 8300), intake (`python -m cplane.intake`), sessions
(`python -m cplane.sessions`) and the scheduler pass (`cplane --actor runner run`).
The root compose file chooses the command; the image has no mode-selecting
entry point and defaults to `cplane --help`.

Build it with `docker build -t factory:local .`. Two stages use
`node:22.23.5-bookworm-slim` to run `npm ci && npm run build` and
`python:3.13.18-slim-bookworm` with uv 0.11.18 to run
`uv sync --frozen --no-dev`. The final image contains the Python application,
locked production dependencies, built `ui/dist`, git, openssh-client, libpq5 and
GitHub CLI 2.103.3. The gh executable comes from the official release with a
pinned SHA256 checksum for amd64 or arm64. Debian packages update on rebuild.

The build context allows only application inputs and excludes private state,
environment files, keys, credentials, deny lists, Git history and `node/`.
The image defaults to UID/GID 65534:65534, disables Python bytecode writes and
places HOME and caches under `/tmp`. CI's `image` job builds it, checks CLI help,
imports, tool versions and `ui/dist/index.html` as UID 65534 with a read-only
root, tmpfs `/tmp` and no capabilities, and reports the image size in bytes.

Since the 2026-11-15 cutover, the four services run healthy in containers
installed by the platform deployer. The root compose file below defines their
UIDs, mounts and networks. The separate CLI fence uses `node/compose.yaml`.
The Dockerfile and CI workflow require the owner's GitHub review before merge.

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
For a synthetic CLI-only check with empty folders (no Git or private state):

```sh
sudo install -d -o 21000 -g 21000 -m 0700 \
  /srv/factory/work/fence-demo /srv/factory/runs/fence-demo
sudo factory-cli run --tool codex --repo /srv/factory/work/fence-demo \
  --run /srv/factory/runs/fence-demo -- codex exec --skip-git-repo-check -- 'Reply with: ok'
sudo factory-cli run --tool claude --repo /srv/factory/work/fence-demo \
  --run /srv/factory/runs/fence-demo -- claude -p -- 'Reply with: ok'
```

Container paths are `/work`, `/run/factory` and `/login`; use container paths for
CLI output arguments. Run closes stdin, has no TTY, and requires `codex exec` or
`claude -p`/`--print`. The launcher adds sandbox/approval bypass flags and disables
Claude's inner sandbox: the sealed container supplies the sandbox. It does not
rewrite runner commands. `docker_arguments()` exposes the argument list to tests.
The exact command `codex debug models` is also allowed in the same container, mounts, network and login, without exec's sandbox/approval bypass flags; all other non-exec Codex commands are refused.
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
`host:443` regexes; ordinary HTTP is refused. There are no wildcard domains.
Package downloads are allowed through `pypi.org`, `files.pythonhosted.org` and
`registry.npmjs.org`, each on port 443, so executors can install Python and Node
dependencies and run repository tests. Claude auto-updates, nonessential traffic
and claude.ai connectors are disabled. Downloads from other hosts may fail. Do
not widen the list to work around a failure.

Accepted risk: a package runs inside the container and can read that tool's
login. It reaches neither the host nor the GitHub token.

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
Docker logging is disabled for both proxy and CLI containers. `factory-cli bundle`
uses the same image and sealing limits with `--network none`, no login mount,
a read-only copy mount, and hooks/fsmonitor/SSH disabled. It exports `HEAD` and the
assigned branch into `/run/factory/branch.bundle`.

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
it checks that an allowed GitHub host and `https://pypi.org` answer through the
proxy, `example.com` returns a proxy 403, and direct HTTPS to a public IP fails.
CI builds both images, prints both CLI versions under sealing flags, and runs
the network check. No real model call or login is tested. After merge the
orchestrator rebuilds the proxy and repeats the fence check on the node and the
owner logs in; neither step is performed by this slice.

## Install the runner after review and merge

The orchestrator installs this slice and performs the switch only with the owner's
go. These are installation instructions, not commands for the implementation agent.
The service follows Home Lab's [root task runner pattern](https://github.com/TelesforoAleix/homelab-v2/blob/main/node/etc/systemd/system/homelab-task-runner.service).
Root is deliberate: Docker access already gives that authority.

Install host dependencies first. Ubuntu's `python3` may be 3.14; explicitly install
and use Python 3.13 for cplane. `psycopg` needs `libpq5` on the host. Use the
[official gh package instructions](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
if the distribution package lacks `gh pr merge --match-head-commit`.

```sh
sudo apt-get update
sudo apt-get install -y git gh curl ca-certificates libpq5
# Download and inspect the pinned official uv installer before executing it.
curl -LsSf https://astral.sh/uv/0.11.18/install.sh -o /tmp/factory-uv-install.sh
less /tmp/factory-uv-install.sh
sudo env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh /tmp/factory-uv-install.sh
sudo env UV_PYTHON_INSTALL_DIR=/opt/python uv python install 3.13
```

The uv installer and versioned URL are documented in [uv installation](https://docs.astral.sh/uv/getting-started/installation/).
Install the reviewed archive at `/opt/factory`, owned by root and unwritable by
21000. It is separate from both agent copies and the orchestrator's briefs clone.
Preserve an existing `/opt/factory/node` installation when placing the archive.
The installer must write the reviewed source revision followed by a newline to
`/opt/factory/REVISION` (root:root, mode 0644). For example, with the reviewed
commit in `REVIEWED_SHA`, use:

```sh
printf '%s\n' "$REVIEWED_SHA" | sudo tee /opt/factory/REVISION >/dev/null
sudo chown root:root /opt/factory/REVISION
sudo chmod 0644 /opt/factory/REVISION
```

Archive installations use this file as the skills version; a missing or empty file refuses ticket cutting/submission.
In a git checkout the skills must still be committed and clean; `REVISION`
does not override that check.

```sh
sudo uv sync --project /opt/factory --python "$(env UV_PYTHON_INSTALL_DIR=/opt/python uv python find 3.13)" --frozen --no-dev
sudo install -d -o root -g root -m 0700 /etc/factory /srv/factory/clean
sudo install -d -o root -g root -m 0711 /srv/factory/work /srv/factory/runs
sudo install -o root -g root -m 0755 /opt/factory/node/bin/factory-cli /usr/local/bin/factory-cli
sudo install -o root -g root -m 0755 /opt/factory/node/bin/factory-cplane /usr/local/bin/factory-cplane
sudo install -o root -g root -m 0755 /opt/factory/node/bin/factory-export /usr/local/bin/factory-export
sudo install -o root -g root -m 0644 /opt/factory/node/systemd/factory-runner.service /etc/systemd/system/
sudo install -o root -g root -m 0644 /opt/factory/node/systemd/factory-runner.timer /etc/systemd/system/
sudo install -o root -g root -m 0644 /opt/factory/node/systemd/factory-export.service /etc/systemd/system/
sudo install -o root -g root -m 0644 /opt/factory/node/systemd/factory-export.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

Provision `/etc/factory/github-token` and `/etc/factory/runner.env` privately, with
owner root:root and mode 0600. Never put their contents in a command line, shell
history, checkout, terminal recording, run folder or notice. The GitHub file is
only the fine-grained token. Allow Contents read/write and Pull requests read/write
on the intended repositories, plus Actions read access for CI results. Fine-grained
tokens do not offer a Checks permission.
No `gh auth login`, credential store, authenticated remote URL or Git config
contains this token. Each authenticated delivery call gets it in its environment;
Git obtains it from a helper for that call. Git/gh failure diagnostics are
suppressed before they can reach state, logs or notices, like database diagnostics.

`CPLANE_GITHUB_AUTH` defaults to `token`, preserving that path. To use a GitHub
App, set it to `app` and put `CPLANE_GITHUB_APP_ID` and
`CPLANE_GITHUB_INSTALLATION_ID` in the same private `runner.env`. Place the App's
RSA private key at `/etc/factory/github-app.pem`, root-owned, regular, mode 0600;
links are refused. OpenSSL must be installed on the host. No Python dependency
or credential store is added. Tokens reach `gh` through `GH_TOKEN` and Git through
the existing `x-access-token` helper; the install host uses the same function.
Within each process, tokens are cached in memory for the same installation,
repository scope and key revision, and renewed when five minutes or less remain
before expiry. The runner's oneshot passes and the separate installer each mint
their own tokens; there is no cross-process mint limit, shared cache or broker.
Tokens are never written to disk. Every call still checks the key file.

| Setting | Default | Sessions behavior |
| --- | --- | --- |
| `CPLANE_GITHUB_AUTH` | `token` | Must be `app`; sessions refuses token-file mode at startup because it cannot narrow that token. |
| `CPLANE_GITHUB_READ_ONLY` | unset (full App permissions) | The sessions entry point always sets `1`, overriding even `0` in the environment. |
| `CPLANE_SESSIONS_CLEAN_ROOT` | `/srv/factory/clean-sessions` | Separate bare clones, fetched on demand; created mode 0700 by the service under a trusted parent. |

With `CPLANE_GITHUB_READ_ONLY=1`, each App request includes only
`permissions: {contents: read}` and the call's repositories. The response must
report `contents: read` and may also report `metadata: read`, which GitHub grants
every App token. Any other permission or value, or missing `contents`, is refused.
The response must report exactly the call's repositories.
Read-only and write tokens have separate in-process cache entries.
Leave this setting unset for the runner. The runner needs write access for
delivery; sessions only fetches repositories for chats. App-authenticated session
repository fetches never use the runner's `/srv/factory/clean`, and each `Fence`
host Git guard accepts only its own root.
The sessions root cannot equal, contain or sit inside the runner root; links and
untrusted ownership or write permissions are refused. Planning document writes
continue to use their existing separate deploy key and existing
`/srv/factory/clean/planning-sessions` clones; that separate write-back path is
unchanged here.

After installing this change, run one chat turn per tool in each area, Home Lab
and Factory, on a repository. Verify the repository appears under sessions'
clean root and the runner root was untouched, then run one runner slice to
verify its App tokens still write. Today's root services may continue to read
the shared App key and environment file; sessions enforces its own mode.

Each App token request names only the repository of its Git, `gh`, or install
call. Scheduler state is never used to supply repositories; calls without an
explicit repository are refused. If GitHub refuses a token request, the error
names the repository and says the App may not be installed there, without
including the HTTP response. Install the
App only on intended delivery repositories with the delivery permissions above.
The JWT uses RS256, an issue time 60 seconds in the past and an expiry nine minutes
ahead, as described in [GitHub's JWT documentation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app).
The response must name exactly the requested repositories, following
[GitHub's installation token API](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app).
Never put the key, JWT, installation token or HTTP response in logs or notices.
The owner reviews credential-path changes before merging. After merging, install
the merged commit, provision the App and key, configure both ids, then have the
owner and orchestrator verify one slice delivered as the App.

Use shell-compatible `KEY='value'` lines in `runner.env` (no shell expansions,
commands or multiline values), so systemd and `factory-cplane` read the same file.
Configure these keys using the actual private values:

```ini
CPLANE_FENCE='1'
CPLANE_STATE='/srv/factory/briefs/slices.json'
CPLANE_RUNS='/srv/factory/runs'
CPLANE_EXPORT_DIR='/path/to/encrypted/root-only/export-directory'
CPLANE_DATABASE_URL='postgresql://REDACTED'
PATH='/opt/factory/.venv/bin:/usr/local/bin:/usr/bin:/bin'
```

Set `CPLANE_EXPORT_DIR` to an existing root-only directory on the mounted encrypted
volume. The daily export runs at 03:45 and retains the newest seven dated state
and outbox pairs; a missing directory fails without creating it. After merge,
the orchestrator enables the timer and runs the service once:

```sh
sudo systemctl enable --now factory-export.timer
sudo systemctl start factory-export.service
```

For the phone bot, the orchestrator can create an existing absolute directory
owned by root, group `homelab-bot`, mode `0750`, and set `CPLANE_BOT_EXPORT`
to that path in `runner.env`. After each pass the runner atomically replaces
`slices.json` and `slices.json.outbox.jsonl` there with mode `0640` and the
directory's group. State includes every slice: accepted slices retain only `id`,
`repo`, `title`, `state`, `pr`, `feature`, `paused`, and `attention`; other slices
retain every field except `log`. The full state export and database are unchanged.
The outbox includes only question, escalation, merge, and owner-check notices in
database order.
Its existing contents must remain a prefix of the next export to preserve the
bot's line-count position. An untrusted directory or export failure produces a
generic stderr line and does not fail the pass. The bot needs no database access.
When the variable is unset, no bot files are written.

`CPLANE_STATE` remains the state-path anchor; its containing folder is the
orchestrator-managed briefs clone. In Postgres mode each pass pulls that clone
with `git pull --ff-only` before reading relative briefs. No state or notices are
committed there. A failed pull stops the pass. Provision this clone separately;
never use an agent's working copy as the anchor. Database provisioning/migration
and import remain the orchestrator's existing process; do not import twice.
In fenced mode a slice's `repo` must be `owner/name`; the root-owned briefs clone
reads with its own deploy key set in its local `core.sshCommand`, never the GitHub token.

The service is a root oneshot triggered every 60 seconds. systemd does not start
another instance while it is active; a long pass delays the next activation
rather than queuing overlapping passes. Its detached turn supervisors survive the end of a pass (`KillMode=process`), as under launchd.
Stopping the timer prevents new passes; it does **not** stop existing CLI
containers or supervisors. Do not start a second scheduler during a handoff.

Over SSH a planner can use the same environment without exposing it:

```sh
ssh NODE sudo factory-cplane pending
ssh NODE sudo factory-cplane --actor planner show PROJECT/SLICE
```

In fenced mode a Frontline `orchestrator` order is acknowledged as failed with
`orchestrator is not available on the node`. It starts no tmux window or host CLI.
Interactive fenced planners are later work. SSH planner commands still work;
with `CPLANE_FENCE` unset, the existing tmux behaviour is unchanged.

On first launch, the runner allocates `slice/<id>` with `/` inside the slice ID
replaced by `-` (for example `voice/W1` becomes `slice/voice-W1`). It pins the
clean clone's fetched default-branch commit as the base. Both values are saved
in root-owned job metadata before starting the tool, and resumes reuse them.
Every turn's prompt says the assigned branch overrides any branch in the brief.
The state contract remains version 1; `flow` is an optional slice field.

Run metadata and supervisor stdout/stderr stay in root-owned turn folders under
`/srv/factory/runs/<anchor-hash>/<turn-id>`. Only their `io` child is mounted in a
CLI container. Turn folders are mode 0700 and job/request JSON files mode 0600;
the Docker daemon mounts `io` directly, without granting the agent access to its
host parents. Clean bare clones under
`/srv/factory/clean/<owner>/<repo>.git` are root-only and are never mounted.
Fresh work copies under `/srv/factory/work/<id>` have no hooks, credentialed
remote or shared object hardlinks, and are owned by 21000:21000, mode 0700.
Keep copies and the selected login until acceptance so resumes find both files
and session. A missing session or copy raises attention; no fresh session is
silently substituted. Normal cleanup after acceptance is an operator action.

Slices default to `flow: cli` when the field is absent. Planners opt in to the
queue with `cplane add --flow tickets` or `cplane edit ID --flow tickets` (and
identify themselves with `--actor`); `--flow cli` selects the existing flow.
Issued and awaiting-handover slices still permit only title/dependency edits.
Only opt in repositories with a queue push key. A tickets slice requires fenced
mode; an unfenced attempt raises attention without starting an executor.

For `flow: tickets`, the first CLI turn receives `skills/cut.md` and the brief,
commits tests on its assigned branch, and ends `waiting` with a fenced JSON plan.
Text may precede the block; the runner uses the last fenced JSON block and validates it
against `schema/plan.schema.json`. It delivers the
commit through the same bundle path, without opening a PR. It builds the queue
task file using the delivered tip as `base_commit` and the assigned branch.
Queue workers push each finished ticket's commit to that branch.

Configure both queue commands in the private runner environment as JSON argv:

```ini
CPLANE_TASK_SUBMIT='["/absolute/path/task-submit"]'
CPLANE_TASK_STATUS='["/absolute/path/task-status"]'
```

Submit reads the task file on stdin and returns a JSON list of IDs. Status is
called with the slice name appended as one argument and returns a position-ordered
JSON list of `{id, position, title, status, reason}` records; an unknown slice
returns `[]`. Status is `queued`, `running`, `done`, `failed` or `escalated`.
Commands run directly, without a shell. Command failure diagnostics are suppressed.
The runner reads status before every submit; existing tickets are followed and
never resubmitted. It saves submission intent before calling the queue. Any failed
or interrupted submission raises attention and is never automatically retried.
Reconcile ambiguous submissions with the queue before any operator recovery.
Each following pass reads status: queued/running keep waiting, failed/escalated
raise attention naming the ticket and reason, and all done starts a fresh fenced
review of the branch. Existing `tickets done` placeholder attention is cleared
when the queue confirms completion.

The reviewer receives `skills/slice-review.md` and the brief, changes nothing,
runs the repository's tests and reads the whole diff from the original slice base,
especially Fixed decisions and Do not. It ends `waiting` with a fenced JSON block
matching `schema/review.schema.json`. Each cut and review run records its skills
version in the private job metadata. Review copies are fresh clones of the branch
from the clean clone; host Git never runs in a copy.

A `pass` supplies the PR title and body and enters the existing PR/CI/merge flow.
A `fix` supplies plan-form tickets (including a done check) and `test_files`.
The runner submits these once as `<id>/repair` on the same branch, using the
reviewed tip as `base_commit`. Repair uses the same status following and durable
submission intent as the initial cut. When all repair tickets are done, a second
fresh review runs. A failed repair ticket or second `fix` raises attention with
what remains. A recovered pass follows the PR flow without resubmitting tickets.

For `flow: cli`, both tools commit and end `waiting` with the existing JSON PR
request. The runner exports the branch in the offline container, snapshots the bundle as a regular
file, fetches it into the clean clone with `transfer.fsckObjects=true`, checks the
pinned branch/default/base, then pushes and opens the PR. Host Git never reads
config, hooks, branches, status or logs from an agent's copy. In fenced mode
tidying is skipped. CI must include a successful check on the delivered
head. Before automatically merging either fenced flow, the runner lists changed
paths in the clean clone. Any path under `.github/workflows/` requires merge
approval, including deletions and renames, just like a stop-before-merge slice.
Approval rechecks CI and the expected head before merging. The runner merges
only that head and resumes the same session with `merged as <sha>`. The saved job
retains the merge across resumed turns (including node-step answers); after a
merge, replies only collect the handover or raise attention. A later `waiting`
reply never delivers another bundle or opens a second PR.
Fenced capacity counts live jobs even when their slice is paused. An issued
slice with missing local job metadata also reserves capacity until reconciled;
pause/attention does not prove that its container has stopped.

Usage gates read Codex's `sessions/**/*.jsonl` under
`/srv/factory/logins/codex` and Claude's `usage-now.json` under
`/srv/factory/logins/claude`. Missing data stays unknown and defers execution;
login success alone supplies no usage percentage. Provision/refresh Claude's
existing usage snapshot through the owner's established mechanism; the runner
does not invent capacity or widen the fence to obtain it.

## Switch-over, by the orchestrator after the owner's go

1. Leave the node timer disabled while installing and reviewing configuration.
   Run the existing fence check, then verify a synthetic planner read with
   `sudo factory-cplane pending`. Do not print environment files or login files.
2. Stop new Mac passes with the existing `cplane uninstall-agent`. Let active
   turns finish and obtain handovers. Existing Mac sessions/copies do not move
   to the node; resolve them on the Mac before issuing fresh node slices.
3. With exactly one scheduler active and owner approval, run one real, explicitly
   selected slice using `sudo factory-cplane --actor runner run`, collecting
   subsequent passes with the same command. Observe container execution, usage
   data, delivery, green CI, any merge approval, and the resumed handover. This
   smoke test belongs to the orchestrator, not this implementation slice.
4. After acceptance, enable the timer:

   ```sh
   sudo systemctl enable --now factory-runner.timer
   sudo systemctl list-timers factory-runner.timer
   sudo journalctl -u factory-runner.service --since today
   ```

For rollback, stop/disable the timer, account for all live containers/supervisors
and outstanding slices, and obtain the owner's go before restoring Mac scheduling
with `CPLANE_FENCE` unset. Never let both schedulers issue concurrently, and never
point the Mac runner at the node's agent-owned copies.

## Install the owner UI after merge

The orchestrator installs the reviewed revision on the node; this slice does not
perform the installation. Build Vite using the `node:22-slim` container; the node does not need Node.js
installed. With the reviewed source at `/opt/factory`, build its static files and
sync its Python environment, then install the service:

```sh
sudo useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin factory-ui
sudo docker run --rm -v /opt/factory/ui:/app -w /app node:22-slim sh -c "npm ci && npm run build"
sudo uv sync --project /opt/factory --python "$(env UV_PYTHON_INSTALL_DIR=/opt/python uv python find 3.13)" --frozen --no-dev
sudo install -o root -g root -m 0644 /opt/factory/node/systemd/factory-ui.service /etc/systemd/system/
```

Keep the installation root-owned and unwritable by `factory-ui`. Provision
`/etc/factory/ui.env` as root:root mode 0600 with **only** the existing
`CPLANE_DATABASE_URL` assignment from `runner.env`, without printing its value.
Systemd reads the file before dropping privileges. The account needs no login,
Docker group, GitHub token, or access to the runner's login files. The database
credential must allow state and notice writes for owner actions.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now factory-ui.service
# Enable Serve once in the tailnet admin console and allow tcp:443 in the tailnet policy.
sudo tailscale serve --bg http://127.0.0.1:8300
```

The server listens only on loopback. Tailscale Serve publishes it to the
configured tailnet; check the tailnet's access policy before enabling it. Serve
uses the existing tailnet identity and the app has no separate login. Open the
HTTPS address reported by `tailscale serve status` on the phone or Mac. To stop
publishing, use `sudo tailscale serve reset`; stop the service with
`sudo systemctl disable --now factory-ui.service`. Serve reset removes all Serve
configuration on that node, so inspect its status first if it is used for other
services.

## Owner message sessions

The web service only reads/writes session rows. It has no Docker group, socket,
CLI execution, or access to briefs/logins. Its systemd mount namespace also hides
the Docker sockets, Docker/launcher binaries and `/srv/factory`. `factory-sessions.service` is a separate
root process with Docker access and the existing private database environment.
Run the existing `cplane migrate` before starting either updated service; migration
002 adds sessions/messages without changing version 1 scheduler state.

After review and merge, the orchestrator installs and starts the service:

```sh
sudo install -o root -g root -m 0755 /opt/factory/node/bin/factory-cli /usr/local/bin/factory-cli
sudo install -o root -g root -m 0644 /opt/factory/node/systemd/factory-sessions.service /etc/systemd/system/
sudo factory-cplane migrate
sudo systemctl daemon-reload
sudo systemctl enable --now factory-sessions.service
```

Rebuild the UI and reinstall its updated unit with the existing installation
procedure, run daemon-reload, and restart factory-ui.
Open Home Lab sessions or Factory sessions. Specify the tool, model, and optional
comma-separated `owner/repo` names. On the first turn, the service creates any missing root-owned bare clone at
`/srv/factory/clean/<owner>/<repo>.git`, fetches its branches, and exports the
remote-tracking default branch. Factory planning is exported from HEAD of the root-only
`/srv/factory/briefs` clone; uncommitted files are excluded. Home Lab planning
uses the git delivery path described below.

Each session gets a new 0700 workspace owned by 21000:21000. Archives exclude
Git metadata and omit links; exports with special entries fail closed. Home Lab
`planning/` is a writable git copy. Factory `planning/` points to the reserved
root-owned `repos/factory-planning-export` export, overmounted read-only using the existing
repository mount contract. Each named `repos/<name>` is also overmounted read-only.
No clean clone or briefs clone is mounted. Duplicate repository basenames are
rejected. Exports are made once; resumed turns never refresh or repair paths in
an agent-owned workspace. Host Git runs only in the root-owned source clones.

The service checks the queue every two seconds, permits one turn per session
and two session turns total, and uses login-folder CLI resume IDs. These session
slots are separate from scheduler slice capacity. A turn is limited to 20 minutes;
the launcher forcibly removes its named container before releasing the slot.
Failure details stay in the journal; the page gets a short failure message and
requires a fresh session. Queued messages in that failed session are marked failed.
On service restart, interrupted turns have their named containers removed before
being marked failed; they are never replayed. Stop the service to stop issuing
turns; on restart it reconciles any containers left by an abrupt service stop.
Workspaces/login histories and database messages are retained for operator cleanup.
Only Home Lab commits are written back through the delivery checks below.
After installation the orchestrator performs a real two-message session smoke
test; this implementation does not run one.

## Library

`/library` replaces the old Home Lab document, backlog and grill pages. The
menu has one Library entry beside Factory, Pipeline and Chats. Each document
has `/library/documents/<path>` and each skill `/library/skills/<name>`.
Old document links redirect to their corresponding Library address; backlog
redirects to `backlog.md`, grills to Library, and Home Lab sessions to Chats
(preserving a selected session ID). Factory routes remain unchanged.

The sessions unit prepares root-owned `/var/lib/factory` mode 0755. Its supervisor
compares the planning clone's `HEAD` every 60 seconds, without pulling. The runner
continues to pull every 300 seconds. On a changed HEAD (and on supervisor startup),
the sessions service exports only committed regular `*.md` files, omitting links,
Git metadata and all other file types, into a temporary sibling directory. It
normalizes directories to 0755 and files to 0644, then atomically exchanges the
whole plain directory at `/var/lib/factory/ui-docs` using Linux `renameat2`.
An export failure retains the preceding generation and is logged for retry.
The sibling `.ui-docs.lock` is root-owned mode 0644; readers take a shared lock so
an old generation cannot be removed during a document read or search. No deploy
key, token, Git configuration or clone is exposed to the web account. The UI's
existing `/srv/factory` exclusion remains in place. No new UI environment key or
filesystem write permission is required.

The Documents tree reads the same committed Markdown export. Search includes
paths, titles, status, dates and body text. Project selection maps the document's
top folder through `cplane_projects.repository` (the repository basename also
works for owner/name values); root documents appear under every project.
Markdown disables raw HTML and unsafe links, with horizontally scrolling GFM
tables. Absolute paths, traversal, non-Markdown files and symlinks are refused.
The viewer and tree are separate screens below 700px, with a back link.

Skills & guides lists repository-owned skills, their git version and selected
project's on/off state. Opening a skill shows its text and project switch, using
the existing `skill_set` transaction path. Select a project before switching.
Switches affect future workspace snapshots under the existing skill contract;
Library never edits a skill or document, runs a CLI, or writes a git repository.

Passage comments store a W3C `TextQuoteSelector` (`exact`, `prefix`, `suffix`),
relative document path, text and creation time. Select text with mouse, touch or
keyboard and save a draft. Exact matches are highlighted; context distinguishes
repeated quotes. Missing or ambiguous passages display “passage changed” and
keep their quote and comment. A unique exact quote can still anchor after its
surroundings move. Comments remain keyed to the original path after a rename.

“Send N comments” queues all drafts for that document as one owner message in
one existing chat. The message includes the document path and each quote/text.
Queue insertion and comment delivery markers commit together under the store
lock; concurrent or repeated sends cannot redeliver a sent draft. Saved history
shows chat and delivery time (queue time, not model completion). The receiver
chip offers non-archived chats. Default routing uses the folder's project chat,
otherwise the orchestrator; archived project chats fall back to the orchestrator.
Failed/archived explicit receivers are refused. Saving a new draft refuses a
batch exceeding the existing 32,000-character chat message limit: send existing
drafts first. Quote and comment limits are 16,000 characters each; contexts are
at most 256 characters. Nothing is silently truncated.

“Grill this document” queues a message naming `planning/<path>` and requesting
the grilling skill, then opens the chosen chat. It neither creates a session nor
changes tools, repositories or skill snapshots. Existing chat execution and
scope restrictions remain authoritative. No chat tool operation is added.

Migration 013 adds `cplane_document_comments` and copies every whole-document
note once as a sent, passage-free imported comment, preserving text and time.
The old notes contain no delivery links, so imported comments show “Imported
note” without inventing a receiver or message. Source notes are retained.
Existing Home Lab `legacy` chats are archived, keeping IDs, messages and queued
history; the orchestrator established by migration 009 remains current.
Archived transcripts remain readable in Chats. Reading does not unarchive them.
Old note/send-note/grill HTTP mutation routes are removed. Existing session API
compatibility and read-only document API aliases remain available.

Library API:

- `GET /api/library?project=FAC&q=words`: filtered flat tree entries and projects.
- `GET /api/library/documents/<path>`: document and default receiver.
- `GET /api/library/comments/<path>`: draft/sent history (also when source is gone).
- `POST /api/library/comments/<path>`: `{text, selector}` creates a draft.
- `POST /api/library/send/<path>`: `{chat: 123}` sends all drafts atomically;
  `{}` selects the default receiver.
- `POST /api/library/grill/<path>`: same receiver payload, queues grill request.
- `GET /api/skills` and `GET /api/skills/<name>`: catalog and text respectively.
- `POST /api/skills/<name>`: `{project: "FAC", enabled: true}` switches a project.

All mutations retain `X-Factory-UI: 1` and the existing owner boundary. Unexpected
backend failures return fixed errors; receiver data excludes CLI resume IDs and
workspace preparation metadata. Library uses `@recogito/text-annotator` 4.3.7
(BSD-3-Clause) for selection and highlights. `react-arborist` 4.0.1 (MIT) was
reviewed; its editable/virtualized tree machinery is unnecessary for this small
read-only tree, which uses semantic folder lists and native disclosure controls.

After merge, use the existing reviewed installer:

```sh
sudo factory-cplane --actor owner install factory/LB1
```

The installer applies migration 013 and restarts the existing services. Check
Library at desktop and phone widths, save a passage draft, send a batch, inspect
the single queued chat message, open a grill, and verify imported note history.
No new service, credential or manual state edit is required.

## Home Lab planning write-back

Stop before merging this change: it crosses the delivery security boundary and
requires merge approval. After merge the orchestrator syncs the reviewed Python
installation, rebuilds the UI, and restarts `factory-sessions` and `factory-ui`.
No launcher change, image rebuild, migration, or additional container mount is
needed. Existing Home Lab sessions with plain planning exports cannot deliver;
create a fresh session. Existing Factory sessions without the read-only planning
export also need a fresh session. Do not repair an agent-owned workspace.

The sessions environment must contain the installer's `CPLANE_PLANNING_REMOTE`
SSH address (`git@github.com:owner/repository.git`). The host reads current `main`
with the existing read identity `/etc/factory/briefs-key/id_ed25519`. The separate
root-only write identity `/etc/factory/planning-write-key/id_ed25519` is used only
for the push, through that process's `GIT_SSH_COMMAND`. Both calls use strict host
checking against `/etc/factory/briefs-key/known_hosts`, batch mode and explicit
identities, without SSH config files. Neither key nor its contents enters a run,
copy, Git config, argument, session message, or Git diagnostic log.

A new Home Lab session gets its own root-owned clean clone at
`/srv/factory/clean/planning-sessions/session-<id>`, created without templates.
The service fetches planning `main` and pins the start commit in a host-only ref.
It clones the session branch into `planning/` without hardlinks, hooks, credentials
or private config before handing ownership to UID/GID 21000. The clone's local
origin names the inaccessible clean clone, not an authenticated remote.
Factory sessions keep a plain read-only export and never invoke this delivery.
Every Home Lab turn instructs the planner to commit each agreed change in that
turn with `git add` and `git commit`, using a short message. Only unprotected
Markdown files may change. Uncommitted edits do not reach `main`; the owner's
stored message remains unchanged. Factory turns do not receive this instruction.

After each successful Home Lab turn, the host calls the existing offline
`factory-cli bundle` and snapshots its regular single-link output. Host Git never
runs in the session copy. The bundle must advertise exactly the session branch
and matching HEAD, verify successfully, and import with
`transfer.fsckObjects=true`. The tip must descend from both the pinned start and
the last delivered source tip. Every commit since the start is checked, including
merge-parent diffs and changes subsequently reverted: only `*.md` paths may
change, with `.github`, `.claude`, `.agents`, and `AGENTS.md` protected at every
depth. Markdown links and submodules are refused. One forbidden commit refuses
the whole delivery before any push.

Only new commits since the last delivery are rebased in the clean clone onto
freshly fetched `main`. Conflicts abort the rebase and produce a session notice;
nothing is pushed. The host verifies ancestry again and pushes normally to
`main`, never with force. A concurrent remote advance rejects the push. Delivery
failures retain the planner reply and resume ID so the session can address them.
Notices identify a failed fetch, rebase, or push without exposing Git output.
Each successfully pushed commit is recorded as a separate message with its full
rebased SHA on the session page, suitable for an operator to revert. Session
workspaces, clean clones, bundle snapshots and database messages are retained for
operator cleanup. The document export refresh continues through the existing
briefs clone refresh path.

After installation, the orchestrator tests one deliberately chosen real Home Lab
Markdown write, confirms its commit notice and remote `main`, and verifies a
Factory session cannot write planning. This implementation uses temporary Git
repositories and does not perform that real write.

## Database dump and restore check

The root-run `factory-dump.timer` makes a custom-format PostgreSQL dump every
night at 03:50, including a missed run after boot. It writes atomically to
`/srv/homelab/factory-data/originals/db/factory-YYYY-MM-DD.dump` with mode 0640,
and retains the seven newest dated dumps after a successful dump. A lock prevents
concurrent dumps. The existing weekly encrypted copy includes this directory.
The separate JSON export remains in place.

After merge, the orchestrator verifies that `/srv/homelab` is the mounted encrypted
volume **before** creating the directory. Stop if it is not mounted; never create
this path on the root disk. Then install and exercise the reviewed scripts:

```sh
mountpoint -q /srv/homelab || { echo 'Encrypted volume is not mounted' >&2; exit 1; }
sudo install -d -o root -g root -m 0750 /srv/homelab/factory-data/originals/db
sudo install -o root -g root -m 0755 /opt/factory/node/bin/factory-dump /usr/local/bin/factory-dump
sudo install -o root -g root -m 0755 /opt/factory/node/bin/factory-restore-check /usr/local/bin/factory-restore-check
sudo install -o root -g root -m 0644 /opt/factory/node/systemd/factory-dump.service /etc/systemd/system/
sudo install -o root -g root -m 0644 /opt/factory/node/systemd/factory-dump.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now factory-dump.timer
sudo systemctl start factory-dump.service
sudo factory-restore-check
```

The check without an argument first makes a fresh dump; it then restores the
newest dated dump to a disposable `pgvector/pgvector:pg17` container with no
network or published port and compares each table's row count to the live database.
To check an older dump, pass its path: `sudo factory-restore-check /path/to/factory-YYYY-MM-DD.dump`.
Changes to live tables after the dump can cause count mismatches, including during
a fresh check; investigate a mismatch before treating it as restore corruption.
The temporary container is removed on completion or failure.

## Feature storage and commands

After merge, the orchestrator installs the reviewed Python revision using the
existing installation procedure, then runs `sudo factory-cplane migrate`.
Migration 004 adds feature tables independently of slices, notices and sessions.
It seeds FAC (factory), LAB (homelab-v2), CTL (control-plane), STU (studio), MED
(med-ask), and NEW (work with no project yet). Repository names are optional;
NEW has no repository. Project keys are permanent.

Feature commands require `CPLANE_DATABASE_URL`; the file store is refused. For
example (use the node's `sudo factory-cplane` wrapper there):

```sh
cplane --actor planner feature add FAC 'Example functionality'
cplane feature list --project FAC --stage shortlist --json
cplane feature show FAC-F1 --json
cplane --actor chat:example feature stage FAC-F1 grilling
cplane --actor planner feature move FAC-F1 LAB
cplane --actor planner feature section FAC-F1 Problem --file problem.md
printf 'Some Markdown\n' | cplane --actor planner feature section FAC-F1 Solution
cplane feature history FAC-F1 --section Problem
cplane --actor planner feature revert FAC-F1 1
```

`add PROJECT TITLE` defaults to shortlist and accepts `--stage` for direct
creation. Migration 007 replaces per-project order with one order per stage,
across every project. Existing rows are ordered by project, then their old
position during migration. Project moves preserve their stage position.
Stage entry appends to the bottom, except returning from testing or parked to
building, which places the feature at the top. Positions may have gaps after
stage moves; explicit placement renumbers the whole stage atomically:

```sh
cplane feature place FAC-F1 --top
cplane feature place FAC-F1 --bottom
cplane feature place FAC-F1 --before LAB-F2
cplane feature place FAC-F1 --after LAB-F2
cplane --actor chat:example feature mark FAC-F1 design
cplane --actor owner feature mark FAC-F1 review
cplane feature mark FAC-F1 review --clear
```

Placement accepts exactly one option; the anchor must be another feature in the
same stage. IDs and aliases both work. Marks are nullable timestamps returned by
`show` and JSON output; setting or clearing a mark records an actor/time event.
Marks persist across stage changes until explicitly cleared. Marks accept owner,
chat, and runner actors; the move table below controls stage authority.

`feature stage ID STAGE` enforces these moves. Actors are `owner`, `chat:<id>`,
and `runner`, passed with `--actor` (default owner). A chat is responsible for
obtaining the owner's agreement; this code does not check it. Other actor names,
unsupported moves, and repeating the current stage are refused in one sentence.

| From | To | Actor | Condition |
|---|---|---|---|
| shortlist | grilling | owner, chat | |
| grilling | ready | chat | agreed design and at least one linked slice |
| ready | next | owner, chat | |
| next | building | runner | |
| building | testing | runner | |
| testing | done | owner, chat | passed review |
| testing | building | chat, runner | |
| next | ready | owner, chat | |
| ready | grilling | owner, chat | |
| grilling | shortlist | owner, chat | |
| building | next or ready | owner, chat | pause linked running slices |
| any except parked | parked | owner, chat | from building, pause linked running slices; otherwise none running unpaused |
| parked | stage it left | owner, chat | destination entry conditions again |

Parking records the stage it left and only permits return to that stage; return
clears the recorded stage. Direct creation in parked has no return stage.
Ready entry from grilling or parked requires `design_agreed` and a linked slice;
done entry requires `review_passed`. A linked slice runs when issued or awaiting handover and not
paused. Leaving Building for Next, Ready or Parked sets those running slices to
paused in the same validated transaction. The pipeline logs its pause ownership;
when the feature returns to Building, the runner clears only pauses it owns. An
existing manual pause, or a later explicit pause command, remains in place. Pending
automatic start slots are cleared on these moves and scheduled again on return.
Pause uses the existing runner pause mechanism: it prevents subsequent delivery
and launches and does not terminate an executor already running. Backlog import still
writes its mapped stages directly, bypassing move gates.

Slices retain their free-text `feature`. `add` and `edit` also accept optional
`--feature-id ID_OR_ALIAS`, checked against Postgres while holding the store's
transaction lock. The supplied ID or alias is retained, and remains linked after
a project move. Setting this field requires Postgres. Existing slices need no
new field; issued and awaiting-handover slices still permit only title and
dependency edits. There is no inference from the free-text field.

Migration 007 also seeds `building_limit` and `waiting_limit` to 3:

```sh
cplane limit show
cplane limit set building_limit 4
cplane limit set waiting_limit 2
```

Values must be whole numbers of at least 1. Limit commands require Postgres.
Once per runner pass, under the pass's existing database lock and active store,
the pipeline step consumes these settings:

- A Building feature is waiting if any linked slice has open, unanswered
  attention. It is active if at least one linked slice is not accepted and it is
  not waiting. Imported Building features with no slices count as neither.
- While both the active count is below `building_limit` and the waiting count is
  below `waiting_limit`, the first Next feature with linked slices enters
  Building. Empty Next features stay where they are and are skipped.
- Building features are considered in stage order. Their ready slices with all
  dependencies accepted are slotted immediately, just as with `cplane start`.
  An independent slice can start even if another slice of the feature is waiting.
  Returning from Testing places a feature first, so its ready slices go first.
- A Building feature with linked slices all accepted enters Testing. Features
  with no linked slices stay in Building.

The launch path still enforces two executors total and one per repository;
capacity or repository conflicts defer slices. Feature moves and automatic starts
are audited on both features and slices with actor `runner`. The step uses a
savepoint: failure rolls it back, emits only `pipeline step failed` on stderr,
and allows the rest of the pass to continue. File-store passes skip this step.
No state schema, migration, session or UI changes are needed.

After merge, the orchestrator installs the reviewed Python revision with the
existing node procedure and runs one normal `sudo factory-cplane run` pass.
Confirm that an empty board stays empty with no feature moves or slice starts.

Each project has a stored counter, advanced under the store's transaction lock.
IDs are never reused after deletion or a project move. Moving assigns a new ID;
all prior IDs resolve to the same feature for every read and mutation. Stage
changes leave the ID unchanged. Features do not alter slices' free-text feature
fields. `list` and `show` support JSON; mutations and `history` print JSON. The
history revision ID, rather than a feature ID number, is passed to `revert`.

Sections are named, ordered by their first save, and contain Markdown of at most
16,000 characters (the existing document-note long-text bound). `section` reads
UTF-8 from `--file PATH`, or stdin by default (`--file -`). Empty section text is
allowed. Saving changed text appends a revision with full text, actor and time;
saving identical text leaves history untouched. Reverting to a revision of the
same feature saves its text as a new revision, even if already current.
Revision history is never edited. Titles, section names and actors are nonempty
and limited to 200 characters. Writes use validated locked transactions;
add/stage/move also retain actor/time audit events. Database diagnostics continue
to be sanitized by the store. No new network service, credential or permission is
needed for feature storage; the export below uses the existing planning keys.

After installation and migration, the orchestrator smoke-tests storage:

```sh
sudo factory-cplane --actor orchestrator feature add NEW 'Feature storage smoke test'
# Use the NEW-F<number> returned by add, rather than assuming a counter value.
sudo factory-cplane feature show NEW-F<number> --json
```

Confirm the returned ID, project, title and shortlist stage agree. The smoke
feature remains in Postgres; no delete command is introduced by this slice.


## Feature backlog import and git export

Migration 005 adds the original backlog cells, row text/order and imported stage
as JSON metadata, plus project creation audit events. Existing feature commands,
IDs, sections and scheduler state retain their contracts. Additional projects use
permanent three-letter uppercase keys:

```sh
sudo factory-cplane --actor orchestrator project add XYZ 'Example project' --repository example
sudo factory-cplane feature import-backlog /path/to/backlog.md --dry-run
```

The nine-column table must have Feature, Kind, Area, Repo, Horizon, Order,
Slices, Readiness, Depends on, in that order. Dry run reports row counts, counts
per stage, unknown or ambiguous repositories, and unparsed row line numbers;
it writes nothing. Repository matching is exact; `—` maps to NEW. Add missing
project keys before importing. A real import uses the same command without
`--dry-run`, runs atomically, and refuses any bad row, unknown repository or
existing imported feature. Run it only when the owner authorizes it. Original
cells retain whitespace, Markdown, escaped pipes and code spans. Feature titles
still have the existing 200-character limit; overlong titles are unparsed rows.

Mapping: now → building; next with Readiness starting `ready` → ready;
other next → shortlist; later and parked → parked (from shortlist); done → done.
The original later/parked spelling remains until the feature's stage differs
from its imported stage. Export then derives Horizon: building/testing → now;
shortlist/grilling/ready/next → next; parked → parked; done → done.

`feature export` takes one locked database snapshot, then publishes
`features/<ID>.md` with title, project, stage and sections in stored order, plus
stored slice briefs at `features/<ID>/<slice ID>.md`. It
removes obsolete generated feature IDs after project moves. Git uses a fresh
root-managed directory beneath the fence clean root, host-only settings and
no hooks. Fetch uses the existing read key; only push gets the existing write
key. The SSH remote comes exclusively from `CPLANE_PLANNING_REMOTE` in the
root-only runner environment. Export commits once when content changes and
pushes main without force. A rejected push fetches and regenerates against the
latest main once, preserving concurrent edits outside generated paths; another
rejection fails. Other push failures fail immediately. Only generated feature
Markdown paths, and optionally backlog.md, can be staged; links are refused.
Clean export clones are removed on success or failure. Timer errors are a
single generic stderr line, with no feature text, Git output or remote details.

Keep `CPLANE_BACKLOG_GENERATED` unset while humans maintain the backlog. Export
then never reads or changes backlog.md. Only an owner-run switch to
`CPLANE_BACKLOG_GENERATED=1` enables replacement of its table rows, retaining the
header, separator and all surrounding prose. Imported rows retain order and
formatting byte for byte unless Horizon changes. New features follow imported
rows, sorted by ID, with title, repository and derived Horizon; other cells are
empty. Imported cells remain the original metadata even after a project move.
No Git content is imported except through the explicit import-backlog command.

After merge the orchestrator installs the reviewed revision, migrates, runs a
dry-run import of the real file, then runs one export with no features. Do not
perform a real import or enable the switch during this rollout:

```sh
sudo factory-cplane migrate
sudo factory-cplane feature import-backlog /path/to/backlog.md --dry-run
sudo factory-cplane feature export
sudo install -o root -g root -m 0755 /opt/factory/node/bin/factory-feature-export /usr/local/bin/factory-feature-export
sudo install -o root -g root -m 0644 /opt/factory/node/systemd/factory-feature-export.service /etc/systemd/system/
sudo install -o root -g root -m 0644 /opt/factory/node/systemd/factory-feature-export.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now factory-feature-export.timer
```

The separate hourly timer has `Persistent=true`, so a missed run executes after
boot. The daily state/outbox export remains on its existing timer. No slices,
sessions, runner, UI, new credentials or network services are involved. The
owner reviews and decides whether to merge this cross-repository write slice.

## Run records and replay

After merge, install the reviewed Python revision using the existing node
installation procedure and run `sudo factory-cplane migrate`. Migration 006 adds
`cplane_run_records`; restart the runner and sessions service with the reviewed
installation. After the next real run, the orchestrator checks its record:

```sh
sudo factory-cplane run list --slice <slice-id> --json
sudo factory-cplane run show <record-id>
sudo factory-cplane run total --slice <slice-id>
```

There is one row per slice CLI invocation or owner-message chat invocation.
Resumed invocations are separate rows; collecting the same run again cannot
insert a second row. A unique internal turn key enforces this in Postgres.
Records survive run-folder cleanup. No ticket-attempt service is queried and no
money is calculated. `cplane run` with no subcommand still runs the scheduler.
File-store execution silently skips recording; record commands require Postgres.

Migration 027 adds nullable JSONB `context` to run records, included in existing
UI and CLI reads. Old rows remain `NULL` (unknown); new invocations record an
array sorted by kind and name, with `{kind, name, sha256}` entries. Chats snapshot
their Factory prompt files using `prompts.sha256(name)` and every installed
`SKILL.md` using its bytes before each turn, including resumes. Ordinary slices
load no Factory prompt or skill files and record `[]`; cut and review launches
embed a source skill and hash that source file's bytes, while resumed slice
invocations load no additional Factory files. Hash failures emit a short diagnostic
and retain the entries that succeeded. Before installing this migration, take a
database dump; after installation, check one chat turn's record and the next slice
run's record for `context`.

`run list` accepts `--slice ID`, `--project KEY`, and `--json`. Lists never return
prompt text, including in JSON. `run show ID` prints the full record as JSON,
including the prompt. `run mark ID` selects an eval candidate; `--clear` removes
that flag. These operations do not start agents or change slice state.

Each record includes provider, model, effort, start time, elapsed seconds,
outcome, project key, feature ID when the slice field matches a stored feature
ID, slice ID or chat session ID, and replay fields. Projects are resolved from
repository names in `cplane_projects`; unknown or ambiguous matches are null.
Chats with several repositories have no single project or starting commit, so
those fields are null. Slice session IDs are CLI resume IDs; chat session IDs
are the database session IDs. Outcomes are the slice reply kind (or `failed`),
and `completed`, `failed`, or `interrupted` for chat.

Replay fields are the starting commit, exact prompt, model, effort and skill
version. Prompts retain up to 16,000 characters, using the existing truncation
marker and an explicit `prompt_truncated` flag when cut. Chat prompts contain
the owner's stored message. Starting commits come from the pinned base for a
fresh fenced slice, local HEAD for an unfenced slice, or the trusted Git archive
for a fresh single-repository chat. Fenced resumes and chat resumes use null
when their exact starting commit is unknown; no host Git runs in an agent-owned
workspace to discover it. Chats without a repository also use null. Ticket-flow
jobs retain their existing skills revision; other unversioned skills use null.
Null replay values mean unknown, rather than a guessed value.

Codex per-turn usage events are summed across the CLI output. Claude fields
map `cache_read_input_tokens` to cached tokens and `cache_creation_input_tokens`
to cache-write tokens. Cache-write tokens are retained separately alongside
input, cached, output and reasoning tokens. Missing counters remain null; a
counter missing from any Codex usage report makes that invocation's counter
unknown. Stored counters remain as reported. `run list --json` also includes `turn_tokens`:
for Codex, each counter is the difference from the previous record with the same
session ID and tool, in record ID order. The first record, a record without a
session ID, or a negative difference counts the current value in full. If either
side of a subtraction is null, that turn's counter is null. Claude turn counters
are the stored values. Previous records are considered before slice or project
filters. `run total` sums known turn counters and seconds across records, with a turn
count; a sum with no known values is null. Totals with unknown counters are
therefore partial, not evidence that the missing work used zero tokens.

Recording errors and unreadable usage produce only fixed, single-line stderr
messages without prompts, provider output, database diagnostics or credentials.
Unreadable usage still permits a record with null counters. Inserts use the
store's locked transaction and a savepoint; a failed write cannot abort the
scheduler's state update or a chat reply. There is no guaranteed retry after a
failed write. Session restart reconciliation records interrupted turns with
unknown usage and timing when they were lost. Full prompts are private database
content; treat `run show`, database access and backups accordingly. No UI,
launcher, credentials or additional network service is introduced.

## Workshop pipeline

The Workshop menu links to `/pipeline`, a feature board backed by Postgres. Select a
project to filter the board; drag the handle to reorder or move a feature, or open a
card and use its available move buttons. On touch screens, hold the handle before
dragging. The preview links to the feature's full sections. The board uses the
existing owner move rules and shows their refusal when a move cannot be made. Run
usage totals contain known counters only and can be partial. Feature data appears
when features are added or imported; an empty board is expected before import.

After merging, install the updated Python package and UI dependencies on the node,
rebuild the UI, and open `/pipeline` in Workshop.

## Request a fixed host install

`factory-cplane --actor owner install PROJECT/SLICE` records a request for an
open, unanswered `node-step`. `--actor chat:<id>` is also accepted. It starts no
executor and runs no node-step text. The next scheduler pass starts a separate
root systemd unit; it survives the pass ending and the UI/sessions restarting.
Only one request may be pending or running across all slices. Requests use the
existing validated, locked, atomic state mutation path, logs and notices; state
remains version 1. `POST /api/slices/PROJECT/SLICE/install` records the same request
as `owner`, requiring the existing `X-Factory-UI: 1` guard. There is no UI button.

One-time setup for this change, from the reviewed merged archive on the node:

1. Bootstrap the new Python modules and reviewed `node/install` into the existing
   `/opt/factory` installation using the manual archive procedure above. Preserve
   the existing fence files. Write the merged revision to `REVISION`, sync Python
   3.13 with `--frozen --no-dev`, and rebuild the UI. Install the launcher:

   ```sh
   sudo install -o root -g root -m 0755 /opt/factory/node/bin/factory-install /usr/local/bin/factory-install
   sudo install -d -o root -g root -m 0700 /var/lib/factory/install
   ```

2. Add exactly this assignment to root-only `/etc/factory/runner.env`:

   ```ini
   CPLANE_INSTALL_REPOS='TelesforoAleix/factory'
   ```

   Entries are comma-separated exact GitHub `owner/repo` names. Leave every other
   repository unlisted. Keep `CPLANE_STATE` and `CPLANE_RUNS` identical for the
   runner and installer. The existing `PATH` must include `/usr/local/bin` and
   `/opt/factory/.venv/bin`. Host requirements are `gh`, `uv`, Docker, `curl`,
   systemd, and Python 3.13 installed under `/opt/python`. The token remains at
   `/etc/factory/github-token`, root:root mode 0600. Never copy runner.env or the
   token into UI configuration, archives, fenced workspaces, or chat sessions.

3. Restart `factory-ui` to expose the route, then request installation of this
   slice with `sudo factory-cplane --actor owner install factory/IN1`. Let the
   timer run the next pass, or explicitly run `sudo factory-cplane --actor runner
   run`. Do not invoke the installer from inside a runner pass or the site.

The unit calls `/usr/local/bin/factory-install PROJECT/SLICE`. Root may also invoke
that command directly for an open node step; it records a request and starts
the same separate systemd unit. The
launcher reads the runner's private merge metadata, checks the repository against
`CPLANE_INSTALL_REPOS`, verifies the exact SHA is an ancestor of GitHub `main`,
and downloads that SHA's archive using the host token. It rejects links and
traversal in archives. It runs **that commit's** `node/install` with no GitHub
token in its environment. Failed verification never runs an archive's code.
The host-wide lock is `/var/lib/factory/install/lock`.

The reviewed installer keeps the old code in `/opt/factory.previous`, without
`.venv`; it reuses and syncs the environment, writes `REVISION`, fixes ownership
and permissions, builds the UI using `node:22-slim`, removes `node_modules`, runs
additive migrations, installs changed launchers and systemd files, reloads
systemd, restarts `factory-ui` and `factory-sessions`, and checks
`http://127.0.0.1:8300/`. Removed launchers/units are removed too. It preserves
existing `node/cli/`, `node/proxy/`, `node/compose.yaml`, `node/check-fence.py`,
and `node/bin/factory-cli`, reporting changed paths as `manual: <paths>`. The
fence launcher stays unchanged in `/opt/factory`, and `/usr/local/bin/factory-cli`
is never touched by the installer. Updating or rebuilding the fence remains a
human operation.

A failed build, migration, restart or health check restores the previous code and
managed host files, re-syncs Python, restarts and checks the services, then reports
failure. **Migrations are not undone.** A failure during rollback needs operator
repair; a failure result never claims the old installation is healthy. Failed
script output is bounded in the private result and a short tail reaches the
Failure card and owner notice, as described below. Environment variables are
never printed and credentials are never added to output. The node-step text is
never evaluated as a command.

Results are small atomic mode-0600 JSON files under
`/srv/factory/runs/<anchor-hash>/installs/<request-id>.json`. The next pass answers
the node step with `Installed <commit>` on success. A failed script leaves the
node step open for owner retry and shows a Failure card; manual protected-file
paths still raise an escalation. Units use stable `factory-install-<request-id>` names,
start without blocking the pass, and remain loaded after exit, so a pass restart
can find them without starting a second installation. A completed unit with no
result, or a lost unit after persisted launch intent, escalates; it is never
automatically replayed. Inspect status with
`sudo systemctl status factory-install-<request-id>` and verify `REVISION` and
service health before resolving an escalation. Finished units and private result
files may be cleaned up by the operator after their result has been consumed
and the node step is closed. Retain failed results while that step is open: they
pin retries to the same repository and merged SHA.
Installations are never requested automatically after a merge.

## Project skills

Skills live only in reviewed `skills/<name>.md` files. Their first line is
`--- {"name": "<name>", "description": "<short description>"}`; the remaining
lines contain instructions. Names use lowercase letters, digits and hyphens.
New skills arrive through a PR. Nothing writes to this directory at runtime.

After merging, the orchestrator installs the reviewed revision with the existing
node procedure, runs `sudo factory-cplane migrate`, and runs
`sudo factory-cplane skill list`. Restart the runner and sessions service with
the new installation. Migration 008 adds project switches and session snapshots.

```sh
sudo factory-cplane skill list
sudo factory-cplane skill list --project FAC
sudo factory-cplane skill on grilling FAC
sudo factory-cplane skill off grilling FAC
```

The unfiltered list includes name, description, version and the enabled project
keys. A project-filtered list contains only skills enabled for that project.
Commands require Postgres. Unknown skills and project keys are refused.
With no switch row, `cut`, `slice-review` and `grilling` are enabled; other
skills are disabled. Explicit off rows override the defaults. New projects
inherit the same defaults.

A chat's project comes from a single repository with one matching project.
No repository, multiple repositories, unknown repositories and ambiguous matches
use only the defaults. The first claimed turn saves the enabled names and
revision on the session. A fresh workspace gets those skills under
`.claude/skills/<name>/SKILL.md`, with standard YAML frontmatter for Claude,
and a short list with paths in `AGENTS.md` for Codex. Switch changes affect new
sessions. Resumes never refresh, repair or walk an agent-owned workspace.
Existing resumed sessions retain their workspace; their unknown skill revision
remains null.

Website grills use the grilling skill from this same catalog. They still name
the planning document and repositories in the opening message. The skill asks
one question at a time, records decisions, resolves contradictions and ends
with the agreed design mark and slice cutting.

New slice invocations record the installed repository revision in
`skill_version`. Chats record their saved workspace revision, including resumed
and interrupted turns. On the node, version comes from `/opt/factory/REVISION`;
in a checkout it is HEAD, with uncommitted skill changes refused. Historical
records are unchanged. State stays version 1. No fence, ownership, service,
credential, UI screen or runtime dependency changes are required.
`GET /api/skills` exposes only catalog metadata and enabled project keys.

## Chat records

Project repositories may be plain names such as `factory`, fully qualified
`owner/name` values, or absent. Absent repositories become an empty chat repository
list. For a plain name, existing Factory sessions supply an exact repository
match when unambiguous; otherwise a single shared owner from Factory sessions
and slice repositories supplies its namespace. Home Lab sessions do not supply
this evidence. Unknown or ambiguous owners leave
the plain name stored without blocking chat creation or entry into Grilling.
The sessions service retries resolution when claiming a turn. If it cannot name a fully qualified repository, it marks the message failed and
adds a system message explaining that the repository is unknown; unrelated chats
can run.
Once resolved, the full repository name is saved before workspace preparation.
The fence continues to accept only validated `owner/name` repositories.

Migration 009 keeps session and message IDs, queued turns, saved CLI resume IDs,
repositories and per-chat tool/model choices. The oldest Home Lab session becomes
the orchestrator; all other existing sessions become `legacy`. An empty database
gets one idle Home Lab orchestrator. Partial unique indexes allow one orchestrator,
one project chat per project key and one feature chat per stable feature identity.
Old session creation and message routes remain available for plain legacy chats.

A feature entering Grilling gets its feature chat and queued automatic `system`
opening message in the same locked transaction. The opening contains its current
ID, title, project and all sections, followed by the instruction to run the grill.
Creation also applies to features added directly at Grilling. Re-entry reuses the
existing chat. Failed chat creation rolls the stage and audit event back. A project
move updates the linked project and displayed feature ID; the original workspace
and repository snapshot remain unchanged. Entering Done archives the feature
chat. Reading an archived chat leaves it archived; a new owner message unarchives
it. Existing failed-session refusals still apply.

The sessions service claims queued owner messages before queued system events,
then uses message ID order within each role. It runs one message per invocation
and resumes the saved CLI session. The CLI receives system text prefixed with
`Workshop event: `. The original text, role and `automatic` flag remain in the
database. System events and Workshop delivery notices have `automatic: true`;
owner messages and normal model replies have `automatic: false`. Archived chats
are excluded from claims. Two chat turns may run at once, with overlapping
repository snapshots serialized. Commands and web handlers only write records;
the existing sessions service performs execution through the existing fence.

A chat is `waiting` if an assistant reply is newer than `last_read_at`, or if it
has an assistant reply and no read time. `open` marks it read and returns the chat
and its messages atomically. Marking it unread clears the read time. A chat with
no assistant reply is never waiting. Listing, reading message history through the
old polling route, and fetching chat metadata do not update read time.

All chat commands require Postgres and print JSON:

```sh
sudo factory-cplane chat list
sudo factory-cplane chat list --kind feature --project FAC --no-archived
sudo factory-cplane chat project FAC
sudo factory-cplane chat open 123
sudo factory-cplane chat read 123
sudo factory-cplane chat unread 123
sudo factory-cplane chat configure 123 --model example-model
sudo factory-cplane chat defaults
sudo factory-cplane chat defaults feature --tool codex --model example-model
```

Defaults are stored per kind as `chat_tool` and `chat_model` and are copied when
new chats are created. Changing a default leaves existing chats alone. Migration
uses the oldest installed Home Lab tool/model for orchestrator defaults and the
oldest Factory choice for other kinds; absent an installed choice it seeds
`codex` and `gpt-5.3-codex`. Set reviewed provider/model choices before using
new automatic feature chats. A running chat refuses configuration changes.
Migration 010 keeps a separate CLI resume ID for each provider and marks existing
resumed workspaces as prepared. Switching tool selects that provider's saved ID,
or starts a new CLI conversation if it has not run in the chat before. Changing
the model keeps the selected provider's resume ID. The original workspace and
skill snapshot are reused: the host performs the same ownership and read-only
export checks and never refreshes, repairs or writes the prepared workspace.
Each provider keeps its own conversation history; messages are not replayed into
the other provider. Resume IDs remain private runner metadata.

The API preserves the existing mutation guard (`X-Factory-UI: 1`):

- `GET /api/chats?kind=feature&project=FAC&archived=false` lists records with
  kind, project, current feature ID, archive, waiting and read-time fields.
- `GET /api/chats/123` fetches metadata without marking it read.
- `POST /api/chats/123/open` marks read and returns metadata plus messages.
- `POST /api/chats/123/read` and `/unread` change the read marker.
- `POST /api/chats/project` with `{"project":"FAC"}` creates a project chat;
  a duplicate is refused.
- `PATCH /api/chats/123` accepts `tool` and/or `model` only.
- `GET /api/chats/defaults` lists defaults; `GET` or `PATCH
  /api/chats/defaults/feature` reads or changes that kind's `chat_tool` and/or
  `chat_model`.

Existing `/api/<area>/sessions` and message routes continue working and expose
the additional record fields. CLI resume IDs remain excluded from chat API and
chat command output. The Workshop tool is described below. The fence,
workspace ownership, UI screens, credentials, runtime dependencies and scheduler
state version remain unchanged.

After merge, request the existing install command for `factory/CH1`:

```sh
sudo factory-cplane --actor owner install factory/CH1
```

The reviewed installer runs the additive migration and restarts UI and sessions.
After it reports success, inspect `sudo factory-cplane chat list` and
`sudo factory-cplane chat defaults`. No manual state edit or new service is needed.

## Workshop tool for chats

Migration 011 adds a compact successful-write audit (`chat`, operation and time).
Before each orchestrator, project or feature chat turn, `factory-sessions` creates
`workshop.sock` inside that turn's root-owned run folder. The socket is owned by
21000:21000 with mode 0600. The folder is mode 0755 so the fenced UID can traverse
its existing `/run/factory` bind mount, but cannot replace the socket or the
root-owned, read-only MCP client and configuration files. The socket closes and
is removed when the CLI returns or raises, including timeout and uncertain
container-cleanup failures. Interrupted services lose the listener; startup reconciliation removes the old
socket after container cleanup, and subsequent turns use fresh run folders. No separate daemon, port, token or credential is added.

The copied `workshop_mcp.py` uses Python's standard library. It speaks newline
JSON-RPC MCP over stdio and relays requests through the Unix socket. The host
holds chat identity; supplied chat IDs, actors and other identity arguments
cannot select another chat. Each socket has its own 50-tool-call allowance,
including refused tool calls; all later tool calls are refused. Initialization,
tool discovery and protocol notifications do not consume that allowance.
Requests are limited to 512,000 bytes (including JSON escaping); brief text is
limited separately to 64 KiB. Stalled socket reads time out after two seconds.
Unexpected host failures return a fixed message; store refusals retain their
short sentence.

The operations are `board`, `feature`, `slices`, `documents`, `document`,
`save_section`, `set_mark`, `move_feature`, `place_feature`, `add_feature`, `add_slice`,
`raise_decision` and `answer_decision`. `move_feature` takes exactly one of `stage` or `project`;
`add_feature` starts in Shortlist. A feature chat may change only its stable linked
feature, including through aliases after project transfers. A project chat may
change only features in its current project and cannot transfer one outside it.
The orchestrator may write anywhere. Feature chats cannot add features.
Placement uses the board's existing global stage order; an anchor is read-only.
Reads may see the whole board and Library. Documents use the same committed
Markdown export and reader as the Library. Explicit feature and slice field lists
exclude executor/session metadata, attention bodies and logs; `slices` additionally returns stored `brief_text`. Settings, limits,
roles, keys, chat transcripts and run-record prompts have no tool operation.
Nothing deletes, and there is no slice-executor attachment.

Every write uses the store's locked transaction path as `chat:<id>`, with current
chat links and scope checked under the same lock. Existing feature transition,
mark and placement rules apply. Feature revisions/events retain their usual
audit, and the new audit records even successful no-op writes. `raise_decision(text,
recommendation, decision?)` sends a new decision from feature to its current
project chat, from project to Development Orchestrator, and from orchestrator to
the owner. Missing, archived or failed levels are skipped immediately. Paused
or automatic-turn-limited project and orchestrator chats still receive the
decision and become its holder; the automatic message waits until reactivation.
A relay is one automatic system message naming the decision id, first chat's
title, text and recommendation. Only a decision reaching the owner appends an `owner-check` notice for Home and the phone; it names the
first chat and links to the orchestrator for the owner's reply (the caller if
no orchestrator exists). A paused project or orchestrator has one Home pause card,
`<chat title> needs help`, with Reactivate and Open chat actions; opening it does
not dismiss the pause card. Feature pause cards retain their existing text and
read behavior and also offer Reactivate. The owner-only
`POST /api/chats/<id>/reactivate` requires `X-Factory-UI: 1`, resets `auto_turns`
to zero and clears `auto_paused`, and logs actor `owner`. It sends no message
and starts no turn itself; queued automatic messages can then run as usual,
and the pause card disappears. No workshop tool can reactivate a chat.

Only the current holding chat may pass a decision up with `raise_decision` and
its id, or close it with `answer_decision(decision, text)`. An answer is a system
message to the first chat, including after several relays. Closed decisions
refuse further answers and passes; decisions at the owner cannot be passed again.
The orchestrator uses `answer_decision` when the owner replies. Chats answer only
from the brief or recorded decisions; owner-only items always pass on. Decision
snapshots use the existing notices log with event `workshop-decision`, ignored
by Home and the phone export allowlist. Delivery, holder validation and snapshots
share the store transaction; no table, migration or state-v1 change is needed.

The image pins were checked with `codex --version` (0.162.1) and
`claude --version` (2.1.318). Codex receives the server before `resume`, if any:

```text
-c mcp_servers.workshop.command="python3"
-c mcp_servers.workshop.args=["/run/factory/workshop_mcp.py"]
```

Claude receives `--mcp-config /run/factory/workshop-mcp.json`. Its JSON contains
`{"mcpServers":{"workshop":{"command":"python3","args":["/run/factory/workshop_mcp.py"]}}}`.
The same configuration is passed on new turns and resumes. Local checks used
`codex mcp get workshop --json`, Codex app-server `mcpServerStatus/list`, and a
Claude print turn against a local mock model endpoint. Both CLIs initialized the
stdio relay and discovered all 11 tools. Claude deferred tool discovery was
disabled only in that isolated mock test to inspect the outgoing tool schemas. No changes to
`factory-cli`, the image, proxy, fence network or version 1 scheduler state are
needed. Legacy chats receive no workshop server.

After the owner approves and merges CH2, use the existing install procedure:

```sh
sudo factory-cplane --actor owner install factory/CH2
```

After the reviewed installer reports success (including migration and service
restarts), run a project or feature chat turn asking it to read the board and
request one disallowed move, for example Shortlist directly to Building. Confirm
it reports the store refusal, the feature remains unchanged, and that turn's
`/srv/factory/runs/session-turn-<turn-id>/workshop.sock` no longer exists. Check
both providers when switching the chat's tool. This host boundary requires owner
merge approval; the implementation PR must remain open until that approval.

## Home

Workshop opens at Home. Its project buttons filter attention, waiting chats,
issued slices, Next and pipeline counts. The attention board puts failures first,
followed by reviewed approvals, node steps, chat decisions, questions, stuck
slices and the waiting limit. Accept confirms the current PR; Install requests
the existing fixed installer only for repositories in `CPLANE_INSTALL_REPOS`.
The site must receive the same value as the runner. Other node steps show their
text. Actions use the existing owner mutation guard and store checks.

Stuck cards require a runner notice for the current stalled interval and disappear
when the slice advances. Chat decisions remain until the chat is opened. Next
uses the same global stage order and placement rules as Pipeline, including when
filtered by project. Home polls every 30 seconds; actions refresh immediately.
After merging this change, request the existing fixed install:

```sh
sudo factory-cplane --actor owner install factory/HM2
```

## Chat event wakes

Migration 012 adds durable chat events, automatic-turn counters and the
`chat_auto_turns` setting (default 5). Source mutations capture linked slice
questions/escalations (including failed checks), transitions to In Review, and
features entering Testing. The runner delivers each event once as an automatic
system message to the feature chat, else its project chat, else the orchestrator.
Handover events include the brief path, PR and handover text. Wake text uses the
existing 32,000-character system-message bound, with truncation marked. Testing events name
the linked slices. Merge approvals and node steps continue through the owner.

Delivery and attention ownership commit together under the scheduler lock.
Ownership is stored on the delivery record and joined onto the attention
projection as `chat_id`; the version 1 state document and its schema stay unchanged.
Home omits questions/escalations taken by a chat. Runner question/escalation
phone notices are suppressed when the event is taken. Only decisions that reach
the owner through `raise_decision` appear on Home and the phone; chat relays do not. Previously exported phone
history is never rewritten. Pending events survive restarts and remain queued
when their responsible chat is paused, failed or archived.

The Workshop operations `answer_slice` (`slice`, `text`), `accept_slice` (`slice`)
and `return_slice` (`slice`, `note`) resolve questions/escalations, accept an
In Review slice, or send it back as Issued with a note for the runner to resume.
Each requires a feature link and checks stable feature/project scope under the
same transaction as the mutation. They cannot approve merges, answer node steps
or run installs. No executor receives Workshop. Broad board/slice reads continue
to exclude attention bodies and executor metadata; routed events carry their
responsible chat's context. All successful writes retain `chat:<id>` audit.

Automatic turns count when claimed, including interrupted turns. An owner
message resets the consecutive count; owner turns retain priority. At the limit,
the chat stops claiming automatic turns and taking events, with one `chat-paused`
notice to Home and the phone. Opening the chat does not resume automation; writing
an owner message does. Already queued events retain their order behind owner
messages. Change the limit with:

```sh
sudo factory-cplane limit set chat_auto_turns 5
```

After merging CH3, request the existing fixed installation:

```sh
sudo factory-cplane --actor owner install factory/CH3
```

The installer applies migration 012 and restarts the existing services. No new
service, credential, fence, runtime dependency or manual state edit is required.

Library LB1 validation used Python 3.13 and an isolated temporary Postgres 17.6:
`CPLANE_TEST_DATABASE_URL=<temporary-url> uv run pytest` passed 1,205 tests,
including 186 Postgres tests; one optional Docker test was skipped because Docker
is unavailable in the implementation container. `cd ui && npm test` passed all
18 UI tests, and `npm run build` passed (Vite reports its advisory bundle-size
warning). Synthetic Chromium checks exercised passage selection, draft saving,
persistent highlights, phone back navigation, the project skill switch, batch
sending and grill navigation. The database contained exactly one batch message
and one grill message; no executor ran. There were no page errors or horizontal
overflow. The two committed screenshots are `ui/evidence/library-desktop.png`
(1440px, folder tree, highlighted quote and draft alongside the viewer) and
`ui/evidence/library-phone.png` (390px, viewer/back link, highlighted quote and
the draft below the document). They contain synthetic content only.

## Chats add slices

Workshop `add_slice` takes `feature`, `title`, `brief` (Markdown text), `model`,
`effort`, optional `depends_on` and optional `stop_before_merge`. Feature chats
write only their own stable feature; project chats write only their current
project; the orchestrator can write anywhere. Scope and current stage are checked
under the same store lock as creation. Allowed stages are Grilling, Ready,
Building and Testing. A project without a repository is refused. Plain repository
names use the existing unambiguous owner resolution; an unresolved owner is refused.

New IDs are `<current feature ID>-S<n>` with a persistent per-feature counter;
numbers survive deletion and project moves. Version 1 continues to accept legacy
`project/slice` IDs and additionally accepts this feature slice form, including
in queued commands. Dependencies must already belong to the same stable feature.
Slices append in list order, start in `ready`, use Codex and flow `cli`, and default
`stop_before_merge` off. Creation does not launch an executor; the existing runner
slots linked work only while Building and after dependencies are accepted. Adding
work in Testing leaves the feature there until the chat moves it back to Building.

The `brief` skill is enabled for every project by default. Read it before
`add_slice`; it specifies self-contained briefs, repository-local paths, no
secrets/private content, all required writing sections, before/after merge
validation, and stopping before merge for security boundaries or irreversible
node steps. The host enforces a maximum of 65,536 UTF-8 bytes, rejects NULs and
requires the cutter's `Fixed decisions` or `Do not` section check. Requests now
allow 512,000 bytes so a full brief fits even with JSON escaping.

Migration 014 adds `brief_id` references backed by immutable Postgres brief rows,
with actor and time, and a per-feature slice counter. `slices` includes stored
`brief_text` so chats can review the original brief. Successful `add_slice`
operations also record chat and time in the workshop audit, feature events,
slice logs and notices. Brief text has no update operation; corrections are new
slices. Planner edits cannot detach the stored brief or change its slice identity,
repository or feature link. The runner reads stored text directly and retains it
in the existing job record for resumes. File-path briefs keep their existing pull,
read, frontmatter handling and validation behavior.

The hourly host feature export writes stored text byte-for-byte to
`features/<current feature ID>/<slice ID>.md` alongside the feature Markdown.
Feature transfers preserve existing slice IDs and move exports to the current
feature folder. No chat receives git write credentials or any new executor
attachment. Merge approval, installs and the fence are unchanged.

After owner approval and merge, request the reviewed install:

```sh
sudo factory-cplane --actor owner install factory/SL1
```

The installer applies migration 014 and restarts the existing services. Check the
new tool in a feature chat, add a deliberately chosen bounded slice in Grilling,
and inspect its stored brief export after the next hourly run. Do not start real
executor work solely as an installation smoke test.

## Testing review and chat installs

An installable linked open `node-step` now wakes the responsible feature chat,
falling back to its project chat or the orchestrator under the existing automatic
turn limit. `install_slice` takes only `slice`. It checks current stable scope,
`CPLANE_INSTALL_REPOS`, an unanswered node step, no pending installation, and no
previous chat request for that node-step interval under the store lock. It calls
the existing request path as `chat:<id>` and audits the successful write. No chat
can answer an install-failure node step/escalation or retry a failed install. Those failures
remain Failure cards on Home and escalation notices to the phone. Non-installable
repositories retain the owner node-step flow. Stop-before-merge approval is unchanged.

Home keeps Install visible after chat delivery and shows `Install requested`
while pending. The owner may still press it: an existing pending chat request is
acknowledged without creating another request. The fixed installer, host service,
allowlist and rollback are unchanged. Workshop `slices` includes safe `installation`
status and recorded `handovers`, without exposing raw logs or executor metadata.

The `testing-review` skill is enabled for every project by default. On Testing,
the chat checks install completion and handovers, runs available quick checks,
saves `Testing review 1`, then successive numbered sections, and asks the owner
in the chat to test and reply in open text. Reviews include changes, Workshop
addresses, evidence and owner checks. Later reviews cover only changes since the
previous review. Workshop refuses replacing original review text or skipping a
number; feedback and `Ideas from testing` may be appended to the current review.
There is no form, review table or Ideas page.

A successful chat reply after saving the review creates one durable
`testing-review` notice per Testing entry, using existing chat events and notices;
no schema migration is needed. Home shows a Testing review card with feature ID,
time waited and chat link, after Question and before Stuck. The existing bot
exports this notice to the phone once. Reading the chat does not clear the card.
Writing an owner message or leaving that Testing entry clears it. A later Testing
entry requires a new review and gets its own notice.

The chat immediately sorts each owner point as defect, change, idea or question
and replies one line per point. Defects become correction slices through
`add_slice`, then Building; changes get a short grill one question at a time,
then agreed slices and Building. Ideas are recorded in the review, and questions
answered in chat. The owner can correct the sort. Only an explicit owner pass with
no open point permits the chat to set `review` and move to Done. Architecture,
scope, contract, security, persistence and topology decisions return to the owner.
No slice executor receives Workshop.

After owner approval and merge of TR1, request the existing install command:

```sh
sudo factory-cplane --actor owner install factory/TR1
```

The runner answers the node step after a good install. Confirm Home retains an
Install card while requested, install failures remain with the owner, and opening
a Testing review chat leaves the card until the owner writes. New chat workspaces
receive the default skill; existing prepared workspaces retain their skill snapshot,
so use a newly prepared chat when validating the installed skill.

TR1 validation used Python 3.13.18 and a disposable Postgres 17.9 with synthetic
schemas: `CPLANE_TEST_DATABASE_URL=<temporary-url> uv run pytest -q` passed 1,252
tests, including 226 Postgres tests; one Docker mount test skipped because Docker
was unavailable. The focused chat, Workshop, event, store, session and install
suite passed 253 tests, including 147 Postgres tests. `cd ui && npm test` passed
all 20 tests in 7 files; `npm run build` passed with Vite's bundle-size advisory.
This container lacked the npm launcher, so those two npm commands used its
installed `npm-cli.js` through Node. `git diff --check` passed. Remote CI must
still report a green `test` check, and this PR requires the owner's go before merge.

## Feature corrections and chat archives

Owner corrections are available through the CLI:

```sh
sudo factory-cplane --actor owner feature title FAC-F1 "Read enabled chat skills"
sudo factory-cplane --actor owner feature close FAC-F1 --reason "Already completed outside the pipeline"
sudo factory-cplane feature history FAC-F1
sudo factory-cplane chat archive 42
sudo factory-cplane chat unarchive 42
```

`feature title` replaces the title without changing the ID or aliases. It rejects
blank titles and titles longer than 120 characters. `feature close` requires the
owner actor and a nonblank reason, and records a correction from any stage except
Building or Testing to Done. It opens no chat and launches nothing. Done still
archives the feature's chats. Ordinary stage transitions and their gates are
unchanged. Both correction commands appear in unfiltered `feature history` with
actor and time. Correction rows use `event_id` and `event`; document revisions
retain their existing `id`, `section` and `text` and can still be reverted.
Section-filtered history continues to contain document revisions only.

Chats also have an Archive/Unarchive secondary button in their header. The
Development Orchestrator cannot be archived. Archived chats stay in the Archived
chats group and keep their transcript. Their Decision cards, automatic pause
cards, Testing review waits and waiting marks leave Home. Unarchiving restores
open marks. A running turn finishes; owner messages can run while the chat stays
archived. Automatic messages already queued when archived, or arriving while
archived, remain recorded as done without execution. Routed events are retained
with their destination and delivered flag. Unarchiving also consumes undelivered
events targeting that chat, so skipped events are never replayed. Future automatic
events run normally, subject to the existing automatic-turn limit.

The session service uses umask 0077 and runs as root, whereas both CLIs run as
21000:21000. Previously installed skills inherited root-only directories and
files. Installation now sets the root-owned skill directories to 0755 and skill
files and AGENTS.md to 0644. The workspace root remains private at 0700 and owned
by 21000:21000. On resume, the service also repairs missing read/traverse bits for
the saved skill snapshot and its AGENTS.md. It opens each component without
following links, validates root ownership and non-writability, rejects file hard
links, and holds descriptors through validation and chmod. It never refreshes
instruction contents, walks the workspace, changes unrelated permissions or adds
mounts. Legacy sessions without a skill snapshot are left untouched.

After merge, request the reviewed install:

```sh
sudo factory-cplane --actor owner install factory/DP2
```

The orchestrator then checks that an archived chat's existing Decision card is
gone from Home. Existing chats with a saved skill snapshot have their instruction
modes repaired at their next turn; no workspace recreation is required.

## Slice order inside a feature

Drag a slice handle in the pipeline preview's Slices list to place it before or
after another linked slice. The equivalent Postgres command is:

```sh
factory-cplane --actor chat:9 slice place factory/SD2 --before factory/SD3
factory-cplane --actor owner slice place factory/SD3 --after factory/SD2
```

Only planned, researching and ready slices that have never been issued can move.
Paused slices follow the same rule. Running and finished rows stay at their
positions; moves across them are refused. A move cannot place a slice before a
linked dependency, including by moving the dependency down. Dependencies outside
the feature still gate execution as usual. Each successful placement records the
actor in the slice log and feature history under the shared transaction lock.

Migration 016 stores this order separately from version 1 slice documents. The
first placement starts with the existing linked sequence; new unordered slices
follow the saved rows in their existing sequence. Features without a saved order
retain their existing sequence. The runner uses this sequence within each feature
and still checks readiness, pause, dependencies, due slots and executor capacity.

After merge, request the reviewed installer:

```sh
sudo factory-cplane --actor owner install factory/SD1
```

The installer applies migration 016, rebuilds the UI and restarts the existing
services. Check a placement survives a reload and that fixed rows have no handle.

## Failed install output and retry

The host installer gives `node/install` the fixed PATH
`/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`; on failure the
script follows its fixed stderr message with one line naming the exception and
missing program, failed program and return code, or other exception message (at
most 200 characters), without dumping the environment or other command arguments.

A nonzero exit from the reviewed `node/install` now records the last 8,192 UTF-8
bytes each of stderr and stdout, the exit code, repository and merged SHA in the
existing private install result (`runs/<state-hash>/installs/<request>.json`). A
partial leading UTF-8 character is omitted. Child command stderr reaches this
record, including migration errors. No environment variables are printed or
credentials added to the installer environment; output is retained without
heuristic scrubbing.

Home's Failure card includes a short tail (up to 512 bytes per stream) and offers
**Retry install** beside **Review**. To inspect the full bounded output, use:

```sh
sudo factory-cplane show factory/IF1b
```

A failed script leaves the original node step unanswered and retains the job's
merge metadata. Only the owner may retry, through Home or the same install
command. Retry uses the recorded repository and exact merged SHA; a different
repository or SHA for that open node-step interval is refused before downloading
or executing code. There is no automatic retry. Answering the node step by hand
still closes it and resumes the existing handover flow. Successful installs that
require manual protected-file work retain the existing escalation behavior.
The version 1 state schema, root execution boundary, main reachability check,
repository allowlist, credential isolation and rollback behavior are unchanged.
Older failed installs whose merge metadata was already cleared are not repaired
by this change.

After the owner merges this security-boundary change with green `test` and `ui`
checks, request the reviewed installation:

```sh
sudo factory-cplane --actor owner install factory/IF1b
```

## IB1 inbox and Secretary installation

After the owner merges IB1 with green `test` and `ui` checks:

```sh
sudo factory-cplane --actor owner install factory/IB1
```

Before installation, confirm `/etc/factory/ui.env` remains root:root 0600 and
contains only the existing `CPLANE_DATABASE_URL` assignment. Systemd loads this
file before dropping intake privileges; do not make it group-readable. If the
node uses a database password/service file inaccessible to the intake account
(including home or host `/tmp` paths hidden by the sandbox), stop and escalate
rather than widening permissions. Credential options are described in
[the intake protocol](inbox.md).

The reviewed installer applies migration 019, creates the `factory-intake`
system group and login-disabled system user with no home, adds `homelab-bot` to
the group, installs/enables the local intake service and restarts the existing
Factory services. Restart the separately managed Telegram bot service to acquire
its new supplementary group; its code and private arrival folder are unchanged.
Confirm `systemctl is-active factory-intake` and that
`/run/factory-intake` is factory-intake:factory-intake 0750 and `intake.sock` is
factory-intake:factory-intake 0660. Confirm the running service UID is the dedicated
user, with no capabilities and no writable paths beyond its runtime/private
scratch space. Attachments are stored in Postgres, so no attachment directory is
made writable. The unit enables ProtectSystem=strict, ProtectHome, PrivateTmp and
NoNewPrivileges.

Run typed synthetic entries for each Secretary label:

```sh
sudo factory-cplane --actor owner inbox add 'Synthetic idea: a switch to hide completed work' --kind idea --target development
sudo factory-cplane --actor owner inbox add 'Synthetic feedback: the completed-work switch is hard to find' --kind message --target development
sudo factory-cplane --actor owner inbox add 'Synthetic question: what does Shortlist mean?' --kind message --target development
sudo factory-cplane --actor owner inbox add 'Synthetic update request: which features are currently Building?' --kind message --target development
sudo factory-cplane --actor owner inbox add 'Synthetic order: please discuss adding a completed-work switch; do not implement it' --kind message --target development
sudo factory-cplane inbox list
```

Verify one Secretary wake per entry, labels and routes, retained original words,
idea provenance, replies reaching the existing phone notice path, and automatic
pause after the configured consecutive-turn limit. Use an owner chat message to
continue a paused chat. The bot does not submit to the socket until its separate
integration is implemented. See [the intake protocol and API](inbox.md).

## Stored models, roles and runner limits

Migration 021 stores model IDs, labels, supported efforts and refresh times in
Postgres. Choosing never launches a CLI. Explicit updates replace one tool's rows
atomically; failure retains its old list and returns the fixed reason
`Model update failed; previous list kept.` No probe output or credentials are saved.

```sh
sudo factory-cplane models update codex
sudo factory-cplane models update claude
sudo factory-cplane models list
```

Codex reads visible entries from `codex debug models`. Claude probes `fable`,
`opus`, `sonnet`, `haiku` once each and records their full IDs and efforts low,
medium, high, xhigh, max. Refreshes use the chat container, UID and login mounts.
Claude aliases that refuse or return no model are skipped and named in the update result; at least one alias must resolve for the update to succeed.
The root session supervisor handles web requests while chat workers are idle,
without holding the database lock during probes, and cleans up interrupted runs.

Seven stored roles replace chat defaults and `roles-command`: orchestrator,
project, feature, secretary, light, standard, strong. Chat roles retain installed
tool/model choices and start at medium effort, except Secretary's low. Role
changes apply on the next turn. Per-chat overrides win; JSON null restores
inheritance. Legacy conversations retain explicit provider/model choices and
follow the project role's effort. Both CLIs receive effort on every turn, and
provider switches retain separate resume IDs. A removed choice keeps working;
API `in_list: false` means “not in the list”. New choices require catalog validation.

Use `cplane add --level light|standard|strong`, default standard. Starting routes:

| Level | Model | Effort |
| --- | --- | --- |
| light | gpt-6-luna | low |
| standard | gpt-6.1-terra | medium |
| strong | gpt-6.1-sol | medium |

The runner resolves the role at launch; explicit slice fields win. Existing
routes stay explicit. Claude IDs pass through without heuristic mapping. Postgres
stores levels and overrides outside version 1 documents; `show` includes the
level and resolved executor. JSON exports omit this policy metadata. File-only
creation snapshots built-in defaults. `--role` and its command lookup are removed.
Planner mutations retain the locked, validated update and audit path.

| Limit | Initial | Stops |
| --- | --- | --- |
| building_limit | 3 | Promotion when active Building capacity is full |
| waiting_limit | 3 | Promotion when too many Building features have unanswered attention |
| chat_auto_turns | 5 | Consecutive automatic chat turns until an owner message |
| executors | 2 | New slice runs when executor capacity is full |
| repository_runs | 1 | Simultaneous slice runs in one repository |

All five live in `cplane_settings`; use `cplane limit show` and `limit set NAME
VALUE`. Executors accepts 1–4, repository_runs only 1; other validation is unchanged.
Capacity checks reread limits and count issued sessions with missing local run files.
Lowering a limit never kills an existing run.

Owner API writes require `X-Factory-UI: 1`. GET/POST `/api/settings/roles` uses
`{role, tool, model, effort}`; GET/POST `/api/settings/limits` uses `{name, value}`
and returns descriptions. GET `/api/settings/models` returns `models` and latest
`updates`; POST `/api/settings/models/update` accepts `{tool}` and returns HTTP
202 with an id and queued/running status. Poll GET for completion or fixed failure.
Pending requests are deduplicated. Chat configuration accepts effort and nullable
overrides; defaults commands alias roles. Legacy session creation also validates
choices. Workshop's existing add_slice schema advertises stored Codex choices;
Settings has no chat write tool. No Settings page or runtime dependency is added.

After resolving the deployment gate and obtaining green `test` and `ui` checks,
the orchestrator requests `sudo factory-cplane --actor owner install factory/RA1`.
Confirm migration 021, run both updates, inspect the list, and confirm a chat turn
records its role's effort. Add a bounded synthetic slice with `--level light` and
verify its next runner launch uses Luna at low effort. Start it only through the
existing runner or an explicit test; never edit state JSON by hand.

Runner refuses GitHub drafts, title prefixes `[Blocked]`, `blocked:`, `Draft:`, `[Draft]`, and `DO NOT MERGE`/`MERGE BLOCKER` anywhere in title/body (case-insensitive): `PR marked not for merging`, with no merge card.
Runner updates mergeable branches reported behind their base through `gh pr update-branch` (merge commit), pins the new head and waits for CI; update conflicts escalate as `PR conflicts with main; needs a new slice from main`.
A non-fast-forward publish escalates once as `branch was rewritten; merge main instead of rebasing`; an answer resumes the same executor copy without retrying the push first.
In default file mode, for a waiting Codex slice at 99% or higher with usage older than 30 minutes, the runner probes Luna at low effort at most hourly, rereads capacity, discards probe output and workspace, and retains only usage windows from the probe rollout.
After a Codex usage cut, the runner uses a future reset from a report window at 99% or higher, otherwise the message time in UTC, otherwise a 60-minute wait.
Answered attention on a ready, issued or escalated slice without a session starts again from the original brief when capacity is available, using the same start path as a scheduled slice.
The synthetic repair/review test uses increasing logical start timestamps so wall-clock adjustments cannot select an older fake turn; validate with 20 consecutive standalone pytest invocations, without retries.

Before merging, the runner classes changed paths using the target repository's
`.github/change-classes` at the slice's pinned base commit. The highest matching
class wins; unmatched paths are class 1. SQL, migrations, dependency and lock
files are at least class 2. Missing or invalid tables default to class 4 for
`.github/**`, `node/**`, any `Dockerfile` or `compose.yaml`, and class 2 elsewhere;
`.github/**` always requires class 4 even with a table. Class 4 raises an owner
merge card listing up to 20 guard paths and a remaining count. Classes 1 and 2
merge with green CI; the nullable run-record `change_class` records the decision.
A brief's `stop_before_merge` can require approval for any class.

The Postgres-backed runner sends a daily `digest` notice on its first pass at or after 07:00 Copenhagen time, covering the preceding 24 elapsed hours. `cplane digest` prints the latest scheduled digest without writing a notice; `cplane digest --date YYYY-MM-DD` selects the local date of its 07:00 boundary. Counts identify slices without including titles or attention bodies. Task spend is shown only when every recorded task attempt in the window has a known cost; other run costs are not available in the records.

## Service secret files and the runner loop

A later service cutover can supply each service's database URL in its own
read-only secret file with `CPLANE_DATABASE_URL_FILE`. The file is read with
surrounding whitespace stripped; an empty, unreadable or missing file fails
without displaying the URL. Set either this setting or `CPLANE_DATABASE_URL`,
never both. Without the file setting, the existing variable works as before.
Workshop, intake, sessions and the scheduler use the same resolver.

These path settings select the other service files:

| Setting | Default |
| --- | --- |
| `CPLANE_GITHUB_APP_KEY` | `/etc/factory/github-app.pem` |
| `CPLANE_BRIEFS_KEY` | `/etc/factory/briefs-key/id_ed25519` |
| `CPLANE_BRIEFS_KNOWN_HOSTS` | `/etc/factory/briefs-key/known_hosts` |
| `CPLANE_PLANNING_WRITE_KEY` | `/etc/factory/planning-write-key/id_ed25519` |
| `CPLANE_DENY_LIST` | `/etc/homelab/deny-list` |

The App key and deny list must be regular files opened without following a
symlink: either root-owned mode 0600, or owned by the service's effective UID
mode 0400. Other owners and modes are refused, including any group/world read
permission. The deny canary and content checks are unchanged. The later service
containers use a fixed non-root UID and separate read-only secret mounts; no
secret belongs in an environment file.

`cplane --actor runner run --every 60` keeps one process alive, running sequential
passes with a 60-second wait after each pass and its jobs. SIGTERM and SIGINT
stop the loop, unwinding any active pass and releasing its transaction and locks.
A pass failure emits a safe message and the loop continues. Without `--every`,
`run` still performs one pass and does not run the two scheduled export jobs.

In loop mode, the first pass finishing after 03:45 local time each day exports
into the existing `CPLANE_EXPORT_DIR` (which must already exist), using
`factory-YYYY-MM-DD.json` and `.json.outbox.jsonl`, mode 0600, and retaining the
seven newest dated pairs. The first completed pass in each local clock hour
also runs `feature export` without output. Each job is attempted once per due
period; failures emit a content-free line and retry at the next daily/hourly
due time. Scheduling is process-local, so restarting the loop can repeat an
export in the same period.

When `CPLANE_TASK_SUBMIT` is unset, tickets slices are not started or resumed,
and eligibility reports `tickets flow off`. Setting the existing JSON argument
list preserves the host submission flow. The owner has disabled that flow from
the container cutover until a later run interface accepts submissions.

Nothing on today's node changes until a later slice supplies the new settings
and loop command. Install with no new setting; the timers and services keep
working. Existing export scripts and systemd timers under `node/` are unchanged.

## Four contained Factory services (cutover contract)

Since the 2026-11-15 cutover, the four services run healthy using the root
`compose.yaml`, installed by the platform deployer. The owner reviews and copies
the compose file and Dockerfile to `/opt/homelab-deployer/factory/`, beside the
installed application manifest and the three env files. The deployer uses its
installed Dockerfile and compose file, builds from the selected commit, and passes
only `HOMELAB_DEPLOY_TAG`. Every service uses
`homelab-deployer-factory:${HOMELAB_DEPLOY_TAG:?commit required}`.
Each service receives that commit as `CPLANE_REVISION` for installations without a `REVISION` file.
The fence uses the separate `node/compose.yaml`. The four host service units
were stopped at cutover.

Services appear in this order so the deployer's health and migration commands run
in `ui`:

| Service | UID:GID | Command | Supplementary groups |
| --- | --- | --- | --- |
| `ui` | 992:978 | `python -m factory_ui.serve` | none |
| `intake` | 991:977 | `python -m cplane.intake` | none |
| `sessions` | 21011:21011 | `python -m cplane.sessions` | homelab-launch (976), factory-cli (21000) |
| `runner` | 21010:21010 | `cplane --actor runner run --every 60` | homelab-launch (976), homelab-deploy (975), factory-cli (21000) |

At cutover, create the two new service accounts `factory-sessions` 21011:21011
and `factory-runner` 21010:21010. The image includes both accounts with home
`/tmp` and no login shell, so SSH and Python can resolve these UIDs. These are
distinct from fence agent UID/GID 21000:21000 and proxy UID 21001. Every service
has a read-only root, tmpfs `/tmp`,
all capabilities dropped, no-new-privileges, journald logging and
`restart: unless-stopped`. UI, intake and sessions each have 512 MiB memory and
128 PIDs; runner has 1 GiB and 256 PIDs. These limits cover service processes;
the launcher's fence limits remain separate.

All four services join only the external Docker network `homelab_default`.
Their database URL files must name the platform database at host `postgres`.
Only UI publishes a port, `127.0.0.1:8300:8300`, preserving Tailscale's host
loopback endpoint. No service receives Docker access, host networking, devices or
additional capabilities.

Each host bind uses the identical container path and refuses to create a missing
host path. Prepare paths and socket permissions before cutover:

| Service | Read-only binds | Read-write binds |
| --- | --- | --- |
| `ui` | `/var/lib/factory/workshop` | none |
| `intake` | none | `/run/factory-intake` |
| `sessions` | `/srv/factory/briefs`, `/srv/factory/runs` | `/srv/factory/work`, `/srv/factory/clean-sessions`, `/srv/factory/runs/sessions`, `/var/lib/factory/sessions`, `/var/lib/factory/workshop`, `/run/homelab-launcher.sock` |
| `runner` | none | `/srv/factory/briefs`, `/srv/factory/runs`, `/srv/factory/work`, `/srv/factory/clean`, `/srv/factory/exports`, `/srv/factory/bot-export`, `/srv/homelab/factory-state`, `/run/homelab-launcher.sock`, `/run/homelab-deployer.sock` |

At cutover, prepare `/var/lib/factory/workshop` owned by sessions, move the
existing documents into `/var/lib/factory/workshop/ui-docs`, and ensure UI can
read the parent, documents and sibling `.ui-docs.lock`. Sessions stages and
exchanges the documents under that parent. Prepare `/var/lib/factory/sessions`
and `/srv/factory/runs/sessions` owned by sessions (21011:21011), and prepare
`/srv/factory/clean-sessions` owned by sessions with mode 0700. Set
both `/srv/factory/work` and `/srv/factory/runs` to root:root, mode 1733
(sticky, writable and traversable by both services). Existing entries remain
protected by the sticky bit and workspace ownership checks. Host root services
and mode 0711 remain supported.

Stopping `factory-intake.service` removes its systemd `RuntimeDirectory`. Add
`d /run/factory-intake 0750 991 977 -` to a `tmpfiles.d` file, then run
`systemd-tmpfiles --create` after stopping the host unit to recreate the bind.

Planning clones are freshly prepared in `clean-sessions/planning-sessions/`;
existing planning clones under the runner's clean root are not moved.

Sessions reads the runner-owned briefs clone with `CPLANE_BRIEFS_OWNER_UID=21010`.
Only document export accepts that additional owner and marks that exact clone as
Git-safe; the sessions bind remains read-only. Keep the clone folder mode 0750,
owned by the runner with group `factory-sessions`. The clone contents were written
by root with umask 077; run `chmod -R o+rX` on the contents so sessions can read
them, without changing the folder itself. Runner pulls and planning fetches
use the configured `CPLANE_BRIEFS_KEY` and `CPLANE_BRIEFS_KNOWN_HOSTS`, overriding
the clone's host SSH command.

The runner anchors metadata at `/srv/factory/briefs/slices.json`, uses
`/srv/factory/runs`, sends the daily export to `/srv/homelab/factory-state`, and
sets `CPLANE_BOT_EXPORT=/srv/factory/bot-export`. The additional exports mount is
reserved by the cutover contract. Set `/srv/factory/bot-export` to mode 2750
(setgid), group `homelab-bot`. The runner is not in that group; setgid gives new
files the folder's group so the export can `fchown` them to that group. No private
state or export data belongs in Git.

Each secret is an individual read-only bind from
`/etc/factory/secrets/<service>/<name>` to `/run/secrets/<name>`, owned by that
service's UID with mode 0400. Parent directories must allow the owning service to
traverse them. Never mount an entire secret folder or share one service's source
file with another service. Even copies of the database URL and planning write key
have separate service-owned source paths.

| Services | File name | Environment path setting |
| --- | --- | --- |
| all four | `database-url` | `CPLANE_DATABASE_URL_FILE` |
| runner, sessions | `github-app.pem` | `CPLANE_GITHUB_APP_KEY` |
| runner, sessions | `briefs-key` | `CPLANE_BRIEFS_KEY` |
| runner, sessions | `briefs-known-hosts` | `CPLANE_BRIEFS_KNOWN_HOSTS` |
| runner, sessions | `planning-write-key` | `CPLANE_PLANNING_WRITE_KEY` |
| runner | `deny-list` | `CPLANE_DENY_LIST` |
| runner | `eval-task-key` | `CPLANE_EVAL_TASK_KEY_FILE` |

At cutover, create sessions' own `/etc/factory/secrets/sessions/briefs-key`
and `/etc/factory/secrets/sessions/briefs-known-hosts`, owned by 21011:21011,
mode 0400. These individual read-only binds provide planning fetch credentials
and SSH host verification independently of the runner's files.

The compose environment contains secret **paths** and non-secret settings.
At cutover, the owner places required `./ui.env`, `./sessions.env` and
`./runner.env` beside the **installed** compose file. Intake needs no env file.
Each service reads only its own file. Use Compose 2.24 or later for the explicit
`env_file.required` entries. These files contain non-secret settings only; do not copy the old host env files wholesale. Database URLs, keys, passwords
and tokens remain in the individual secret binds above. In particular, an orders
endpoint or planning remote must not embed credentials, and task argument lists
must not contain credentials. These files are consumed by Compose, not mounted
inside containers. No private env file is checked into this repository.

Compose's explicit `environment` overrides its service's env file. The owner
must populate the service files from the existing non-secret configuration:

| File | Settings to carry forward |
| --- | --- |
| `ui.env` | `CPLANE_INSTALL_REPOS`, `CPLANE_TASK_SUBMIT` |
| `sessions.env` | `CPLANE_INSTALL_REPOS`, `CPLANE_PLANNING_REMOTE`, `CPLANE_GITHUB_APP_ID`, `CPLANE_GITHUB_INSTALLATION_ID` |
| `runner.env` | `CPLANE_GITHUB_APP_ID`, `CPLANE_GITHUB_INSTALLATION_ID`, `CPLANE_PLANNING_REMOTE`, `CPLANE_ORDERS_URL`, `CPLANE_INSTALL_REPOS`, `CPLANE_TASK_STATUS`, `CPLANE_TASK_SUBMIT`, `CPLANE_BACKLOG_GENERATED` |

Both App IDs are required positive integers for runner and sessions App
mode; there are no defaults. Keep the install allowlist identical in all three
files so Home, session tools and the runner agree. Sessions needs its own file
because its planning preparation and Workshop install tools read those settings.

Set `CPLANE_TASK_SUBMIT` to the same existing JSON argument list in **both**
`ui.env` and `runner.env`. If tickets are disabled at cutover as currently planned,
omit the assignment from **both** files; the files themselves remain required.
An empty assignment still enables the eligibility flag and is invalid for actual
submission. The runner's `CPLANE_TASK_STATUS` is the corresponding JSON argument
list for polling. The existing host commands still need a supported container
submission interface before tickets can run. Never enable this flag in just one
of UI and runner. Sessions does not execute the runner's pipeline scheduler or
compute the UI's eligibility snapshot, so it does not consume this flag.

### Environment read audit

The audit used `rg -n 'environ|getenv|expanduser|Path.home' cplane/ factory_ui/`
and followed calls from each of the four service commands, including UI request
handlers, session Workshop tools, scheduled runner jobs, and child executors.
An import alone does not make every CLI subcommand reachable. The tables cover
application reads in these packages, including conditional authentication reads;
third-party library environment interfaces are outside this source audit.
`cplane migrate` in UI additionally uses only the shared database resolver.

All four services resolve `CPLANE_DATABASE_URL_FILE` from compose environment as
`/run/secrets/database-url`. The fallback `CPLANE_DATABASE_URL` defaults to unset
and must stay absent, including from env files: setting it together with the file
setting raises an error. Secret values are read from the file, never Compose.

All four explicitly receive `HOME=/tmp` from compose environment, matching the
image default and keeping Python home expansion writable. The image supplies
`PATH` with `/opt/factory/.venv/bin` first, `PYTHONDONTWRITEBYTECODE=1`,
`PYTHONUNBUFFERED=1`, `XDG_CACHE_HOME=/tmp/.cache`,
`XDG_CONFIG_HOME=/tmp/.config`, `UV_CACHE_DIR=/tmp/.cache/uv` and
`UV_PYTHON_DOWNLOADS=never`. These are image defaults, not owner env-file entries.
Sessions and runner also receive `GH_CONFIG_DIR=/tmp/.config/gh` from compose.
Python temp files default to `/tmp`; no extra tmpfs or host mount is needed.

**UI** (`factory_ui.serve`, request handlers and `eligibility.observed`):

| Setting read | Source at cutover | Reader / purpose |
| --- | --- | --- |
| `CPLANE_DATABASE_URL_FILE`, `CPLANE_DATABASE_URL` | compose / unset fallback, as above | `state.database_url` |
| `FACTORY_UI_HOST`, `HOMELAB_API_URL`, `CPLANE_UI_DOCS` | compose: `0.0.0.0`, `http://api:8000`, `/var/lib/factory/workshop/ui-docs` | UI bind, platform API and document reader |
| `CPLANE_INSTALL_REPOS` | `ui.env`; code default empty allowlist | `home.home_data`, installation checks and store chat-event capture |
| `CPLANE_TASK_SUBMIT` | `ui.env`, matching runner; omit in both to disable | `eligibility.eligibility` tests presence |
| `CPLANE_STATE` | compose: `/srv/factory/briefs/slices.json` | `eligibility.observed` anchors the same run hash as runner |
| `CPLANE_RUNS` | compose: `/srv/factory/runs` | `installation.runs_path`, `Runner.__init__`, usage-report lookup |
| `CPLANE_REPOS` | compose: `/srv/factory/work` | `Runner.__init__` during eligibility observation; avoids default `~/Code` |

The paths align metadata names; they grant no filesystem access. UI's decided
mounts do not expose runs or fence logins, so its current eligibility snapshot
cannot see those host job/usage files.

**Intake** (`cplane.intake` and its inbox insertion path):

| Setting read | Source at cutover | Reader / purpose |
| --- | --- | --- |
| `CPLANE_DATABASE_URL_FILE`, `CPLANE_DATABASE_URL` | compose / unset fallback, as above | `state.database_url` |

The socket path is fixed; compose sets `CPLANE_INTAKE_GID=977` for its group. Intake does
not execute arbitrary CLI commands or the runner's scheduler through imports.

The sessions App key is its own copy at
`/etc/factory/secrets/sessions/github-app.pem`, owned by UID 21011, mode 0400,
mounted read-only at `/run/secrets/github-app.pem`, the same in-container path
used by the runner's separate copy. Prepare `/srv/factory/clean-sessions` owned
by 21011:21011, mode 0700, and bind it writable only in sessions. These sessions
binds and App settings are included in the compose contract for cutover.

**Sessions** (`cplane.sessions`, model probes and Workshop tools):

| Setting read | Source at cutover | Reader / purpose |
| --- | --- | --- |
| `CPLANE_DATABASE_URL_FILE`, `CPLANE_DATABASE_URL` | compose / unset fallback, as above | `state.database_url` |
| `CPLANE_INSTALL_REPOS` | `sessions.env`; code default empty allowlist | Workshop install eligibility and store chat-event handling |
| `CPLANE_PLANNING_REMOTE` | `sessions.env`; code default empty, which refuses planning preparation | `Planning.prepare`, SSH remote without credentials |
| `CPLANE_PLANNING_WRITE_KEY` | compose: `/run/secrets/planning-write-key` | `Planning.git` push identity |
| `CPLANE_BRIEFS_KEY` | compose: `/run/secrets/briefs-key` | `Planning.git` fetch identity |
| `CPLANE_BRIEFS_KNOWN_HOSTS` | compose: `/run/secrets/briefs-known-hosts` | planning SSH host verification |
| `CPLANE_FENCE_COMMAND` | compose: `socket` | turn launch, model probes, cleanup and bundle export |
| `CPLANE_GITHUB_AUTH` | compose: `app`; code default `token` is refused at startup | `fence.github_environment` for repository fetches |
| `CPLANE_GITHUB_READ_ONLY` | entry point forces `1`, whatever the environment says | repository-scoped App tokens with exactly `contents: read` |
| `CPLANE_GITHUB_APP_ID`, `CPLANE_GITHUB_INSTALLATION_ID` | `sessions.env`, required; default unset | `github_app.installation_token` |
| `CPLANE_GITHUB_APP_KEY` | compose: `/run/secrets/github-app.pem`; code default `/etc/factory/github-app.pem` | sessions' own UID 21011 mode 0400 key copy, mounted read-only |
| `CPLANE_BRIEFS_OWNER_UID` | compose: `21010`; default unset retains root/service ownership only | `DocumentExporter` accepts the runner's read-only briefs clone |
| `CPLANE_SESSIONS_CLEAN_ROOT` | compose: `/srv/factory/clean-sessions`, also the code default | sessions' own repository and planning clones; never the runner's root |
| `PATH`, `LANG`, `PYTHONPATH` | image/default inherited `PATH` and `LANG` if present; `PYTHONPATH` unset | `fence.host_environment` forwards only present values |
| `GH_TOKEN` | generated in the authenticated Git child's environment; no deployed value | `python -m cplane.fence credential get` returns the scoped token to Git |

`BRIEFS` and `WORK_ROOT` in sessions remain fixed. `CPLANE_SESSION_RUNS`,
`CPLANE_UI_DOCS` and `CPLANE_SESSIONS_LOCK` configure the session paths in compose
to `/srv/factory/runs/sessions`, `/var/lib/factory/workshop/ui-docs` and
`/var/lib/factory/sessions/sessions.lock`, respectively. `CPLANE_RUNS` separately
names the shared runs root for trust checks (default `/srv/factory/runs`).

**Runner** (`cplane --actor runner run --every 60`, delivery and scheduled jobs):

| Setting read | Source at cutover | Reader / purpose |
| --- | --- | --- |
| `CPLANE_DATABASE_URL_FILE`, `CPLANE_DATABASE_URL` | compose / unset fallback, as above | `state.database_url` |
| `CPLANE_STATE` | compose: `/srv/factory/briefs/slices.json` | CLI metadata anchor and runner |
| `CPLANE_RUNS` | compose: `/srv/factory/runs` | runner, install records and usage-report lookup |
| `CPLANE_REPOS` | compose: `/srv/factory/work` | runner repository base; replaces code default `~/Code` |
| `CPLANE_FENCE` | compose: `1` | `executors.fenced` |
| `CPLANE_FENCE_COMMAND` | compose: `socket` | fenced subprocess launch, bundle export, cleanup and usage probes |
| `CPLANE_USAGE_SOURCE` | compose: `launcher`; default unset | sealed launcher reads; no login file access |
| `CPLANE_DEPLOYER_SOCKET` | compose: `/run/homelab-deployer.sock`; default unset | detached install client; unset retains the host systemd unit |
| `CPLANE_GITHUB_AUTH` | compose: `app` | selects App authentication instead of the legacy token file |
| `CPLANE_GITHUB_READ_ONLY` | unset | preserves the runner's full App permissions and separate write-token cache |
| `CPLANE_GITHUB_APP_ID`, `CPLANE_GITHUB_INSTALLATION_ID` | `runner.env`, required for App mode | `github_app.installation_token` |
| `CPLANE_GITHUB_APP_KEY` | compose: `/run/secrets/github-app.pem` | token minting key path |
| `CPLANE_BRIEFS_KEY` | compose: `/run/secrets/briefs-key` | briefs pull and planning fetch identity |
| `CPLANE_BRIEFS_KNOWN_HOSTS` | compose: `/run/secrets/briefs-known-hosts` | briefs pull and planning SSH host verification |
| `CPLANE_PLANNING_WRITE_KEY` | compose: `/run/secrets/planning-write-key` | planning export push identity |
| `CPLANE_DENY_LIST` | compose: `/run/secrets/deny-list` | public-content delivery gate |
| `CPLANE_EVAL_TASK_URL`, `CPLANE_EVAL_TASK_KEY_FILE` | compose: `http://api:8000`, `/run/secrets/eval-task-key` | authenticated platform eval task endpoint |
| `CPLANE_PLANNING_REMOTE` | `runner.env`; code default empty and refuses export | hourly `feature_export`, SSH remote without credentials |
| `CPLANE_ORDERS_URL` | `runner.env`; if absent, code falls back to `/srv/factory/orders-url`, which is unmounted | orders collector; empty string explicitly disables collection |
| `CPLANE_INSTALL_REPOS` | `runner.env`; code default empty allowlist | install eligibility and store chat-event handling |
| `CPLANE_TASK_SUBMIT` | `runner.env`, matching UI; omit in both to disable | ticket eligibility and `cut.submit` |
| `CPLANE_TASK_STATUS` | `runner.env`; code default empty, which refuses polling | `cut.status` |
| `CPLANE_BACKLOG_GENERATED` | `runner.env`; code default false, enabled only by `1` | hourly feature export's generated backlog table |
| `CPLANE_EXPORT_DIR` | compose: `/srv/homelab/factory-state` | daily state/outbox export; code default absent disables the job |
| `CPLANE_BOT_EXPORT` | compose: `/srv/factory/bot-export` | bot export; code default absent disables the job |
| `PATH`, `LANG`, `PYTHONPATH` | image/default inherited `PATH` and `LANG` if present; `PYTHONPATH` unset | `fence.host_environment` and detached executor environment |
| `GH_TOKEN` | generated from the App for the authenticated Git/gh child; no deployed value | Git credential helper's conditional environment read |

The grep also finds `primer.render`/launchd installation and `install_host.main`
reads. Those are separate host entry points, not called by these service commands.
By default the runner requests a host systemd install unit rather than calling
`install_host.main` in-process; `CPLANE_DEPLOYER_SOCKET` selects the detached
deployer socket client described below. Other CLI subcommands do not run merely because UI
imports `cplane.cli`.

Although compose sets a writable `HOME` and `GH_CONFIG_DIR`, the present
`fence.host_environment()` explicitly replaces the Git/gh child environment with
`HOME=/nonexistent`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null` and
`GIT_TERMINAL_PROMPT=0`, forwarding only `PATH`, `LANG` and `PYTHONPATH`.
`github_environment()` adds the scoped `GH_TOKEN`; executor supervisors similarly
forward only `PATH`, `LANG`, `PYTHONPATH` and an optional `CPLANE_FENCE_COMMAND`.
Thus Git's global configuration remains disabled intentionally, and the new
`GH_CONFIG_DIR` cannot reach those gh calls until a reviewed application change
preserves a writable scratch configuration location. Setting more env-file values
cannot override this hard-coded child environment. App signing uses a separate
OpenSSL child with `os.defpath` and `HOME=/nonexistent` and writes no home config.

Every healthcheck uses Python from the service image, without curl, wget or a
shell. UI fetches its root page; intake connects to the Unix socket without
submitting an arrival. Sessions and runner check PID 1 exists and execute
`SELECT 1` using their own database URL file with a five-second connection timeout.
Those two checks establish process/database availability, not scheduling progress
or successful agent turns. Checks run every 30 seconds with a ten-second timeout,
three retries and a twenty-second startup period.

The deployer's manifest health command, executed inside the first service, is
exactly the UI compose health command:

```sh
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8300/', timeout=5).read()"
```

After taking its database dump, the deployer runs this migration command in a
**new container of `ui`**, with UI's own database URL file mounted:

```sh
cplane migrate
```

### Application prerequisites before cutover

The application and platform prerequisites for the 2026-11-15 cutover were
met; none remain open. Static compose tests validate the reviewed boundary but
do not prove runtime readiness.

### Install after merge

The orchestrator installs the merged revision through the platform deployer.
Factory is not on its automatic application list, so run the deployer's
command-line install from a terminal:

```sh
sudo homelab-deployer install factory <sha>
```

The deployer's compose file, Dockerfile and `ui.env`, `sessions.env` and
`runner.env` live in `/opt/homelab-deployer/factory/`. An install of a commit
that changes guard files requires the owner's approving review on that commit's
PR. The owner cannot approve a PR they authored, so guard changes come through
PRs opened by the runner's GitHub App.

### Runner usage and install switches

Both switches are off by default. With neither set, the runner retains its host
login-file reads and `factory-install` systemd units.

Set `CPLANE_USAGE_SOURCE=launcher` for the runner immediately after installing
this slice. Each pass shares at most one `usage` launcher run, named
`usage-read-<token>`, and always sends `stop` afterward; `unknown_run` means it
is already stopped. Invalid, null, refused or failed reads mean unknown usage.
The runner opens, lists and stats no path under `/srv/factory/logins` in this
mode. Claude usage is unknown, as on today's node. Resume skips the transcript
existence check; a missing session fails its resume turn into attention.

Launcher readings have no timestamp. Their age uses the newer of the last
`usage-probe.json` timestamp and the newest Codex run record's end
(`started_at + seconds`). With neither, usage is stale. When a Codex read is
needed and that age exceeds 30 minutes, a due probe runs before the shared
launcher read, at most once per hour and within executor capacity. The probe
still uses the normal fenced CLI run and stop, but neither deletes login
transcripts nor writes `usage-report.jsonl`. The existing file-mode usage gate
and probe rules remain unchanged.

Set `CPLANE_DEPLOYER_SOCKET=/run/homelab-deployer.sock` only at container cutover.
The deployer installs the Factory containers.
`process` persists install intent and starts a detached Python child, then
returns without waiting. The child requests installation of the repository name
`factory` at the recorded merge SHA, waits without a socket timeout, and writes
the existing private install result file. A held `.started` file lock tracks the
child across runner restarts. A child that ends without a result escalates and
is never replayed. Failures include the deployer's reason and any guard paths;
`waits for the owner` reports the exact manual `sudo homelab-deployer install
factory <sha>` command. The platform owns rollback after install failures.
Factory is not on its automatic application list.

After merge, the orchestrator must: install; set
`CPLANE_USAGE_SOURCE=launcher` for the runner; check one pass reads Codex usage
through the launcher. Confirm one `usage-read-*` record, no login file access by
the runner, and that a slice or eval needing Codex can still start. Keep the
deployer switch unset until cutover. To roll back either switch, unset that
setting and restart the runner.

### Factory launcher socket switch

Set `CPLANE_FENCE_COMMAND=socket` for Factory to invoke
`python -m cplane.launcher` through its current Python interpreter. The client
connects to `/run/homelab-launcher.sock`; `CPLANE_LAUNCHER_SOCKET` overrides that
path for tests. Detached executor supervisors preserve both settings.

The client sends one JSON request per connection. Run requests pass stdout and
stderr as two writable descriptors and wait for the container exit code.
Launcher refusals print `launcher: <reason>` and exit 125. Chat turns use the
`chat` profile with run ID `turn-N`; slice turns, warm-ups, version checks and
model/usage probes use `cli-run`. Bundle exports use `bundle`. Other runs get
fresh random IDs, except probes, whose explicit IDs allow timeout cleanup and
catalog recovery to send `stop`. Session cleanup stops `turn-N`. An `unknown_run` stop response is logged once
at info level and treated as already stopped. Other cleanup errors are logged
and recorded as a turn failure; a failed turn does not stop the supervisor.
Factory planning uses the reserved `repos/factory-planning-export` name, and
repository lists containing that basename are refused.

Work paths must be beneath `/srv/factory/work` with one or two components; run
paths must be beneath `/srv/factory/runs` with one to three components. The client
refuses outside paths before connecting. The launcher validates existing folders
and rejects links. Read-only exports remain names under the work folder's
`repos/` directory. The platform launcher must support two-component work paths
and three-component run paths before enabling this switch.

With the switch enabled, whole-tree ownership transfers and removal of
agent-owned temporary folders go through launcher `own` and `remove`, to
UID/GID 21000. Before transfer, Factory sets `io` folders whose outputs it reads
to mode 0750. Work/review copies, planning trees, and probe/warm-up work folders
whose contents Factory does not read retain mode 0700. Services read agent
outputs through group 21000; unreadable output fails the run, with no root
fallback. Output reads use directory descriptors and `O_NOFOLLOW` and require
regular files with one link.

Chat session folders (`work/session-N`) remain owned by the creating Factory
service, with group 21000 and exactly mode 1770. The agent writes through the
group; the sticky bit prevents it renaming or deleting Factory-owned entries.
`repos/` and its exports remain Factory-owned, mode 0755, and must not be group-
or other-writable. An old agent-owned 0700 session folder is never reused;
an incompatible workspace is removed through `remove` and replaced. Its saved
CLI session IDs are cleared, chat messages remain, and a system line reports that
earlier tool context was reset. The next turn starts a fresh CLI session.

The same code supports root services on the host. A non-root service must use
`CPLANE_FENCE_COMMAND=socket`; any direct ownership hand-off with the switch off
fails explicitly. Setting the session folder's group preserves its service uid
and needs only membership in group 21000.

After merging, the orchestrator installs this revision and then enables the socket
switch. Run one chat turn per tool in each area, Home Lab and Factory; also run a
feature chat with an old folder and one runner slice. Check new session ownership,
group 21000 and mode 1770, and Home Lab planning delivery. Keep rollback ready:
delete the switch line and restart `factory-sessions`. For root services, unset or any other switch
value retains the existing command behavior (default `factory-cli`, or the
configured executable); non-root services require the socket switch.

Eval runs execute through the runner's normal fence with Codex or Claude. A due
planned run becomes running; slices start first, then an attempt may use a free
`executors` place. Only one eval attempt runs at a time across Factory, and it
also respects the repository execution limit. Pi is not available yet.

Each attempt uses a fresh detached work copy at the case's pinned base commit,
after fetching the clean clone. It has a 30-minute limit and does not publish or
install. Its diff, including untracked and binary files, lives at
`/srv/factory/runs/<state-hash>/<turn-id>/attempt.patch` (or the configured runner
run area). The attempt's `output_ref` names that file. The enclosing attempt
folder is mode 0700 and the diff is mode 0600. Eval work copies grant group 21000 read/traversal before ownership transfer, so
the non-root runner can snapshot them without executing agent Git metadata.
An agent file that cannot be read fails collection without privilege fallback.
The work copy is removed after collection. Token metrics come from the CLI output; subscription attempts have
no `cost_usd` value. No slice/chat run record is created.

Use `cplane eval run cancel ID` to stop a run from starting more attempts. An
attempt already running finishes and keeps its diff and metrics. Usage-limit
interruptions return an attempt to planned and hold eval starts until reset.
Grading is separate from execution.
