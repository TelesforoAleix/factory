# Keeping the documents current

This document covers how to update the documents and `docs/claims.json` when a
change alters a fact. Read it before you finish any PR that changes behaviour,
a command, a setting, a contract or a document.

## Rules

- One fact in one place. The [AGENTS.md](../AGENTS.md) document map names the
  document that owns each subject; update that one and link to it from elsewhere.
- Do not restate what code, config or `--help` already shows. Record the why, the
  connections, the traps and the order of steps.
- State the current design only. History belongs to git and
  [DECISIONS.md](../DECISIONS.md), which is append-only: add a dated entry, never
  edit an old one.
- Every document opens with what it covers and when to read it. Every link says
  when to follow it.
- When you move text, the fact must reappear in its owning document, unless it is
  history or no longer true.
- No private content: no host addresses, tailnet names, private paths, account
  names other than `TelesforoAleix`, secret values or private repository links.

## Claims

`docs/claims.json` follows [`schema/claims.schema.json`](../schema/claims.schema.json).
It lists every factual claim in the core documents (AGENTS.md, ARCHITECTURE.md,
docs/contracts.md, docs/operations.md, docs/migrations.md and this file), every
part named in ARCHITECTURE.md, every relation between parts and to other
repositories, and every contract in docs/contracts.md.

- Cite the narrowest code or config lines that prove the claim, and every line it
  needs. A claim the lines support only in part fails; split a claim that joins
  facts from distant places.
- Cite another document only for a fact this repository's code cannot show, such
  as platform behaviour.
- Line numbers move. After editing a cited file, check every range that cites it.
- Keep ids short and stable; never reuse one for a different claim.

## Before you finish

```sh
uv run pytest tests/test_docs_links.py
uv run cplane docs-verify . --graph-only --out /tmp/claims-record.json
```

The link test checks that every file in the document map exists, that relative
links and anchors in the documents resolve, and that every path cited in
`docs/claims.json` exists. `--graph-only` checks the schema, citation ranges and
part graph without calling the decisions API. After each merge the runner runs
the same graph check and raises `docs-graph` attention when it fails.
