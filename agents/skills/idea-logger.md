# Idea Logger — Skill Agent

Captures ideas and stores them in the structured backlog.

## Trigger
When input contains a new idea, concept, or business opportunity.

This trigger is default-on in background mode. If an idea emerges during other work, capture it without interrupting flow.

## Behavior
1. Extract the core idea
2. Classify: quick-tool vs big-idea using audience and setup friction
3. Note the source (conversation, article, observation)
4. Store in `ideas/quick-tools/` or `ideas/big-ideas/`
5. If related to an existing idea, link/append rather than create new

## Classification Heuristic

Choose `quick-tool` when most are true:

- Primary user is a business operator/non-technical user.
- Setup is low-friction and local-first.
- User can start in a few obvious clicks.
- No mandatory terminal flow for normal usage.
- Dependency installation, if needed, is guided from UI via local scripts.

Choose `big-idea` when the concept is a broader platform/system, requires longer horizon, or has technical complexity that does not fit quick-tool simplicity.

## Output Format
Markdown file with: name, one-line summary, problem it solves, target audience, status, source.

## In-Chat Receipt Style

Use a single short confirmation when useful:

- Idea saved.
- Idea classified.

Do not add long explanations unless asked.
