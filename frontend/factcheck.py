"""
Plain-code fact check for Guide answers. No AI.

Every number in an answer is looked up in the radar result files in data/real.
A number passes when it matches a value in a file (after normal rounding and
km/m conversion), a method setting such as the 200 m red cutoff, or a simple
difference between two file values (for example 374 m - 63 m = 311 m closer).
Dates and years are skipped. Anything else is flagged.
"""
import glob
import json
import os
import re
from datetime import datetime
from itertools import combinations

MONTHS = ("january february march april may june july august september october november december "
          "jan feb mar apr jun jul aug sep sept oct nov dec")
MONTH = r"(?:" + "|".join(sorted(MONTHS.split(), key=len, reverse=True)) + r")\.?"
DATE_SPANS = [
    re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),
    re.compile(rf"\b{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b", re.I),
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH}(?:,?\s+\d{{4}})?\b", re.I),
    re.compile(r"\b(?:19|20)\d{2}\b"),
]
NUMBER = re.compile(r"(?<![\w.])[-−]?\d+(?:,\d{3})*(?:\.\d+)?")
RANGE_GAP = re.compile(r"^\s*(?:–|—|-|to|and)\s*$", re.I)
UNITS = [
    ("km2", re.compile(r"^\s*(?:km²|km2|km\^2|sq\.?\s*km|square\s+kilomet)", re.I)),
    ("pct", re.compile(r"^\s*(?:%|percent\b|per\s+cent\b)", re.I)),
    ("km", re.compile(r"^\s*(?:km\b|kilomet)", re.I)),
    ("m", re.compile(r"^\s*(?:m\b|metres?\b|meters?\b)", re.I)),
]

# Settings used by the pipeline, not measurements.
SETTINGS = [
    (200, "m", "Red cutoff: within 200 m of water", "pipeline/analyze.py"),
    (1000, "m", "Yellow cutoff: within 1 km of water", "pipeline/analyze.py"),
    (5000, "m", "Ice zone around each town (5 km)", "ice_stats.json rule"),
    (15000, "m", "Upstream starts 15 km from a town", "ice_stats.json rule"),
    (70, "pct", "Ice-jam rule: near-town river at least 70% frozen", "ice_stats.json rule"),
    (40, "pct", "Ice-jam rule: upstream at most 40% frozen", "ice_stats.json rule"),
    (20, "m", "Radar pixel size (20 m)", "README.md"),
    (40, "m", "April 30 scene shifted about 40 m", "README.md"),
    (12.5, "m", "April 30 scene resolution (12.5 m)", "README.md"),
]


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _short(iso):
    dt = datetime.strptime(iso, "%Y-%m-%d")
    return f"{dt:%b} {dt.day}"


def _town(name):
    return name.split(" (")[0]


def build_facts(real_dir):
    """Every number in the radar result files, with where it came from."""
    facts = []
    series = {}

    def add(value, kind, label, path, key=None):
        if value is None or isinstance(value, bool):
            return
        rel = os.path.relpath(path, os.path.dirname(real_dir.rstrip("\\/"))).replace("\\", "/")
        rel = "data/" + rel if not rel.startswith("data/") else rel
        facts.append({"value": float(value), "kind": kind, "label": label, "source": rel, "how": "file"})
        if key:
            series.setdefault(key, []).append((float(value), label))

    normal = None
    count_lifelines = set()
    flood_dates = []
    for stats_path in sorted(glob.glob(os.path.join(real_dir, "*", "stats.json"))):
        folder = os.path.dirname(stats_path)
        date = os.path.basename(folder)
        when = _short(date)
        flood_dates.append(date)
        stats = _load(stats_path) or {}
        normal = stats.get("normal_date") or normal
        add(stats.get("extra_water_km2"), "km2", f"Extra water, {when}", stats_path, "extra")
        add(stats.get("extra_water_incl_coast_km2"), "km2", f"Extra water incl. coast, {when}", stats_path, "extra_coast")
        add(stats.get("flood_water_km2"), "km2", f"Open water, {when}", stats_path, "open")
        add(stats.get("normal_water_km2"), "km2", "Normal river water (Aug 7)", stats_path)
        for field, word in (("lifelines_red", "red"), ("lifelines_yellow", "yellow"), ("lifelines_no_data", "not assessed")):
            add(stats.get(field), "count", f"Lifelines {word}, {when}", stats_path)

        lines_path = os.path.join(folder, "lifelines_status.json")
        for line in _load(lines_path) or []:
            name = line.get("name", "Lifeline")
            count_lifelines.add(name)
            add(line.get("dist_flood_m"), "m", f"{name}: distance to water, {when}", lines_path, f"dist:{name}")
            add(line.get("dist_open_water_m"), "m", f"{name}: distance to open water, {when}", lines_path)
            add(line.get("dist_normal_m"), "m", f"{name}: normal distance (Aug 7)", lines_path)
            closer = line.get("closer_by_m")
            if closer:
                add(abs(closer), "m", f"{name}: change from normal, {when}", lines_path)

        ice_path = os.path.join(folder, "ice_stats.json")
        ice = _load(ice_path)
        if ice:
            add(ice.get("pct_frozen_overall"), "pct", f"River frozen overall, {when}", ice_path, "ice:overall")
            add(ice.get("upstream_pct_frozen"), "pct", f"Frozen upstream, {when}", ice_path, "ice:upstream")
            add(ice.get("river_km2_seen"), "km2", f"River area checked for ice, {when}", ice_path)
            for town, val in (ice.get("near_towns") or {}).items():
                if isinstance(val, dict):
                    add(val.get("pct_frozen"), "pct", f"{_town(town)}: frozen within 5 km, {when}", ice_path, f"ice:{town}")
                    add(val.get("river_km2_seen"), "km2", f"{_town(town)}: river area checked, {when}", ice_path)

    # The normal day is compared with itself, so its extra water is zero.
    facts.append({"value": 0.0, "kind": "km2", "label": "Extra water on the normal day (Aug 7)",
                  "source": "baseline definition", "how": "setting"})
    if count_lifelines:
        facts.append({"value": float(len(count_lifelines)), "kind": "count", "label": "Lifelines tracked",
                      "source": "data/lifelines.json", "how": "file"})
    if flood_dates:
        facts.append({"value": float(len(flood_dates)), "kind": "count", "label": "Flood dates", "source": "data/real", "how": "file"})
        facts.append({"value": float(len(flood_dates) + 1), "kind": "count", "label": "Radar dates incl. normal day",
                      "source": "data/real", "how": "file"})

    for value, kind, label, source in SETTINGS:
        facts.append({"value": float(value), "kind": kind, "label": label, "source": source, "how": "setting"})

    derived = []
    for key, items in series.items():
        for (a, la), (b, lb) in combinations(items, 2):
            diff = abs(a - b)
            if diff > 0:
                kind = "km2" if key in ("extra", "extra_coast", "open") else "pct" if key.startswith("ice:") else "m"
                derived.append({"value": diff, "kind": kind, "label": f"Difference: {la} vs {lb}",
                                "source": "calculated from the files", "how": "calculated"})
    normal_km = next((f["value"] for f in facts if f["label"] == "Normal river water (Aug 7)"), None)
    if normal_km is not None:
        for value, label in series.get("open", []):
            derived.append({"value": abs(normal_km - value), "kind": "km2",
                            "label": f"Difference: {label} vs normal river", "source": "calculated from the files",
                            "how": "calculated"})
    return facts, derived


PLAIN = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2212": "-",
                       "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u2007": " "})


def _mask_dates(text):
    text = text.translate(PLAIN)
    chars = list(text)
    for pattern in DATE_SPANS:
        for match in pattern.finditer(text):
            for i in range(match.start(), match.end()):
                chars[i] = " "
    return "".join(chars)


MONTH_NUM = {name[:3]: i + 1 for i, name in enumerate(
    "january february march april may june july august september october november december".split())}
MONTH_NUM["sep"] = 9


def _date_marks(text):
    """(position, 'Apr 30') for every date written in the text."""
    text = text.translate(PLAIN)
    marks = []
    for match in re.finditer(r"\b\d{4}-(\d{1,2})-(\d{1,2})\b", text):
        month, day = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            marks.append((match.start(), month, day))
    for match in re.finditer(rf"\b({MONTH})\s+(\d{{1,2}})\b", text, re.I):
        month = MONTH_NUM.get(match.group(1).lower().rstrip(".")[:3])
        if month:
            marks.append((match.start(), month, int(match.group(2))))
    for match in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTH})", text, re.I):
        month = MONTH_NUM.get(match.group(2).lower().rstrip(".")[:3])
        if month:
            marks.append((match.start(), month, int(match.group(1))))
    names = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return sorted((pos, f"{names[month - 1]} {day}") for pos, month, day in marks)


def _date_before(marks, position):
    current = None
    for pos, label in marks:
        if pos >= position:
            break
        current = label
    return current


def _unit_after(text, end):
    tail = text[end:end + 24]
    for kind, pattern in UNITS:
        if pattern.match(tail):
            return kind
    return None


def extract_numbers(text):
    """Numbers with their position and unit. Dates and years are left out."""
    masked = _mask_dates(text)
    found = []
    for match in NUMBER.finditer(masked):
        raw = match.group(0)
        clean = raw.replace(",", "").replace("−", "-")
        try:
            value = abs(float(clean))
        except ValueError:
            continue
        decimals = len(clean.split(".")[1]) if "." in clean else 0
        found.append({"start": match.start(), "end": match.end(), "raw": raw, "value": value,
                      "decimals": decimals, "unit": _unit_after(masked, match.end())})
    for i in range(len(found) - 1, -1, -1):
        item = found[i]
        if item["unit"] is None and i + 1 < len(found):
            nxt = found[i + 1]
            if nxt["unit"] and RANGE_GAP.match(masked[item["end"]:nxt["start"]]):
                item["unit"] = nxt["unit"]
    return found


def _tolerance(kind, value, decimals):
    step = 0.5 * 10 ** (-decimals)
    if kind == "km2":
        return max(0.05, step) + 1e-9
    if kind == "pct":
        return max(0.5, step) + 1e-9
    if kind == "m":
        if decimals:
            return step + 1e-9
        return max(5.0, 0.05 * value) if value % 10 == 0 else 1.0
    return 1e-9


STOP = {"the", "and", "was", "were", "from", "with", "this", "that", "for", "near", "water", "distance"}


def _words(text):
    return {word[:3] for word in re.findall(r"[a-z]+", text.lower()) if len(word) >= 3 and word not in STOP}


def _best(value, kind, tol, pool, context, when=None):
    best = None
    for fact in pool:
        if fact["kind"] != kind:
            continue
        diff = abs(fact["value"] - value)
        if diff > tol:
            continue
        overlap = len(context & _words(fact["label"]))
        same_day = 1 if when and re.search(rf"\b{re.escape(when)}\b", fact["label"]) else 0
        rank = (round(diff, 6), -same_day, -overlap, 0 if fact["how"] == "setting" else 1)
        if best is None or rank < best[0]:
            best = (rank, fact)
    return best[1] if best else None


def _lookup(item, facts, derived):
    value, unit, decimals = item["value"], item["unit"], item["decimals"]
    context = item.get("context", set())
    when = item.get("when")
    tries = []
    if unit == "km":
        metres = value * 1000
        tries.append(("m", metres, max(0.5 * 10 ** (-decimals) * 1000, 0.05 * metres)))
        tries.append(("km2", value, _tolerance("km2", value, decimals)))
    elif unit in ("km2", "pct", "m"):
        tries.append((unit, value, _tolerance(unit, value, decimals)))
    else:
        if decimals == 0 and value <= 12:
            tries.append(("count", value, 1e-9))
        strict = 0.5 * 10 ** (-decimals) + 1e-9
        for kind in ("km2", "pct", "m"):
            tries.append((kind, value, strict))
    for kind, val, tol in tries:
        hit = _best(val, kind, tol, facts, context, when)
        if hit:
            return hit
    for kind, val, tol in tries:
        hit = _best(val, kind, tol, derived, context, when)
        if hit:
            return hit
    return None


def _fmt(value, kind):
    if kind == "km2":
        return f"{value:g} km²"
    if kind == "pct":
        return f"{value:g}%"
    if kind == "m":
        return f"{value:g} m"
    return f"{value:g}"


def check_answer(text, facts, derived):
    """Returns {'status': 'verified'|'flagged'|'none', 'items': [...]} for one answer."""
    items = []
    text = text or ""
    marks = _date_marks(text)
    for item in extract_numbers(text):
        item["when"] = _date_before(marks, item["start"])
        sentence_start = max(text.rfind(".", 0, item["start"]), text.rfind("\n", 0, item["start"])) + 1
        window = text[max(sentence_start, item["start"] - 70):item["end"] + 40]
        item["context"] = _words(window)
        if item["unit"] is None and item["decimals"] == 0 and item["value"] <= 12:
            hit = _lookup(item, facts, derived)
            if not hit:
                continue
        else:
            hit = _lookup(item, facts, derived)
        said = item["raw"] + ({"km2": " km²", "pct": "%", "km": " km", "m": " m"}.get(item["unit"], ""))
        items.append({
            "start": item["start"], "end": item["end"], "said": said,
            "ok": hit is not None,
            "how": hit["how"] if hit else "missing",
            "label": hit["label"] if hit else "Not found in the radar files",
            "file_value": _fmt(hit["value"], hit["kind"]) if hit else "",
            "source": hit["source"] if hit else "",
        })
    if not items:
        return {"status": "none", "items": []}
    status = "verified" if all(entry["ok"] for entry in items) else "flagged"
    return {"status": status, "items": items}
