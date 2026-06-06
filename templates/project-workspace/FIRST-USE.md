# Project Workspace First-Use Checklist

Use this checklist when applying the project workspace template to a real Factory-managed project.

The goal is to start a project cleanly without mixing canonical Factory assets, project-local ops state, and product implementation files.

## 1. Choose The Workspace

- Confirm the project name, project ID, and repository or folder location.
- Confirm whether the project is general Factory work, [project]-specific work, or another project.
- If the project is [project]-specific, follow the [project] branch workflow before editing project truth.
- Check the working tree and protect unrelated untracked files before copying anything.

## 2. Copy The Template

- Copy the full `project-workspace/` folder into the target project location.
- Rename the copied folder to the project workspace name.
- Keep `.github/`, `agents/`, `product/`, and `ops/` unless there is a project-specific reason to defer one.
- Keep README placeholders until the first project-specific content replaces them.

## 3. Set Project Identity

- Add or update the project-local README with project name, purpose, and owner.
- Decide the local project ID used in ops files.
- Note the canonical source for reusable Factory definitions: `04-agents/` and `.github/prompts/factory/` in the brain.
- Decide whether project-local `agents/` should copy definitions, sync selected files, or only link back to the brain for now.

## 4. Run The First Discovery Phase

Use the Product department and [Factory Project Discovery](../../../../04-agents/skills/factory-project-discovery.md) before creating executable work.

- Update `product/DISCOVERY.md` with raw intent, objectives, users/workflows, product shape, constraints, scope, and non-goals.
- Update `product/ROADMAP.md` with the first usable version, later version candidates, parked ideas, and feature ordering.
- Check relevant brain knowledge, source notes, project history, domain notes, and reusable patterns before shaping the first ticket.
- Separate decisions needed now from decisions that can wait.
- Put postponed decisions in the discovery brief or roadmap with a trigger condition for reopening them.
- Create founder inbox items for decisions that block the first execution loop.
- Decide which Factory roles, departments, skills, reviewers, and context packs the first loop needs.

Do not treat a vague future idea as first-version scope just because it was mentioned during discovery.

## 5. Seed The First Ops Objects

Create the smallest useful operating set in `ops/`:

- first goal or feature if the project scope is already clear
- first task
- first ticket
- first context pack
- first run record when work starts

Use [Factory Ops Templates](../ops/README.md) as the source shape.

Do not start execution until the first ticket has:

- current discovery brief and roadmap/version context
- one parent task
- objective
- acceptance criteria
- scope and out-of-scope
- required context pack
- required reviewers
- approval level
- known blockers

## 6. Select Factory Inputs

- Choose the prompt wrappers needed for the first loop: orchestrator, product, execution, review, release, advisory, or founder interface.
- Copy or link only the role specs and department packs the project needs now.
- Preserve the rule that canonical Factory improvements happen in the brain, not silently inside a project copy.
- Record any project-specific override in `agents/` and keep the reason close to the override.

## 7. Validate Before First Commit

Run checks appropriate to the project and the files changed.

Minimum template checks:

- verify the expected folder tree exists
- parse YAML/JSON ops files when they exist
- run Markdown/link checks when docs changed
- check `git status --short --untracked-files=all`
- stage only intended project files

## 8. Record The Handoff

Before ending the setup session:

- update the project README or progress/current-state file
- link the discovery brief and roadmap/version plan
- record the first ticket/run/review/release state when used
- add a session note for the setup
- capture any template friction as a learning candidate

## Stop Conditions

Stop before copying or committing when:

- project identity is unclear
- objectives, first version, or product scope are unclear
- the target branch or repository is unclear
- unrelated dirty or untracked files could be staged accidentally
- [project]-specific truth would be edited on the wrong branch
- canonical Factory definitions would be changed inside a project copy without a promotion path
- the first ticket cannot name its parent task or acceptance criteria
- a decision needed for first execution is hidden inside a postponed-decision list