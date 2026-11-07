# Factory CLI containers

Factory's independent Docker stack fences each CLI run in one container. It copies
Home Lab's sealed-task and two-network proxy pattern without modifying Home Lab.
`CPLANE_FENCE=1` routes runner turns and usage warm-ups through `factory-cli run`.
With it unset, the Mac launchd runner keeps its existing commands and behaviour.
The host prepares a credential-free repository copy and pushes changes after the run.
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

`CPLANE_STATE` remains the state-path anchor; its containing folder is the
orchestrator-managed briefs clone. In Postgres mode each pass pulls that clone
with `git pull --ff-only` before reading relative briefs. No state or notices are
committed there. A failed pull stops the pass. Provision this clone separately;
never use an agent's working copy as the anchor. Database provisioning/migration
and import remain the orchestrator's existing process; do not import twice.
In fenced mode a slice's `repo` must be `owner/name`; the root-owned briefs clone
reads with its own deploy key set in its local `core.sshCommand`, never the GitHub token.

The service is a root oneshot triggered every 300 seconds. Its detached turn
supervisors survive the end of a pass (`KillMode=process`), as under launchd.
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
commits tests on its assigned branch, and ends `waiting` with a fenced JSON plan
matching `schema/plan.schema.json`. The runner validates it and delivers its
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
root-owned `repos/.planning` export, overmounted read-only using the existing
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

## Home Lab documents, notes and grills

After merging this slice, the orchestrator rebuilds the UI, syncs the reviewed
Python installation, runs `sudo factory-cplane migrate` (migration 003 adds
`cplane_document_notes`), and reinstalls the sessions unit before restarting both
services:

```sh
sudo install -o root -g root -m 0644 /opt/factory/node/systemd/factory-sessions.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart factory-sessions.service factory-ui.service
```

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

Home Lab lists documents by folder and searches paths, titles, status, dates and
body text. Scalar `title`, `status`, `date` and `updated` frontmatter fields are
used for display; complex YAML values are not evaluated. A missing date uses the
Git archive's file timestamp (the commit date), and a missing status displays
“Unspecified”. Documents render Markdown with raw HTML disabled and GFM tables
inside a horizontally scrollable container. `/home-lab/backlog` reads the root
`backlog.md` through the same renderer. Paths are relative to the export; absolute
paths, traversal, non-Markdown files and symlink components are refused.

Owner notes live only in Postgres, keyed by the document's relative path, and are
shown beside the document (below it on a phone). They survive refreshes and
sessions; a renamed document has a new path and its previous notes remain stored
under the old path. Notes are retained for operator cleanup along with session
messages. A note can be copied into a selected Home Lab session as one queued
owner message. Writes use the existing required UI request header and database
transaction path; Factory sessions cannot receive a Home Lab note through this
route.

“Start a grill” requires a document, tool/model and at least one named repository.
It creates a Home Lab session and queues its first message atomically. The first
message tells the planner to read the document at `planning/<path>`, use the named
repositories, ask one question at a time, and wait for the owner's answer. The
document must exist, but its size does not limit grill creation.
Grills use existing one-message/one-turn execution and repository exports.
Conversation bubbles distinguish the owner from the planner; planner replies
containing a question mark are highlighted as questions. This is a display cue,
not a new agent response protocol. Committed Home Lab planning edits use the
planning delivery path below.

After installation, check the sessions journal for export errors, confirm
`/var/lib/factory/ui-docs` is a plain directory readable by `factory-ui`, and open
Home Lab and Backlog. Verify a note can be saved and sent to a Home Lab session,
and perform a grill smoke test with a deliberately chosen document/repository.
The orchestrator performs these node checks; this slice uses synthetic fixtures.


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
Each successfully pushed commit is recorded as a separate message with its full
rebased SHA on the session page, suitable for an operator to revert. Session
workspaces, clean clones, bundle snapshots and database messages are retained for
operator cleanup. The document export refresh continues through the existing
briefs clone refresh path.

After installation, the orchestrator tests one deliberately chosen real Home Lab
Markdown write, confirms its commit notice and remote `main`, and verifies a
Factory session cannot write planning. This implementation uses temporary Git
repositories and does not perform that real write.
