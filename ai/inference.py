"""Inference layer for the flood assistant.

What this adds on top of plain lookup tools:
  1. build_findings(): code precomputes trends, status changes, ice contrast, water jumps.
     The model reasons over these instead of raw numbers, and never does the maths.
  2. search_knowledge(): small RAG over sourced background docs in data/knowledge/*.md
     (ice-jam science, community dependence on lifelines, guidance, regional context).
  3. SYSTEM: forces hypothesis testing (2-3 explanations, evidence for/against, one verdict).
  4. finish(): rejects any claim whose evidence ids were not actually returned by a tool
     in this request, and flags numbers that appear in no tool result.

This file does NOT import api.ai, so there is no circular import.
Wire-up instructions are at the bottom of this file.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from api.data import DataError, get_ice, get_lifelines, get_stats, list_dates, revision

RED_M = 200    # matches template_report: red is 200 m or less
FLAT_M = 25    # change smaller than this counts as "steady"
KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "data" / "knowledge"

# ---------------------------------------------------------------- findings

_findings_cache: dict = {}


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def build_findings() -> dict:
    """Small, pre-digested claims computed in code. Every item has a stable `id`."""
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
            if f["direction"] == "closing" and days > 0:
                rate = -change / days
                f["rate_m_per_day"] = round(rate, 1)
                if last["dist_flood_m"] > RED_M:
                    f["days_to_red_if_unchanged"] = round((last["dist_flood_m"] - RED_M) / rate, 1)
                    f["extrapolation_note"] = ("straight-line continuation of the observed "
                                               "trend, not a forecast")
        lifelines.append(f)

    out = {"lifelines": lifelines, "ice": ice_rows, "water": water}
    _findings_cache.clear()
    _findings_cache[key] = out
    return out

NO_TOOLS_NOTE = (
    "to call tools. In 'findings', each lifeline's series rows are [date, dist_flood_m, status], "
    "and its dist_normal_m applies to every row."
)


def slim(findings: dict) -> dict:
    """Same facts as build_findings, in fewer tokens."""
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


# ---------------------------------------------------------------- knowledge (RAG)

_chunks: list[dict] = []
_vec = _mat = None


def _load_knowledge() -> None:
    global _vec, _mat
    if _vec is not None or not KNOWLEDGE_DIR.exists():
        return
    for p in sorted(KNOWLEDGE_DIR.glob("*.md")):
        if p.stem.startswith("_"):
            continue
        blocks = p.read_text(encoding="utf-8").split("\n\n")
        url = blocks[0].splitlines()[0].replace("source:", "").strip() if blocks else ""
        for i, para in enumerate(blocks[1:]):
            if len(para.split()) > 20:
                _chunks.append({"id": f"{p.stem}#{i}", "source": p.stem, "url": url,
                                "text": para.strip()})
    if _chunks:
        from sklearn.feature_extraction.text import TfidfVectorizer
        _vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        _mat = _vec.fit_transform([c["text"] for c in _chunks])


def search_knowledge(query: str, k: int = 3):
    _load_knowledge()
    if not _chunks:
        return {"error": "No background documents are loaded."}
    from sklearn.metrics.pairwise import cosine_similarity
    sims = cosine_similarity(_vec.transform([query]), _mat)[0]
    top = sims.argsort()[::-1][:k]
    hits = [{**_chunks[i], "score": round(float(sims[i]), 2)} for i in top if sims[i] > 0.05]
    return hits or {"error": "Nothing relevant in the background documents."}


# ---------------------------------------------------------------- tools + prompt

TOOLS = [
    {"type": "function", "function": {
        "name": "get_findings",
        "description": ("Pre-computed findings across all flood dates: per-lifeline distance trend, "
                        "direction, rate, status changes, closest approach; river-ice contrast "
                        "(frozen near towns vs upstream); water-extent jumps between dates. "
                        "Start here for any 'why', 'which', or 'what changed' question."),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "search_knowledge",
        "description": ("Search sourced background documents (ice-jam science, community reliance on "
                        "airstrips and roads, flood guidance, regional climate context). Use it to "
                        "explain what radar observations MEAN. Never a source of radar measurements."),
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"], "additionalProperties": False}}},
]

RUNNERS = {
    "get_findings": lambda args: build_findings(),
    "search_knowledge": lambda args: search_knowledge(args["query"]),
}


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
2. For "which is worst / what should I check first" questions, rank lifelines by status first, then
   distance, then recent_direction, and say why.
3. When you describe a trend, always give the current status and distance beside it, so "closing"
   is never shown without "still green, 1815 m away".

WHAT TO PUT IN THE ANSWER
- summary: 2 to 3 plain sentences that answer the user's actual question first.
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

DOCUMENTS
- Documents describe how ice jams work in general. They never show that something happened on a
  particular date. Cite a document only when your claim is about that general mechanism, and word it
  as "ice jams can ..." Put what happened on the date in a separate claim that cites findings only.
- If the findings show jam_risk is false for the date, the ice-jam documents do not explain it. Say
  the available documents do not explain the change.
- When a claim cites a document id, copy under 15 words from that document into doc_quote, exactly
  as written. If you cannot quote it, do not cite the document.

RADAR VOCABULARY
- Radar here gives distance to water and water extent. It does not measure water level, depth,
  flow, rainfall or meltwater. Do not say any of these rose or fell unless a quoted document says it.

SUMMARY
- The summary may only restate what your claims say. No new causes.

RANKING AND TRENDS
- For "which is worst / most trouble", rank by latest_status first, then dates_red, then the latest
  distance. Name any lifeline whose worst moment was earlier but has since improved separately.
- Radar gives area and distance, never volume. total open water (flood_water_km2) can grow when river
  ice melts and the channel becomes visible, so do not read it as flooding spreading. Use extra water
  for flooding beyond the normal river.
- Describe the size of a change with the numbers. Do not call it an improvement or "lessened" unless
  the latest status is better; if recent_direction is steady, say it has been flat.
- When a status changed more than once, mention the intermediate date, not just the start and end.
- When a lifeline's recent_direction is steady, say its distance has been flat since the previous
  scan, even if its overall change from the first date looks like an improvement.

OUTPUT: reply with ONLY this JSON object. No markdown, no text before or after.
{
  "summary": "<2-3 plain sentences answering the question>",
  "claims": [
    {
      "claim": "<one specific inference>",
      "evidence": ["<id copied from EVIDENCE>", "<another id>"],
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


def _norm(n: str) -> str:
    n = n.replace(",", "")
    return str(int(n)) if n.isdigit() else n


def _numbers(text: str) -> set[str]:
    return {_norm(n) for n in _NUM.findall(text)}


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


# Replace the existing finish() in ai/inference.py with everything in this file.
# (Keep _NUM, _norm, _numbers and _parse_json as they are.)


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


def _squash(text: str) -> str:
    return " ".join(str(text).lower().split())


_CAUSAL = re.compile(
    r"\b(because|caused|due to|driven|led to|resulting|surge|pulse|rise in|raised|"
    r"indicat\w*|reflect\w*|suggest\w*|backing)\b", re.I)


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
                "claims": [], "dropped_claims": 0, "not_known": [], "verified": False,
                "unverified_numbers": []}

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
        c.pop("doc_quote", None) if not supported else None

        # A cause with no verified document behind it is only a hypothesis.
        if _CAUSAL.search(c.get("claim", "")) and not supported:
            c["confidence"] = "low"
            if not c["claim"].startswith("Unsourced hypothesis"):
                c["claim"] = "Unsourced hypothesis: " + c["claim"]

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

    shown = " ".join([data.get("summary", "")] + [
        " ".join(str(c.get(k, "")) for k in ("claim", "alternative", "would_change_if"))
        for c in kept])
    unverified = sorted(_numbers(shown) - _numbers(blob))
    if not kept:          # a refusal has no claims to check
        unverified = []
    return {**base,
            "summary": data.get("summary", ""),
            "claims": kept,
            "dropped_claims": dropped,
            "not_known": not_known,
            "unverified_numbers": unverified,
            "verified": dropped == 0 and not unverified}


# ---------------------------------------------------------------- wire-up (edit your ai module)
#
# 1) Near the top of your ai module:
#        from api import inference
#        _RUNNERS.update(inference.RUNNERS)
#
# 2) In _tool_loop, keep a copy of every tool result so claims can be checked:
#        evidence: list[str] = []                       # next to tools_used
#        ...
#        thread.append({... "content": json.dumps(result)})
#        evidence.append(json.dumps(result))            # add right after that append
#    and add  "evidence": "\n".join(evidence)  to BOTH returned dicts in _tool_loop.
#    Also raise `rounds = 5 if tools else 1` to 6 so hypothesis testing has room.
#
# 3) Add this function to the ai module and expose it as POST /api/infer:
#        def infer(question: str, history: list[dict] | None = None) -> dict:
#            if not os.environ.get("GROQ_API_KEY"):
#                return {"summary": "AI not configured.", "claims": [], "verified": False}
#            result = _complete_with_fallback(
#                inference.SYSTEM,
#                _history_messages(history or []) + [{"role": "user", "content": question.strip()}],
#                tools=TOOLS + inference.TOOLS,
#                max_tokens=1500,
#            )
#            return inference.finish(result, question)
#
# 4) Put sourced documents in data/knowledge/*.md. First line: "source: <url>", then a blank
#    line, then paragraphs of 20+ words. Files starting with "_" are ignored.
#    Needs: pip install scikit-learn