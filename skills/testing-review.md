--- {"name": "testing-review", "description": "Prepare a text testing review on Testing events and act on the owner's testing feedback in the chat."}
On a `testing` event, use workshop `feature` and `slices`. Check every linked
slice's installation status and read its handovers against the agreed feature.
`finished` confirms a recorded good install; `not-required` means no install was
recorded as required. Pending, required, failed or unconfirmed installs block a
claim that the feature is ready to test. Request an install only with
`install_slice` for an installable open node step. Each node step allows one chat
request. Never retry an install failure; it belongs to the owner. For other node
steps, use `raise_decision` for the required owner work. Do not use the shell to bypass a tool
refusal or approve a stop-before-merge slice.

Run the quick checks your available tools permit. State exactly what you checked
and what you could not check. Save `Testing review <n>` with `save_section`, using
the next number from 1. Never overwrite an earlier review. Include:
- What changed, compared with the last review (first review: the whole feature).
- Where to look, with Workshop addresses: `/pipeline/<feature ID>`,
  `/factory/slices/<slice ID>` and relevant Library addresses.
- Install evidence, handovers and quick check results.
- What the owner should try and the expected results.

Ask the owner in this chat to test and reply in open text. No form or review table.
If installation is incomplete, explain the blocker and raise the needed owner
work with `raise_decision`; do not describe uninstalled changes as checked on the node.

Act on the owner's reply immediately. First reply with your sort, one line per
point: `defect`, `change`, `idea` or `question`, and a brief description. The owner
can correct the sort in this chat. Track open points in the chat and append their
outcomes to the current review without replacing its original text.
- Defect: read the brief skill, add a bounded correction with `add_slice`, then
  `move_feature` back to Building. Respect dependencies and merge approval rules.
- Change: run a short grill here, one question at a time; once agreed, read the
  brief skill, add the new slices, and return to Building.
- Idea: append it under `Ideas from testing` in the current review section. There
  is no Ideas page. An idea does not imply approval to implement it.
- Question: answer in this chat, or ask for the missing information.

Architecture, scope, contract, security, persistence and topology decisions go to
the owner with a recommendation through `raise_decision`; do not cut speculative
work. A later Testing event gets the next numbered review covering only changes
since the previous review. When the owner says the feature passes and no point is
open, `set_mark` review and `move_feature` to Done. Silence or reading the chat is
not a pass.

Raise decisions with `raise_decision` and a recommendation. When you receive a
decision, use `answer_decision(decision, text)` only when the brief or recorded
decisions settle it. Otherwise pass it on with `raise_decision`, supplying its
`decision` id, text and recommendation. Owner-only items are always passed on,
never answered by a chat: a guard file, a secret’s value, deleting irreplaceable
data, a money limit, a new public endpoint or a repository made public. When the
owner answers in the orchestrator chat, close that decision with `answer_decision`.
