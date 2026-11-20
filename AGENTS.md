# Factory repository instructions

Factory turns agreed software work into reviewed, merged pull requests. Its core is
`cplane`: the scheduler, the runner and the commands, with Workshop (`factory_ui/`,
`ui/`) as the owner's console. The Home Lab platform executes the work.

## CI commands

The required check is `test`. It runs, on Python 3.13 with a PostgreSQL 17 service:

```sh
uv sync --locked
uv run pytest
```

Changes under `ui/` also run `npm ci`, `npm test` and `npm run build` in `ui/`.
Run `uv run pytest` before submitting. Work through a PR with a green `test` check.

## Hard rules

- Use Python 3.13 and uv. Runtime dependencies are those in `pyproject.toml`
  (jsonschema, psycopg 3, Flask, waitress); adding one is a class 2 change.
- Keep the version 1 slice state contract and the CLI rules stable.
- Test against synthetic fixtures, temporary git repositories and disposable
  Postgres schemas. Never check private state, outbox data, exports or run records
  into this repository; it is public.
- The runner submits slice, cut, ticket and review work to the platform run API by
  role and level. The platform owns executor choice, usage waits, harness
  concurrency, repository isolation and branch delivery. Factory owns PRs, CI,
  merge approval, attention and node steps. Never add a local slice execution path.
- Answers and merge notices are messages to the existing run. Paused slices only
  poll and keep results; abandoned slices cancel their runs, retrying running turns
  until the cancellation is accepted. Eval attempts never open PRs or change slices;
  chats run through the `sessions` service.
- Planning agents use `add`, `edit`, `state`, `attention`, `review` and `show`, never
  hand edits to state. Each project's planner owns its briefs, readiness, handover
  review and acceptance. Pass `--actor` to identify the planner in mutation logs.
- Keep every planner write on the store's locked, validated, atomic update path,
  with notices handled there. Planner commands never start an executor.
- Preserve the transition rules: ready requires a brief, external issuance requires
  a session, and a forced reset to planned requires a logged reason. Issued and
  awaiting-handover slices may only have their titles and dependencies edited.
- Class 4 guard paths in `.github/change-classes` need the owner's GitHub approval.

## Document map

When you do X, read Y first, and keep Y current in the same PR.

- Learn what Factory is for and how work moves → [README.md](README.md)
- Change anything that crosses a part or repository boundary → [ARCHITECTURE.md](ARCHITECTURE.md)
- Change an API call, format, shared table, setting or called command → [docs/contracts.md](docs/contracts.md)
- Make or reverse a design decision → [DECISIONS.md](DECISIONS.md) (append only)
- Install, roll back, restore, or change the runner loop or exports → [docs/operations.md](docs/operations.md)
- Change a service, mount, secret or environment variable → [docs/node.md](docs/node.md)
- Change a planner or owner command → [docs/commands.md](docs/commands.md)
- Change run requests, reviews, messages, merges or recovery → [docs/runner.md](docs/runner.md)
- Change eval cases, configurations, attempts or grading → [docs/evals.md](docs/evals.md)
- Change the inbox, the Secretary or ideas → [docs/inbox.md](docs/inbox.md)
- Change project pages or project fields → [docs/project-pages.md](docs/project-pages.md)
- Change Workshop pages, polling, chat recovery or comments → [docs/workshop.md](docs/workshop.md)
- Change the claims check or its format → [docs/docs-verify.md](docs/docs-verify.md)
- Add a database migration → [docs/migrations.md](docs/migrations.md)
- Finish any PR that changes a fact → [docs/documentation.md](docs/documentation.md)
- Change a cited line or a core document → [docs/claims.json](docs/claims.json)
- Read the record of the first Home approval → [docs/functional-tests.md](docs/functional-tests.md) (do not edit)

Code that other files describe: `skills/` (chat, brief, cut, review and judge
instructions), `cplane/prompts/` (turn prompts), `schema/` (JSON formats).

## Update rule

A change that alters a fact updates the document that owns it, in the same PR.
A change to a contract in `docs/contracts.md` is declared in the PR request's
`contract_changes`.

The core documents are this file, ARCHITECTURE.md, docs/contracts.md,
docs/operations.md, docs/migrations.md and docs/documentation.md; every factual
claim they make is listed with its proof in `docs/claims.json`. When you edit one of
them or a file it cites, update the claims as
[docs/documentation.md](docs/documentation.md) describes, and run
`uv run pytest tests/test_docs_links.py`.
