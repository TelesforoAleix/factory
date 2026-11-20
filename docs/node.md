# Factory on the node

This document covers the node's Factory services: the operator wrapper, the four
containers, their accounts, mounts, secrets and environment, and the launcher
socket. Read it before you change `compose.yaml`, the Dockerfile, `node/`, a mount,
a secret or an environment variable. Install, rollback and backup steps are in
[operations.md](operations.md).

Factory's `ui`, `intake`, `sessions` and `runner` services run in containers
installed by the platform deployer.
Operator commands use a running Factory container's code, environment and state.

```sh
sudo factory-cplane pending
sudo factory-cplane show <slice-id>
sudo factory-cplane --actor owner install <slice-id>
```

`node/bin/factory-cplane` is a root-only wrapper for
`docker exec -i <container> cplane "$@"`. It preserves stdin,
arguments and exit status. It reads no host environment file and uses the container's
configured service UID. The wrapper uses `deployer-factory-runner-1` when it is
running, otherwise `deployer-factory-sessions-1` when it is running.
Running state is checked with `docker inspect`; the wrapper never starts or restarts containers.
If neither container is running, it prints `factory-cplane: no Factory container is running`
to stderr and exits 1. Docker access remains a host administrator capability.

## Automatic installs

The install procedure is in [operations.md](operations.md#install-after-a-merge).
Whether the deployer installs at once or replies `waits for the owner` is its own
decision; it checks the owner's GitHub review before installing a commit whose
guard files differ from the installed commit.

Before merging a Factory PR, the runner compares `CPLANE_REVISION`
with the tree produced by merging the PR into freshly fetched `origin/main`.
A guard merely absent on a stale branch does not count; a guard changed on main but not installed still does. If main
cannot be fetched, the runner compares with the PR tip instead. Merge conflicts
fail the check closed. The runner accepts the owner's GitHub approval on the
delivered tip. The owner cannot approve a PR they authored, so guard changes come through
PRs opened by the runner's GitHub App. Guard changes under `node/**` require the
owner's GitHub approval before the runner merges the PR.

## Backups and retained tools

The platform's `homelab-dump` dumps every database daily, including `factory`.
`factory-restore-check` reads those dumps from
`/srv/homelab/homelab-v2-data/originals/postgres`, owned by root with mode 0640; it
refuses with a clear message if none exists and never creates a dump.

`factory-cli` stays: `cplane/fence.py` still uses it as the default fence command,
and its login and isolated CLI tooling remain useful. The deployed services use
the platform launcher socket.

## Four contained Factory services

The four services run under the root `compose.yaml`. The owner reviews and copies
the compose file and Dockerfile to `/opt/homelab-deployer/factory/`, beside the
installed application manifest and the three env files. The deployer uses its
installed Dockerfile and compose file, builds from the selected commit, and passes
only `HOMELAB_DEPLOY_TAG`. Every service uses
`homelab-deployer-factory:${HOMELAB_DEPLOY_TAG:?commit required}`.
Each service receives that commit as `CPLANE_REVISION` for installations without a `REVISION` file.
The fence uses the separate `node/compose.yaml`.

Services appear in this order so the deployer's health and migration commands run
in `ui`:

| Service | UID:GID | Command | Supplementary groups |
| --- | --- | --- | --- |
| `ui` | 992:978 | `python -m factory_ui.serve` | none |
| `intake` | 991:977 | `python -m cplane.intake` | none |
| `sessions` | 21011:21011 | `python -m cplane.sessions` | homelab-launch (976), factory-cli (21000) |
| `runner` | 21010:21010 | `cplane --actor runner run --every 60` | homelab-launch (976), homelab-deploy (975), factory-cli (21000) |


The service accounts are `factory-sessions` 21011:21011 and `factory-runner`
21010:21010. The image includes both accounts with home
`/tmp` and no login shell, so SSH and Python can resolve these UIDs. These are
distinct from fence agent UID/GID 21000:21000 and proxy UID 21001. Every service
has a read-only root, tmpfs `/tmp`,
all capabilities dropped, no-new-privileges, journald logging and
`restart: unless-stopped`. UI, intake and sessions each have 512 MiB memory and
128 PIDs; runner has 1 GiB and 256 PIDs. These limits cover service processes;
the launcher's fence limits remain separate.

All four services join only the external Docker network `homelab_default`.
Their database URL files must name the platform database at host `postgres`.
Set `FACTORY_TIME_ZONE` to an IANA time zone name in `ui.env`, `sessions.env`
and `runner.env` to configure server-side timestamps and calendar expressions.
It defaults to `UTC`; an invalid name fails at startup. The UI displays dates in
the browser’s time zone.
Only UI publishes a port, `127.0.0.1:8300:8300`, preserving Tailscale's host
loopback endpoint. No service receives Docker access, host networking, devices or
additional capabilities.

Each host bind uses the identical container path and refuses to create a missing
host path. Prepare paths and socket permissions on a new node:

| Service | Read-only binds | Read-write binds |
| --- | --- | --- |
| `ui` | `/var/lib/factory/workshop` | none |
| `intake` | none | `/run/factory-intake` |
| `sessions` | `/srv/factory/briefs`, `/srv/factory/runs` | `/srv/factory/work`, `/srv/factory/clean-sessions`, `/srv/factory/runs/sessions`, `/var/lib/factory/sessions`, `/var/lib/factory/workshop`, `/run/homelab-launcher.sock` |
| `runner` | none | `/srv/factory/briefs`, `/srv/factory/runs`, `/srv/factory/work`, `/srv/factory/clean`, `/srv/factory/exports`, `/srv/factory/bot-export`, `/srv/homelab/factory-state`, `/run/homelab-launcher.sock`, `/run/homelab-deployer.sock` |


Prepare `/var/lib/factory/workshop` owned by sessions, with the
documents in `/var/lib/factory/workshop/ui-docs`, and ensure UI can
read the parent, documents and sibling `.ui-docs.lock`. Sessions stages and
exchanges the documents under that parent. Prepare `/var/lib/factory/sessions`
and `/srv/factory/runs/sessions` owned by sessions (21011:21011), and prepare
`/srv/factory/clean-sessions` owned by sessions with mode 0700. Set
both `/srv/factory/work` and `/srv/factory/runs` to root:root, mode 1733
(sticky, writable and traversable by both services). Existing entries remain
protected by the sticky bit and workspace ownership checks.
Create the intake socket folder with
`d /run/factory-intake 0750 991 977 -` in a `tmpfiles.d` file, then run
`systemd-tmpfiles --create`.

Planning clones are prepared in `clean-sessions/planning-sessions/`.

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
sets `CPLANE_BOT_EXPORT=/srv/factory/bot-export`. The additional `/srv/factory/exports` mount is
reserved. Set `/srv/factory/bot-export` to mode 2750
(setgid), group `homelab-bot`. The runner is not in that group; setgid gives new
files the folder's group so the export can `fchown` them to that group. No private
state or export data belongs in Git.

Each secret is an individual read-only bind from
`/etc/factory/secrets/<service>/<name>` to `/run/secrets/<name>`, owned by that
service's UID with mode 0400. Parent directories must allow the owning service to
traverse them. Never mount an entire secret folder or share one service's source
file with another service. Even copies of the database URL and planning write key
have separate service-owned source paths.

Sessions has its own `/etc/factory/secrets/sessions/briefs-key`
and `/etc/factory/secrets/sessions/briefs-known-hosts`, owned by 21011:21011,
mode 0400. These individual read-only binds provide planning fetch credentials
and SSH host verification independently of the runner's files.

The compose environment contains secret **paths** and non-secret settings.
The owner places required `./ui.env`, `./sessions.env` and
`./runner.env` beside the **installed** compose file. Intake needs no env file.
Each service reads only its own file. Use Compose 2.24 or later for the explicit
`env_file.required` entries. These files contain non-secret settings only. Database URLs, keys, passwords
and tokens remain in the individual secret binds above. In particular, an orders
endpoint or planning remote must not embed credentials, and task argument lists
must not contain credentials. These files are consumed by Compose, not mounted
inside containers. No private env file is checked into this repository.

Compose's explicit `environment` overrides its service's env file. The owner
populates the service files with these non-secret settings:

| File | Settings |
| --- | --- |
| `ui.env` | `CPLANE_INSTALL_REPOS` |
| `sessions.env` | `CPLANE_INSTALL_REPOS`, `CPLANE_PLANNING_REMOTE`, `CPLANE_GITHUB_APP_ID`, `CPLANE_GITHUB_INSTALLATION_ID` |
| `runner.env` | `CPLANE_GITHUB_APP_ID`, `CPLANE_GITHUB_INSTALLATION_ID`, `CPLANE_PLANNING_REMOTE`, `CPLANE_ORDERS_URL`, `CPLANE_INSTALL_REPOS`, `CPLANE_BACKLOG_GENERATED`, and optionally `CPLANE_TASK_SUBMIT` and `CPLANE_TASK_STATUS` |

Both App IDs are required positive integers for runner and sessions App
mode; there are no defaults. Keep the install allowlist identical in all three
files so Home, session tools and the runner agree. Sessions needs its own file
because its planning preparation and Workshop install tools read those settings.

`CPLANE_TASK_SUBMIT` and `CPLANE_TASK_STATUS` are JSON argument lists read only by
the manual `cplane cut-submit` queue command; the platform ticket flow does not use
them. Leave them unset unless that manual queue is in use.

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

| Setting read | Source | Reader / purpose |
| --- | --- | --- |
| `CPLANE_DATABASE_URL_FILE`, `CPLANE_DATABASE_URL` | compose / unset fallback, as above | `state.database_url` |
| `FACTORY_UI_HOST`, `HOMELAB_API_URL`, `CPLANE_UI_DOCS` | compose: `0.0.0.0`, `http://api:8000`, `/var/lib/factory/workshop/ui-docs` | UI bind, platform API and document reader |
| `CPLANE_INSTALL_REPOS` | `ui.env`; code default empty allowlist | `home.home_data`, installation checks and store chat-event capture |
| `CPLANE_STATE` | compose: `/srv/factory/briefs/slices.json` | `eligibility.observed` anchors the same run hash as runner |
| `CPLANE_RUNS` | compose: `/srv/factory/runs` | `installation.runs_path`, `Runner.__init__`, usage-report lookup |
| `CPLANE_REPOS` | compose: `/srv/factory/work` | `Runner.__init__` during eligibility observation; avoids default `~/Code` |

The paths align metadata names; they grant no filesystem access. UI's decided
mounts do not expose runs or fence logins, so its current eligibility snapshot
cannot see those host job/usage files.

**Intake** (`cplane.intake` and its inbox insertion path):

| Setting read | Source | Reader / purpose |
| --- | --- | --- |
| `CPLANE_DATABASE_URL_FILE`, `CPLANE_DATABASE_URL` | compose / unset fallback, as above | `state.database_url` |

The socket path is fixed; compose sets `CPLANE_INTAKE_GID=977` for its group. Intake does
not execute arbitrary CLI commands or the runner's scheduler through imports.

The sessions App key is its own copy at
`/etc/factory/secrets/sessions/github-app.pem`, owned by UID 21011, mode 0400,
mounted read-only at `/run/secrets/github-app.pem`, the same in-container path
used by the runner's separate copy. Prepare `/srv/factory/clean-sessions` owned
by 21011:21011, mode 0700, and bind it writable only in sessions. 

**Sessions** (`cplane.sessions`, model probes and Workshop tools):

| Setting read | Source | Reader / purpose |
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

| Setting read | Source | Reader / purpose |
| --- | --- | --- |
| `CPLANE_DATABASE_URL_FILE`, `CPLANE_DATABASE_URL` | compose / unset fallback, as above | `state.database_url` |
| `CPLANE_STATE` | compose: `/srv/factory/briefs/slices.json` | CLI metadata anchor and runner |
| `CPLANE_RUNS` | compose: `/srv/factory/runs` | runner, install records and usage-report lookup |
| `CPLANE_REPOS` | compose: `/srv/factory/work` | runner repository base; replaces code default `~/Code` |
| `CPLANE_FENCE` | compose: `1` | `executors.fenced` |
| `CPLANE_FENCE_COMMAND` | compose: `socket` | retained launcher helpers for sessions and usage telemetry |
| `CPLANE_USAGE_SOURCE` | compose: `launcher`; default unset | retained launcher usage telemetry; no slice or eval usage gate |
| `CPLANE_DEPLOYER_SOCKET` | compose: `/run/homelab-deployer.sock`; default unset | detached install client; missing socket refuses installation |
| `CPLANE_GITHUB_AUTH` | compose: `app` | selects App authentication instead of the legacy token file |
| `CPLANE_GITHUB_READ_ONLY` | unset | preserves the runner's full App permissions and separate write-token cache |
| `CPLANE_GITHUB_APP_ID`, `CPLANE_GITHUB_INSTALLATION_ID` | `runner.env`, required for App mode | `github_app.installation_token` |
| `CPLANE_GITHUB_APP_KEY` | compose: `/run/secrets/github-app.pem` | token minting key path |
| `CPLANE_BRIEFS_KEY` | compose: `/run/secrets/briefs-key` | briefs pull and planning fetch identity |
| `CPLANE_BRIEFS_KNOWN_HOSTS` | compose: `/run/secrets/briefs-known-hosts` | briefs pull and planning SSH host verification |
| `CPLANE_PLANNING_WRITE_KEY` | compose: `/run/secrets/planning-write-key` | planning export push identity |
| `CPLANE_DENY_LIST` | compose: `/run/secrets/deny-list` | public PR metadata gate |
| `CPLANE_EVAL_TASK_URL`, `CPLANE_EVAL_TASK_KEY_FILE` | compose: `http://api:8000`, `/run/secrets/eval-task-key` | authenticated platform run API for slices and marked evals |
| `CPLANE_PLANNING_REMOTE` | `runner.env`; code default empty and refuses export | hourly `feature_export`, SSH remote without credentials |
| `CPLANE_ORDERS_URL` | `runner.env`; if absent, code falls back to `/srv/factory/orders-url`, which is unmounted | orders collector; empty string explicitly disables collection |
| `CPLANE_INSTALL_REPOS` | `runner.env`; code default empty allowlist | install eligibility and store chat-event handling |
| `CPLANE_TASK_SUBMIT` | `runner.env`, optional | manual `cut-submit` only; slice runner uses the run API |
| `CPLANE_TASK_STATUS` | `runner.env`, optional | manual queue status helper; unused by the slice runner |
| `CPLANE_BACKLOG_GENERATED` | `runner.env`; code default false, enabled only by `1` | hourly feature export's generated backlog table |
| `CPLANE_EXPORT_DIR` | compose: `/srv/homelab/factory-state` | daily state/outbox export; code default absent disables the job |
| `CPLANE_BOT_EXPORT` | compose: `/srv/factory/bot-export` | bot export; code default absent disables the job |
| `PATH`, `LANG`, `PYTHONPATH` | image/default inherited `PATH` and `LANG` if present; `PYTHONPATH` unset | `fence.host_environment` and detached executor environment |
| `GH_TOKEN` | generated from the App for the authenticated Git/gh child; no deployed value | Git credential helper's conditional environment read |

The launchd primer subcommands are separate Mac entry points. Factory's
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

## Factory launcher socket

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
`repos/` directory.

With the socket, whole-tree ownership transfers and removal of
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
