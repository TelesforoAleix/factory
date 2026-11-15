"""Loopback platform eval client. Never expose credentials or HTTP error bodies."""

import json
import os
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class Unavailable(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self):
        self.url = os.environ.get("CPLANE_EVAL_TASK_URL", "").rstrip("/")
        filename = os.environ.get("CPLANE_EVAL_TASK_KEY_FILE")
        if not self.url or not filename:
            raise Unavailable("Platform eval settings unavailable")
        try:
            self.key = Path(filename).read_text().strip()
        except (OSError, UnicodeError, ValueError):
            raise Unavailable("Platform eval key file unavailable or invalid") from None
        if not self.key or "\n" in self.key or "\r" in self.key:
            raise Unavailable("Platform eval key file unavailable or invalid")

    def request(self, path, body=None):
        try:
            request = Request(
                self.url + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={
                    "Authorization": "Bearer " + self.key,
                    "Content-Type": "application/json",
                },
            )
            try:
                response = build_opener(ProxyHandler({}), NoRedirect).open(
                    request, timeout=10
                )
            except HTTPError as error:
                if body is None or error.code != 409:
                    error.close()
                    raise Unavailable(f"Platform eval HTTP {error.code}") from None
                response = error
            with response:
                if response.status not in ((201, 409) if body is not None else (200,)):
                    raise Unavailable(f"Platform eval HTTP {response.status}")
                # Bound responses (the diff is at most 2 MB before base64 encoding).
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError
                value = json.loads(raw)

                # A server diagnostic must never reflect a credential into a record.
                def redact(item):
                    if isinstance(item, str):
                        return item.replace(self.key, "[redacted]")
                    if isinstance(item, list):
                        return [redact(v) for v in item]
                    if isinstance(item, dict):
                        return {redact(k): redact(v) for k, v in item.items()}
                    return item

                return redact(value)
        except (OSError, URLError, ValueError, HTTPException):
            raise Unavailable("Platform eval response unavailable") from None

    def submit(self, body):
        response = self.request("/v1/tasks/eval", body)
        task = response.get("task") if isinstance(response, dict) else None
        if type(task) is not int or task < 1:
            raise Unavailable("Platform eval task id unavailable")
        return task

    def get(self, task):
        return self.request(f"/v1/tasks/eval/{task}")
