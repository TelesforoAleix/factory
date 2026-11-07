"""Standalone stdlib MCP stdio relay, copied into each chat turn's run folder."""
import json
from pathlib import Path
import socket
import sys

SOCKET = Path(__file__).with_name('workshop.sock')
MAX_REQUEST = 65_536


def relay(request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.settimeout(30)
        channel.connect(str(SOCKET))
        channel.sendall(request + b'\n')
        with channel.makefile('rb') as stream:
            return json.loads(stream.readline())


def main():
    while line := sys.stdin.buffer.readline(MAX_REQUEST + 1):
        request_id = None
        try:
            if len(line) > MAX_REQUEST or not line.endswith(b'\n'):
                raise ValueError
            request = json.loads(line)
            request_id = request.get('id')
            response = relay(line.rstrip(b'\n'))
        except Exception:
            response = dict(jsonrpc='2.0', id=request_id,
                            error=dict(code=-32603, message='Workshop unavailable'))
        if request_id is not None:
            print(json.dumps(response), flush=True)


if __name__ == '__main__':
    main()
