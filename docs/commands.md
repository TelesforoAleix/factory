# Active projects

Projects are active by default. The shared flag controls page visibility only;
execution, queue order, limits and notices are unaffected. `NEW` is always active.

```sh
cplane project list
cplane project active FAC
cplane project active FAC off --actor owner
cplane project active FAC on --actor owner
```

Activation also creates the project's orchestrator chat if missing, using the
project chat defaults. Repeated activation reuses the existing chat. Deactivation
keeps all features, chats and documents. Settings › Projects changes the same flag.

Project pages and owner field editing use the same store methods as the CLI:

```sh
cplane project add SYN 'Synthetic project' --actor owner
cplane project set SYN --name 'Synthetic' --about 'What we are building.' \
  --public-url https://example.test --repository-url https://example.test/repo \
  --actor owner
```

Keys are permanent and unique; adding creates an active project with its chat.
Names allow 1–60 characters and About allows up to 600. URLs must use HTTPS;
pass an empty URL to remove it. See [Project pages](project-pages.md) for usage
accounting, validation and installation.

## Slice housekeeping

Slice creation and edits require either a valid `--feature-id` (a current ID or
alias) or `--no-feature REASON` for work without a feature. The free-text
`--feature` name is not a link. Reasons must be nonempty and at most 200
characters. The options are mutually exclusive. Use `edit --no-feature REASON`
to remove a feature link; setting `--feature-id` removes the previous reason.
Existing unassociated slices need one of these options when edited. Issued and
awaiting-handover slices retain their existing edit restrictions, so their
association cannot be changed in those states.

```sh
cplane add --id example/W1 --repo owner/repo --feature Chore --title Cleanup --no-feature 'One-off cleanup' --actor planner
cplane edit example/W1 --feature-id FAC-F1 --actor planner
```

```sh
cplane state SLICE dropped --actor owner  # Pause issued or awaiting-handover slices first.
cplane install SLICE --actor owner
cplane installed SLICE FULL_MERGE_SHA --note 'Installed by hand' --actor owner
```

Use `installed` for repositories outside `CPLANE_INSTALL_REPOS` after installing the exact merged commit by hand. Answer any node-step attention separately.

## Eval catalogue and runs

These commands require `CPLANE_DATABASE_URL` or `CPLANE_DATABASE_URL_FILE` and
always emit JSON. They store experiments without starting executors.
See [Eval store](evals.md) for the case format and versioning rules.

```sh
cplane eval import FOLDER
cplane eval case from-slice SLICE --kind KIND --check COMMAND --grade {tests_and_judge,judge} --validation TEXT [--hidden PATH ...]
cplane eval case list [--kind KIND] [--tag-kind TAG] [--size SIZE] [--language LANGUAGE] [--half HALF]
cplane eval config add ID --path {slice,tickets} --role 'ROLE=JSON'... [--note TEXT] [--actor ACTOR]
cplane eval config list
cplane eval config show ID
cplane eval set create ID --title TITLE --filter JSON [--description TEXT] [--note TEXT] [--actor ACTOR]
cplane eval set add ID CASE... [--note TEXT] [--actor ACTOR]
cplane eval set list
cplane eval set show ID [--version N]
cplane eval run create --title TITLE --set ID[:VERSION]... --configuration ID... --repeats N [--at TIME] [--actor ACTOR]
cplane eval run list
cplane eval run show ID
```

Repeat `--set` and `--configuration` for multiple selections. Filters are JSON
objects using `kind`, `tag_kind`, `size`, `language`, and `half` keys.


Slice execution uses the platform run API. `add` and `edit` accept `--level
light|standard|strong`; per-slice `--tool`, `--model` and `--effort` are removed.
Legacy executor metadata in version 1 documents remains for compatibility and is
not used to select an executor. `show --final` reads the saved API final message.
`why` reports platform usage waits with their `resume_at`; Factory no longer
applies executor or repository slot limits to slice requests. See [runner
operation](runner.md). Chat settings and model choices remain separate.


An escalated slice may move to `issued` to continue its existing run, or to `ready`
to request a fresh attempt. Ready still requires a brief. Use the locked planner
commands and identify the planner:

```sh
cplane state SLICE ready --actor planner
cplane start SLICE --actor planner
```

On the next start, Factory cancels the previous attempt's runs (retrying running
turns until cancellation is accepted), clears attention and raises the existing
attempt number. Request ids change and the base is the default branch's current
tip. The slice keeps its id, brief, level, flow and branch name. Paused slices do
not start until resumed. The state command itself starts no executor.

`show` and `show --json` display `runs` from the slice's run records, newest
first, with role, tool, model, effort and start time. Older records may have an
empty role. The slice detail API and Workshop use the same records.
