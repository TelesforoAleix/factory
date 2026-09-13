# Factory Workbench

Workbench executes **Factory project operations**. A configured adapter executes
**AI and concrete tools**. That split is the whole design, and the line it draws
is that Workbench holds no backend credential, no model registry and no tool
implementation.

## Layering

```text
surfaces (CLI, local server)  ->  engine  ->  records  ->  ops/ + git
```

Every write goes through `engine.py`. The server implements no write of its own —
it translates HTTP into engine calls. That is what makes the surfaces
interchangeable, and it is enforced by a test: a write issued through the server
and the same write issued through the CLI produce byte-identical `ops/` output.

## Modules

| Module | Does |
|---|---|
| `records.py` | **The only parser.** Reads and writes YAML, JSON and Markdown-frontmatter records |
| `schema.py` | What a valid record is; reports every problem, not the first |
| `engine.py` | The single validated write path |
| `approvals.py` | Approvals bound to one immutable action by fingerprint |
| `audit.py` | Append-only trail with a previous-hash chain; records refusals too |
| `identity.py` | Execution identity, attached by the runtime and never claimed by a model |
| `agents.py` | Manifests: portable `capabilities`, optional concrete `tools` |
| `budget.py` | Two limits — monetary and model-call. Unknown cost stays unknown |
| `gitops.py` | Branch, worktree, commit, push, merge, and the protected-branch guard |
| `project.py` | Open or create a project and its minimum `ops/` |
| `adapters/` | The adapter interface, the deterministic fake, and `homelab` — the second adapter (Phase 23.0), over homelab's endpoint on loopback. `select.py` picks one by the project's `adapter` key |
| `cli.py`, `server.py` | The two surfaces |

## The configured adapter and `run` (Phase 23.0)

`ops/project.json` may carry one key, `"adapter": "fake" | "homelab"`; absent means `fake`. It is
the only adapter configuration there is — the `homelab` adapter's URL (`127.0.0.1:8766`) is fixed
in its module because loopback is not a per-project choice (ADR-038 §2).

`python3 -m workbench.cli --project <p> run <TICKET-or-TASK-id>` is the smallest action that calls
the configured adapter: it builds a `Request` from the item (`assigned_agent` → `agent_role`,
title → `task_summary`, `objective`/`intent` → `instructions`, empty `context`, the item's
`priority`), checks the agent is on the roster and activates it against the adapter, calls the
adapter **once** under a `Budget(max_calls=1)`, records a `run` object (existing type, existing
statuses: `succeeded` or `refused`) holding the `Result`, and appends the run id to the item's
`run_ids`. Results are the client's to record — the endpoint returns and forgets.

Three things to know: the roster name **is** the role key sent to the endpoint (Factory has no JSON
agent manifests yet; roles are prose under `agents/roles/`); the `homelab` adapter advertises no
capabilities, so an agent that declares any is refused at activation — the endpoint answers
questions and executes nothing in 23.0; and the endpoint's `request_id` is recorded on the run
out of band (`adapter.last_request_id`) because `Result` has no field for it — a named finding for
ADR-035 §4, not a quiet extension.

## Why a worktree, not a checkout

A project keeps `ops/` in the same repository as its product. Switching the main
checkout to a feature branch takes the live `ops/` directory with it, and a
`git reset --hard` on that checkout deletes records written since the last
commit. Both were observed while building this, not predicted. Product work
happens in a disposable worktree; the main checkout stays on `main` with `ops/`
intact.

## Running the tests

```bash
python3 -m unittest discover -s tests -v
python3 acceptance/synthetic_project.py
```

Every refusal is proved against a **planted positive control** — the
byte-identical case with only the offending element removed, which must pass.
A refusal test with no passing control proves only that the code is broken.
