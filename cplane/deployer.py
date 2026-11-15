"""Detached installer client for the platform deployer; no host privileges."""

import json
import os
import re
import socket
import sys
from pathlib import Path

from .executors import atomic_json


def install(path, application, sha):
    if application != "factory" or not re.fullmatch("[0-9a-f]{40}", sha):
        return {"ok": False, "error": "Install failed: invalid request"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            # Build, migration, switch and health can take a long time. The
            # scheduler never waits for this detached process.
            client.settimeout(None)
            client.connect(path)
            client.sendall(
                (
                    json.dumps(dict(op="install", application=application, sha=sha))
                    + "\n"
                ).encode()
            )
            with client.makefile("rb") as stream:
                line = stream.readline()
            if not line.endswith(b"\n"):
                raise ValueError
            reply = json.loads(line)
            if not isinstance(reply, dict) or type(reply.get("ok")) is not bool:
                raise ValueError
            if reply["ok"]:
                if (
                    reply.get("application") != application
                    or reply.get("commit") != sha
                    or reply.get("result") != "installed"
                ):
                    raise ValueError
                return {"ok": True, "commit": sha}
            reason = reply.get("result")
            if not isinstance(reason, str):
                raise ValueError
            if reason == "waits for the owner":
                text = f"Install waits for the owner: sudo homelab-deployer install {application} {sha}"
            else:
                text = "Install failed: " + reason
            paths = reply.get("paths")
            if paths:
                if not isinstance(paths, list) or not all(
                    isinstance(p, str) for p in paths
                ):
                    raise ValueError
                text += "\n" + "\n".join(paths)
            return {"ok": False, "error": text}
    except (OSError, ValueError):
        return {"ok": False, "error": "Install failed: deployer unavailable"}


def main():
    path, application, sha, result, descriptor = sys.argv[1:]
    # The inherited descriptor holds the .started lock until process exit,
    # including the interval before this module starts executing.
    with os.fdopen(int(descriptor), "rb"):
        atomic_json(Path(result), install(path, application, sha))


if __name__ == "__main__":
    main()
