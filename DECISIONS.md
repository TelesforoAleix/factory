# Decisions

This log records Factory's design decisions: what was decided, when and why. Read
it before you reverse or work around a decision. It is append-only: add a new dated
entry at the end, and never edit an old one; a later entry may supersede an earlier
one. Each date is the day the change merged, from git history. The current design
is in [ARCHITECTURE.md](ARCHITECTURE.md).

## 2026-10-15 — A slice is a bounded contract, and its questions stay on it

Each slice has one branch, one PR, one done-criterion and a validated state.
Questions and escalations are attention on the slice that raised them, so a missing
answer holds that slice only and other eligible work continues.

## 2026-11-06 — Postgres stores work state and notices together

Slice documents and their notices commit or roll back in one transaction, under one
lock per runner pass. On 2026-11-11 the file store was removed as a production
backend; file state remains only as a test double and an import/export format.

## 2026-11-07 — A feature needs an agreed design before work

Features move through fixed stages, with the actor allowed for each move. A
feature reaches Ready only after the orchestrator records the agreed design and
writes the slice briefs.

## 2026-11-08 — Merged results are records; defects become correction slices

A merged branch is never edited to repair a defect. A correction is a new slice
linked to the one it corrects, so every merged result stays a true record.

## 2026-11-09 — An idea is not a commitment

Inbox arrivals and ideas are kept apart from features. An idea can be classified,
explored, promoted or rejected; only promotion creates or links a feature.

## 2026-11-11 — GitHub access uses an App, scoped per repository

The runner and sessions use GitHub App installation tokens, each scoped to the
repository of its call, instead of a personal token. From 2026-11-13, sessions
receive read-only tokens.

## 2026-11-12 — Change classes come from the pinned base

Each repository's `.github/change-classes` assigns classes 1, 2 and 4 to paths,
read from the PR's pinned base so a PR cannot lower its own class. Class 4 guard
paths need the owner's GitHub approval. Class 3, proceed and notify, is a
decision rule, not a path class.

## 2026-11-12 — Public PR metadata passes a private-content deny-list

Factory scans the branch name, PR title and PR body for public repositories before
writing them, and refuses a write that matches. The platform separately scans outgoing commits.

## 2026-11-15 — Factory runs as four containers installed by the platform deployer

`ui`, `intake`, `sessions` and `runner` run from one image under the root
`compose.yaml`, installed by the deployer from a merged commit. The host checkout,
systemd units and host installer were removed on 2026-11-16.

## 2026-11-16 — CI runs on pull requests only

The runner merges only with green checks on an up-to-date PR head, so CI on pushes
to `main` would repeat work. Path filters and one combined image job reduce
billed Actions minutes.

## 2026-11-16 — Review findings are evidence, not the merge gate

A separate read-only review run checks each PR beside CI. Its verdict is
recorded and advisory; green CI on the current head and any required approval
control the merge. A failed or late review records `missing`.

## 2026-11-17 — Factory asks for work by role and level; the platform executes it

Slice, cut, ticket and review work goes to the platform run API with a role and a
level. The platform chooses the executor, handles usage waits and concurrency,
isolates the repository and delivers the branch, so sandbox rules and usage waits
live in one place. Factory keeps PRs, CI, approval, attention and node steps.
The switch was installed at a quiet slice boundary; rollback reinstalls the
previous image, with no dual execution path.

## 2026-11-18 — Evals reuse the runner pipeline against accepted work

Eval attempts run the same job code as slices, marked as evals, on their own
branches, and never open PRs or change slices. Cases come from accepted slices,
with hidden tests and the reference diff kept from the executor.

## 2026-11-19 — Slice eval attempts are graded by a fixed judge

A fixed judge, with a hashed prompt from `skills/judge.md`, compares the brief, the
attempt diff and the reference diff with hidden tests removed, rather than trusting
the executor's own account of success.

## 2026-11-19 — Contracts are declared in the PR request and checked after merge

The executor's PR request carries `contract_changes`. After a merge the runner raises
`contract-change` attention for each declared change and runs the documentation
graph check on the merged commit, raising `docs-graph` attention when it fails.
Neither blocks the merge or the install.

## 2026-11-20 — A claim passes only when all three answers say supported

`cplane docs-verify` records the classifier's confidence and agreement but decides
each verdict from the three answers alone.

## 2026-11-20 — A tests-only change keeps the PR review

When a new PR tip differs from the reviewed tip only in test files, the recorded
review stays, so a repair to tests does not start a new review.

## 2026-11-20 — Factory documents itself with one core set

Every repository keeps the same core documents: AGENTS.md as the router with a
document map, ARCHITECTURE.md, docs/contracts.md, docs/operations.md, this log and
one document per recurring procedure, with `docs/claims.json` proving each factual
claim. A link test in `uv run pytest` keeps the map, links and citations valid.
Operator text that described past installations (the file store, the launchd
runner, the container cutover and the run API switch) was removed from the
reference documents; git history keeps it.

## 2026-11-20 — Contracts between repositories are machine-checked by one tool

Each contract is a schema generated from code in the repository that provides it
and committed there; each user keeps a pinned copy. Both sides run one tool in CI,
`factory-contracts` from the new `contracts` package, so the rules cannot drift
between repositories.

1. Full compatibility: a change must work with the previous version in both
   directions. `compat` runs `oasdiff breaking` (pinned v1.37.0) from base to
   revision and from revision to base, and fails when either reports a breaking
   change, naming the direction and each rule id.
2. One canonical JSON form for every file the tool writes or compares:
   `json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"`.
3. A pin is a folder with the provider's canonical `schema.json` and `pin.json`
   holding exactly `contract`, `provider`, `commit` and `sha256`; there are no
   version numbers.
4. Tolerant readers, strict senders: the sender check refuses any request field the
   pinned schema does not define for the operation, following `$ref`, and validates
   the known fields' types with `jsonschema`.
5. Each check names its practice skill in `skills/`; a test fails when a check has
   no skill file or names one that does not exist.
6. The `contracts` package ships in the existing distribution as the
   `factory-contracts` script, imports only the standard library and `jsonschema`,
   never `cplane` or `factory_ui`, and finds `oasdiff` from `--oasdiff`, `OASDIFF`,
   then `PATH`.

## 2026-11-20 — The run-api pin and the sender check

Factory pins the provider's run-api OpenAPI document in `pins/run-api/`
(`TelesforoAleix/homelab-v2` at `e675179213ccc9cd81f44d69035aa995e6d034f7`). The sender
check is a test, `tests/test_run_api_contract.py`, in the existing `uv run pytest` step:
it verifies the pin and checks bodies built by the runner's own code (slice, cut,
ticket and review requests, an answer, the completion message) with
`contracts.sender.check`, plus one misspelt-key negative case.

The check found a gap. Factory's cancel call sends `{}`, but the pinned cancel
operation defines no request body, and Home Lab's cancel never reads one. The true
contract is that cancel takes no body. The runner fix (send a POST with no JSON body)
is a follow-up slice, outside this slice's allowed files. Until then the cancel test is
`xfail(strict=True)`, so it fails the day the gap closes and must then be unmarked.
## 2026-11-20 — Run API cancel sends no request body

Factory sends the run API cancel operation as POST with no body or JSON content
type, matching the pinned schema and Home Lab handler. The sender accepts a missing
body only for operations whose pinned schema defines no JSON request body.

## 2026-11-20 — The compatibility check accepts a new operation and a new response enum value

`factory-contracts compat` no longer fails on two additions that readers tolerate: a
new operation (a user treats a 404 from a new endpoint as "not available yet") and a new
response enum value (a reader maps an unknown value to its fallback). oasdiff reports
them as level 3 findings, so `compare` accepts exactly `api-path-removed-without-deprecation`
and `api-removed-without-deprecation` in the direction revision against base, and
`response-property-enum-value-added` in the direction base against revision. The same
ids in the other direction stay breaking. A direction passes when it has no other
level 3 finding; oasdiff's exit code 1 alone no longer decides. Accepted findings are
listed as `tolerated`. There is no option to widen the set: a new id needs a reviewed
code change.

## 2026-11-21 — Pins discover the catalog and drive contract updates

The runner discovers contract users from active projects' default-branch pins,
then reads and hashes each provider's committed canonical schema. There is no
separate catalog registry. `cplane contracts catalog` reads this live catalog;
the job saves it beside the state anchor.

Each outdated user gets a two-file pin commit and one `contracts/<contract>` PR,
written through the Git Data API without a checkout. Equal hashes and branches
already carrying the provider pin need no write. Factory retains the public PR
deny check. Green CI merges as class 1 without review only after the App author,
branch, exact pin paths and head are checked; invalid PRs raise planner attention.
Red CI creates a planned adaptation slice with no brief and one planner attention
per PR head, through the store's locked mutation path.

Open update PRs are checked each pass. Full scans run daily after 03:45 local time
and after recorded provider-schema merges, with dates and observed merges saved
across restarts. A scan before the daily boundary does not consume that day's
scheduled scan. Errors never fail the runner pass. The existing claims-based
contract-change notice stays until other contracts move to pins.

## 2026-11-21 — Identify update PR authors by the App bot login

The update PR guard checks for a Bot whose login is the authenticated Factory
App's slug followed by `[bot]`. GitHub's issue attribution can be null for an
App-created PR, so it is not evidence for this guard. The runner reads the App
slug with an App JWT, verifies the returned App id, and caches the slug per
process. A failed slug read is transient and does not create planner attention.
The other update PR checks remain unchanged.

## 2026-11-21 — The drain check gates a contract step

A contract step is marked on its slice with an optional `contract_step` object
(contract, old shape, expand slice, quiet days, default 7), added to the slice
schema rather than patched in at import. Eligibility blocks the slice with reason
`drain` until the expand slice has merged, Home Lab's usage counter shows no use
of the old shape for the quiet days, and no slice or run job created before the
expand merge is still open in the contract's catalog repositories. The check fails
closed and reads the usage endpoint at most once per pass. New unknown fields in
the same answer raise one planner notice each, on the provider's repository; the
first read only records them. The slice state format keeps version 1: the field is
optional and Factory's own.

