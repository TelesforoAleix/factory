# Inbox intake and ideas

Migration 019 adds a singleton Secretary, immutable arrival provenance, attachments,
ideas, feature links, actor history and durable exploration/promotion requests. It
preserves version 1 slice documents. Entries have no delete operation. Attachments
are Postgres `bytea` records under the same transaction as the entry and its wake;
no sender-controlled filesystem paths are used. Include them in database backups.

The Secretary uses Codex `gpt-6-luna` at low effort. Its tool/model can be configured
through the existing chat configuration/defaults commands. It has a Factory-area
workspace with read-only planning exports, rather than the Development
Orchestrator's writable homelab planning workspace. It receives the existing
Workshop reads plus inbox/idea reads, and only three writes: `inbox_route`,
`inbox_answer`, `secretary_question`. Host authorization checks each call even if
an agent invokes a tool absent from its advertised list. Its questions can target
only the Development Orchestrator or a project orchestrator. All new arrivals, questions and returned orchestrator answers are automatic turns and retain the existing pause limit. The Secretary
cannot be archived. A fresh arrival after a failed Secretary turn starts a fresh
CLI conversation while preserving the automatic count and pause. Archived or
failed destination chats refuse delivery, leaving arrivals New for the owner.

Text, sender fields, transcripts and file results are explicitly marked as phone
data, never instructions. Deliveries retain the owner's complete original text
inside a uniquely delimited verbatim block, then the Secretary's label. File
contents are available through bounded base64 reads, including arbitrary binary
files; no automatic PDF parsing or audio transcription service is added. Audio
metadata says `not transcribed` until an entry transcript is attached.

The Secretary's successful arrival-turn reply and the successful reply to the
exact delivered chat message become existing `owner-check` notices, which the
runner already exports to the phone. Self-answered update requests retain a link
to an assistant message in the Secretary chat. Answers to Secretary questions return in durable automatic turns; unusually large
answers are bounded for the return prompt, with the full reply retained in the
orchestrator transcript. Phone delivery remains the bot's
responsibility; this slice does not change or connect the bot.

## Local socket protocol

`factory-intake.service` runs as the dedicated `factory-intake` system user and
binds only `/run/factory-intake/intake.sock`. Systemd creates the runtime directory
as factory-intake:factory-intake, mode 0750; the service owns its socket with group
factory-intake and mode 0660. The installer creates the system group and a system
user with no login or home directory, and adds `homelab-bot` to the group. It
refuses an existing account with conflicting ownership, home or login settings.
Existing bot processes need restarting by their operator to acquire supplementary
membership.
The intake listener uses `AF_UNIX` only and opens no network port; the service
may still connect to Postgres using the existing configured database URL.

The service reuses `/etc/factory/ui.env`, the existing **database-only** settings
file. It remains root:root 0600: systemd reads it before dropping privileges and
passes `CPLANE_DATABASE_URL` in the process environment. The service does not read
`runner.env`, the GitHub token, or other runner settings. No credential file is
made group-readable and no database secret is copied into the checkout or unit.
This uses the same credential-loading arrangement as the existing unprivileged
UI service. Before installation, confirm `ui.env` still contains only that
assignment. If this node instead uses a password/service file inaccessible to the
new account or hidden by the sandbox, **stop and escalate**; do not broaden its
permissions. Options for owner review are a dedicated intake database login in a
root-only environment file, or a service-private systemd credential provisioned
with `LoadCredential`. This slice does not provision either automatically.

The unit keeps `NoNewPrivileges`, clears capabilities, and enables
`ProtectSystem=strict`, `ProtectHome=true`, `PrivateTmp=true`, private devices and
SUID/personality restrictions. Its only explicit `ReadWritePaths` grant is
`/run/factory-intake`; attachments remain in Postgres and need no filesystem write
grant. Runner secrets, runner storage and Docker sockets are also inaccessible.
Database sockets under the host's `/tmp` and credentials under home directories
are intentionally unavailable, as for the existing UI sandbox. Private temporary
storage is ephemeral. The runtime directory disappears when the service stops.

Send one UTF-8 JSON object followed by a newline per connection:

```json
{"text":"Owner's original words","fields":{"kind":"idea","target":"development","intent":"explore","related":[],"clarifications":[],"due_date":"2026-12-01"},"files":[{"name":"note.txt","media_type":"text/plain","base64":"SGVsbG8="}]}
```

Only `text`, `fields`, `files` are accepted. `text` is required (it may be empty
when files are supplied). Sender fields are optional and restricted to the keys
shown. Sender kinds are `idea`, `link`, `file`, `message`; intent is `explore` or
`discuss`. Targets may be `development`, a project key or its unique name.
Arrival kinds are preserved independently of the Secretary's five labels.
The response is `{"id":42}` or an error object, then the connection closes.
There is no deduplication key: retries create separate arrivals. A client that
loses a response should check the inbox before resubmitting.

Bounds: 16,000 text characters (24,000 JSON-encoded characters), 4,000 encoded
sender-field characters, ten files, 8 MiB per file, 16 MiB total file content,
4,000 encoded file-metadata characters, and 23 MiB per wire request. File names
must be simple names without path separators. Requests time out after ten
seconds. Invalid payloads and failed transactions create no partial entry, file
or wake. Files are immutable; transcripts attach later without changing originals.

## Owner commands and lifecycle

```sh
factory-cplane --actor owner inbox add 'A useful idea' --kind idea --target FAC
factory-cplane inbox add 'See attachment' --file /tmp/synthetic-note.txt
factory-cplane inbox list
factory-cplane inbox show 42
factory-cplane --actor transcriber inbox transcript 42 'Transcribed owner words'
factory-cplane --actor owner idea add 'New idea' --note 'Why it matters' --tag FAC
factory-cplane idea list
factory-cplane idea show 7
factory-cplane --actor owner idea tag 7 FAC intake
factory-cplane --actor owner idea explore 7 8 --project FAC
factory-cplane --actor owner idea promote 7 8 --project FAC
factory-cplane --actor owner idea promote 9 --feature FAC-F1
factory-cplane --actor owner idea reject 10 --reason 'No longer useful'
```

`idea add` / New idea retains a typed inbox entry, files and a Secretary wake as
provenance, then creates an idea in `new`. Secretary classification makes an idea
`classified`; uncertainty leaves it `new` and its arrival `New`. Owner actions
record actor history. Owner-only actions require actor `owner`; transcript
attachment accepts the service's actor name. No planner or executor is launched
by these commands.

Explore sends one message for up to twenty ideas to the chosen project (inferred
from a single existing project tag when omitted), or to Development for a new
project. A successful reply to that exact message is saved on every idea, which
remains `exploring`. Promotion to an existing feature links the ideas and sends
context to its feature chat, or its project orchestrator when the feature chat is absent, archived or failed. New-feature promotion
requires an existing project; it never silently creates a project. Its
orchestrator drafts a short title and 2–3 sentence summary, then calls
`idea_draft` for the running request message ID. The host validates that chat and
pending owner request before atomically creating a Shortlist feature, saving its
Summary and linking every idea. Repeated or cancelled drafts cannot create a
second feature. Ideas become `implemented` when any linked feature reaches Done,
including owner correction closes. Reject requires a one-line reason; already
promoted/implemented ideas cannot be rejected. The existing 32,000-character
chat-message limit also applies to combined idea context; split a larger batch.

## API for the next page

All writes require the existing `X-Factory-UI: 1` header and operate as `owner`.
No page is included.

| Method | Path | Payload/result |
| --- | --- | --- |
| GET | `/api/inbox` | Entries, newest first, with labels, routes and links |
| POST | `/api/inbox` | Socket arrival shape; source is always `typed` |
| GET | `/api/inbox/<entry>` | Original text/fields, metadata, transcript, idea/message links |
| GET | `/api/inbox/files/<file>?offset=0` | Up to 64,000 bytes, base64, total length and offset |
| POST | `/api/inbox/<entry>/transcript` | `{text}` |
| GET | `/api/ideas` | Ideas, newest first |
| POST | `/api/ideas` | `{title, note?, tags?, files?}`; New idea with typed provenance (files use the socket shape) |
| GET | `/api/ideas/<idea>` | Idea, attachments, feature links, state and actor history |
| POST | `/api/ideas/explore` | `{ideas: [7,8], project?: "FAC"}` |
| POST | `/api/ideas/promote` | `{ideas: [7,8], project?: "FAC", feature?: "FAC-F1"}` |
| POST | `/api/ideas/reject` | `{idea: 7, reason: "One line"}` |
| POST | `/api/ideas/tag` | `{idea: 7, tags: ["FAC", "intake"]}` |

API responses retain owner content; the next page must render it as text, never
HTML. Reads do not execute models. Explore/promote enqueue chat work and return
its message ID; the detail/history endpoints expose subsequent completion.

## Validation and UI follow-up

IB1 local validation used Python 3.13.18 and a disposable Postgres 17.6 database
with synthetic schemas only:

```sh
CPLANE_TEST_DATABASE_URL='<disposable-Postgres-17-url>' uv run pytest -q --basetemp='<scratch-directory>'
cd ui
node /usr/local/lib/node_modules/npm/bin/npm-cli.js ci
node /usr/local/lib/node_modules/npm/bin/npm-cli.js test
node /usr/local/lib/node_modules/npm/bin/npm-cli.js run build
```

Python: 1,387 passed, including 331 Postgres tests; one Docker test skipped. UI: 56 tests in
13 files passed; production build passed with its existing bundle-size advisory.
The unprivileged-service update includes account creation/idempotence, refusal of
conflicting identities or a privileged group, socket ownership, database-only
settings and unit hardening checks. `git diff --check` passed. Remote `test` and
`ui` checks remain the runner's
responsibility before the owner merges.

The existing Chats page groups only its previous kinds. An unread Secretary
reply appears under Waiting for you, but after it is read the chat has no list
group. Its direct `/chats/<id>` route, message composer and model configuration
work. Find its ID with `factory-cplane chat list --kind secretary`. The next UI
slice should add its navigation group; IB1 changes only APIs, as scoped. No
Ideas page or Telegram bot integration is included here.

On installer rollback, intake is stopped before code is restored. Additive
migrations and the service account/group membership remain, as do all durable records.
