"""Evidence preparation and answer checking for the flood assistant.

  build_findings(): code precomputes trends, status changes, ice contrast and water extent.
  search_knowledge(): small keyword search over sourced documents in data/knowledge/*.md.
  SYSTEM: the prompt for the one-call infer() path.
  finish(): validates the model's JSON against the evidence it was given.

This file does not import ai.llm, so there is no circular import.
"""
from __future__ import annotations

import json
import math
import os
import re
import types
from collections import Counter
from datetime import date
from pathlib import Path

from api.data import DataError, get_ice, get_lifelines, get_stats, list_dates, revision

VERSION = "inference-single-file-2026-10-03"
RED_M = 200    # red is 200 m or less
FLAT_M = 25    # a change smaller than this counts as "steady"

# ---------------------------------------------------------------- findings

_findings_cache: dict = {}


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def build_findings() -> dict:
    """Small, pre-digested facts computed in code. Every item has a stable `id`."""
    key = revision()
    if key in _findings_cache:
        return _findings_cache[key]

    dates = list_dates()["flood_dates"]
    series: dict[str, list] = {}
    meta: dict[str, dict] = {}
    water, ice_rows = [], []
    prev = None

    for iso in dates:
        try:
            rows = get_lifelines(iso)
        except DataError:
            rows = []
        for r in rows:
            meta[r["name"]] = {"type": r.get("type"), "verified": r.get("verified")}
            series.setdefault(r["name"], []).append({
                "date": iso,
                "dist_flood_m": r.get("dist_flood_m"),
                "dist_normal_m": r.get("dist_normal_m"),
                "status": r.get("status"),
            })

        try:
            stats = get_stats(iso)
            row = {"id": f"finding:water:{iso}", "date": iso,
                   "extra_water_km2": stats.get("extra_water_km2")}
            if prev and prev["extra_water_km2"] is not None and row["extra_water_km2"] is not None:
                row["change_since_prev_km2"] = round(row["extra_water_km2"] - prev["extra_water_km2"], 2)
                row["days_since_prev"] = _days(prev["date"], iso)
            water.append(row)
            prev = row
        except DataError:
            pass

        try:
            ice = get_ice(iso)
        except DataError:
            ice = None
        if ice:
            near = {
                k.split(" (")[0]: v.get("pct_frozen")
                for k, v in (ice.get("near_towns") or {}).items()
                if isinstance(v, dict)
            }
            ice_rows.append({
                "id": f"finding:ice:{iso}", "date": iso,
                "pct_frozen_overall": ice.get("pct_frozen_overall"),
                "near_towns_pct_frozen": near,
                "upstream_pct_frozen": ice.get("upstream_pct_frozen"),
                "jam_risk": ice.get("jam_risk"),
            })

    lifelines = []
    for name, rows in series.items():
        pts = [p for p in rows if p["dist_flood_m"] is not None]
        f = {"id": f"finding:lifeline:{name}", "name": name, **meta[name], "series": rows}
        changes, last_status = [], None
        for p in rows:
            if last_status is not None and p["status"] != last_status:
                changes.append({"date": p["date"], "from": last_status, "to": p["status"]})
            last_status = p["status"]
        f["status_changes"] = changes
        f["latest_status"] = rows[-1]["status"]
        f["latest_dist_m"] = rows[-1]["dist_flood_m"]
        f["latest_date"] = rows[-1]["date"]
        f["dates_red"] = sum(1 for p in rows if p["status"] == "red")
        if len(pts) >= 2:
            first, last = pts[0], pts[-1]
            change = last["dist_flood_m"] - first["dist_flood_m"]
            days = _days(first["date"], last["date"])
            f["closest"] = min(pts, key=lambda p: p["dist_flood_m"])
            f["change_m"] = change
            f["days"] = days
            f["direction"] = ("steady" if abs(change) < FLAT_M
                              else "closing" if change < 0 else "receding")
            prev_pt, last_pt = pts[-2], pts[-1]
            rc = last_pt["dist_flood_m"] - prev_pt["dist_flood_m"]
            f["recent_change_m"] = rc
            f["recent_days"] = _days(prev_pt["date"], last_pt["date"])
            f["recent_direction"] = ("steady" if abs(rc) < FLAT_M
                                     else "closing" if rc < 0 else "receding")
        lifelines.append(f)

    out = {"lifelines": lifelines, "ice": ice_rows, "water": water}
    _findings_cache.clear()
    _findings_cache[key] = out
    return out


def slim(findings: dict) -> dict:
    """The same facts in fewer tokens: series rows become [date, distance, status]."""
    lifelines = []
    for l in findings["lifelines"]:
        row = {k: v for k, v in l.items() if k != "series"}
        row["dist_normal_m"] = next(
            (p["dist_normal_m"] for p in l["series"] if p.get("dist_normal_m") is not None), None)
        row["series"] = [[p["date"], p["dist_flood_m"], p["status"]] for p in l["series"]]
        lifelines.append(row)
    return {"lifelines": lifelines, "ice": findings["ice"], "water": findings["water"]}


def digest(findings: dict) -> str:
    """Compact plain-text view of the findings, for the query-rewriting model."""
    lines = []
    for l in findings["lifelines"]:
        seq = ", ".join(f"{p['date'][5:]} {p['status']}" for p in l["series"])
        lines.append(f"{l['name']} ({l['type']}): {seq}; recent trend {l.get('recent_direction', 'n/a')}")
    for i in findings["ice"]:
        lines.append(f"{i['date']}: {i['pct_frozen_overall']}% of river frozen, jam_risk={i['jam_risk']}")
    for w in findings["water"]:
        lines.append(f"{w['date']}: extra water {w['extra_water_km2']} km2")
    return "\n".join(lines)


# ---------------------------------------------------------------- knowledge search (built in)
# Keyword search (BM25) over data/knowledge/*.md. Format: first line "source: <url>", a blank line,
# then paragraphs. Edits to the files are picked up automatically, with no restart.

KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "data" / "knowledge"
MIN_WORDS = 15
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set("a an and are as at be been but by can did do does for from had has have how if in into is it its "
            "of on or so than that the their then there these they this to was were what when where which "
            "who why will with would you your".split())
_SYNONYMS = {"dyke": "dike", "dykes": "dikes", "levee": "dike", "levees": "dikes",
             "embankment": "dike", "embankments": "dikes"}


def _stem(t: str) -> str:
    if len(t) > 5 and t.endswith("ing"):
        return t[:-3]
    if len(t) > 4 and t.endswith("ed"):
        return t[:-2]
    if len(t) > 4 and t.endswith("es"):
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _tokens(text: str) -> list[str]:
    return [_stem(_SYNONYMS.get(t, t)) for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class _BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b, self.n = docs, k1, b, len(docs)
        self.avgdl = sum(len(d) for d in docs) / max(self.n, 1)
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [Counter(d) for d in docs]

    def scores(self, query_tokens: list[str]) -> list[float]:
        out = [0.0] * self.n
        for t in set(query_tokens):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                f = tf.get(t, 0)
                if f:
                    norm = f + self.k1 * (1 - self.b + self.b * len(self.docs[i]) / self.avgdl)
                    out[i] += idf * f * (self.k1 + 1) / norm
        return out


_kb: dict = {"sig": None, "chunks": [], "bm25": None}


def _signature() -> tuple:
    if not KNOWLEDGE_DIR.exists():
        return ()
    return tuple((p.name, p.stat().st_mtime_ns) for p in sorted(KNOWLEDGE_DIR.glob("*.md"))
                 if not p.stem.startswith("_"))


def _load_kb() -> dict:
    sig = _signature()
    if _kb["sig"] == sig:
        return _kb
    chunks = []
    for p in sorted(KNOWLEDGE_DIR.glob("*.md")) if KNOWLEDGE_DIR.exists() else []:
        if p.stem.startswith("_"):
            continue
        blocks = [b.strip() for b in p.read_text(encoding="utf-8").split("\n\n") if b.strip()]
        if not blocks or not blocks[0].lower().startswith("source:"):
            print(f"knowledge file {p.name} skipped: the first line must start with 'source:'")
            continue
        first, *rest = blocks[0].splitlines()
        url = first.split(":", 1)[1].strip()
        paragraphs = ["\n".join(rest).strip()] if "\n".join(rest).strip() else []
        paragraphs += blocks[1:]
        for i, text in enumerate(paragraphs):
            text = " ".join(text.split())
            if len(text.split()) >= MIN_WORDS:
                chunks.append({"id": f"{p.stem}#{i}", "source": p.stem, "url": url, "text": text})
    _kb.update(sig=sig, chunks=chunks,
               bm25=_BM25([_tokens(c["text"]) for c in chunks]) if chunks else None)
    return _kb


def search_knowledge(query: str, k: int = 3, expansion: str = ""):
    """Keyword search over the knowledge files. `expansion` is extra keywords to match."""
    kb = _load_kb()
    if not kb["chunks"]:
        return {"error": "No background documents are loaded."}
    scores = kb["bm25"].scores(_tokens(f"{query} {expansion}"))
    top = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: -scores[i])[:k]
    hits = [{**{key: kb["chunks"][i][key] for key in ("id", "source", "url", "text")},
             "score": round(scores[i], 4)} for i in top]
    return hits or {"error": "Nothing relevant in the background documents."}


def dense_ready() -> bool:
    """llm.py runs an extra query-rewrite model call unless this is True.
    Set RAG_SKIP_REWRITE=1 in .env to skip that call and save tokens."""
    return os.environ.get("RAG_SKIP_REWRITE", "").strip() == "1"


def _index_stamp() -> str:
    """Part of the answer-cache key: changes when any knowledge file changes."""
    return f"kw-1|{hash(_signature())}|{len(_load_kb()['chunks'])}"


# llm.py reads inference.rag.index_stamp(); this keeps it working with no separate rag.py.
rag = types.SimpleNamespace(VERSION="kw-1", KNOWLEDGE_DIR=KNOWLEDGE_DIR, index_stamp=_index_stamp)


STATUS_RULES = ("red = 200 m or less from flood water; yellow = within 1 km (1000 m); "
                "green = farther than that. Distances are to the nearest detected water.")

# ---------------------------------------------------------------- tools (used by the ask() path)

TOOLS = [
    {"type": "function", "function": {
        "name": "get_findings",
        "description": ("Pre-computed findings across all flood dates: per-lifeline distance trend, "
                        "direction, status changes, closest approach; river-ice contrast; "
                        "water-extent change between dates."),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "search_knowledge",
        "description": ("Search sourced background documents about ice jams and the community. "
                        "Use it to explain what radar observations mean, never for measurements."),
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"], "additionalProperties": False}}},
]

RUNNERS = {
    "get_findings": lambda args: build_findings(),
    "search_knowledge": lambda args: search_knowledge(args["query"]),
}

# ---------------------------------------------------------------- prompt

NO_TOOLS_NOTE = (
    "\n\nNOTE: no tools are available for this request. In 'findings', each lifeline's series "
    "rows are [date, dist_flood_m, status], and its dist_normal_m applies to every row."
)

SYSTEM = """
You are an analyst explaining the spring 2025 Albany River ice-jam flood at Fort Albany and
Kashechewan, using RADARSAT Constellation Mission (RCM) radar results. Your readers are emergency
coordinators, pilots and community members. They already see the map, so never just restate it.
Say what the results mean for getting in and out, for safety, and for what to check next.

EVIDENCE
The user message contains an EVIDENCE JSON block with two parts: findings (precomputed trends,
status changes, ice contrast and water extent) and documents (sourced background text, or an
error if none are loaded). Use only that block. If documents holds an error, there are no sources.

METHOD
1. For why, how or what-does-this-mean questions, weigh 2 or 3 possible explanations (for example
   ice-jam backwater, meltwater or wet snow, radar noise). Look for evidence for and against each in
   the EVIDENCE. Keep the best-supported one as the claim and the runner-up as the alternative.
2. For "which is worst / what should I check first" questions, rank lifelines by latest_status first,
   then dates_red, then the latest distance. Name any lifeline whose worst moment was earlier but has
   since improved separately.
3. When you describe a trend, always give the current status and distance beside it, so "closing"
   is never shown without "still green, 1815 m away".

WHAT TO PUT IN THE ANSWER
- summary: 2 to 3 plain sentences that answer the user's actual question first. The summary may only
  restate what your claims say. If no document explains a change, say so plainly and do not name a
  cause in the summary.
- claims: 1 to 3, each telling the reader something the map does not. Rank by importance. Do not
  repeat the same point in two claims.

GROUNDING RULES (software checks these, and breaking them gets the claim thrown out)
- Numbers: use only numbers that appear in EVIDENCE. Copy them exactly as plain digits with no
  spaces or commas (1424, not 1,424 or 1 424), no rounding and no unit conversion (keep metres as
  metres). Never calculate a new number. Give the radar date next to each number.
- Evidence ids: every claim lists ids copied exactly from EVIDENCE, such as
  finding:lifeline:Kashechewan (community), finding:ice:2025-05-07 or a document id. A claim with
  no real id is not allowed.
- Causes: any claim about WHY something happened must cite at least one document id. If no document
  fits, write it as an unsourced hypothesis ("one possible explanation is..."), set confidence to
  low, and cite only finding ids.
- Never state a fact about ice, weather, flow, rainfall or a melt pulse unless a finding or a
  document says it. Do not describe events the data does not contain.
- Confidence is low, medium or high. High needs at least one finding id and one document id. Use
  "likely" or "may" for every inference.

DOCUMENTS
- Documents describe how ice jams work, or describe the community, in general. They never show that
  something happened on a particular date. Cite a document only when your claim is about that general
  mechanism or background, and word it as "ice jams can ..." Put what happened on the date in a
  separate claim that cites findings only.
- If the findings show jam_risk is false for the date, the ice-jam documents do not explain it. Say
  the available documents do not explain the change.
- When a claim cites a document id, copy under 15 words from that document into doc_quote, exactly
  as written. If you cannot quote it, do not cite the document.

SAFETY WORDING
- Radar measures distance to water. It cannot show that an airstrip, road or building is safe, open or
  usable. Never write "safe", "can land", "usable" or "access is possible". Write what radar shows,
  for example "no water was detected within 1815 m of the airstrip on 2025-05-19", and say in
  not_known that conditions on the ground must be confirmed with local officials or observers.
- status_rules in EVIDENCE explains the colours. Use its wording for thresholds and do not quote any
  other threshold.

BACKGROUND QUESTIONS
- If the question asks why a place, lifeline or the dike matters, or what a result means for people,
  explain it from the documents in EVIDENCE and cite them with doc_quote. Keep the radar facts in a
  separate claim that cites findings only. If no document fits, say the available documents do not
  cover it.

RADAR VOCABULARY
- Radar here gives distance to water and water extent. It does not measure water level, depth,
  flow, rainfall or meltwater. Do not say any of these rose or fell unless a quoted document says it.
- Radar gives area and distance, never volume. Total open water can grow when river ice melts and the
  channel becomes visible, so do not read it as flooding spreading. Use extra water for flooding
  beyond the normal river.

TRENDS
- For anything described as current, latest or now, use latest_dist_m and latest_date. Never present
  the first or the closest distance as the current one, and always give the date beside a distance.
- Describe the size of a change with the numbers. Do not call it an improvement or "lessened" unless
  the latest status is better. When recent_direction is steady, say the distance has been flat since
  the previous scan, even if the overall change from the first date looks like an improvement.
- When a status changed more than once, mention the intermediate date, not just the start and end.

LIMITS TO STATE WHEN THEY APPLY (put them in not_known)
- If a river channel is ice-covered, open water cannot be seen under ice.
- If verified is false, that lifeline's location is approximate.
- If you cite 2025-04-30, note that scene is a grainier, shifted product, so treat it with care.
- Radar shows where water was on a scan date. It cannot show depth, conditions between scans, or
  what happens next.

WHAT YOU MUST REFUSE
- Forecasts or "will it flood" questions: say radar results show past scan dates only and cannot
  predict. Return an empty claims list and describe what the scans do show.
- "Did climate change cause this?": say one event's radar results cannot show that cause. Mention
  regional context only if a document in EVIDENCE supports it, and only as background.
- Anything outside this flood and these radar results: say you can only answer about this analysis.

OUTPUT: reply with ONLY this JSON object. No markdown, no text before or after.
{
  "summary": "<2-3 plain sentences answering the question>",
  "claims": [
    {
      "claim": "<one specific inference>",
      "evidence": ["<id copied from EVIDENCE>", "<another id>"],
      "doc_quote": "<exact words copied from the cited document, under 15 words, or empty string>",
      "confidence": "low|medium|high",
      "alternative": "<next most likely explanation, or empty string>",
      "would_change_if": "<the observation that would overturn this claim>"
    }
  ],
  "not_known": ["<gap or limit that matters for this answer>"]
}
""".strip()

# ---------------------------------------------------------------- validation

_NUM = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_SAFETY = re.compile(r"\b(safe|safely|safest|can land|usable|passable|open for)\b", re.I)
SAFETY_LIMIT = ("Radar shows distance to water only. It cannot confirm that an airstrip or road is "
                "safe or usable; confirm conditions on the ground with local officials.")
_CAUSAL = re.compile(
    r"\b(because|caused|due to|driven|led to|resulting|surge|pulse|rise in|raised)\b", re.I)


def _norm(n: str) -> str:
    n = n.replace(",", "")
    return str(int(n)) if n.isdigit() else n


def _numbers(text: str) -> set[str]:
    return {_norm(n) for n in _NUM.findall(text)}


def _squash(text: str) -> str:
    return " ".join(str(text).lower().split())


def _parse_json(raw: str):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _doc_texts(evidence: str) -> dict:
    """Map document id -> text, read from the EVIDENCE JSON that infer() sent to the model."""
    try:
        docs = json.loads(evidence).get("documents")
    except Exception:
        return {}
    if not isinstance(docs, list):
        return {}
    return {d["id"]: d["text"] for d in docs
            if isinstance(d, dict) and "id" in d and "text" in d}


def finish(result: dict, question: str) -> dict:
    """Validate the model's JSON against the evidence it was given."""
    evidence = result.pop("evidence", "")
    blob = evidence + " " + question
    doc_texts = _doc_texts(evidence)
    data = _parse_json(result.get("answer", ""))
    base = {"tools_used": result.get("tools_used", []),
            "dates_cited": result.get("dates_cited", [])}
    if not isinstance(data, dict):
        return {**base, "summary": result.get("answer", "")[:2000] or "No answer.",
                "summary_warning": None, "claims": [], "dropped_claims": 0,
                "not_known": [], "verified": False, "unverified_numbers": []}

    approx = {l["id"]: l["name"] for l in build_findings()["lifelines"] if not l.get("verified")}
    kept, dropped, limits = [], 0, []

    for c in data.get("claims") or []:
        ev = [e for e in (c.get("evidence") or []) if isinstance(e, str)]
        if not ev or not all(e in blob for e in ev):
            dropped += 1
            continue
        if c.get("confidence") not in {"low", "medium", "high"}:
            c["confidence"] = "low"

        # A document id only counts if the claim quotes words that really appear in that document.
        quote = _squash(c.get("doc_quote", ""))
        doc_ids = [e for e in ev if e in doc_texts]
        supported = bool(quote) and len(quote.split()) <= 25 and any(
            quote in _squash(doc_texts[d]) for d in doc_ids)
        if doc_ids and not supported:
            ev = [e for e in ev if e not in doc_texts]
            c["note"] = "Document citation removed: the quoted words were not found in the document."
            c["confidence"] = "low"
        if not ev:
            dropped += 1
            continue
        c["evidence"] = ev
        c["grounded_in_docs"] = supported
        if not supported:
            c.pop("doc_quote", None)

        # A cause with no verified document behind it is only a hypothesis.
        if _CAUSAL.search(c.get("claim", "")) and not supported:
            c["confidence"] = "low"
            if not c["claim"].startswith("Unsourced hypothesis"):
                c["claim"] = "Unsourced hypothesis: " + c["claim"]

        if _SAFETY.search(c.get("claim", "")):
            if c["confidence"] == "high":
                c["confidence"] = "medium"
            limits.append(SAFETY_LIMIT)

        for e in ev:
            if e in approx:
                limits.append(f"{approx[e]} location is approximate (not verified).")
        if "2025-04-30" in c.get("claim", "") or any("2025-04-30" in e for e in ev):
            limits.append("The 2025-04-30 scene is grainier and was shifted to line up, "
                          "so treat it with care.")
        kept.append(c)

    model_limits = [x for x in (data.get("not_known") or [])
                    if isinstance(x, str) and not x.strip().lower().startswith("if ")]
    drop = [w for w in ("grainier", "approximate") if any(w in x for x in limits)]
    model_limits = [x for x in model_limits if not any(w in x.lower() for w in drop)]
    not_known = list(dict.fromkeys(model_limits + limits))

    summary = data.get("summary", "")
    warning = None
    if _SAFETY.search(summary):
        warning = "Radar cannot confirm that anything is safe or usable. Confirm with local officials."
        limits.append(SAFETY_LIMIT)
        not_known = list(dict.fromkeys(not_known + [SAFETY_LIMIT]))
    if kept and not warning and _CAUSAL.search(summary) and not any(c.get("grounded_in_docs") for c in kept):
        warning = ("The summary suggests a cause, but no background document supports it. "
                   "Treat it as a hypothesis.")

    shown = " ".join([summary] + [
        " ".join(str(c.get(k, "")) for k in ("claim", "alternative", "would_change_if"))
        for c in kept])
    unverified = sorted(_numbers(shown) - _numbers(blob))
    if not kept:          # a refusal has no claims to check
        unverified = []
    return {**base,
            "summary": summary,
            "summary_warning": warning,
            "claims": kept,
            "dropped_claims": dropped,
            "not_known": not_known,
            "unverified_numbers": unverified,
            "verified": dropped == 0 and not unverified and not warning}