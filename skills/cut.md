--- {"name": "cut", "description": "Cut a brief into ordered tickets and executable tests."}
You plan work for a much weaker coding model. It sees one ticket at a time and nothing else:
not the task below, not the other tickets. It has about 40 steps, a shell, and no network.

Read this repository, which is at the commit where the task starts, and cut the task into 3 to 10
tickets, in the order they must be done. Then write the tests for every ticket into the repository's
test files. Change test files only: no implementation, not even stubs. The tests fix the names,
signatures and behaviour the code must have. Each ticket has:
- title: a few words.
- files: the source files to read and change, each named exactly.
- change: exactly what to do, with the decisions already made, so the worker has no design choice
  left. Do not paste the finished code unless a line must be exact.
- check: one shell command, run from the repository's root, that runs only this ticket's new tests
  (`uv run --frozen pytest tests/test_x.py -k "name_a or name_b"`, for example). It must fail now and
  pass when the ticket is done, without needing any later ticket.

Every rule in the task's Fixed decisions and Do not sections needs a test where a test can show it.

Ignore the task's instructions about branches, pull requests, merging, CI, deployment, remote
machines and the handover. Spend as little reading as the cut needs.

End your reply with one fenced `json` block containing a JSON object with exactly these fields:
- `tickets`: an array of 1 to 10 objects. Each object has exactly `title`, `files`, `change`,
  and `check`. `title`, `change`, and `check` are nonempty strings; `files` is a nonempty
  array of nonempty repository-relative path strings.
- `test_files`: a nonempty array of nonempty repository-relative path strings naming the test
  files you wrote. Paths must not be absolute, contain `..` components, backslashes, or NULs,
  or be `.`. The same path rules apply to `files`.

# Task

