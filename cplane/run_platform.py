"""Run API v1 client, sharing eval's bounded, credential-redacting connection."""

from urllib.parse import quote

from .eval_platform import Client as Connection
from .eval_platform import Unavailable


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
