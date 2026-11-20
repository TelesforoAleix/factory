# Workshop pages

This document covers how Workshop's owner pages load and refresh, how a failed chat
recovers, how chat events are routed, how Library comments resolve, and how to
measure page timings. Read it before you change a Workshop page, its API
projections, polling, chat recovery or comments. Project pages are in
[project-pages](project-pages.md); the inbox and ideas in [inbox](inbox.md).

## Pages and projections

`/api/home` and `/api/pipeline` return feature card fields only: ID, title,
project, stage, position, display line, slice counts, open-attention count and
waiting mark. They do not construct sections, moves, slice history, handovers or
usage totals. `/api/pipeline/<id-or-alias>` builds only the requested feature. Both
preview layouts share one detail fetch; full feature pages do not fetch the board
to obtain a project name. Home links open that detail page.

Owner page projections read persisted, write-validated documents under the same
store lock instead of validating every stored slice again. Scheduler loads,
save/import validation and the atomic mutation paths still validate. A regression
test compares the projected responses with the validated-load responses.

Visible tabs poll Home every 30 seconds and open-chat messages every five seconds.
The chat and project lists refresh every 30 seconds; usage refreshes when an
assistant message arrives. Requests do not overlap, hidden tabs do not poll, and
returning to a visible tab refreshes at once. Waitress serves the API with eight
threads: headroom for short database-bound requests and page-opening bursts on the
four-core node. It does not change the store's advisory lock or executor concurrency.

Settings shows the stored model list and lets owners queue refreshes for Codex and
Claude. Roles choose a tool, model and effort from that list, and Limits saves each
capacity separately. Chat model overrides use the same stored choices and can be
cleared to the role default; planned and ready slices can select an executor level.

## Chat recovery

An owner message atomically changes a failed chat to idle, clears the failed
provider's resume ID, appends `New session started`, and queues the new message.
Previous messages and failed or queued records remain. Provider IDs for other
providers are kept. Fresh CLI sessions receive a bounded description of the chat,
its opening record and its last eight owner/assistant records, which also supplies
context when a provider switch starts a new CLI session. Existing workspaces keep
their skill snapshot and pass the same ownership, mode and export checks as a
resumed session. Owner messages sent from Library use the same recovery path.

## Chat events

Slice events are always recorded. At delivery, only slices with an `add_slice` log
entry by `chat:<id>` wake chats. Owner and planner slices stay with their existing
owners. The first event line includes the slice ID; the transcript derives that
label for older messages without rewriting them. Home suppresses inactivity-only
Stuck cards while a reviewed merge waits for owner approval.

## Library comments

Drafts can be deleted. Sent comments can only be resolved, with a bounded one-line
note; the database requires a sent comment and a nonempty one-line note for a
resolution. Resolved comments lose their passage highlights and appear in a
collapsed `Resolved (n)` list with note, receiving chat and resolution time. The
owner HTTP routes use the mutation header and the serialized transaction path. No
comment operation is exposed to chats, and no sent comment, message or event record
is deleted.

## Measuring pages

`tests/measure_pages.py` creates and drops its own schema on a **disposable**
PostgreSQL 17 database, never production state. It loads 24 synthetic features and
41 slices with history and measures seven responses per endpoint, including
serialization and response bytes.

```sh
CPLANE_TEST_DATABASE_URL=... uv run python tests/measure_pages.py
CPLANE_TEST_DATABASE_URL=... uv run python tests/measure_pages.py --http --projects --profile /tmp/page-profiles
CPLANE_TEST_DATABASE_URL=... uv run python tests/measure_pages.py --source /path/to/base-archive
```

`--http` measures over loopback instead of the Flask test client, `--projects`
adds the project page, and `--profile` writes one cProfile per endpoint. To compare
with an older commit, archive it outside the checkout, write its SHA into the
archive's `REVISION` file, and pass the archive with `--source`. Synthetic timings
do not replace measurements on the node.
