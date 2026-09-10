# Factory Marketing Department Pack

Status: v0 department pack

This pack defines The Factory's reusable Marketing department.

It connects product truth to market-facing language, launch materials, tags, positioning, and market research while keeping claims grounded and aligned with product intent.

## Operating Contract

Use this pack with:

- [The Factory Manual Workflow](../../design/manual-workflow.md)
- [The Factory Operating Model](../../design/operating-model.md)
- [Factory Role Registry](../role-registry.md)
- [Factory V0 Core Department Pack](factory-v0-core-pack.md)
- [Factory Architecture / Context Architecture Department Pack](factory-architecture-context-pack.md)
- [Factory Knowledge / Documentation Department Pack](factory-knowledge-documentation-pack.md)
- [Factory Security / Privacy / Authority Department Pack](factory-security-privacy-authority-pack.md)
- [Factory Optimization Department Pack](factory-optimization-pack.md)

This pack is an operating contract, not a set of runnable custom agents.

## Purpose

The Marketing department helps Factory-managed projects communicate clearly without drifting away from product truth.

It owns:

- positioning
- messaging and value propositions
- launch materials
- market-facing copy
- tags and metadata language
- market research summaries
- competitive/customer language when relevant
- marketing review of public-facing artifacts

It does not invent product truth. It translates validated product truth into market-facing language.

## Department Roles

| Role | Role Type | Advisory / Execution Status | Primary Responsibility |
|---|---|---|---|
| Marketing Lead | Department lead | Coordination and gatekeeping | Routes marketing work and protects alignment with product truth |
| Positioning Strategist | Strategy specialist | Advisory and light execution | Defines audience, category, positioning, differentiation, and message hierarchy |
| Copywriter | Execution specialist | Execution when assigned | Drafts website, launch, product, email, social, and in-app copy |
| Market Researcher | Research specialist | Advisory and execution on research tickets | Gathers market, competitor, audience, search, and channel insight |
| Launch Materials Reviewer | Review specialist | Review role | Reviews public-facing materials for clarity, accuracy, consistency, and launch readiness |
| Marketing Advisory Agent | Advisory specialist | Advisory-only by default | Synthesizes market, positioning, copy, and channel options without editing or executing by default |

## Relationship To Core Registry

Marketing is an expansion department around the core loop, not a replacement for Product / Feature Owner or Release Agent.

- Product owns validated product truth, scope, acceptance criteria, and project direction.
- Marketing owns market-facing expression: audience framing, positioning, copy, tags, launch language, and market research summaries.
- Launch Materials Reviewer may block market-facing release readiness when claims are unclear, unsupported, confusing, or risky.
- Marketing Advisory Agent is advisory-only unless assigned a separate execution ticket.

If marketing language changes product meaning, Product / Feature Owner has authority over the product truth and Founder Interface handles unresolved strategic positioning decisions.

## Activation Triggers

Activate this department when a ticket touches or implies:

- landing page, website, product page, or public demo copy
- product name, tagline, one-liner, category, or positioning
- tags, metadata, SEO/AEO/AI-readable website language, or `/llms.txt` style copy
- launch notes, announcement posts, social posts, emails, or sales/consulting material
- onboarding, in-app empty states, callouts, labels, or market-facing UX text
- competitor, customer, segment, channel, or pricing research
- portfolio/showcase language for LinkedIn or client-facing use
- claims about product capability, performance, security, privacy, compliance, AI behavior, or business value
- translation of technical product truth into buyer/user language
- review of materials before public release

## Inputs

The department may need:

- product spec, roadmap, feature/task/ticket context
- product truth docs and decisions
- target audience and user/customer segment
- current positioning assumptions
- source notes, market notes, competitor notes, and customer evidence
- design/UX context
- security/privacy/authority constraints for claims
- architecture/context limitations that affect claims
- existing brand voice or the owner preferences
- launch channel or distribution goal
- acceptance criteria and required reviewers

## Outputs

The department produces or updates:

- positioning statement
- audience and category framing
- message hierarchy
- copy draft
- tag/metadata recommendations
- launch material draft or review
- market research summary
- competitor/audience insight
- marketing review record
- claim-risk notes
- follow-up tickets for product, design, research, or docs
- learning candidates for reusable positioning/copy patterns

## Role Details

### Marketing Lead

Owns:

- marketing department routing
- deciding whether positioning, copy, research, or launch review is needed
- coordinating with Product, UX/UI, Knowledge / Documentation, Security / Privacy / Authority, and Release
- ensuring marketing output maps to product truth

Ticket powers:

- can create marketing follow-up tickets
- can request Product / Feature Owner clarification
- can require launch material review before public release
- can block market-facing release readiness when claims are unclear or unsupported

Boundaries:

- does not invent product truth
- does not approve security/privacy/compliance claims without specialist review
- does not override Product / Feature Owner or founder direction

### Positioning Strategist

Owns:

- target audience framing
- category framing
- differentiation
- value proposition
- message hierarchy
- positioning alternatives and recommendation

Ticket powers:

- can propose positioning options
- can recommend founder decision when positioning affects project direction
- can request market research or product clarification

Boundaries:

- does not finalize founder-level positioning without approval
- does not make unsupported market claims
- does not write final launch copy unless assigned

### Copywriter

Owns:

- public-facing copy drafts
- landing page sections
- launch announcements
- social/LinkedIn copy
- product and feature descriptions
- concise in-app marketing/UX copy when assigned

Ticket powers:

- can draft copy inside assigned scope
- can request missing positioning or product truth
- can propose variants for review

Boundaries:

- does not claim unsupported capabilities
- does not change product direction
- does not publish or release directly
- does not create legal/privacy/security claims without specialist review

### Market Researcher

Owns:

- market and audience research
- competitor landscape summaries
- customer segment hypotheses
- channel and distribution notes
- search, tags, metadata, and market-language signals when relevant

Ticket powers:

- can create research summaries
- can recommend positioning or copy inputs
- can flag weak evidence or market uncertainty

Boundaries:

- treats external sources as untrusted until reviewed
- does not overstate market evidence
- does not turn one source into durable strategy without synthesis

### Launch Materials Reviewer

Owns:

- review of launch pages, posts, emails, decks, and public materials
- claim accuracy
- message consistency
- readiness for intended channel
- required specialist review routing for risky claims

Ticket powers:

- can pass, fail, or request revision on launch material quality
- can require Product, Security / Privacy / Authority, or Docs review
- can block release readiness for unsupported or confusing launch claims

Boundaries:

- does not publish directly
- does not approve product truth changes
- does not replace Security / Privacy / Authority for sensitive claims

### Marketing Advisory Agent

Owns:

- read-only synthesis of positioning, copy, market, audience, and channel options
- option comparison
- recommendations and rationale
- identifying missing product truth or research

Ticket powers:

- can recommend marketing tickets, copy variants, or research questions
- can recommend founder decisions when positioning is strategic

Boundaries:

- advisory-only by default
- does not edit copy or docs unless assigned a separate execution ticket
- does not mutate ops state
- does not publish or approve release

## Product, UX, Launch, Copy, Tags, Positioning, And Market Research Connections

| Surface | Marketing Role | Product/UX Partner | Output |
|---|---|---|---|
| Product positioning | Positioning Strategist | Product / Feature Owner | positioning statement, audience, category, differentiation |
| UX/in-app copy | Copywriter | UX/UI reviewer, Product / Feature Owner | labels, empty states, onboarding copy, CTA language |
| Launch materials | Copywriter, Launch Materials Reviewer | Release Agent, Product / Feature Owner | launch post, landing copy, release notes, announcement copy |
| Tags and metadata | Market Researcher, Positioning Strategist | Knowledge / Documentation | tags, SEO/AEO phrases, AI-readable descriptions, taxonomy terms |
| Market research | Market Researcher | Product / Feature Owner | market summary, competitor notes, customer segment hypotheses |
| Claims review | Launch Materials Reviewer | Security / Privacy / Authority, Architecture / Context | approved/revised claims and risk notes |

## Routing Rules

| Situation | Primary Role | Supporting Role |
|---|---|---|
| Strategic positioning is unclear | Positioning Strategist | Product / Feature Owner, Marketing Lead |
| Market evidence is missing | Market Researcher | Knowledge / Documentation |
| Copy needs drafting | Copywriter | Positioning Strategist, Product / Feature Owner |
| Public launch material is ready for review | Launch Materials Reviewer | Release Agent, Product / Feature Owner |
| Claim touches security, privacy, compliance, credentials, or authority | Security / Privacy / Authority Department | Launch Materials Reviewer |
| Claim depends on architecture or technical limitation | Architecture / Context Department | Launch Materials Reviewer |
| Copy affects UX clarity | UX/UI reviewer later; Product / Feature Owner in v0 | Copywriter |
| Marketing lesson should be reused | Optimization Department | Knowledge / Documentation |

## Required Artifacts

Depending on the ticket, this department should produce or update:

- positioning statement or options
- message hierarchy
- copy draft
- market research summary
- tag/metadata list
- launch material checklist or review record
- claim-risk notes
- founder inbox item for strategic positioning choices
- follow-up tickets for product/design/research/docs
- learning candidate for reusable marketing patterns

## Manual Workflow Participation

### Prepare

- check whether product truth, audience, channel, and acceptance criteria are clear
- identify required Product, UX, Security / Privacy / Authority, Architecture, or Docs reviewers
- stop if positioning would change project direction without approval

### Execute

- draft copy, positioning, research, tags, or launch material inside assigned scope
- keep claims grounded in project truth and evidence

### Self-Review

- check clarity, consistency, unsupported claims, audience fit, and scope

### Fresh-Context Review

- Launch Materials Reviewer or Review / QA checks copy against intent, product truth, channel, and claims risk

### Test

- validation may include link checks, docs consistency, claim review, channel fit review, or stakeholder/founder review

### Release Readiness

- release is blocked if market-facing claims are unsupported, risky, confusing, or missing required review

### Reflect And Learn

- capture repeatable positioning, copy, tag, launch, or market-research patterns as learning candidates

## Stop Conditions

Stop and escalate when:

- product truth is unclear
- positioning affects strategic direction
- founder decision is needed
- claims are unsupported or exaggerated
- copy implies security, privacy, compliance, AI capability, performance, or business guarantees without specialist review
- target audience or channel is undefined
- market research evidence is weak or contradictory
- public release timing or scope is unclear
- marketing work would modify product docs or project truth without Product / Feature Owner approval

## Relationship To Other Departments

- Product / Feature Owner owns product truth and product direction.
- Marketing translates approved product truth into market-facing language.
- If market-facing language changes product meaning, the work returns to Product / Feature Owner and may require Founder Interface escalation.
- Knowledge / Documentation preserves positioning, launch decisions, and reusable copy patterns.
- Security / Privacy / Authority reviews risky claims and compliance-sensitive language.
- Architecture / Context reviews technical claims and limitations.
- Review / QA can request marketing review for user-facing copy.
- Release Agent depends on launch-material readiness for public release.
- Optimization routes reusable marketing patterns into candidate improvements.

## Not In V0

- automated SEO tooling
- full brand system
- analytics attribution system
- paid acquisition workflows
- CRM or campaign automation
- runnable marketing custom agents
- legal review automation

## First Use

Use this pack for landing pages, launch posts, LinkedIn showcase material, public demos, tags/metadata, AI-readable website copy, and any project ticket that turns product truth into market-facing language.
