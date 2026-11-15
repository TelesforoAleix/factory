"""One-request UNIX socket client for the node's privileged launcher."""

import argparse
import array
import json
import logging
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import uuid

from .fence import WORK_ROOT

RUN_ROOT = Path("/srv/factory/runs")
LIMIT = 64 * 1024
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class LauncherError(OSError):
    pass


def folder_id(path, role):
    root, depth = (WORK_ROOT, 2) if role == "work" else (RUN_ROOT, 3)
    path = Path(path)
    if ".." in path.parts or not path.is_absolute():
        raise LauncherError("invalid_folder")
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        raise LauncherError("invalid_folder") from None
    if not 1 <= len(parts) <= depth:
        raise LauncherError("invalid_folder")
    return "/".join(parts)


def request(payload, descriptors=()):
    data = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
    if len(data) > LIMIT:
        raise LauncherError("request_too_large")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(
                os.environ.get("CPLANE_LAUNCHER_SOCKET", "/run/homelab-launcher.sock")
            )
            if descriptors:
                sent = client.sendmsg(
                    [data],
                    [
                        (
                            socket.SOL_SOCKET,
                            socket.SCM_RIGHTS,
                            array.array("i", descriptors),
                        )
                    ],
                )
                if sent < len(data):
                    client.sendall(data[sent:])
            else:
                client.sendall(data)
            with client.makefile("rb") as stream:
                line = stream.readline(LIMIT + 1)
            if len(line) > LIMIT or not line.endswith(b"\n"):
                raise LauncherError("invalid_response")
            reply = json.loads(line)
    except (OSError, ValueError) as error:
        if isinstance(error, LauncherError):
            raise
        raise LauncherError("unavailable") from None
    if not isinstance(reply, dict) or type(reply.get("ok")) is not bool:
        raise LauncherError("invalid_response")
    if not reply["ok"]:
        reason = reply.get("error")
        raise LauncherError(reason if isinstance(reason, str) else "invalid_response")
    return reply


def usage():
    """Read sealed usage telemetry and always release the single-use run."""
    run_id = "usage-read-" + uuid.uuid4().hex
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            reply = request(
                dict(op="run", profile="usage", run_id=run_id),
                (stdout.fileno(), stderr.fileno()),
            )
            if type(reply.get("exit_code")) is not int or reply["exit_code"] != 0:
                return None
            stdout.seek(0)
            limits = json.loads(stdout.read(LIMIT + 1))
            return limits if isinstance(limits, dict) else None
    except (OSError, ValueError):
        return None
    finally:
        try:
            request(dict(op="stop", run_id=run_id))
        except LauncherError as error:
            if str(error) != "unknown_run":
                logging.getLogger(__name__).warning(
                    "Usage run cleanup failed: %s", error
                )


def manage(op, role, path):
    return request(dict(op=op, role=role, folder_id=folder_id(path, role)))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise LauncherError("invalid_arguments")


def translate(argv):
    parser = Parser()
    sub = parser.add_subparsers(dest="op", required=True)
    for op in ("run", "bundle"):
        command = sub.add_parser(op)
        command.add_argument("--repo", required=True)
        command.add_argument("--run", required=True)
        if op == "bundle":
            command.add_argument("--branch", required=True)
        else:
            command.add_argument("--tool", choices=("codex", "claude"), required=True)
            ids = command.add_mutually_exclusive_group()
            ids.add_argument("--session-turn", type=int)
            ids.add_argument("--run-id")
            command.add_argument("--read-only-path", action="append", default=[])
            command.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("session-cleanup").add_argument("turn", type=int)
    sub.add_parser("stop").add_argument("run_id")
    args = parser.parse_args(argv)
    if args.op in ("session-cleanup", "stop"):
        if args.op == "session-cleanup" and not 1 <= args.turn <= (1 << 63) - 1:
            raise LauncherError("invalid_turn")
        run_id = f"turn-{args.turn}" if args.op == "session-cleanup" else args.run_id
        if not RUN_ID.fullmatch(run_id):
            raise LauncherError("invalid_run_id")
        return dict(op="stop", run_id=run_id)
    payload = dict(
        op="run",
        profile="bundle" if args.op == "bundle" else "cli-run",
        run_id=uuid.uuid4().hex,
        folders=dict(work=folder_id(args.repo, "work"), run=folder_id(args.run, "run")),
    )
    if args.op == "bundle":
        payload["branch"] = args.branch
        return payload
    if args.session_turn is not None:
        if not 1 <= args.session_turn <= (1 << 63) - 1:
            raise LauncherError("invalid_turn")
        payload.update(
            profile="chat", turn=args.session_turn, run_id=f"turn-{args.session_turn}"
        )
    elif args.run_id is not None:
        if not RUN_ID.fullmatch(args.run_id):
            raise LauncherError("invalid_run_id")
        payload["run_id"] = args.run_id
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise LauncherError("invalid_command")
    exports = []
    for path in args.read_only_path:
        try:
            parts = Path(path).relative_to(Path(args.repo) / "repos").parts
        except ValueError:
            raise LauncherError("invalid_folder") from None
        if len(parts) != 1 or parts[0] in (".", ".."):
            raise LauncherError("invalid_folder")
        exports.append(parts[0])
    payload.update(tool=args.tool, command=command, exports=exports)
    return payload


def main(argv=None):
    try:
        payload = translate(sys.argv[1:] if argv is None else argv)
        try:
            reply = request(
                payload,
                (sys.stdout.fileno(), sys.stderr.fileno())
                if payload["op"] == "run"
                else (),
            )
        except LauncherError as error:
            if payload["op"] == "stop" and str(error) == "unknown_run":
                logging.basicConfig(level=logging.INFO)
                logging.getLogger(__name__).info(
                    "Launcher run %s already stopped", payload["run_id"]
                )
                return 0
            raise
        if payload["op"] == "run":
            code = reply.get("exit_code")
            if type(code) is not int or not 0 <= code <= 255:
                raise LauncherError("invalid_response")
            return code
        return 0
    except LauncherError as error:
        print(f"launcher: {error}", file=sys.stderr)
        return 125


if __name__ == "__main__":
    sys.exit(main())
