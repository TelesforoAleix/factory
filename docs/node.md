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
repair; a failure result never claims the old installation is healthy. No raw
command diagnostics, environment values or credentials go into scheduler state,
notices or the unit journal. The node-step text is never evaluated as a command.

Results are small atomic mode-0600 JSON files under
`/srv/factory/runs/<anchor-hash>/installs/<request-id>.json`. The next pass answers
the node step with `Installed <commit>` on success. Failure or any manual paths
raises an escalation. Units use stable `factory-install-<request-id>` names,
start without blocking the pass, and remain loaded after exit, so a pass restart
can find them without starting a second installation. A completed unit with no
result, or a lost unit after persisted launch intent, escalates; it is never
automatically replayed. Inspect status with
`sudo systemctl status factory-install-<request-id>` and verify `REVISION` and
service health before resolving an escalation. Finished units and private result
files may be cleaned up by the operator after their result has been consumed.
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
`save_section`, `set_mark`, `move_feature`, `place_feature`, `add_feature`, `add_slice` and
`raise_decision`. `move_feature` takes exactly one of `stage` or `project`;
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
audit, and the new audit records even successful no-op writes. `raise_decision`
stores an `owner-check` phone notice with chat ID, actor, time, chat title, text
and recommendation. The existing runner bot export delivers these notices;
there is no new Home screen in this change.

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
phone notices are suppressed when the event is taken; owner decisions raised by
`raise_decision` continue to reach Home and the phone. Previously exported phone
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
can answer an install-failure escalation or retry a failed install. Those failures
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
