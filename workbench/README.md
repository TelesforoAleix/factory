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
| `adapters/` | The adapter interface and the deterministic fake |
| `cli.py`, `server.py` | The two surfaces |

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
