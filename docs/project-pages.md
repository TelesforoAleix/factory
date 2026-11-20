# Project pages

This document covers project pages, project fields and their usage totals. Read it
before you change a project page, project fields or project commands.

`/projects/<KEY>` shows each real project, including inactive projects linked
from Settings. `NEW` remains the unassigned bucket and has no project page.
Active projects appear in the desktop header as italic links; below 700 px a
native Projects dropdown shares the first header row with Workshop. The menu has
its own horizontally scrolling row, with a gap between it and Workshop.

Owners edit the name (1–60 characters), About (up to 600), public address and
repository link on the project page. Each Save immediately writes one audited
transaction with actor `owner`. Empty URLs clear the link; otherwise URLs require
HTTPS and a host, without embedded credentials. Setting the public address makes
the project published. The repository link is informational and does not change
the existing repository mapping used by executors.

Settings adds a project with a unique, permanent three-capital key and a name.
Creation, its active flag, project chat and audit event commit together or roll
back together. Reactivation keeps the existing chat. The database rejects project
key updates.

Equivalent trusted owner CLI commands:

```sh
cplane project add SYN 'Synthetic project' --actor owner
cplane project set SYN --name 'New name' --about 'A few sentences.' \
  --public-url https://example.test --repository-url https://example.test/repo \
  --actor owner
cplane project set SYN --public-url '' --actor owner
```

`project add` also accepts `--about`, `--public-url` and `--repository-url` and
retains `--repository` for the existing executor mapping. Project field updates
require actor `owner`; no project editing operations were added to chat tools.

The page shares Home's attention projection and action component. It includes
Building, Acceptance and Testing features with running slices, the Next queue, stage counts
linking to the project-filtered Pipeline, the project orchestrator followed by
open feature chats, usage and a project-filtered Library link. Explicit project
context survives opening/closing a Pipeline preview and opening the Library.
Default inactive-project visibility elsewhere stays intact.

Usage uses UTC calendar months and all-time totals. Codex cumulative counters
are differenced per tool/session before filtering by project and month, following
existing run-record accounting, including resets and unknown counters. Claude
counters are already per run. Input, output and cached tokens are distinct sums;
run seconds become hours. Empty periods show zero; entirely unrecorded metrics
show “Not recorded”. Known values in partially recorded periods are summed,
matching the existing feature totals. There are no monetary values; costs wait
for Insights.

Page timings and how to measure them are in [workshop](workshop.md#measuring-pages).
