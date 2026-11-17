# Factory repository instructions

Factory’s core is the `cplane` scheduler and runner.

This repository implements a scheduler's state file, commands, and runner. The runner
submits slice, cut, ticket and review work to the platform run API by role and level.
The platform owns executor choice, usage waits, harness concurrency, repository isolation
and branch delivery. Factory owns PRs, CI, merge approval, attention and node steps.
Slice answers and merge notices are messages to the existing run. Paused slices only
poll and retain results; abandoned slices cancel their runs, retrying running turns
until cancellation is accepted. Subscription evals and chat execution are separate.
Keep the version 1 state contract and CLI rules stable. Use Python 3.13 and uv;
jsonschema and psycopg 3 are the only runtime dependencies. Test against synthetic fixtures and temporary git
repositories. Never check private state or outbox data into this repository.
Run `uv run pytest` before submitting changes. Work through a PR with a green `test` check.

Planning agents use `add`, `edit`, `state`, `attention`, and `show` rather than
editing state JSON by hand. Each project's planner owns its briefs, readiness,
handover review, and acceptance. Pass `--actor` to identify the planner in mutation
logs. Keep all planner writes on the store’s locked, validated, atomic update path, with
notices and optional `--commit` handled there. Preserve the documented transition
rules: ready requires a brief, external issuance requires a session, and forced
resets to planned require a logged reason. Issued and awaiting-handover slices may
only have their titles and dependencies edited. Planner commands never start an
executor. Test planner changes using synthetic state and temporary repositories.
