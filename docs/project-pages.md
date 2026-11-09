# Project pages

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
back together. Reactivation keeps the existing chat. Migration 018 adds the
fields and audit payload, and rejects project key updates at the database level.
It does not create chats for existing projects.

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
Building and Testing features with running slices, the Next queue, stage counts
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

## Performance and validation

The profile identified repeated JSON schema validation of persisted slice history
as the dominant work: 111.86 ms in Home and 111.42 ms in feature detail under
cProfile on the synthetic fixture. Owner page projections now read persisted
write-validated documents under the same store lock, following the existing card
projection pattern. Scheduler loads, save/import validation, atomic mutation paths
and the version 1 state contract remain unchanged. Feature detail also resolves
attention ownership in bulk. A regression test compares the projected responses
with the validated-load responses and verifies invalid writes still fail.

Measured in this executor over HTTP on **127.0.0.1**, using disposable Postgres
17.7, 24 synthetic features, 41 slices with history, seven requests per endpoint:

| Endpoint | Base median / max (ms) | Changed median / max (ms) |
| --- | ---: | ---: |
| `/api/home` | 56.06 / 58.25 | 20.70 / 25.36 |
| `/api/pipeline/FAC-F1` | 71.20 / 72.55 | 33.34 / 34.70 |
| `/api/pipeline` | 10.25 / 10.70 | 10.17 / 10.72 |
| `/api/projects/FAC` | — | 21.53 / 22.00 |

Home and feature-detail payload sizes stayed exactly 7,597 and 33,056 bytes.
These container figures do not substitute for the owner-node measurements in the
brief (about 300 and 290 ms before). The required node check remains to run.
No browser was available; phone layout was checked through source, component
tests and the build, without a screenshot or browser layout measurement.

Reproduce with a **disposable Postgres 17 database**, never production state:

```sh
CPLANE_TEST_DATABASE_URL=postgresql://... uv run python tests/measure_pages.py \
  --http --projects --profile /tmp/project-page-profiles
```

For the pinned-base comparison, archive `f3d3be65b0d7d00b2a6d33f94104c023e4a5da94`
outside the checkout, write that SHA into the archive's `REVISION` file, and run
the current benchmark with `--source /path/to/archive --http --profile /tmp/base-profiles`
(omit `--projects` because the base has no project endpoint). The benchmark always
creates and removes its own random schema; profiles and fixtures stay out of git.

Local checks use Python 3.13 and uv, `uv run pytest` against Postgres 17,
`npm test` (including contrast), and `npm run build` in `ui/`. In this container,
npm was run through a temporary npm CLI and Postgres through temporary packaged
binaries; no runtime or lockfile dependency changes were needed. The first full
run exhausted the 512 MB `/tmp` volume; the disposable database was moved to the
larger ignored virtual-environment directory before rerunning.

After the runner has green `test` and `ui` checks and merges the PR, request the
reviewed installation on the owner node:

```sh
sudo factory-cplane --actor owner install factory/PJ1
```

The installer applies migration 018, builds the UI and restarts existing services.
Then measure the real Home, `FAC-F5` detail and project endpoint locally on the
node, confirming all three are below 100 ms; inspect profiles if any miss the
bar. Verify the 390 px header and project edit/add flows there, since this
executor has no browser or access to the owner node.

Final local results: `uv run pytest` with `CPLANE_TEST_DATABASE_URL` pointing to
that disposable Postgres 17 instance: **1,344 passed, 1 skipped** in 149.59 seconds,
including **297 Postgres tests passed**. `npm test`: **56 tests passed** across
13 files; the separate contrast run: **1 passed**. `npm run build` succeeded
(Vite reports the existing large-chunk advisory). `git diff --check` passed.
CI `test` and `ui`, owner-node timing and browser verification remain runner/node
checks; they have not been claimed as completed here.
