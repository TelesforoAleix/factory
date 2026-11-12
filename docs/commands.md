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
cplane eval case list [--kind KIND] [--tag-kind TAG] [--size SIZE] [--language LANGUAGE] [--half HALF]
cplane eval set create ID --title TITLE --filter JSON [--description TEXT] [--note TEXT] [--actor ACTOR]
cplane eval set add ID CASE... [--note TEXT] [--actor ACTOR]
cplane eval set list
cplane eval set show ID [--version N]
cplane eval run create --title TITLE --set ID[:VERSION]... --configuration JSON... --repeats N [--at TIME] [--actor ACTOR]
cplane eval run list
cplane eval run show ID
```

Repeat `--set` and `--configuration` for multiple selections. Filters are JSON
objects using `kind`, `tag_kind`, `size`, `language`, and `half` keys.
