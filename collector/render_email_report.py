"""Render and send the twice-daily scraper status email."""
from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
from collections import Counter
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo


def status_counts(path: Path, heading: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = line == heading
            continue
        if in_section:
            match = re.match(r"^- ([A-Z_]+):\s+(\d+)", line)
            if match:
                counts[match.group(1)] = int(match.group(2))
    return counts


def lifecycle_counts(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) >= 4 and cells[1].isdigit():
            counts[cells[3]] += 1
    return counts


def render(status: Path, lifecycle: Path, health: Path, runs: Path) -> str:
    now = datetime.now(ZoneInfo("Europe/Amsterdam"))
    queue = status_counts(status, "## Statusaantallen")
    lifecycle_state = lifecycle_counts(lifecycle)
    health_lines = [line for line in health.read_text(encoding="utf-8").splitlines()
                    if line.startswith("| ") and not line.startswith("|---")]
    run_data = json.loads(runs.read_text(encoding="utf-8"))
    recent = []
    for run in run_data.get("workflow_runs", [])[:10]:
        recent.append(f"- {run.get('name', 'workflow')}: {run.get('status')}/{run.get('conclusion') or '—'}")
    lines = [
        "Vinylofy scraper status",
        f"Rapporttijd: {now:%Y-%m-%d %H:%M} Europe/Amsterdam",
        "",
        "CENTRALE QUEUE",
        *(f"- {key}: {value}" for key, value in sorted(queue.items())),
        "",
        "LIFECYCLE",
        *(f"- {key}: {value}" for key, value in sorted(lifecycle_state.items())),
        "",
        f"HEALTH: {max(0, len(health_lines) - 1)} geregistreerde scraper/mode-regels",
        "",
        "RECENTE ACTIONS",
        *(recent or ["- Geen recente runs gevonden"]),
        "",
        "Zie GitHub Actions en scraper-status.md voor de volledige details.",
    ]
    return "\n".join(lines) + "\n"


def send(body: str, *, subject: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    recipient = os.environ.get("REPORT_TO", "edwindejager@gmail.com")
    message = EmailMessage()
    message["From"] = username
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(username, password)
            smtp.send_message(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--lifecycle", type=Path, required=True)
    parser.add_argument("--health", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    args = parser.parse_args()
    body = render(args.status, args.lifecycle, args.health, args.runs)
    now = datetime.now(ZoneInfo("Europe/Amsterdam"))
    send(body, subject=f"Vinylofy scraper update — {now:%Y-%m-%d %H:%M}")
    print("Status email sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
