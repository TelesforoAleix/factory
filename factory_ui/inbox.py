"""Owner inbox/ideas API. Uses the application's mutation origin guard."""

from flask import jsonify, request
from cplane.state import StateError


def register_inbox(app, backend):
    def response(operation):
        try:
            return jsonify(operation())
        except (StateError, TypeError, ValueError) as error:
            return jsonify(
                error=str(error)
                if isinstance(error, StateError)
                else "Invalid arguments"
            ), 400
        except Exception:
            return jsonify(error="Inbox unavailable"), 503

    @app.route("/api/inbox", methods=["GET", "POST"])
    def inbox_entries():
        if request.method == "GET":
            return response(lambda: backend().inbox_list())
        from cplane.intake import decode_arrival, MAX_REQUEST

        if request.content_length is None or request.content_length > MAX_REQUEST:
            return jsonify(error="Invalid request size"), 413

        def add():
            values = decode_arrival(request.get_json(silent=True))
            values["source"] = "typed"
            return backend().inbox_add(**values)

        return response(add)

    @app.get("/api/inbox/<int:entry>")
    def inbox_entry(entry):
        return response(lambda: backend().inbox_show(entry))

    @app.get("/api/inbox/files/<int:file>")
    def inbox_file(file):
        return response(
            lambda: backend().inbox_file(file, int(request.args.get("offset", "0")))
        )

    @app.post("/api/inbox/<int:entry>/transcript")
    def transcript(entry):
        def attach():
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict) or set(payload) != {"text"}:
                raise StateError("Text required")
            return backend().inbox_transcript(entry, payload["text"], actor="owner")

        return response(attach)

    @app.route("/api/ideas", methods=["GET", "POST"])
    def ideas():
        if request.method == "GET":
            return response(lambda: backend().idea_list())

        from cplane.intake import MAX_REQUEST, decode_arrival

        if request.content_length is None or request.content_length > MAX_REQUEST:
            return jsonify(error="Invalid request size"), 413

        def add():
            payload = request.get_json(silent=True)
            if (
                not isinstance(payload, dict)
                or set(payload) - {"title", "note", "tags", "files"}
                or "title" not in payload
            ):
                raise StateError("Invalid idea")
            if "files" in payload:
                payload["files"] = decode_arrival(
                    dict(text="", files=payload["files"])
                )["files"]
            return backend().idea_new(**payload, actor="owner")

        return response(add)

    @app.get("/api/ideas/<int:idea>")
    def idea_detail(idea):
        return response(lambda: backend().idea_show(idea))

    @app.post("/api/ideas/<action>")
    def idea_action(action):
        def perform():
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                raise StateError("Invalid action")
            if action in ("explore", "promote") and not set(payload) - {
                "ideas",
                "project",
                "feature",
            }:
                return backend().idea_request(**payload, action=action, actor="owner")
            if action == "reject" and set(payload) == {"idea", "reason"}:
                return backend().idea_reject(**payload, actor="owner")
            if action == "tag" and set(payload) == {"idea", "tags"}:
                return backend().idea_tag(**payload, actor="owner")
            raise StateError("Invalid action")

        return response(perform)
