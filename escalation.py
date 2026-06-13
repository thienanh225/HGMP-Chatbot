"""
Escalation + conversation logging, and ROUTE-tag parsing.

Log destinations, in priority order (first that succeeds wins):
  1. Webhook  — a Google Apps Script Web App that appends to your Google Sheet.
     Free, no GCP/service account. Set LOG_WEBHOOK_URL in secrets.
     Script: tools/apps_script_logger.gs.
  2. CSV      — local data/*.csv fallback. Always works; note it is EPHEMERAL on
     Streamlit Community Cloud (resets on restart), so use the webhook for a
     durable record there.

Three streams: conversations (every turn), escalations (tickets), feedback.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
ESCALATION_CSV = ROOT / "data" / "escalations.csv"
FEEDBACK_CSV = ROOT / "data" / "feedback.csv"
CONVERSATION_CSV = ROOT / "data" / "conversations.csv"

_ROUTE_RE = re.compile(r"ROUTE:\s*([a-z\-]+)", re.IGNORECASE)
VALID_ROUTES = frozenset({"qualified-person", "customer-service", "account-management", "sales"})


# ---------------------------------------------------------------------------
# ROUTE tag (pure, testable)
# ---------------------------------------------------------------------------

def parse_route(text: str) -> str | None:
    match = _ROUTE_RE.search(text or "")
    if not match:
        return None
    candidate = match.group(1).strip().lower().rstrip(".")
    return candidate if candidate in VALID_ROUTES else None


def clean_reply(text: str) -> str:
    cleaned = _ROUTE_RE.sub("", text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def notify(route: str, session_id: str = "?", audience: str = "?", message: str = "") -> None:
    logger.warning("ESCALATION | route=%s | session=%s | audience=%s | msg=%.160s",
                   route, session_id, audience, message)


# ---------------------------------------------------------------------------
# Destinations
# ---------------------------------------------------------------------------

class _PostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep POST + body on Google Apps Script's 302 redirect.

    urllib.request converts POST→GET on 302 by default (RFC 2616).  Apps Script
    executes doPost *after* the redirect, so the default handler drops the body
    and calls doGet instead — the sheet never gets written.  This handler
    re-issues the POST with the original body to the redirect target.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return urllib.request.Request(
            newurl, data=req.data, method="POST",
            headers={"Content-Type": "application/json"},
        )


def _post_webhook(url: str, payload: dict) -> bool:
    """POST a JSON record to the Apps Script Web App. True on 2xx."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        opener = urllib.request.build_opener(_PostRedirectHandler())
        with opener.open(req, timeout=6) as resp:  # noqa: S310 (trusted user URL)
            return resp.status < 400
    except Exception:
        logger.exception("Webhook logging failed — falling back")
        return False


def _append_csv(path: Path, header: list[str], row: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(header)
        writer.writerow(row)


def _dispatch(worksheet: str, header: list[str], row: list[str], csv_path: Path,
              secrets: dict | None) -> str:
    """Try webhook → CSV. Returns where it was logged."""
    secrets = secrets or {}
    url = secrets.get("LOG_WEBHOOK_URL")
    if url and _post_webhook(url, {"sheet": worksheet, **dict(zip(header, row))}):
        return "webhook"
    _append_csv(csv_path, header, row)
    return "csv"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Public log functions
# ---------------------------------------------------------------------------

def log_escalation(question: str, user_id: str, route: str = "qualified-person",
                   secrets: dict | None = None) -> str:
    header = ["timestamp", "user_id", "route", "question"]
    row = [_now(), user_id, route, question]
    return _dispatch("escalations", header, row, ESCALATION_CSV, secrets)


def log_feedback(text: str, user_id: str, secrets: dict | None = None) -> str:
    header = ["timestamp", "user_id", "feedback"]
    row = [_now(), user_id, text]
    return _dispatch("feedback", header, row, FEEDBACK_CSV, secrets)


def log_conversation(session_id: str, audience: str, model: str, route: str | None,
                     sources: list[str], question: str, answer: str,
                     secrets: dict | None = None) -> str:
    """Log a single chat turn (every conversation, not just escalations)."""
    header = ["timestamp", "session_id", "audience", "model", "route", "sources",
              "question", "answer"]
    row = [_now(), session_id, audience, model, route or "", ",".join(sources or []),
           question, answer]
    return _dispatch("conversations", header, row, CONVERSATION_CSV, secrets)
