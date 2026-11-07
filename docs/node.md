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
Once the owner agrees to a decision, the planner records it in the appropriate
document and commits it.
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
| building | next or ready | owner, chat | no linked slice running unpaused |
| any except parked | parked | owner, chat | no linked slice running unpaused |
| parked | stage it left | owner, chat | destination entry conditions again |

Parking records the stage it left and only permits return to that stage; return
clears the recorded stage. Direct creation in parked has no return stage.
Ready entry from grilling or parked requires `design_agreed` and a linked slice;
done entry requires `review_passed`. A linked slice runs when issued or awaiting handover and not
paused. These rules read slice state without changing it. Backlog import still
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

Values must be whole numbers of at least 1. These are stored settings only;
no runner or board behavior consumes them yet. Limit commands require Postgres.
After merge, install the reviewed revision using the existing node procedure,
then run `sudo factory-cplane migrate` and `sudo factory-cplane limit show`.
Confirm both defaults are 3 on first migration. No runner restart, slice action,
session change, or UI change is needed for this slice.

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
`features/<ID>.md` with title, project, stage and sections in stored order. It
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
