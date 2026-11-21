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
- Run and message bodies carry `"contract": 1`; cancel sends a POST with no body or JSON content type. Calls: `POST /v1/runs`, `GET /v1/runs/<id>`,
  `GET /v1/runs?request_id=<id>`, `POST /v1/runs/<id>/messages`, `POST /v1/runs/<id>/cancel`.
- Source: `cplane/run_platform.py` (client) and `Runner.new_request` in `cplane/runner.py`
  (body); protocol in [runner.md](runner.md). Settings: `CPLANE_EVAL_TASK_URL`, `CPLANE_EVAL_TASK_KEY_FILE`.
- Change safely: the platform adds the new version first; Factory switches its body
  in one PR; saved job bodies in the private ledger are retried unchanged, so keep
  the old version accepted until no saved job uses it.
- Pin and sender check: `pins/run-api/` holds the provider's OpenAPI document at a
  named commit; `tests/test_run_api_contract.py` verifies it and checks the bodies Factory
  builds against it. The sender accepts a missing body when the pinned operation defines none.

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
  `/run/factory-intake/intake.sock`; the reply is `{"id": N}` or an error. The phone bot user is granted group access, but no client currently connects to this socket. Source:
  `cplane/intake.py`; bounds in [inbox.md](inbox.md#local-socket-protocol).
- Change safely: add optional fields only; the server refuses unknown keys.

### `service-environment`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/homelab-v2`.
- The services, mounts, secrets and environment variables in the root `compose.yaml`,
  which the deployer installs, and the owner's `ui.env`, `sessions.env` and `runner.env`.
  Source: `compose.yaml`; each variable's reader in [node.md](node.md#environment-read-audit).
- Change safely: `compose.yaml` is a class 4 guard path; the owner copies it to the
  deployer before the install that needs it.

### `contract-tool`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/factory`, `TelesforoAleix/homelab-v2`.
- The `factory-contracts` command, its exit codes (0 pass, 1 check failed, 2 usage
  or input error) and the pin folder format, described in
  [the contract tool](#the-contract-tool). Source: `contracts/cli.py`, `contracts/pins.py`.
- Change safely: add options and commands; keep existing ones and the pin keys
  while any repository's CI installs a Factory commit that uses them.

### `contracts-catalog`

- Version 1 · provider `TelesforoAleix/factory` · users `TelesforoAleix/factory`.
- `cplane contracts catalog` prints the JSON list described in
  [contract updates](#contract-updates); the runner saves the same form as
  `contracts-catalog.json` beside its state anchor. Source: `cplane/contract_updates.py`.
- Change safely: keep the catalog fields stable for commands and readers of the
  saved catalog; a new shape needs a new version here.

## The contract tool

`factory-contracts` (package `contracts/`, shipped in the Factory distribution)
checks machine-readable contracts between repositories. The provider generates
each contract's schema from its code and commits it; each user keeps a pinned
copy. Both run the tool in CI, installed from a pinned Factory commit, for example
`uv tool install git+https://github.com/TelesforoAleix/factory@<sha>`. It imports
only the standard library and `jsonschema`, so it needs no Postgres, Flask or
runner. Each check names its practice skill, `skills/expand-contract.md`;
`factory-contracts practices` lists them.

- Every file it writes or compares is in one canonical JSON form:
  `json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"`
  (`factory-contracts canonical`).
- `generated` runs the provider's generator command, which prints the schema, and
  fails with a short diff when the committed file is not its canonical output.
- `compat` requires full compatibility: it runs `oasdiff breaking --fail-on ERR`
  from base to revision and from revision to base, and fails when either reports a
  level 3 finding outside a fixed set, naming the direction and each rule id. The set
  is a new operation (`api-path-removed-without-deprecation` and
  `api-removed-without-deprecation`, revision against base only) and a new response
  enum value (`response-property-enum-value-added`, base against revision only);
  they are reported as `tolerated`. The set has no option; widening it is a code
  change. The base may be
  `git:REF:PATH`, read with `git show`. It needs `oasdiff` v1.37.0, found from
  `--oasdiff`, then `OASDIFF`, then `PATH`; it passes `--allow-external-refs=false`
  and runs in a temporary folder without `OASDIFF_CONFIG`, so neither remote
  references nor an `.oasdiff` configuration take part.
- A pin is a folder holding `schema.json` (the provider's file, canonical) and
  `pin.json` with exactly `contract`, `provider` (owner/name), `commit` (40 hex)
  and `sha256` (of `schema.json`'s bytes). There are no version numbers.
  `pin write` creates it; `pin verify` fails when a key, the form or the hash is wrong.
- `sender` checks a request body against a pinned OpenAPI document: any field the
  operation's JSON request schema does not define, followed through local `$ref`s,
  `allOf`, `anyOf` and `oneOf`, is refused, and the known fields' types are
  validated with `jsonschema`. Tests call `contracts.sender.check(pin_dir, method,
  path, body)`, which returns the errors, each naming the operation and JSON path.
  Readers stay tolerant: they accept and record unknown fields.

## Contract updates

`cplane/contract_updates.py` discovers uses from `pins/*/pin.json` at each active
project repository's default tip, using the records behind `cplane project list`.
Short repository names use owner `TelesforoAleix`; the `NEW` project has no
repository. For each named provider it reads `contracts/<contract>/openapi.json`
at the provider's default tip and hashes its canonical JSON form. The catalog is
a JSON list, grouped by contract and provider:

```json
[
  {
    "contract": "example-api",
    "provider": "TelesforoAleix/provider",
    "provider_commit": "<provider default tip>",
    "sha256": "<provider schema hash>",
    "users": [
      {
        "repository": "TelesforoAleix/user",
        "commit": "<provider commit recorded in the user's pin>",
        "sha256": "<pinned schema hash>",
        "current": false
      }
    ]
  }
]
```

`current` compares hashes, so an unchanged schema needs no update even when the
provider has newer commits. An unreadable provider schema leaves its entry with
null `provider_commit` and `sha256`, and raises no PR. Repositories that cannot be
read cannot contribute discovered uses. The command reads live data; the runner
saves the result of each full scan as `contracts-catalog.json` beside its state.

At the end of every pass the runner checks open `contracts/*` PRs. A full scan
runs at the first pass after 03:45 in `FACTORY_TIME_ZONE`, once per local date,
and after a runner-recorded merge changes `contracts/<contract>/openapi.json`.
`contracts-state.json` beside the state anchor keeps the last scan date, the last
daily scan date and observed merges across restarts. A schema scan before 03:45
does not consume that day's scheduled scan. Job errors log one content-free line
and leave the runner pass successful.

Without a GitHub App id and installation id, or without an active project with
a repository, the job returns silently before any GitHub call. Missing App
configuration is checked before opening the store.

For each outdated use, the job creates one commit on the user's default tip,
changing exactly `pins/<contract>/schema.json` and `pins/<contract>/pin.json` with
`contracts.pins.write`. The pin names the provider's full tip. Git Data API blobs,
trees, commits and refs create or force-update only `contracts/<contract>`; the
runner keeps no checkout. A branch already carrying that provider pin is left
alone. The commit message and PR title are
`Update the <contract> pin to <provider-name>@<short commit>`; the body names the
provider commit and both hashes. Opening or editing goes through `Runner.open_pr`
and its public-repository deny check.

Green CI merges as class 1 without a review. Before merging, including after the
CI read, the job requires the exact `contracts/<contract>` branch, Factory's App
bot login as author, exactly the two pin paths, and the PR head matching the branch commit.
The merge uses that expected head. A valid pin is also required; forks, renames,
other paths or changed evidence raise `contract-change` attention for the planner
and leave the PR alone. Pending CI waits.

Red CI records a planned slice `<repository>/pin-<contract>-<short provider commit>`
in the user's repository, linked to the PR, with title
`Adapt to the <contract> change from <provider>@<short>`. It has no brief: the
planner writes it. A `contract-change` attention addressed to the planner names
the PR and failed checks. The slice log deduplicates notices per PR head, even
across restarts; later heads can raise new attention without replacing planner
work. Slice and attention writes use the locked, validated store mutation path.
The claims-based `Runner.after_merge` contract notice remains for contracts
that have not moved to pins.
