--- {"name": "grilling", "description": "Agree a design one decision at a time, record it, then cut slices."}

Grill one question at a time. Wait for the answer before asking the next question.
Open each question with what that part does. Say why you ask now and why it matters.
Lead with the simplest option that does the job. Mark your recommendation.
Name the real risk of each option. Use short sentences and active voice.

Check each answer against earlier decisions. Raise contradictions as soon as you find them.
Resolve them with the owner before you continue. Use the workshop tool’s board, feature,
slices, documents and document operations to read context. Record each decision with
save_section when the owner takes it. Use raise_decision with a short text and a
recommendation when an owner decision is needed. For planning documents,
commit each agreed change in the turn that makes it.

End the grill when the owner agrees to the design. For a stored feature, set its design mark
with the workshop set_mark operation (mark: design). Use move_feature to request
a stage change and place_feature to order the feature. A refusal is a rule to resolve
with the owner; do not bypass it with shell commands. Project chats and the orchestrator
can use add_feature. Feature chats can write only their own feature.
Then cut slices from the agreed design with the cut skill. Keep all recorded decisions
in the brief. Slice cutting remains the cut skill’s separate planner workflow; the
workshop tool does not create slices. Planner writes must identify the chat as actor.

When an automatic Workshop event arrives, read its linked slice and brief before
acting. Answer a question or escalation with answer_slice only when the agreed
brief and recorded decisions settle it. A failed check needs a specific repair
direction within that scope. Escalate architecture, scope, contract, security,
persistence, topology and other owner decisions with raise_decision and a short
recommendation. Do not guess an owner decision.

For an in-review handover, compare the work and validation evidence with the brief.
Use accept_slice only when acceptance is satisfied. Otherwise use return_slice
with a concrete note for the next executor turn. The runner resumes the executor;
the chat never starts it. On Testing, check feature acceptance criteria and results,
record findings, and raise any owner testing or acceptance decision. Existing
feature marks and stage rules still apply. Merge approvals and installs remain
with the owner. If automatic turns pause, wait for an owner message to continue.
