# Contracts

This document lists every interface another system depends on, in both directions:
what Factory uses from other repositories and what it provides to them. Read it
before you change an API call, a file format, a shared table, an environment
variable or a command another tool calls. Each entry names the version, provider,
user repositories, the source that defines it, and how to change it safely. Detail
lives in the linked document; this file is the index and the version record.

A format without a version field in its own data has version 1 here; raise it on
any change of shape or meaning. A PR that changes a contract below declares it in
the PR request's `contract_changes` (see [`pr-request`](#pr-request)); after the
merge the runner raises a `contract-change` attention item, and each user
repository needs an adapting slice in the same feature.

## Contracts Factory uses

### `run-api`

- Version 1 · provider `TelesforoAleix/homelab-v2` · users `TelesforoAleix/factory`.
- Run and message bodies carry `"contract": 1`; cancel sends `{}`. Calls: `POST /v1/runs`, `GET /v1/runs/<id>`,
  `GET /v1/runs?request_id=<id>`, `POST /v1/runs/<id>/messages`, `POST /v1/runs/<id>/cancel`.
- Source: `cplane/run_platform.py` (client) and `Runner.new_request` in `cplane/runner.py`
  (body); protocol in [runner.md](runner.md). Settings: `CPLANE_EVAL_TASK_URL`, `CPLANE_EVAL_TASK_KEY_FILE`.
- Change safely: the platform adds the new version first; Factory switches its body
  in one PR; saved job bodies in the private ledger are retried unchanged, so keep
  the old version accepted until no saved job uses it.

### `decisions-api`

- Version 1 · provider `TelesforoAleix/homelab-v2` · users `TelesforoAleix/factory`.
- `POST /v1/decisions` on the run API's URL and key, with `text`, one question
  `support` and `repeats`. Source: `Decisions` in `cplane/run_platform.py`, `request`
  in `cplane/docs_verify.py`; behaviour in [docs-verify.md](docs-verify.md).
- Change safely: change the platform first, keeping the old body accepted; then
  change `cplane/docs_verify.py` and its tests.

### `deployer-socket`

- Version 1 · provider `TelesforoAleix/homelab-v2` · users `TelesforoAleix/factory`.
- One JSON line `{"op": "install", "application": "factory", "sha": <40 hex>}` on
  `CPLANE_DEPLOYER_SOCKET`; one JSON line back with `ok`, `result`, and on success
  `application` and `commit`. Source: `cplane/deployer.py`.
- Change safely: the deployer accepts both shapes before `cplane/deployer.py` changes.

### `launcher-socket`

- Version 1 · provider `TelesforoAleix/homelab-v2` · users `TelesforoAleix/factory`.
- One JSON request per connection on `/run/homelab-launcher.sock`
  (`CPLANE_LAUNCHER_SOCKET` overrides it). Source: `cplane/launcher.py`; profiles and
  path rules in [node.md](node.md#factory-launcher-socket).
- Change safely: the launcher accepts both shapes before `cplane/launcher.py` changes.

### `manage-api`

- Version 1 · provider `TelesforoAleix/homelab-v2` · users `TelesforoAleix/factory`.
- `GET /v1/manage/routes` and `GET /v1/manage/providers` on `HOMELAB_API_URL`, read
  only, shown in Workshop Settings. Source: `settings_home_lab` in `factory_ui/__init__.py`.
- Change safely: Workshop passes the JSON through; a shape change needs only a UI change.

### `github`

- REST API version `2022-11-28` · provider GitHub · users `TelesforoAleix/factory`.
- App installation tokens scoped to the repositories of each call. Source:
  `cplane/github_app.py`. Settings: `CPLANE_GITHUB_APP_ID`, `CPLANE_GITHUB_INSTALLATION_ID`,
  `CPLANE_GITHUB_APP_KEY`.
- Change safely: change the `X-GitHub-Api-Version` header in one PR with its tests.

### `orders-endpoint`

- Version 1 · provider the owner node's orders endpoint · users `TelesforoAleix/factory`.
- `GET <base>/orders` returns `{"orders": [...]}`; each result goes back with
  `POST <base>/orders/<id>/ack`. Each order is `{id, created, action, slice, argument,
  expect}`; actions `start`, `slot`, `pause`, `resume`, `answer`, `approve`,
  `orchestrator`. Source: `validate` and `Collector.collect` in `cplane/orders.py`.
  Setting: `CPLANE_ORDERS_URL`; behaviour in [operations.md](operations.md#owner-orders).
- Change safely: the collector refuses unknown fields, so the endpoint must not
  add fields before `cplane/orders.py` accepts them.

## Contracts Factory provides

### `pr-request`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/factory`, `TelesforoAleix/homelab-v2`.
- The fenced JSON an executor returns: exactly `branch`, `title`, `body`,
  `node_steps` (text or null) and `contract_changes` (null, or a non-empty list of
  `{name, version, users}` with non-empty users). Source: `Runner.pr_request` and
  `Runner.contract_changes_valid` in `cplane/runner.py`; [runner.md](runner.md#pr-request-and-post-merge-checks).
- Change safely: the goal text in `Runner.launch_work` and the parser change in one
  PR; saved jobs without a field must keep reading (absent `contract_changes` is null).

### `brief`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/factory`, `TelesforoAleix/homelab-v2`.
- The sections a planner writes: Facts, Fixed decisions, Steps, Allowed changes,
  Do not, Validation, Git, Escalation and Handover. Source: `skills/brief.md`; the
  ticket builder copies the `## Fixed decisions` and `## Do not` sections into each
  ticket (`cplane/cut.py`).
- Change safely: change `skills/brief.md` and `cplane/cut.py` together; briefs already
  stored keep their old sections.

### `slice-state`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/factory`.
- The slice document: `schema/slices.schema.json`, checked on every write by
  `cplane/state.py`, which also requires unique slice ids. Field and transition rules
  are in [commands.md](commands.md).
- Change safely: keep version 1 stable. A new optional field needs a schema change
  (class 2) and must leave existing documents valid.

### `plan`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/factory`.
- The cutter's ticket plan: `schema/plan.schema.json`, read by `cplane/cut.py`.
- Change safely: change the schema, `skills/cut.md` and `cplane/cut.py` in one PR.

### `review-verdict`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/factory`.
- The PR review's verdict JSON: `schema/review.schema.json`, parsed by `cplane/review.py`
  and requested by `skills/slice-review.md`.
- Change safely: change the schema, the skill and the parser in one PR.

### `claims`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/factory`, `TelesforoAleix/homelab-v2`.
- `docs/claims.json` in each repository: `schema/claims.schema.json`, checked by
  `cplane docs-verify` ([docs-verify.md](docs-verify.md)).
- Change safely: a new version must be accepted beside version 1 until every user
  repository's `docs/claims.json` moves.

### `cplane-cli`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/factory`, `TelesforoAleix/homelab-v2`.
- The commands chats, planners and node wrappers call: `add`, `edit`, `state`,
  `attention`, `review`, `show`, `pending`, `install`, `docs-verify` and their exit
  codes. Source: `parser` in `cplane/cli.py`; rules in [commands.md](commands.md).
- Change safely: add options; do not rename or remove a command or option while a
  skill, prompt or wrapper still calls it.

### `change-classes`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/factory`, `TelesforoAleix/homelab-v2`.
- `.github/change-classes`: `<class> <pattern>` lines, gitignore-style, highest class
  wins, no match is class 1. The runner reads it before a merge and the deployer
  before an install. Source: `cplane/classes.py`.
- Change safely: the runner reads it from the pinned base, so a PR's own change
  to the file applies only to later PRs.

### `planning-export`

- Version 1 · provider `TelesforoAleix/factory` · users the private planning repository.
- Hourly commits of `features/<ID>.md`, `features/<ID>/<ID>-S<n>.md` and, when
  `CPLANE_BACKLOG_GENERATED=1`, `backlog.md` to `CPLANE_PLANNING_REMOTE`. Source:
  `cplane/feature_export.py`.
- Change safely: the exporter refuses any other path, so widen `allowed` first.

### `bot-export`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/homelab-v2`.
- After each pass, `slices.json` and `slices.json.outbox.jsonl` in `CPLANE_BOT_EXPORT`,
  mode 0640 with the folder's group; accepted and dropped slices keep only
  `BOT_ACCEPTED_FIELDS`, and the outbox only `BOT_EVENTS`. Source: `export_bot` in `cplane/runner.py`.
- Change safely: the outbox is append-only; a change that rewrites its history stops the export.

### `intake-socket`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/homelab-v2`.
- One JSON arrival `{text, fields, files}` per connection on
  `/run/factory-intake/intake.sock`; the reply is `{"id": N}` or an error. Source:
  `cplane/intake.py`; bounds in [inbox.md](inbox.md#local-socket-protocol).
- Change safely: add optional fields only; the server refuses unknown keys.

### `service-environment`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/homelab-v2`.
- The services, mounts, secrets and environment variables in the root `compose.yaml`,
  which the deployer installs, and the owner's `ui.env`, `sessions.env` and `runner.env`.
  Source: `compose.yaml`; each variable's reader in [node.md](node.md#environment-read-audit).
- Change safely: `compose.yaml` is a class 4 guard path; the owner copies it to the
  deployer before the install that needs it.
