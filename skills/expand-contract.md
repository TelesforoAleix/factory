--- {"name": "expand-contract", "description": "Change a contract between repositories without breaking either side, in expand, migrate and contract steps."}
Use this skill when you change a contract: a schema another repository depends on,
such as an API's OpenAPI document. Each contract is generated from code in the
repository that provides it and committed there; each user keeps a pinned copy.
The `factory-contracts` commands below enforce the rules in CI.

## Full compatibility

Every change must work with the previous version in both directions: new senders
with old readers, and old senders with new readers. Within one change:

- Add a field only as optional, with a default.
- Remove only an optional field.
- Never rename a field or change its type in one step; use the three steps below.
- Give every enum an unknown fallback in readers, so a new value does not fail them.

Two additions are compatible because readers tolerate them:

- A new operation. A user treats a 404 from a new endpoint as "not available yet".
- A new enum value in a response. A reader maps an unknown value to its fallback.

`compat` accepts only these two additions and reports them as `tolerated`.

`factory-contracts compat --base git:origin/main:<schema> --revision <schema>`
runs `oasdiff breaking` both ways (base against revision, revision against base)
and fails when either direction reports a breaking change other than those two
additions, naming the direction and each rule id. Fix the change; do not ignore the rule.

## Larger changes: expand, migrate, contract

A rename, a retype, a new required field or a removal of something in use takes
three separate changes, each fully compatible on its own:

1. Expand. Add the new shape beside the old one. Readers accept both; senders
   still send the old one. Count each use of the old shape (a usage counter).
2. Migrate. Move every sender, in every user repository, to the new shape. Each
   user re-pins the provider's schema and its sender checks run against the pin.
3. Contract. Remove the old shape, only when both hold:
   - the old shape's usage counter has been zero for the agreed period, and
   - no work created before the expand change is still open (queued runs, saved
     job bodies, open slices or PRs that may still send the old shape).

Never merge two of these steps into one change.

## Readers and senders

- Readers are tolerant: accept unknown fields and record them (log or count them)
  instead of failing, so a provider can expand first.
- Senders are strict: send only fields the pinned schema defines, with their
  defined types. `factory-contracts sender --pin <dir> --method <M> --path <p>
  --body <file>` refuses any other field, following `$ref`s, and checks types; in
  tests, call `contracts.sender.check(pin_dir, method, path, body)`.

## The files

- The provider commits its schema in canonical JSON (`factory-contracts canonical`).
  `factory-contracts generated --command "<generator>" --file <schema>` fails when
  the committed file differs from what the code generates; regenerate and commit.
- A user's pin is a folder with `schema.json` and `pin.json` (`contract`,
  `provider`, `commit`, `sha256`), written by `factory-contracts pin write` and
  checked by `factory-contracts pin verify <dir>`. Never edit a pin by hand; write
  it again from the provider's commit.
- There are no version numbers in a pin: compatibility is checked, not declared.

`factory-contracts practices` lists each check with this skill.
