# Architecture

This document covers Factory's parts, what each owns, how data and requests flow,
where each part runs, and which other repositories it depends on. Read it before
a change that crosses a part boundary or touches another repository. It states the
current design only; [DECISIONS.md](DECISIONS.md) records why it is so.

## Boundary

```text
 owner (phone, laptop)                        TelesforoAleix/homelab-v2
        |                                     +-------------------------+
        | HTTP 127.0.0.1:8300                 | api: /v1/runs           |
        v                                     |      /v1/decisions      |
 +------+-------------------------------+     |      /v1/manage/*       |
 | Factory (one image, four services)   |     | deployer socket         |
 |  ui -------- reads ----------------- |---->| launcher socket         |
 |  intake <--- unix socket <- phone bot|     | postgres, homelab-dump  |
 |  sessions -- chat turns ------------ |---->+-------------------------+
 |  runner ---- runs, installs -------- |---->        |  executors deliver
 |  cli (cplane, factory-cplane)        |             v  branches
 |  store ---- Postgres (platform db)   |      GitHub (PRs, CI, App)
 +--------------------------------------+<---- runner opens PRs, merges
```

## Parts

| Part | Code | Owns |
| --- | --- | --- |
| `ui` | `factory_ui/`, `ui/` | `factory_ui/__init__.py` imports Flask |
| `intake` | `cplane/intake.py` | `SOCKET` path |
| `sessions` | `cplane/sessions.py`, `cplane/workshop.py` | chat turns and their scoped Workshop tools |
| `runner` | `cplane/runner.py` and the modules it calls | scheduling passes, run requests, PRs, CI, merges, installs, exports |
| `cli` | `cplane/cli.py` | the `cplane` command for owners, planners and operators |
| `store` | `cplane/state.py`, `cplane/stores.py`, `cplane/migrations/` | Postgres storage and the version 1 slice validator |
| `schemas` | `schema/` | the JSON formats Factory validates |
| `skills` | `skills/`, `cplane/prompts/` | the `instructions` function |
| `docs-verify` | `cplane/docs_verify.py` | the documentation claims check |
| `node-tools` | `node/` | host wrappers and the retained fenced CLI image |

`factory_ui/` sets `DIST` to `ui/dist`.
The `frontend` route serves files from `ui/dist` and falls back to `index.html`.
The Flask app registers routes under `/api/`. `intake` accepts one JSON arrival per connection on a Unix socket
and opens no network port. No client currently connects to it; the phone bot user is granted group access. `sessions` runs chat turns through the platform
launcher. `runner` runs `cplane --actor runner run --every 60`: one locked pass,
then a wait, repeated. `store` keeps every slice document in Postgres and checks
each write against `schema/slices.schema.json`.

## Flow

1. Work enters as inbox arrivals (`intake`, `ui`) or chat decisions (`sessions`),
   and becomes features and slices in `store`.
2. Each runner pass, under one database lock, collects owner orders, steps the
   feature pipeline, routes chat events, then collects and delivers
   slices, and finally writes the phone bot export.
3. The runner submits slice, cut, ticket and review work to the platform run API
   by role and level. The platform chooses the executor and delivers the branch.
4. The runner opens the PR. The runner reads CI checks.
5. The runner requires merge approval when class 4 paths are present.
6. The runner merges with `--squash`.
7. The runner raises node-step attention when `node_steps` is present.
8. After a merge the runner raises `contract-change` and `docs-graph` attention
   items when they apply.

## Where each part runs

All four services run from one image on the owner's node, installed by the platform
deployer from the root `compose.yaml`. They join only the Docker network
`homelab_default`; only `ui` publishes a port, on `127.0.0.1:8300`. `cli` runs
inside a service container through `node/bin/factory-cplane`, or locally for
development and tests. Service accounts, mounts and secrets are in
[docs/node.md](docs/node.md).

## Other repositories

| Repository | Contract | Direction |
| --- | --- | --- |
| `TelesforoAleix/homelab-v2` | `run-api` | Factory uses: `runner` submits and polls runs |
| `TelesforoAleix/homelab-v2` | `decisions-api` | Factory uses: `docs-verify` asks for claim verdicts |
| `TelesforoAleix/homelab-v2` | `deployer-socket` | Factory uses: `runner` requests installs |
| `TelesforoAleix/homelab-v2` | `launcher-socket` | Factory uses: `sessions` launches chat turns |
| `TelesforoAleix/homelab-v2` | `manage-api` | Factory uses: `ui` shows routes and providers |
| `TelesforoAleix/homelab-v2` | `service-environment` | Factory provides: the deployer installs `compose.yaml` |
| `TelesforoAleix/homelab-v2` | `claims`, `pr-request`, `brief` | Factory provides: formats its slices follow |

Each contract, its version and how to change it safely are in
[docs/contracts.md](docs/contracts.md).
