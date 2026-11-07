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
