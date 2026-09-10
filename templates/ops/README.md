# The Factory Ops Templates

Initial examples for the file-backed `ops/` objects described in [V0 Operating Objects](../../design/v0-operating-objects.md).

Use these as copyable starting points when creating a real project workspace. The filenames are generic template names, not live object IDs.

## Files

| Template | Future Project Destination | Object |
|---|---|---|
| [task.yaml](task.yaml) | `ops/tasks/TASK-YYYY-0001.yaml` | Task |
| [ticket.yaml](ticket.yaml) | `ops/tickets/TICKET-YYYY-0001.yaml` | Ticket |
| [run.json](run.json) | `ops/runs/RUN-YYYY-0001.json` | Run / Session |
| [interaction.yaml](interaction.yaml) | `ops/interactions/INTERACTION-YYYY-0001.yaml` | Interaction / Communication Card |
| [founder-inbox-item.yaml](founder-inbox-item.yaml) | `ops/inbox/INBOX-YYYY-0001.yaml` | Founder Inbox Item |
| [approval.yaml](approval.yaml) | `ops/approvals/APPROVAL-YYYY-0001.yaml` | Approval |
| [context-pack.md](context-pack.md) | `ops/context-packs/CP-YYYY-0001.md` | Context Pack |
| [review-record.yaml](review-record.yaml) | `ops/reviews/REVIEW-YYYY-0001.yaml` | Review Record |
| [release-checklist.md](release-checklist.md) | `ops/releases/RELEASE-YYYY-0001.md` | Release Checklist |
| [learning-candidate.yaml](learning-candidate.yaml) | `ops/learning/LEARN-YYYY-0001.yaml` | Learning Candidate |

## Use Notes

- Replace placeholder IDs like `PROJECT-ID`, `GOAL-ID`, `TASK-YYYY-0001`, and `TICKET-YYYY-0001` with project-local stable IDs.
- Keep one file per object in v0.
- Keep product truth in product/spec docs; use these files for operating state.
- Add fields conservatively. A missing field is easier to add later than a bloated schema is to maintain.
- Use interaction records for structured agent-to-agent or agent-to-founder communication that should appear as a dashboard card but does not require a full founder inbox item or approval gate.
- Review records are YAML in this first template set for dashboard parsing. If reviews become narrative-heavy, use a linked Markdown note or revisit Markdown-with-frontmatter.
