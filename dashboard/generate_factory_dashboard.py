#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
import json
import os
import re


PROJECT_DIR = Path(__file__).resolve().parents[1]
OPS_DIR = PROJECT_DIR / "ops"
DASHBOARD_DIR = PROJECT_DIR / "dashboard"
OUTPUT_PATH = DASHBOARD_DIR / "index.html"


FINAL_TICKET_STATUSES = {"release_ready", "done", "completed", "cancelled"}
READY_RELEASE_STATUSES = {"ready", "released"}


def parse_scalar(value: str):
    value = value.strip()
    if value in {"", "null", "~"}:
        return None
    if value == "[]":
        return []
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def parse_loose_yaml(text: str) -> dict:
    data = {}
    current_key = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        if indent == 0 and ":" in line and not line.startswith("- "):
            key, raw_value = line.split(":", 1)
            key = key.strip()
            value = raw_value.strip()
            if value == "":
                data[key] = []
                current_key = key
            else:
                data[key] = parse_scalar(value)
                current_key = None
            continue

        if current_key and line.startswith("- "):
            data.setdefault(current_key, [])
            data[current_key].append(parse_scalar(line[2:].strip()))

    return data


def extract_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:index])
    return ""


def rel_link(path: Path) -> str:
    return path.relative_to(DASHBOARD_DIR).as_posix() if path.is_relative_to(DASHBOARD_DIR) else path.relative_to(DASHBOARD_DIR.parent).as_posix()


def object_link(path: Path) -> str:
    return Path("..", path.relative_to(PROJECT_DIR)).as_posix()


def load_yaml_objects(folder: str) -> list[dict]:
    objects = []
    directory = OPS_DIR / folder
    for path in sorted(directory.glob("*.yaml")):
        if path.name == "README.md":
            continue
        data = parse_loose_yaml(path.read_text(encoding="utf-8"))
        data["_file"] = path
        data["_link"] = object_link(path)
        data["_filename"] = path.name
        objects.append(data)
    return objects


def load_json_objects(folder: str) -> list[dict]:
    objects = []
    directory = OPS_DIR / folder
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_file"] = path
        data["_link"] = object_link(path)
        data["_filename"] = path.name
        objects.append(data)
    return objects


def load_markdown_frontmatter(folder: str) -> list[dict]:
    objects = []
    directory = OPS_DIR / folder
    for path in sorted(directory.glob("*.md")):
        if path.name == "README.md":
            continue
        frontmatter = extract_frontmatter(path.read_text(encoding="utf-8"))
        if not frontmatter:
            continue
        data = parse_loose_yaml(frontmatter)
        data["_file"] = path
        data["_link"] = object_link(path)
        data["_filename"] = path.name
        objects.append(data)
    return objects


def ensure_list(value) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def sort_key(value: str) -> tuple:
    numbers = tuple(int(number) for number in re.findall(r"\d+", str(value)))
    return numbers or (0,)


def sort_object(obj: dict) -> tuple:
    return sort_key(obj.get("id", obj.get("_filename", "")))


def status_class(status: str) -> str:
    status = str(status or "unknown")
    if status in {"release_ready", "ready", "completed", "passed", "promoted"}:
        return "is-good"
    if status in {"active", "in_progress", "assigned", "self_review", "waiting"}:
        return "is-active"
    if status in {"blocked", "failed", "cancelled"}:
        return "is-bad"
    if status in {"revision", "changes_requested"}:
        return "is-warn"
    return "is-muted"


def html(value) -> str:
    return escape(str(value or ""), quote=True)


def truncate(value, limit: int = 150) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def href_from_project_link(target: str) -> str:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return target

    path_part, separator, anchor = target.partition("#")
    target_path = (PROJECT_DIR / path_part).resolve()
    href = Path(os.path.relpath(target_path, DASHBOARD_DIR)).as_posix()
    if separator:
        href = f"{href}#{anchor}"
    return href


def render_inline_links(text: str) -> str:
    parts = []
    cursor = 0
    pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

    for match in pattern.finditer(str(text)):
        parts.append(html(text[cursor : match.start()]))
        label = match.group(1)
        target = match.group(2)
        parts.append(f'<a href="{html(href_from_project_link(target))}">{html(label)}</a>')
        cursor = match.end()

    parts.append(html(text[cursor:]))
    return "".join(parts)


def link_to(obj: dict, label: str | None = None, css_class: str = "record-link") -> str:
    href = obj.get("_link")
    text = label or obj.get("id") or obj.get("_filename") or "record"
    if not href:
      return html(text)
    return f'<a class="{css_class}" href="{html(href)}">{html(text)}</a>'


def chip(value: str, extra_class: str = "") -> str:
  value = str(value or "unknown")
  classes = f"chip {status_class(value)} {extra_class}".strip()
  return f'<span class="{classes}">{html(value.replace("_", " "))}</span>'


def extract_section(text: str, heading: str) -> str:
  pattern = rf"^## {re.escape(heading)}\s*\n(?P<body>.*?)(?=\n## |\Z)"
  match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
  return match.group("body").strip() if match else ""


def first_nonempty_line(text: str, fallback: str = "") -> str:
  for line in text.splitlines():
      cleaned = line.strip()
      if cleaned:
          return cleaned
  return fallback


def render_metric(label: str, value: int | str, detail: str) -> str:
  return f"""
  <section class="metric panel">
    <div class="metric-label">{html(label)}</div>
    <div class="metric-value">{html(value)}</div>
    <div class="metric-detail">{html(detail)}</div>
  </section>
  """


def render_process(process_counts: list[tuple[str, int]]) -> str:
  items = []
  for label, count in process_counts:
      items.append(
          f"""
          <li class="process-step">
            <span class="process-count">{html(count)}</span>
            <span class="process-label">{html(label)}</span>
          </li>
          """
      )
  return "\n".join(items)


def render_ticket_rows(tickets: list[dict], runs_by_ticket: dict, reviews_by_ticket: dict, release_by_ticket: dict, context_pack_ids: set[str]) -> str:
  rows = []
  for ticket in sorted(tickets, key=sort_object, reverse=True):
      ticket_id = ticket.get("id")
      runs = sorted(runs_by_ticket.get(ticket_id, []), key=sort_object)
      reviews = reviews_by_ticket.get(ticket_id, [])
      release = release_by_ticket.get(ticket_id)
      context_id = ticket.get("required_context_pack_id")
      latest_run = runs[-1] if runs else {}
      next_action = latest_run.get("next_action") or first_nonempty_line("\n".join(ensure_list(release.get("post_release_followups") if release else [])))
      evidence = []
      if context_id in context_pack_ids:
          evidence.append(f'<span class="mini-chip">{html(context_id)}</span>')
      if runs:
          evidence.append(f'<span class="mini-chip">{html(runs[-1].get("id"))}</span>')
      if reviews:
          passed = sum(1 for review in reviews if review.get("decision") == "passed" or review.get("status") == "passed")
          evidence.append(f'<span class="mini-chip">reviews {passed}/{len(reviews)}</span>')
      if release:
          evidence.append(f'<span class="mini-chip">release {html(release.get("status"))}</span>')

      rows.append(
          f"""
          <tr>
            <td>{link_to(ticket)}</td>
            <td>
              <div class="row-title">{html(ticket.get("title"))}</div>
              <div class="row-subtitle">{html(truncate(ticket.get("objective"), 130))}</div>
            </td>
            <td>{chip(ticket.get("status"))}</td>
            <td>{html(ticket.get("owner_role"))}</td>
            <td>{chip(ticket.get("priority"), "priority")}</td>
            <td><div class="evidence-stack">{"".join(evidence) or '<span class="muted">No linked evidence</span>'}</div></td>
            <td>{html(truncate(next_action, 120))}</td>
          </tr>
          """
      )
  return "\n".join(rows)


def render_run_rows(runs: list[dict]) -> str:
  rows = []
  for run in sorted(runs, key=sort_object, reverse=True)[:8]:
      rows.append(
          f"""
          <tr>
            <td>{link_to(run)}</td>
            <td>{html(run.get("related_ticket_id"))}</td>
            <td>{chip(run.get("status"))}</td>
            <td>{html(run.get("owner_role"))}</td>
            <td>{html(truncate(run.get("output_summary"), 130))}</td>
            <td>{html(truncate(run.get("next_action"), 120))}</td>
          </tr>
          """
      )
  return "\n".join(rows)


def render_record_list(records: list[dict], empty_label: str) -> str:
  if not records:
      return f'<div class="empty-state">{html(empty_label)}</div>'
  items = []
  for record in sorted(records, key=sort_object, reverse=True):
      items.append(
          f"""
          <li class="record-item">
            <div>{link_to(record)} <span class="muted">{html(record.get("title"))}</span></div>
            <div>{chip(record.get("status"))}</div>
          </li>
          """
      )
  return f'<ul class="record-list">{"".join(items)}</ul>'


def build_dashboard() -> str:
  tickets = load_yaml_objects("tickets")
  tasks = load_yaml_objects("tasks")
  reviews = load_yaml_objects("reviews")
  learning = load_yaml_objects("learning")
  inbox = load_yaml_objects("inbox")
  approvals = load_yaml_objects("approvals")
  runs = load_json_objects("runs")
  releases = load_markdown_frontmatter("releases")

  context_pack_ids = {
      path.stem for path in (OPS_DIR / "context-packs").glob("CP-*.md") if path.name != "README.md"
  }

  runs_by_ticket = defaultdict(list)
  for run in runs:
      runs_by_ticket[run.get("related_ticket_id")].append(run)

  reviews_by_ticket = defaultdict(list)
  for review in reviews:
      reviews_by_ticket[review.get("related_ticket_id")].append(review)

  release_by_ticket = {}
  for release in releases:
      for ticket_id in ensure_list(release.get("ticket_ids")):
          release_by_ticket[ticket_id] = release

  ticket_statuses = Counter(ticket.get("status") for ticket in tickets)
  open_tickets = [ticket for ticket in tickets if ticket.get("status") not in FINAL_TICKET_STATUSES]
  blocked_tickets = [
      ticket
      for ticket in tickets
      if ticket.get("status") == "blocked" or ensure_list(ticket.get("blocking_object_ids"))
  ]
  ready_releases = [release for release in releases if release.get("status") in READY_RELEASE_STATUSES]
  self_reviews = [review for review in reviews if review.get("review_type") == "self_review"]
  fresh_reviews = [review for review in reviews if review.get("review_type") == "fresh_context"]

  progress_text = (PROJECT_DIR / "progress.md").read_text(encoding="utf-8")
  current_phase = first_nonempty_line(extract_section(progress_text, "Current Phase"), "Unknown")
  next_moves = [line.strip()[3:] for line in extract_section(progress_text, "Next Recommended Moves").splitlines() if re.match(r"^\d+\. ", line.strip())]
  next_move_html = "".join(f"<li>{render_inline_links(move)}</li>" for move in next_moves[:5])

  process_counts = [
      ("Tickets", len(tickets)),
      ("Context Packs", len(context_pack_ids)),
      ("Runs", len(runs)),
      ("Self Reviews", len(self_reviews)),
      ("Fresh Reviews", len(fresh_reviews)),
      ("Releases Ready", len(ready_releases)),
      ("Learning", len(learning)),
  ]

  generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
  latest_ticket = sorted(tickets, key=sort_object, reverse=True)[0] if tickets else {}
  latest_run = sorted(runs, key=sort_object, reverse=True)[0] if runs else {}

  css = """
  :root {
    --bg: #f4f3ef;
    --surface: #ffffff;
    --surface-alt: #f9f8f4;
    --ink: #202124;
    --muted: #626970;
    --line: #d9d6cc;
    --accent: #2f6f6d;
    --accent-soft: #e2f0ee;
    --amber: #8a5a00;
    --amber-soft: #f7ead0;
    --red: #a33225;
    --red-soft: #f7ded9;
    --green: #24734d;
    --green-soft: #dff0e7;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.45;
  }

  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }

  .page {
    max-width: 1360px;
    margin: 0 auto;
    padding: 28px;
  }

  .topbar {
    display: flex;
    justify-content: space-between;
    gap: 20px;
    align-items: flex-end;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--line);
  }

  h1, h2, h3, p { margin: 0; }

  h1 { font-size: 30px; font-weight: 700; letter-spacing: 0; }
  h2 { font-size: 18px; font-weight: 700; letter-spacing: 0; }
  h3 { font-size: 15px; font-weight: 700; letter-spacing: 0; }

  .subtitle { margin-top: 6px; color: var(--muted); max-width: 760px; }
  .timestamp { color: var(--muted); text-align: right; white-space: nowrap; }

  .grid { display: grid; gap: 14px; }
  .metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 20px 0; }
  .two-col { grid-template-columns: minmax(0, 1.3fr) minmax(320px, 0.7fr); }
  .side-grid { grid-template-columns: 1fr; }

  .panel {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 16px;
  }

  .metric-label { color: var(--muted); font-size: 12px; text-transform: uppercase; }
  .metric-value { font-size: 30px; font-weight: 700; margin-top: 4px; }
  .metric-detail { color: var(--muted); margin-top: 2px; min-height: 20px; }

  .section-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 12px;
  }

  .section-note { color: var(--muted); font-size: 13px; }

  .process {
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 10px;
  }

  .process-step {
    background: var(--surface-alt);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 12px;
    min-height: 76px;
  }

  .process-count { display: block; font-size: 22px; font-weight: 700; }
  .process-label { display: block; color: var(--muted); margin-top: 4px; }

  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; min-width: 920px; }
  th, td { padding: 10px 8px; border-bottom: 1px solid var(--line); vertical-align: top; text-align: left; }
  th { color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; }
  tr:last-child td { border-bottom: 0; }

  .row-title { font-weight: 650; }
  .row-subtitle { color: var(--muted); margin-top: 3px; max-width: 520px; }

  .chip, .mini-chip {
    display: inline-flex;
    align-items: center;
    min-height: 24px;
    padding: 3px 8px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: var(--surface-alt);
    color: var(--ink);
    white-space: nowrap;
    font-size: 12px;
  }

  .mini-chip { margin: 0 4px 4px 0; }
  .is-good { background: var(--green-soft); border-color: #b7dcc7; color: var(--green); }
  .is-active { background: var(--accent-soft); border-color: #bddbd8; color: var(--accent); }
  .is-warn { background: var(--amber-soft); border-color: #e5c67d; color: var(--amber); }
  .is-bad { background: var(--red-soft); border-color: #e0aaa1; color: var(--red); }
  .is-muted { color: var(--muted); }

  .evidence-stack { max-width: 260px; }
  .muted { color: var(--muted); }
  .empty-state { color: var(--muted); padding: 12px 0; }

  .record-list { list-style: none; margin: 0; padding: 0; }
  .record-item {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid var(--line);
  }
  .record-item:last-child { border-bottom: 0; }

  .next-list { margin: 0; padding-left: 18px; color: var(--ink); }
  .next-list li { margin: 6px 0; }

  .footer {
    margin-top: 18px;
    color: var(--muted);
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
  }

  @media (max-width: 980px) {
    .page { padding: 18px; }
    .topbar { align-items: flex-start; flex-direction: column; }
    .timestamp { text-align: left; }
    .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .two-col { grid-template-columns: 1fr; }
    .process { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }

  @media (max-width: 560px) {
    .metrics { grid-template-columns: 1fr; }
    .process { grid-template-columns: 1fr; }
    h1 { font-size: 24px; }
  }
  """

  return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Factory Dashboard</title>
<style>{css}</style>
</head>
<body>
<main class="page">
  <header class="topbar">
    <div>
      <h1>The Factory Dashboard</h1>
      <p class="subtitle">Read-only local snapshot of Factory ops: tickets, runs, reviews, release state, decisions, and learning.</p>
    </div>
    <div class="timestamp">Generated {html(generated_at)}</div>
  </header>

  <section class="grid metrics" aria-label="Factory metrics">
    {render_metric("Tickets", len(tickets), f"{len(open_tickets)} open, {ticket_statuses.get('release_ready', 0)} release ready")}
    {render_metric("Runs", len(runs), f"latest {latest_run.get('id', 'none')}")}
    {render_metric("Reviews", len(reviews), f"{len(self_reviews)} self, {len(fresh_reviews)} fresh")}
    {render_metric("Releases", len(ready_releases), f"{len(blocked_tickets)} blocked tickets")}
  </section>

  <section class="panel">
    <div class="section-head">
      <h2>Current Operating Flow</h2>
      <span class="section-note">Phase: {html(current_phase)}</span>
    </div>
    <ol class="process">
      {render_process(process_counts)}
    </ol>
  </section>

  <section class="grid two-col" style="margin-top: 14px;">
    <section class="panel">
      <div class="section-head">
        <h2>Ticket Board</h2>
        <span class="section-note">Latest: {link_to(latest_ticket) if latest_ticket else 'none'}</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Ticket</th>
              <th>Work</th>
              <th>Status</th>
              <th>Owner</th>
              <th>Priority</th>
              <th>Evidence</th>
              <th>Next</th>
            </tr>
          </thead>
          <tbody>{render_ticket_rows(tickets, runs_by_ticket, reviews_by_ticket, release_by_ticket, context_pack_ids)}</tbody>
        </table>
      </div>
    </section>

    <aside class="grid side-grid">
      <section class="panel">
        <div class="section-head"><h2>Next Moves</h2></div>
        <ol class="next-list">{next_move_html}</ol>
      </section>
      <section class="panel">
        <div class="section-head"><h2>Founder Inbox</h2></div>
        {render_record_list(inbox, "No open founder inbox items.")}
      </section>
      <section class="panel">
        <div class="section-head"><h2>Approvals</h2></div>
        {render_record_list(approvals, "No pending approvals.")}
      </section>
      <section class="panel">
        <div class="section-head"><h2>Learning</h2></div>
        {render_record_list(learning, "No learning candidates yet.")}
      </section>
    </aside>
  </section>

  <section class="panel" style="margin-top: 14px;">
    <div class="section-head">
      <h2>Recent Runs</h2>
      <span class="section-note">Execution evidence from ops/runs</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Ticket</th>
            <th>Status</th>
            <th>Owner</th>
            <th>Output</th>
            <th>Next</th>
          </tr>
        </thead>
        <tbody>{render_run_rows(runs)}</tbody>
      </table>
    </div>
  </section>

  <footer class="footer">
    <a href="../ops/README.md">Ops</a>
    <a href="../progress.md">Progress</a>
    <a href="../roadmap.md">Roadmap</a>
    <a href="generate_factory_dashboard.py">Renderer</a>
  </footer>
</main>
</body>
</html>
"""


def main() -> None:
  DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
  OUTPUT_PATH.write_text(build_dashboard(), encoding="utf-8")
  print(f"Wrote {OUTPUT_PATH.relative_to(PROJECT_DIR.parent.parent)}")


if __name__ == "__main__":
  main()
