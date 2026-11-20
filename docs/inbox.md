# Inbox intake and ideas

This document covers inbox arrivals, the Secretary chat that routes them, ideas,
the intake socket protocol and the owner's inbox and idea commands and API. Read it
before you change intake, the Secretary, ideas or their pages.

The inbox has a singleton Secretary, immutable arrival provenance, attachments,
ideas, feature links, actor history and durable exploration/promotion requests,
all beside the version 1 slice documents. Entries have no delete operation. Attachments
are Postgres `bytea` records under the same transaction as the entry and its wake;
no sender-controlled filesystem paths are used. Include them in database backups.

The Secretary uses Codex `gpt-6-luna` at low effort. Its tool/model can be configured
through the existing chat configuration/defaults commands. It has a Factory-area
workspace with read-only planning exports, rather than the Development
Orchestrator's writable homelab planning workspace. It receives the existing
Workshop reads plus inbox/idea reads, and only three writes: `inbox_route`,
`inbox_answer`, `secretary_question`. Host authorization checks each call even if
an agent invokes a tool absent from its advertised list. Its questions can target
only the Development Orchestrator or a project orchestrator. New arrival turns do not count toward the automatic-turn limit and are handled even when the Secretary is paused. The Secretary’s questions and returned orchestrator answers remain automatic turns subject to the pause limit. The Secretary
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
orchestrator transcript. Phone delivery is the bot's responsibility.

## Local socket protocol

The `intake` service binds only `/run/factory-intake/intake.sock`, sets the socket's
group to `CPLANE_INTAKE_GID` (977 in `compose.yaml`) and its mode to 0660. The host
prepares `/run/factory-intake` ([node](node.md)); the phone bot connects as a member
of that group. The listener uses `AF_UNIX` only and opens no network port; the
service connects to Postgres with its own database URL secret and reads no runner
settings. Attachments stay in Postgres and need no filesystem write.

Send one UTF-8 JSON object followed by a newline per connection:

```json
{"text":"Owner's original words","fields":{"kind":"idea","target":"development","intent":"explore","related":[],"clarifications":[],"due_date":"2026-12-01"},"files":[{"name":"note.txt","media_type":"text/plain","base64":"SGVsbG8="}]}
```

Only `text`, `fields`, `files` are accepted. `text` is required (it may be empty
when files are supplied). Sender fields are optional and restricted to the keys
shown. Sender kinds are `idea`, `link`, `file`, `message`; intent is `explore` or
`discuss`. Targets may be `development`, a project key or its unique name.
Arrival kinds are preserved independently of the Secretary's five labels. Each arrival turn lists existing project keys and names; the Secretary selects the matching project key and uses `new project` only when no existing project fits. The `development` target selects the Development Orchestrator and does not imply a new project.
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

## Owner page and API

All writes require the existing `X-Factory-UI: 1` header and operate as `owner`.
The Ideas page at `/ideas` provides Inbox and Ideas tabs, owner routing, idea actions and detail views. Failed or refused arrival turns remain New and display a fixed reason; raw errors are not shown.

| Method | Path | Payload/result |
| --- | --- | --- |
| GET | `/api/inbox` | Entries, newest first, with labels, routes and links |
| POST | `/api/inbox` | Socket arrival shape; source is always `typed` |
| GET | `/api/inbox/<entry>` | Original text/fields, metadata, transcript, idea/message links |
| GET | `/api/inbox/files/<file>?offset=0` | Up to 64,000 bytes, base64, total length and offset |
| POST | `/api/inbox/<entry>/transcript` | `{text}` |
| POST | `/api/inbox/<entry>/route` | `{route: "Idea"}`, `{route: "chat", chat: 42}`, or `{route: "Rejected", reason: "One line"}` |
| GET | `/api/ideas` | Ideas, newest first |
| POST | `/api/ideas` | `{title, note?, tags?, files?}`; New idea with typed provenance (files use the socket shape) |
| GET | `/api/ideas/<idea>` | Idea, attachments, feature links, state and actor history |
| POST | `/api/ideas/explore` | `{ideas: [7,8], project?: "FAC"}` |
| POST | `/api/ideas/promote` | `{ideas: [7,8], project?: "FAC", feature?: "FAC-F1"}` |
| POST | `/api/ideas/reject` | `{idea: 7, reason: "One line"}` |
| POST | `/api/ideas/tag` | `{idea: 7, tags: ["FAC", "intake"]}` |

API responses retain owner content; the page renders it as text, never HTML. Reads do not execute models. Explore/promote enqueue chat work and return
its message ID; the detail/history endpoints expose subsequent completion.

## Pages

The Chats page includes the Secretary group. Rollback leaves the additive inbox
migrations, the intake group and all durable records in place.
