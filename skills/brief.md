--- {"name": "brief", "description": "Write a self-contained executor brief before adding a feature slice through workshop."}

For every feature or slice you create or propose, use a title of about 60 characters
at most. Name what it does for the owner, without a project prefix (the project
shows beside it) or file references. Put Summary first: 2–3 sentences saying what
the owner can do when it is done and what it leaves out. Keep one concern per
feature: two outcomes joined by "and" are two features. Slices follow the same
title rule and have a one-sentence goal.

Use this skill before workshop `add_slice`. Raise architecture, scope, contract,
security, persistence and topology decisions with `raise_decision` before cutting work.
Only add work within the feature's agreed scope.

Write a self-contained Markdown brief: the executor has only its target repository
and this text. Name only files inside that repository, using repository-relative
paths. Include no secrets, private state, private content or credentials. Do not
rely on chat history, other repositories or a later feature export being available.

Include these sections:
- Facts: the relevant existing behavior and files to read.
- Fixed decisions: settled behavior and contracts. Use a `## Fixed decisions` heading.
- Steps: concrete implementation steps in order.
- Allowed changes: the repository paths within scope.
- Do not: boundaries and invariants, under `## Do not`.
- Validation: split commands and expected evidence into before merge and after
  merge. Put required post-merge node work in `node_steps` in the waiting reply.
- Git: a PR, the required green checks and who approves the merge.
- Escalation: decisions that must return through `raise_decision`.
- Handover: changed files, behavior, local choices, validation results,
  compatibility/security notes, unresolved issues and repository state.

Call `add_slice` with feature, title, brief, model and effort. It uses Codex,
flow `cli` and the feature's project repository. Dependencies may name only slices
of that feature. Set `stop_before_merge` on for a security boundary or a step on
the node that cannot be undone; otherwise it defaults off. The UTF-8 brief must
fit in 64 KiB. Read the result and dependencies before adding subsequent work.
A stored brief is immutable. Correct it by adding a new slice, never by rewriting
an issued brief. This operation does not approve merges, run installs or give the
executor workshop access.

Raise decisions with `raise_decision` and a recommendation. When you receive a
decision, use `answer_decision(decision, text)` only when the brief or recorded
decisions settle it. Otherwise pass it on with `raise_decision`, supplying its
`decision` id, text and recommendation. Owner-only items are always passed on,
never answered by a chat: a guard file, a secret’s value, deleting irreplaceable
data, a money limit, a new public endpoint or a repository made public. When the
owner answers in the orchestrator chat, close that decision with `answer_decision`.

When a slice changes a contract listed in `docs/contracts.md`, state `contract_changes` (each contract, its new version and its user repositories) in its brief.
