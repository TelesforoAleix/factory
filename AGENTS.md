# Repository instructions

This repository implements a scheduler's state file, commands, and runner. The runner
starts and resumes Codex and Claude agents only as the runner slice contract describes: at most two at once, never two in one
repository, and only through `cplane run` under launchd or an explicit test.
Keep the version 1 state contract and CLI rules stable. Use Python 3.13 and uv;
jsonschema is the only runtime dependency. Test against synthetic fixtures and temporary git
repositories. Never check private state or outbox data into this repository.
Run `uv run pytest` before submitting changes. Work through a PR with a green `test` check.

Planning agents use `add`, `edit`, `state`, `attention`, and `show` rather than
editing state JSON by hand. Each project's planner owns its briefs, readiness,
handover review, and acceptance. Pass `--actor` to identify the planner in mutation
logs. Keep all planner writes on the locked, validated, atomic update path, with
notices and optional `--commit` handled there. Preserve the documented transition
rules: ready requires a brief, external issuance requires a session, and forced
resets to planned require a logged reason. Issued and awaiting-handover slices may
only have their titles and dependencies edited. Planner commands never start an
executor. Test planner changes using synthetic state and temporary repositories.
