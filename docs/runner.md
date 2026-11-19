# Runner operation

Factory schedules and coordinates slices. The platform run service executes them.
The runner uses the existing `CPLANE_EVAL_TASK_URL` connection and the bearer key
file named by `CPLANE_EVAL_TASK_KEY_FILE`. Eval attempts use the same run API;
see [evals](evals.md) for marked execution and sealed grading.

A whole-slice request uses `role: slice`, `mode: write`, and the slice's level.
Factory reads the repository's default branch tip with its own App at the start,
pins that commit, and assigns `slice/<slice id with slashes replaced by hyphens>`.
The goal contains the brief and assignment. It includes the PR request format and
handover protocol, without local fence, bundle or implementation-push instructions.
Pre-merge PR results use a handover containing the PR JSON so the platform can
release dependent review work. A legacy waiting result receives an idempotent
acknowledgment message on the same run asking it to finish done before successors.
If blocked before committing, the executor commits nothing and explains why in
the PR body. A done slice with no commits raises that final body as a question
without reading a branch that the platform did not create.

Ticket flow submits a write-mode `cut` run to commit the failing tests, then one
write-mode `ticket` request per plan ticket. Each request includes its goal,
allowed files, pinned tests and check command. `after` chains request ids in plan
order, starting with the cut. A ticket goal ends with an assignment to review its
own diff against the ticket and check, correcting mismatches before finishing.
The platform runs the check, commits and pushes; the ticket executor does not.
The cut ends with a handover so its platform status is done and successors can
run. After the last ticket is done, Factory opens the PR with the slice title and
a body listing every ticket's title and check. The cut plan supplies the node step
from the brief, or null when none is declared. After merge, Factory records the PR
request and review verdict and findings as the final handover, then moves to the
node step or in review without messaging the cut run. New ticket flows have no blocking
slice review or repair tickets. Saved jobs already in `review-ready` or a repair
round can finish through their existing path.

Both flows receive the same PR review beside CI, in a separate read run with full
history. Review goals request a handover carrying verdict JSON; the parser also
accepts a waiting final and prose after its leading JSON block. The review records
pass, fix or missing; its verdict never gates a merge. Factory waits for its end
or time limit (default 20 minutes); failures and timeouts record missing and let
CI and approval decide the merge. Questions create attention and answers route to
the review run; an unanswered question also expires at the deadline. A waiting
review can be cancelled after its verdict is recorded.

The review's `review_tip` and request base record the commit reviewed. New slice
commits supersede the prior review and start a new review on the new tip, with a
new deadline. Supersession is recorded in the slice log with the old purpose and
tips; its original request remains in the ledger. It is never recorded as missing.
A BEHIND update from the default branch keeps the existing review and its reviewed
tip. Factory retains PR creation, red/pending/green CI handling, branch updates, guard-path
classification, owner GitHub approval, merge, notices and node steps. Policy comes
from the pinned base; PR paths include deletions and rename sources. Uninstalled
Factory guard drift is checked with App reads. GitHub truncation fails closed.
Public PR metadata still passes Factory's deny-list scan before a write.

The platform owns model/tool/effort selection by role and level, provider fallback,
usage waits, harness concurrency and repository exclusion, copies, allowed/pinned
path checks, outgoing public-commit scans and non-force branch delivery. Factory
neither launches a slice process nor reads Codex/Claude usage. Eval attempts use the same runner job code with an eval mark on each request.
Their private adapter stops at the PR boundary, runs sealed grading and deletes
the attempt branch; it never opens a PR or changes scheduler slices. Chats retain
the sessions service and launcher. The deny-list mount still protects PR metadata.

## Durable requests and messages

Private jobs live under
`CPLANE_RUNS/<state hash>/<slice hash>-attempt-<number>/job.json`. Each job saves its
slice attempt number. Request ids hash the slice identity and attempt, then append
a purpose (`slice`, `cut`, `ticket-N`,
`review-N`, or a repair ticket). The exact body is persisted before POST. A lost
response retries that same id/body; a confirmed request is recovered by polling.
Do not delete the ledger or change its state path during active work.

Moving an escalated slice to ready and starting it creates the next attempt,
even when its old run is resumable. The mutation log records the restart request
against the old run. Starting clears its attention, cancels the old attempt's
runs, and uses a new job folder, new request ids and the default branch's current
tip. The slice keeps its id, brief, level, flow and branch name. Resetting other
terminal, non-resumable runs to ready also uses this existing attempt mechanism.
Old attempt records remain available. Before retrying a failed ticket chain,
Factory cancels its old queued successors and resumable predecessors, waiting for any running turn's
cancellation to be accepted. A question, waiting or done run that is resumable
keeps its attempt and continues through messages. Existing jobs without an attempt
number keep their saved identities and count as attempt one when retried.

Answers and whole-slice merge notices are messages to the existing resumable run. Message ids
include the attempt in their hashed identity, and their exact text is persisted
before POST. Collected-result markers are also scoped to the attempt. No restart
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
state retains its legacy executor/session fields for compatibility. `show`, the
slice detail API and Workshop display the slice's run records newest first, with
role, tool, model, effort and start time. Records created before roles were stored
have an empty role; slices without records have no runs to display. Reading records
does not migrate them, and finished slices are left unchanged by runner passes.
Synthetic file-store planner tests retain level selection in mutation log entries
because that document contract has no level field. There is no model fallback in Factory.

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

## PR request and post-merge checks

The executor's PR request is `{branch, title, body, node_steps, contract_changes}`.
`contract_changes` is required: `null`, or a non-empty list of
`{"name", "version", "users": ["owner/name", ...]}` with non-empty users. A request
without it, or with a malformed one, is invalid. A saved job request without the field
(written earlier) is read as `null`.

After a merge the runner may raise two further attention items, one after another and
after any `node-step` is answered. Neither blocks the merge or the install.
- `contract-change`: lists each contract, its new version and its user repositories; each
  user repository needs an adapting slice in the same Feature.
- `docs-graph`: when the merged commit has `docs/claims.json`, the runner reads that
  commit through the GitHub API and runs the `--graph-only` check, logs `docs-graph:
  pass|fail`, and raises this item with the failing rule lines on exit 1 or 2. Without
  `docs/claims.json` nothing is logged.
