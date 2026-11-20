"""The `factory-contracts` command. Exit 0 passes, 1 fails a check, 2 is a usage error."""
import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path

from . import compat, pins, sender
from .canonical import ContractError, canonical_file, dumps, load, parse
from .practices import CHECKS

DESCRIPTION = '''Check machine-readable contracts between repositories.
Every file the tool writes or compares uses one canonical JSON form:
json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + newline.
Exit status: 0 passed, 1 a check failed, 2 a usage or input error.
Run `factory-contracts practices` for the skill each check enforces.'''


def parser():
    top = argparse.ArgumentParser(prog='factory-contracts', description=DESCRIPTION,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = top.add_subparsers(dest='name', required=True, metavar='command')

    p = commands.add_parser('canonical', help='print the canonical form of a JSON file')
    p.add_argument('file')
    p.add_argument('--check', action='store_true', help='print nothing; exit 1 unless the file is already canonical')

    p = commands.add_parser('generated', help="check the committed schema equals the provider's generator output")
    p.add_argument('--command', required=True, help='shell command that prints the schema to stdout')
    p.add_argument('--file', required=True, help='the committed schema file')

    p = commands.add_parser('compat', help='fail unless the revision is compatible with the base in both directions')
    p.add_argument('--base', required=True, help='a file, or git:REF:PATH read with git show in the current repository')
    p.add_argument('--revision', required=True, help='the revised schema file')
    p.add_argument('--oasdiff', help=f'oasdiff v{compat.OASDIFF_VERSION} binary (else $OASDIFF, else PATH)')

    pin = commands.add_parser('pin', help="write or verify a user's pinned copy of a contract")
    actions = pin.add_subparsers(dest='action', required=True, metavar='action')
    p = actions.add_parser('write', help='write schema.json and pin.json into a folder')
    p.add_argument('--contract', required=True, help='contract name, for example run-api')
    p.add_argument('--provider', required=True, help='provider repository, owner/name')
    p.add_argument('--commit', required=True, help="provider commit the schema comes from, 40 hex")
    p.add_argument('--schema', required=True, help="the provider's schema file")
    p.add_argument('--out', required=True, help='the pin folder')
    p = actions.add_parser('verify', help='fail unless pin.json is valid and matches schema.json')
    p.add_argument('dir')

    p = commands.add_parser('sender', help='fail when a request body uses a field or type the pin does not define')
    p.add_argument('--pin', required=True, help='the pin folder')
    p.add_argument('--method', required=True, help='HTTP method, for example POST')
    p.add_argument('--path', required=True, help='request path, for example /v1/runs/42/messages')
    p.add_argument('--body', required=True, help='JSON file holding the request body')

    commands.add_parser('practices', help='print each check command with its practice skill')
    return top


def canonical(args):
    text = canonical_file(args.file)
    if args.check:
        if Path(args.file).read_bytes() != text.encode():
            print(f'{args.file} is not in canonical form', file=sys.stderr)
            return 1
        return 0
    sys.stdout.write(text)
    return 0


def generated(args):
    result = subprocess.run(args.command, shell=True, capture_output=True, text=True)
    if result.returncode:
        raise ContractError(f'generator exited {result.returncode}: {result.stderr.strip()[:2000]}')
    fresh = dumps(parse(result.stdout, 'generator output'))
    try:
        committed = Path(args.file).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as error:
        raise ContractError(f'{args.file}: {error}') from None
    if committed == fresh:
        print(f'{args.file} matches the generator')
        return 0
    diff = list(difflib.unified_diff(committed.splitlines(), fresh.splitlines(),
                                     args.file, 'generator output', lineterm='', n=1))
    print(f'{args.file} differs from the generator; commit its canonical output', file=sys.stderr)
    print('\n'.join(diff[:60] + ([f'... {len(diff) - 60} more diff lines'] if len(diff) > 60 else [])),
          file=sys.stderr)
    return 1


def compatibility(args):
    oasdiff = compat.find_oasdiff(args.oasdiff)
    passed, lines = compat.compare(compat.read_base(args.base), load(args.revision), oasdiff)
    print('\n'.join(lines))
    print('compatible in both directions' if passed else 'not fully compatible')
    return 0 if passed else 1


def pin(args):
    if args.action == 'write':
        record = pins.write(args.contract, args.provider, args.commit, args.schema, args.out)
        print(f"pinned {record['contract']} at {record['provider']}@{record['commit']} in {args.out}")
        return 0
    errors = pins.verify(args.dir)
    for error in errors:
        print(f'{args.dir}: {error}', file=sys.stderr)
    if not errors:
        print(f'{args.dir}: pin verified')
    return 1 if errors else 0


def send(args):
    try:
        body = json.loads(Path(args.body).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise ContractError(f'{args.body}: {error}') from None
    errors = sender.check(args.pin, args.method, args.path, body)
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f'{args.method.upper()} {args.path}: body matches the pin')
    return 1 if errors else 0


def practices(args):
    width = max(map(len, CHECKS))
    for check, skill in CHECKS.items():
        print(f'{check.ljust(width)}  {skill} (skills/{skill}.md)')
    return 0


HANDLERS = {'canonical': canonical, 'generated': generated, 'compat': compatibility,
            'pin': pin, 'sender': send, 'practices': practices}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return HANDLERS[args.name](args)
    except ContractError as error:
        print(f'factory-contracts {args.name}: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
