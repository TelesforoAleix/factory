"""Bounded, credential-redacting run API v1 client."""

from urllib.parse import quote

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


class Connection:
    def __init__(self):
        self.url = os.environ.get("CPLANE_EVAL_TASK_URL", "").rstrip("/")
        filename = os.environ.get("CPLANE_EVAL_TASK_KEY_FILE")
        if not self.url or not filename:
            raise Unavailable("Platform run settings unavailable")
        try:
            self.key = Path(filename).read_text().strip()
        except (OSError, UnicodeError, ValueError):
            raise Unavailable("Platform run key file unavailable or invalid") from None
        if not self.key or "\n" in self.key or "\r" in self.key:
            raise Unavailable("Platform run key file unavailable or invalid")

    def request(self, path, body=None, *, accepted=None):
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
                    raise Unavailable(f"Platform run HTTP {error.code}") from None
                response = error
            with response:
                if response.status not in (accepted or ((201, 409) if body is not None else (200,))):
                    raise Unavailable(f"Platform run HTTP {response.status}")
                # Bound run records and never retain credential-bearing diagnostics.
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
            raise Unavailable("Platform run response unavailable") from None


class NotResumable(Unavailable):
    """Cancellation can be retried after a running turn ends."""


class Client(Connection):
    def request(self, path, body=None):
        value = super().request(path, body, accepted=(200, 201, 409))
        if not isinstance(value, dict):
            raise Unavailable("Platform run response unavailable")
        if value.get("error") == "not_resumable":
            raise NotResumable("Platform run not resumable")
        if "error" in value:
            # Never reflect a response's diagnostics, ids or request content.
            raise Unavailable("Platform run request refused")
        return value

    def submit(self, body):
        value = self.request("/v1/runs", body)
        identity = value.get("run_id")
        if not isinstance(identity, str) or not identity:
            raise Unavailable("Platform run id unavailable")
        return identity

    def get(self, identity):
        value = self.request("/v1/runs/" + quote(identity, safe=""))
        if value.get("status") not in (
            "queued",
            "running",
            "done",
            "question",
            "waiting",
            "escalated",
            "failed",
            "cancelled",
        ):
            raise Unavailable("Platform run status unavailable")
        return value

    def find(self, request_id):
        value = self.request("/v1/runs?request_id=" + quote(request_id, safe=""))
        rows = value.get("runs")
        if not isinstance(rows, list) or len(rows) > 1:
            raise Unavailable("Platform run lookup unavailable")
        if not rows:
            return None
        row = rows[0]
        if (
            not isinstance(row, dict)
            or row.get("request_id") != request_id
            or not isinstance(row.get("run_id"), str)
        ):
            raise Unavailable("Platform run lookup unavailable")
        return row["run_id"]

    def message(self, identity, body):
        return self.request("/v1/runs/" + quote(identity, safe="") + "/messages", body)

    def cancel(self, identity):
        return self.request("/v1/runs/" + quote(identity, safe="") + "/cancel", {})


class DecisionsError(Unavailable):
    """A decisions API refusal; keeps only the HTTP status and the error code."""

    def __init__(self, status, code):
        super().__init__(f"Platform decisions HTTP {status}")
        self.status = status
        self.code = code


class Decisions(Connection):
    """Home Lab decisions API on the run platform's URL and bearer key."""

    def decide(self, body):
        try:
            request = Request(
                self.url + "/v1/decisions",
                data=json.dumps(body).encode(),
                headers={
                    "Authorization": "Bearer " + self.key,
                    "Content-Type": "application/json",
                },
            )
            try:
                response = build_opener(ProxyHandler({}), NoRedirect).open(
                    request, timeout=60
                )
            except HTTPError as error:
                with error:
                    code = None
                    try:
                        value = json.loads(error.read(64 * 1024))
                        # Only a short, plain code; never a diagnostic.
                        if (isinstance(value, dict) and isinstance(value.get("error"), str)
                                and len(value["error"]) <= 64 and value["error"].replace("_", "").isalnum()):
                            code = value["error"]
                    except (OSError, ValueError, HTTPException):
                        pass
                raise DecisionsError(error.code, code) from None
            with response:
                if response.status != 200:
                    raise DecisionsError(response.status, None)
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError
                value = json.loads(raw)
        except DecisionsError:
            raise
        except (OSError, URLError, ValueError, HTTPException):
            raise Unavailable("Platform decisions response unavailable") from None
        if not isinstance(value, dict):
            raise Unavailable("Platform decisions response unavailable")
        return value
