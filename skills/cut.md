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

End with a JSON object matching schema/plan.schema.json: tickets with title, files, change and
check, and test_files listing the test files you wrote.

# Task

