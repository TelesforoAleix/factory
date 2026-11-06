# Source Comparison Plan

## Purpose

The Factory should merge the best patterns from source repositories instead of copying one system blindly.

This plan defines how to compare overlapping patterns from ECC, gstack, Paperclip, SkillOpt, Claude Playbook, and related sources.

## Comparison Method

For each implementation area:

1. Identify relevant source patterns.
2. Read the specific source sections or files, not only prior summaries.
3. Compare overlap and contradictions.
4. Present 2-4 options to the owner.
5. Recommend one hybrid and explain why.
6. Capture the owner's choice as a Factory design decision.
7. Convert the decision into docs/templates only after agreement.

## Initial Comparison Areas

### 1. Control Plane And Ticketing

Sources:

- Paperclip
- ECC
- gstack

Questions:

- What objects do we need: project, goal, feature, task, ticket, run, inbox, approval?
- Which state belongs in files versus future database?
- How should agents create and claim tickets?

### 2. Workflow Loop

Sources:

- gstack
- ECC
- Claude Playbook

Questions:

- How much of Think -> Plan -> Build -> Review -> Test -> Release -> Reflect is mandatory?
- Which stages can be skipped for tiny tasks?
- Which artifacts does each stage produce?

### 3. Agent And Skill Structure

Sources:

- ECC
- Claude Playbook
- Matt Pocock Skills
- Prompt Master

Questions:

- What belongs in rules, skills, agents, prompts, commands, hooks, or scripts?
- How many agents exist in v0?
- Which agents are always available versus project-selected?

### 4. Review And Release Gates

Sources:

- gstack
- Claude Playbook
- Paperclip
- Cybersecurity Skills

Questions:

- What checks happen before release agent commits?
- When are specialist reviewers required?
- What requires founder approval?

### 5. Self-Improvement

Sources:

- SkillOpt
- Hermes Agent
- existing knowledge-base validation work
- ECC continuous learning patterns

Questions:

- What evidence triggers an improvement proposal?
- What belongs in memory, session search, candidate lessons, or canonical skills?
- Should improvement notes live per department, centrally, or both?
- How are agent/skill updates validated and promoted?
- Does v0 need a curator, or is a session-note learning inbox enough?
- What can be auto-captured, and what always needs the owner approval?

### 6. Dashboard And Bridge

Sources:

- Paperclip
- Odysseus
- gstack browser/QA patterns

Questions:

- Is v0 read-only, write-capable, or CLI-assisted?
- How does dashboard state route to VS Code/Copilot?
- What is the minimum useful control plane?

## Output Format For Each Comparison

Use this conversational comparison shape:

| Option | Source Inspiration | Strength | Weakness | Fit For the owner |
|---|---|---|---|---|

Then conclude with:

- Recommended hybrid
- Decision needed from the owner
- Implementation consequence

## Next Comparison Pass

Start with control plane and ticketing, because it affects every later layer.
