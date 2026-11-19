# Documentation claims check

`cplane docs-verify` checks `docs/claims.json`: the machine-readable list of every
claim a repository's core documents make, with the lines that prove each one. It
reads the repository with git at one revision and never writes to it. Nothing
runs it automatically yet.

```sh
cplane docs-verify REPO [--rev REV] [--with PATH ...] [--graph-only] --out RECORD.json
```

`--rev` defaults to `HEAD`. Each `--with PATH` names another checked-out repository
(read at its `HEAD`) for the cross-repository graph rules. `--graph-only` makes no
API call: it checks the schema, citations and graph only.

## Input

The format is [`schema/claims.schema.json`](../schema/claims.schema.json), version 1:
`parts`, `claims`, `relations` and `contracts`. Line ranges are 1-based and
inclusive. Before any call the command fails (exit 1, record with `errors`) when:

- the file is missing, is not JSON, or does not match the schema;
- an id (part or contract `name`, claim or relation `id`) repeats within its kind;
- a cited file does not exist at the revision, or a range is reversed or runs past
  the file's end;
- a relation cites no lines at all, or names a contract not in `contracts`;
- a `--with` repository's claims file is invalid, or repeats a repository.

Error messages give locations and validator names, never file content.

## Checking

Each claim and relation is one `POST /v1/decisions` request on the platform run
URL and key (`CPLANE_EVAL_TASK_URL`, `CPLANE_EVAL_TASK_KEY_FILE`), with one
question, `support`, and three repeats. Code assembles the `text` from cited
lines, each prefixed `path:line: `:

- a claim: `claim`, `document`, and `source_1`, `source_2`, … in citation order;
- a relation: `relation` (from, to, how, contract and text, one per line),
  `provider`, `user`, and `contract` (the contract's lines in
  `docs/contracts.md`) when one is named.

| Verdict | When |
| --- | --- |
| `pass` | all three answers are `supported` and the confidence is at least 0.9 |
| `flagged` | anything else; every answer is kept |
| `too_large` | the text is over 80,000 characters (no call), or the API returned 413; narrow the citations |
| `error` | a 502 twice (one retry), a 422, another HTTP failure, or an invalid response |
| `not_checked` | the run stopped first |

A 429 or 503, a 401 or 403, a transport failure, or missing platform settings
stops the run (exit 2). The record is still written with the stop reason, and
the remaining items are `not_checked`.

## Graph rules

Code only, no API:

- `relation_parts`: a relation's `from`, and a local `to`, name parts;
- `part_connected`: every part is `standalone` or has a passing relation from or
  to it (with `--graph-only`, any relation counts);
- `relation_contract`: a relation's contract exists;
- `contract_parties`: every contract has a provider and at least one user;
- `contract_version`: a contract name listed by two checked repositories has the
  same version in both;
- `remote_part`: an `owner/name:part` target exists in that repository's parts.
  Targets in repositories not given with `--with` are recorded as unchecked
  (`passed: null`) and do not fail the run.

## Record and exit code

The record holds the repository, revision, the claims file's SHA-256, start and
end times, the model reported (a list if several), summed usage, input `errors`,
the stop reason, per item its id, kind, verdict, choice, confidence and the three
raw answers, the graph checks, and a summary of counts. It holds no source text.
Stdout shows the counts per verdict and the ids that did not pass.

Exit 0 when everything passes; 1 when anything is flagged, too large, in error,
fails a graph rule, or the input is invalid; 2 when the run stopped.

After each merge the runner runs this check in `--graph-only` mode on the merged commit
(read through the GitHub API, with no checkout) when the commit has `docs/claims.json`;
a failure raises a `docs-graph` attention item. See docs/runner.md.
