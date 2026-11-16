# Factory on the node

Since 2026-11-15, Factory's `ui`, `intake`, `sessions` and `runner` services run
in containers installed by the platform deployer. The host checkout is obsolete.
Operator commands use the installed runner container's code, environment and state.

```sh
sudo factory-cplane pending
sudo factory-cplane show <slice-id>
sudo factory-cplane --actor owner install <slice-id>
```

`node/bin/factory-cplane` is a root-only wrapper for
`docker exec -i deployer-factory-runner-1 cplane "$@"`. It preserves stdin,
arguments and exit status. It reads no host environment file, uses the container's
configured service UID, and needs the runner container to be running. Docker
access remains a host administrator capability.

## Automatic installs

Once `factory` is on the platform deployer's automatic list, the runner's
post-merge install request installs the merged Factory commit automatically.
Changes touching a deployer guard path still require the owner's GitHub review;
the deployer checks that review before installing. To roll back, ask the deployer
to reinstall the previous known-good commit. Record that commit before an
installation so it is available if rollback is needed.

## Remove the old host installation after merging K8f

The orchestrator performs these steps after the deployer installs the merged commit.
Rollback first: the deployer reinstalls the previous commit; the unit files and
`/opt/factory` are restorable from the previous commit's tree. Save the previous
commit before installation. Do not delete service data or secrets.

1. Run `sudo systemctl disable --now factory-dump.timer`.
2. Remove the old unit files listed below from `/etc/systemd/system/`, then run
   `sudo systemctl daemon-reload`. The other old services and timers are already
   disabled and stopped.
3. From the reviewed merged tree, install `node/bin/factory-cplane` as
   `/usr/local/bin/factory-cplane`, root:root, mode 0755. Remove
   `/usr/local/bin/factory-{dump,export,feature-export,install}`. Also install the
   updated `node/bin/factory-restore-check` as `/usr/local/bin/factory-restore-check`,
   root:root, mode 0755, so its default reads the platform backups.
4. Check that `sudo factory-cplane pending` answers from the container. Check
   `sudo docker exec deployer-factory-runner-1 printenv CPLANE_REVISION` matches
   the merged commit. Also check `sudo factory-cplane show <a-slice>` over SSH.
5. Remove `/opt/factory` after those checks pass.

The old unit files are exactly:

```text
factory-dump.service
factory-dump.timer
factory-export.service
factory-export.timer
factory-feature-export.service
factory-feature-export.timer
factory-intake.service
factory-runner.service
factory-runner.timer
factory-sessions.service
factory-ui.service
```

`node/install`, `cplane.install_host`, the transient systemd installer, and these
unit files are removed. Installs use only the deployer. Guard changes under
`node/**` require the owner's GitHub approval before the runner merges the PR.

## Backups and retained tools

The platform's `homelab-dump` dumps every database daily, including `factory`;
`factory-2026-11-15.dump` and `factory-2026-11-16.dump` already exist. No separate
Factory dump service is needed. State/outbox and feature exports are scheduled
by the contained runner loop described below.

`factory-cli` stays: `cplane/fence.py` still uses it as the default fence command,
and its login and isolated CLI tooling remain useful. The deployed services use
the platform launcher socket. The host script does not load code from
`/opt/factory`; keep the installed script and platform-managed fence assets.

`factory-restore-check` stays for operator backup verification in a disposable,
network-isolated PostgreSQL container. With no argument, it selects the newest
file by date in its name matching `factory-YYYY-MM-DD.dump` under
`/srv/homelab/homelab-v2-data/originals/postgres`. These are the platform
`homelab-dump` backups, owned by root with mode 0640. It refuses with a clear
message if none exists and never creates a dump. An explicit dump path remains
supported:

```sh
sudo factory-restore-check
sudo factory-restore-check /path/to/factory-YYYY-MM-DD.dump
```

Row counts are compared with the live database, so a daily backup may differ after
subsequent writes.

## Runner loop and exports

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

## Four contained Factory services

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
protected by the sticky bit and workspace ownership checks.
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
| `CPLANE_DEPLOYER_SOCKET` | compose: `/run/homelab-deployer.sock`; default unset | detached install client; missing socket refuses installation |
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

The launchd installation subcommands are separate Mac entry points. Factory's
runner installs only through the deployer socket; other CLI subcommands do not
run merely because UI imports `cplane.cli`.

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
whose guard files differ from the installed commit requires the owner's
approving review on that commit's PR. The runner uses `CPLANE_REVISION` to
account for this difference before merging, and accepts the owner's GitHub
approval on the delivered tip. The owner
cannot approve a PR they authored, so guard changes come through
PRs opened by the runner's GitHub App.

### Runner usage and installs

Set `CPLANE_USAGE_SOURCE=launcher` for the contained runner. Each pass shares at most one `usage` launcher run, named
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

The runner has `CPLANE_DEPLOYER_SOCKET=/run/homelab-deployer.sock` set in Compose.
Without a deployer socket, a new install request refuses with a clear escalation;
no host unit is started. Existing deployer children and recorded results can
still be collected.
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

The contained services use `CPLANE_FENCE_COMMAND=socket` and group 21000 for
agent output access. No root fallback is available.

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
