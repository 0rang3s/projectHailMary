"""Bridge between the Streamlit Guide chat and our checked AI answers (ai.llm.infer).

frontend/app.py calls two functions from here:
    ask_checked(question, date, audience_label)  -> {"text", "dates", "raw"} or None
    answer_html(raw)                              -> one line of safe HTML for the chat bubble

None means "the checked AI is not available right now", and app.py then uses its own fallback.
Nothing here invents content: it only formats what ai.llm.infer returned.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_AUDIENCE = {"Coordinator": "coordinator", "Community": "community", "Pilots": "pilots"}
_UNAVAILABLE = ("couldn't answer just now", "AI not configured")
_COLOUR = {"low": "#f59e0b", "medium": "#38bdf8", "high": "#4ade80"}


def prettify_dates(text: str) -> str:
    """2025-05-19 -> May 19, 2025, the style the page's own answers use."""
    def repl(match):
        year, month, day = (int(g) for g in match.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{MONTHS[month - 1]} {day}, {year}"
        return match.group(0)
    return _ISO.sub(repl, text or "")


def plain_text(raw: dict) -> str:
    """Summary plus one bullet per claim. This is the text the page's number check reads."""
    lines = [raw.get("summary") or ""]
    lines += [f"- {c.get('claim', '')}" for c in raw.get("claims") or []]
    return "\n".join(line for line in lines if line.strip())


def _dates_from(raw: dict) -> list[str]:
    found = set()
    for claim in raw.get("claims") or []:
        for evidence_id in claim.get("evidence") or []:
            found.update(m.group(0) for m in _ISO.finditer(str(evidence_id)))
    return sorted(found)


def ask_checked(question: str, date: str | None = None, audience_label: str | None = None):
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from ai.llm import infer
        ui = {}
        if date:
            ui["date"] = date
        if _AUDIENCE.get(audience_label or ""):
            ui["audience"] = _AUDIENCE[audience_label]
        raw = infer(question, None, ui or None)
    except Exception as exc:                      # import error, missing key, anything unexpected
        print("AI bridge error:", type(exc).__name__, exc)
        return None
    summary = (raw or {}).get("summary") or ""
    if (raw or {}).get("error_kind"):
        # The assistant is busy or failed: tell the user, in words, instead of silently using the template.
        return {"text": summary, "dates": [],
                "raw": {"summary": summary, "claims": [], "not_known": [], "notice": True}}
    if not summary or any(marker in summary for marker in _UNAVAILABLE):
        return None                                   # no key configured: the page's own answer is intended
    return {"text": prettify_dates(plain_text(raw)), "dates": _dates_from(raw), "raw": raw}


def _e(text) -> str:
    return html.escape(prettify_dates(str(text)))


def answer_html(raw: dict) -> str:
    """Single-line HTML (no blank lines, no indentation) so Markdown never turns it into a code block."""
    if raw.get("notice"):
        return ("<div style='padding:8px 10px;border:1px solid rgba(245,158,11,.55);border-radius:10px;"
                f"color:#f59e0b'>⏳ {_e(raw.get('summary', ''))}</div>")
    parts = [f"<div>{_e(raw.get('summary', ''))}</div>"]
    if raw.get("summary_warning"):
        parts.append(f"<div style='margin-top:6px;font-size:12px;color:#f59e0b'>⚠ {_e(raw['summary_warning'])}</div>")
    for claim in raw.get("claims") or []:
        level = claim.get("confidence", "low")
        colour = _COLOUR.get(level, "#f59e0b")
        tags = f"<b style='font-size:11px;color:{colour}'>{html.escape(str(level))} confidence</b>"
        if claim.get("grounded_in_docs"):
            tags += " <span style='font-size:11px;color:#4ade80'>· source checked</span>"
        elif str(claim.get("claim", "")).startswith("Unsourced hypothesis"):
            tags += " <span style='font-size:11px;color:#f59e0b'>· no document source</span>"
        box = ("<div style='margin-top:8px;padding:8px 10px;border:1px solid rgba(148,163,184,.35);"
               "border-radius:10px'>")
        box += f"{tags}<div>{_e(claim.get('claim', ''))}</div>"
        if claim.get("alternative"):
            box += f"<div style='font-size:12px;opacity:.75'>Another possibility: {_e(claim['alternative'])}</div>"
        if claim.get("would_change_if"):
            box += f"<div style='font-size:12px;opacity:.75'>This would change if: {_e(claim['would_change_if'])}</div>"
        if claim.get("note"):
            box += f"<div style='font-size:12px;color:#f59e0b'>{_e(claim['note'])}</div>"
        ids = "".join(f"<code style='font-size:10px;margin-right:4px'>{html.escape(str(i))}</code>"
                      for i in claim.get("evidence") or [])
        if ids:
            box += f"<div style='margin-top:4px'>{ids}</div>"
        parts.append(box + "</div>")
    limits = [x for x in raw.get("not_known") or [] if isinstance(x, str)]
    if limits:
        items = "".join(f"<li>{_e(x)}</li>" for x in limits)
        parts.append("<details style='margin-top:8px;font-size:12px'><summary>What we can't tell</summary>"
                     f"<ul style='margin:4px 0 0 16px'>{items}</ul></details>")
    return "".join(parts)