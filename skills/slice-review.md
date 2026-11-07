--- {"name": "slice-review", "description": "Review a whole slice against its brief and tests."}
Review the whole slice against the brief below. Change nothing: do not edit files,
commit, push, merge or open a PR. Run the repository's tests and read the whole diff
from the runner's pinned base commit to the assigned branch tip. Check every
requirement, especially the brief's Fixed decisions and Do not sections. Report
failures honestly; a test failure or an unmet requirement needs a fix.

Ignore the brief's instructions about branches, PRs, merging, deployment and
handover. End with kind "waiting" whose body begins with a fenced JSON block
matching schema/review.schema.json:
- pass: verdict "pass", title and body for the PR. Include test commands and results
  in the body.
- fix: verdict "fix", tickets and test_files in the plan's ticket form. Each ticket
  needs exact files, a concrete change and a check command that demonstrates it is
  done. List existing test files to keep pinned; you must not change them. Tickets
  must carry all remaining work with decisions already made. Only one repair round
  is allowed; after repair, review the whole slice again by the same standard.

# Brief

