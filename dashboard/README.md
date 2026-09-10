# Factory Dashboard

Read-only local management dashboard for The Factory's own operating state.

Open [index.html](index.html) in a browser.

## Local Data Loading

The dashboard reads local ops files in the browser. It does not require the Python renderer, a server, or a database.

- Use `Load Project Folder` and choose either a project workspace or its `ops/` folder.
- Use `Refresh` after changing ops files when the browser supports directory handles.
- If the browser does not support directory handles, the dashboard falls back to a folder-file picker.

The dashboard reads JSON, YAML, and Markdown-frontmatter records from `ops/`. It does not write tickets, runs, approvals, or other operational state.

## Scope

- Shows current Factory mission control, role roster, stage board, run ledger, release lane, decision queue, context panel, approvals, and learning records.
- Provides read-only task/ticket drill-down: click a task to see child tickets, or a ticket to see context, runs, reviews, release evidence, files/tests, and next owner/action.
- Renders communication cards from runs, reviews, releases, founder inbox items, approvals, learning records, and optional interaction records.
- Filters tickets by text search, status, owner, risk level, and blocked-only state, with filtered stage board, task explorer, role roster, run ledger, and communication feed.
- Links back to the source Markdown, YAML, and JSON records.
- Avoids server, database, CLI bridge, and write actions in this slice.

## Browser Boundary

Local browser pages cannot silently scan arbitrary folders. The folder picker is the permission boundary that lets the dashboard consume local files directly without a background process.
