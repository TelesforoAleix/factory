# CS1: pages, chat recovery, event routing and comment resolution

The list projections are now separate from feature detail. `/api/home` and
`/api/pipeline` return feature card fields only: ID, title, project, stage,
position, display line, slice counts, open-attention count and waiting mark.
They do not construct sections, moves, slice history, handovers or usage totals.
The existing `/api/pipeline/<id-or-alias>` endpoint now builds only the requested
feature. Both preview layouts share one detail fetch; full feature pages no longer
fetch the board to obtain a project name. Home links open that detail page.

Visible tabs poll Home every 30 seconds and open-chat messages every five seconds.
The chat/project lists refresh every 30 seconds; usage refreshes when an assistant
message arrives. The legacy sessions page also uses visibility-aware polling.
Requests do not overlap. Returning to a visible tab refreshes immediately.
Waitress has eight threads: modest headroom for short database-bound requests and
page-opening bursts on the four-core node. This reduces request queue contention;
it does not change the store's advisory lock or executor concurrency.

An owner message atomically changes a failed chat to idle, clears the failed
provider's resume ID, appends `New session started`, and queues the new message.
Previous messages and failed/queued records remain intact. Provider IDs for other
providers are retained. The pinned base had provider-specific resume IDs but no
conversation-summary helper. Fresh CLI sessions now receive a bounded description
of the chat, its opening record and its last eight owner/assistant records. This
also supplies context when a provider switch starts a new CLI session. Existing
workspaces retain their skill snapshot and pass the same ownership, mode and
export checks as a resumed session; no filesystem reset or new execution path is
introduced. Owner messages sent from Library use the same recovery path.

Slice events remain recorded. At delivery, only slices with an `add_slice` log
entry by `chat:<id>` wake chats, including previously pending events and old automatic messages already queued in a chat. Owner and
planner slices remain with their existing owners, including Home/notice ownership
after historical chat delivery; no chat tool's scope changes.
The first event line includes the slice ID. The transcript also derives that
label for historical messages without rewriting them. Grilling and Testing
feature-event delivery is unchanged. Home suppresses inactivity-only Stuck cards
while a reviewed merge waits for owner approval.

Migration `017_comment_resolution.sql` adds nullable resolution time and note
columns, with a constraint requiring a sent comment and a nonempty one-line note.
Drafts can be deleted. Sent comments can only be resolved, with a bounded one-line
note. Resolved comments lose their passage highlights and appear in a collapsed
`Resolved (n)` list with note, receiving chat and resolution time. The owner HTTP
routes use the existing mutation header and serialized transaction path. No
comment operation is exposed to chats. No sent comment, message or event record
is deleted; version 1 state and stage/scheduling rules remain unchanged.

## Reproducible measurements

`tests/measure_pages.py` creates and drops its own schema on disposable Postgres
17. It uses 24 features, 41 slices with roughly 3 KB of history each, approximately
4 KB of section text per feature, and an eight-message chat. It measures seven
Flask test-client responses per endpoint, including serialization and response
bytes. These are local synthetic measurements, not HTTP timings on the owner
node. Compare the pinned base and this branch with the same fixture:

```sh
CPLANE_TEST_DATABASE_URL=... uv run python tests/measure_pages.py --source /path/to/pinned-base
CPLANE_TEST_DATABASE_URL=... uv run python tests/measure_pages.py
```

A source archive used for the baseline needs a `REVISION` containing the pinned
commit, as required by the existing skill-version code outside a Git checkout.

| Endpoint | Before median / max (ms) | Before bytes | After median / max (ms) | After bytes |
| --- | ---: | ---: | ---: | ---: |
| `/api/home` | 162.06 / 249.70 | 257,862 | 52.50 / 80.86 | 7,642 |
| `/api/pipeline` | 94.25 / 100.23 | 257,685 | 9.54 / 10.64 | 7,465 |
| `/api/pipeline/FAC-F1` | 92.85 / 94.25 | 11,763 | 54.45 / 61.06 | 11,788 |
| `/api/factory/sessions/2/messages` | 7.92 / 8.10 | 4,738 | 9.33 / 15.38 | 4,738 |

Measured 2026-11-09, against pinned base
`d47eb70f6768be8665035102ea05730ec214567f` and this implementation, on the same
local Postgres 17.6 instance with other tests stopped. Both lists meet the local
200 ms / 40 KB targets, including the slowest of seven samples. List payloads
shrank approximately 97%. Chat messages remain the same size; the gain there is
fewer polling requests. Real node measurements remain necessary.

## Validation

- `CPLANE_TEST_DATABASE_URL=... uv run pytest`: **1,325 passed, 1 skipped**, in
  142.23 seconds; **278 Postgres 17 tests passed**. The skip is the existing
  Docker-dependent mount test, because Docker is unavailable in this container.
- `uv run --with nodejs-wheel npm test --prefix ui`: **44 tests passed** in 12
  files, including contrast, with Node 24.19.0. CI uses its existing Node 22 job.
- `uv run --with nodejs-wheel npm test --prefix ui -- src/contrast.test.js`:
  **1 passed** explicitly.
- `uv run --with nodejs-wheel npm run build --prefix ui`: **passed**. Vite retains
  its existing warning about the main JavaScript chunk exceeding 500 KB.
- `git diff --check`: passed.

Postgres 17 and Node test tools were bootstrapped outside the tracked tree;
`psycopg-binary` supplied the missing local libpq for tests only. No dependency or
lockfile changed. An initial full run exhausted the container's 512 MB temporary
filesystem; the disposable database was reinitialized on the workspace filesystem
and the final full run above completed successfully. GitHub `test` and `ui` checks
must still be verified by the runner before merging.


## Installation and node verification

After the PR has green `test` and `ui` checks and is merged, request the existing
reviewed installation with:

```sh
sudo factory-install factory/CS1
```

That command starts the separate installer unit. Wait for it to complete and
verify `/opt/factory/REVISION` matches the merged commit. It builds the UI, runs
additive migrations and restarts the UI and sessions services. Repeat these
read-only timings, using a real feature ID, chat area and chat ID:

```sh
curl -sS -o /dev/null -w 'home %{time_total}s %{size_download} bytes\n' http://127.0.0.1:8300/api/home
curl -sS -o /dev/null -w 'pipeline %{time_total}s %{size_download} bytes\n' http://127.0.0.1:8300/api/pipeline
curl -sS -o /dev/null -w 'feature %{time_total}s %{size_download} bytes\n' http://127.0.0.1:8300/api/pipeline/FEATURE_ID
curl -sS -o /dev/null -w 'messages %{time_total}s %{size_download} bytes\n' http://127.0.0.1:8300/api/AREA/sessions/CHAT_ID/messages
```

Repeat seven times; list targets are below 200 ms and 40 KB. The node owns the
final measurements, browser smoke check, installation and CI/merge verification.
No browser is available in the executor; UI behavior is covered with jsdom.
