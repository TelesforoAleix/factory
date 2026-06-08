# Factory Dashboard

Read-only local management dashboard for The Factory's own operating state.

Open [index.html](index.html) in a browser.

## Local Data Loading

The dashboard reads local ops files in the browser. It does not require the Python renderer, a server, or a database.

- Use `Load Project Folder` and choose either `03-projects/ai-development-team/` or its `ops/` folder.
- Use `Refresh` after changing ops files when the browser supports directory handles.
- If the browser does not support directory handles, the dashboard falls back to a folder-file picker.

The dashboard reads JSON, YAML, and Markdown-frontmatter records from `ops/`. It does not write tickets, runs, approvals, or other operational state.

## Scope

- Shows current Factory mission control, role roster, stage board, run ledger, release lane, decision queue, context panel, approvals, and learning records.
- Links back to the source Markdown, YAML, and JSON records.
- Avoids server, database, CLI bridge, and write actions in this slice.

## Browser Boundary

Local browser pages cannot silently scan arbitrary folders. The folder picker is the permission boundary that lets the dashboard consume local files directly without a background process.
