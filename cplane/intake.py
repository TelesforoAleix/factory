"""Local, group-restricted, one-arrival JSON protocol. No network listener."""

import base64
import binascii
import grp
import json
import os
from pathlib import Path
import socketserver
from .inbox import TOTAL_LIMIT
from .state import StateError, database_url
from .stores import PostgresStore

MAX_REQUEST = 23 * 1024 * 1024
SOCKET = "/run/factory-intake/intake.sock"
_GID_SETTING = os.environ.get("CPLANE_INTAKE_GID")
if _GID_SETTING is not None:
    if not _GID_SETTING.isascii() or not _GID_SETTING.isdecimal() or int(_GID_SETTING) <= 0:
        raise ValueError("CPLANE_INTAKE_GID must be a positive integer")
    GID = int(_GID_SETTING)
else:
    GID = None


def decode_arrival(value):
    if (
        not isinstance(value, dict)
        or set(value) - {"text", "fields", "files"}
        or "text" not in value
    ):
        raise StateError("Invalid arrival")
    files = value.get("files", [])
    if not isinstance(files, list) or len(files) > 10:
        raise StateError("Invalid files")
    decoded = []
    total = 0
    for f in files:
        if (
            not isinstance(f, dict)
            or set(f) != {"name", "media_type", "base64"}
            or not isinstance(f["base64"], str)
        ):
            raise StateError("Invalid file")
        try:
            content = base64.b64decode(f["base64"], validate=True)
        except (ValueError, binascii.Error):
            raise StateError("Invalid base64 file") from None
        total += len(content)
        if total > TOTAL_LIMIT:
            raise StateError("Files exceed size limit")
        decoded.append(
            dict(name=f["name"], media_type=f["media_type"], content=content)
        )
    return dict(
        text=value["text"],
        fields=value.get("fields", {}),
        files=decoded,
        source="phone",
    )


class IntakeServer(socketserver.UnixStreamServer):
    def __init__(self, path, store_factory, gid):
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(10)
                try:
                    line = self.rfile.readline(MAX_REQUEST + 1)
                    if len(line) > MAX_REQUEST or not line.endswith(b"\n"):
                        raise StateError("Arrival exceeds size limit")
                    fields = decode_arrival(json.loads(line))
                    result = dict(id=store_factory().inbox_add(**fields)["id"])
                except (StateError, ValueError, TypeError, UnicodeError):
                    result = dict(error="Invalid arrival or size limit exceeded")
                except Exception:
                    result = dict(error="Intake unavailable")
                try:
                    self.wfile.write(json.dumps(result).encode() + b"\n")
                except OSError:
                    pass

        super().__init__(str(path), Handler)
        os.chown(path, os.geteuid(), gid)
        Path(path).chmod(0o660)


def main():
    gid = GID if GID is not None else grp.getgrnam("factory-intake").gr_gid
    path = Path(SOCKET)
    # Systemd creates the service-owned parent, group-traversable and never group-writable.
    path.unlink(missing_ok=True)
    with IntakeServer(
        path, lambda: PostgresStore(database_url()), gid
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
