---
template_version: "0.1"
object_type: release_checklist
id: RELEASE-YYYY-0001
title: "Release checklist title"
status: draft
project_id: PROJECT-ID
release_scope: task
owner_role: "Release Agent"
related_task_id: TASK-YYYY-0001
ticket_ids:
  - TICKET-YYYY-0001
review_ids: []
approval_ids: []
test_evidence: []
docs_updated:
  required: true
  complete: false
scope_match: null
release_decision: null
branch_name: null
commit_message: null
pr_url: null
release_notes: ""
changed_files: []
migration_notes: ""
rollback_notes: ""
blocked_by: []
batching_reason: ""
post_release_followups: []
related_docs: []
related_objects: []
created_at: "YYYY-MM-DDTHH:MM:SSZ"
updated_at: "YYYY-MM-DDTHH:MM:SSZ"
---

# Release Checklist: Short Title

## Scope Match

- [ ] Result matches the assigned ticket or task scope.
- [ ] No unrelated work is included.
- [ ] Changed files are accounted for.

## Review And Testing

- [ ] Execution self-review is complete.
- [ ] Fresh-context review passed or requested revisions are complete.
- [ ] Required specialist reviews are complete.
- [ ] Tests or checks are sufficient for the risk level.

## Docs And State

- [ ] Ticket and task state are updated.
- [ ] Project docs, decisions, changelog, or release notes are updated when needed.
- [ ] Founder inbox items and approvals are closed or explicitly carried forward.

## Release Decision

Record the release agent's decision, commit or PR details, and any follow-up tickets.