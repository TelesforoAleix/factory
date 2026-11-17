# Runner operation

Factory schedules and coordinates slices. The platform run service executes them.
The runner uses the existing `CPLANE_EVAL_TASK_URL` connection and the bearer key
file named by `CPLANE_EVAL_TASK_KEY_FILE`; eval routes and behavior are unchanged.

A whole-slice request uses `role: slice`, `mode: write`, and the slice's level.
Factory reads the repository's default branch tip with its own App at the start,
pins that commit, and assigns `slice/<slice id with slashes replaced by hyphens>`.
The goal contains the brief and assignment. It includes the PR request format and
handover protocol, without local fence, bundle or implementation-push instructions.
Pre-merge PR results use a handover containing the PR JSON so the platform can
release dependent review work. A legacy waiting result receives an idempotent
acknowledgment message on the same run asking it to finish done before successors.

Ticket flow submits a write-mode `cut` run to commit the failing tests, then one
write-mode `ticket` request per plan ticket. Each request includes its goal,
allowed files, pinned tests and check command. `after` chains request ids in plan
order, starting with the cut. The cut ends with a handover so its platform status
is done and successors can run. A read-mode review uses the delivered branch tip
and full history. One repair round remains supported. Review goals request a
handover carrying the verdict JSON; the parser also accepts a waiting final and
allows prose after its leading JSON block.

Whole-slice PR review is a separate read run. It records pass, fix or missing as
before; CI and the existing approval rules still decide whether to merge. Review
questions and failures create attention; answers route to the review run. A
record-only waiting review can be cancelled after its verdict is recorded. Factory
retains PR creation, red/pending/green CI handling, branch updates, guard-path
classification, owner GitHub approval, merge, notices and node steps. Policy comes
from the pinned base; PR paths include deletions and rename sources. Uninstalled
Factory guard drift is checked with App reads. GitHub truncation fails closed.
Public PR metadata still passes Factory's deny-list scan before a write.

The platform owns model/tool/effort selection by role and level, provider fallback,
usage waits, harness concurrency and repository exclusion, copies, allowed/pinned
path checks, outgoing public-commit scans and non-force branch delivery. Factory
neither launches a slice process nor reads Codex/Claude usage. Subscription evals
keep their separate legacy adapter; chats retain the sessions service and launcher.
Consequently the runner still needs its existing launcher/clean/work mounts for
evals, and its deny-list mount for PR metadata. The sessions service is unchanged.

## Durable requests and messages

Private jobs live under `CPLANE_RUNS/<state hash>/<slice hash>/job.json`. Request ids
hash the slice identity and append a purpose (`slice`, `cut`, `ticket-N`,
`review-N`, or a repair ticket). The exact body is persisted before POST. A lost
response retries that same id/body; a confirmed request is recovered by polling.
Do not delete the ledger or change its state path during active work.

Answers and merge notices are messages to the existing resumable run. Message ids
are deterministic, and their exact text is persisted before POST. No restart
searches for or stops slice containers. API failures defer work without exposing
response bodies, keys, App ids or node ids.

Polling maps done to handover/PR processing; question and escalated to attention
with the final body; client-step waiting to PR or node-step handling; failed and
cancelled to escalation with the status reason. Usage-limit waiting logs and shows
`resume_at` without attention. The platform resumes usage waits automatically.

Pause sends no new request or message and cancels nothing. Factory keeps polling
and saves results, then acts on them after unpause. Permanent abandonment (dropped
or accepted/closed state) cancels queued and resumable runs immediately. Cancellation
of running runs retries each pass after `409 not_resumable`, until the turn ends.
Unpause therefore never needs a cancelled run.

Slice levels remain in the existing Postgres table; overrides and old role rows
are no longer read for execution. Columns and tables remain untouched. Version 1
state retains its legacy executor/session fields for compatibility. Synthetic
file-store planner tests retain level selection in mutation log entries because
that document contract has no level field. There is no model fallback in Factory.

## Switch and rollback

**Install at the switch only**, through the deployer. The PR is a guard-path change:
it waits for the owner's GitHub review and remains open until rehearsal starts.
Enable the platform roles and its write-cut fix before installation. Switch at a
quiescent slice boundary: existing local-fence jobs have no automatic conversion. Rehearse one
whole-slice slice and one ticket slice through delivery, review, CI and merge.

Rollback reinstalls the previous Factory image. There is no dual execution path or
database migration. Coordinate running platform work before rollback and keep its
private ledger to prevent duplicate work. The switch rehearsal is an owner-node
step, not a local test or an action performed by this PR.

The wire contract is maintained in the public platform repository:
[request models](https://github.com/TelesforoAleix/homelab-v2/blob/main/src/homelab/api/run_contract.py),
[routes and records](https://github.com/TelesforoAleix/homelab-v2/blob/main/src/homelab/api/runs.py),
[run storage and cancellation](https://github.com/TelesforoAleix/homelab-v2/blob/main/src/homelab/tasks/runs.py).
Explicit per-run limits are omitted: the live API rejects a supplied `limits` field.
