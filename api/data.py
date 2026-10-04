"""Read processed radar results from data/real. Nothing here is hard-coded."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data" / "real"
SIMPLIFY_TOL = 0.0002

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_cache: dict[str, tuple] = {}
_lock = threading.Lock()


class DataError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def list_dates() -> dict:
    if not REAL.is_dir():
        raise DataError("data/real is missing.", 500)
    floods = sorted(
        p.name for p in REAL.iterdir() if p.is_dir() and (p / "stats.json").is_file()
    )
    normals = sorted(REAL.glob("normal_*_water.geojson"))
    if not normals:
        raise DataError("Normal baseline scene is missing from data/real.", 500)
    if not floods:
        raise DataError("No flood dates found in data/real.", 500)
    normal = normals[0].name.split("_")[1]
    return {"flood_dates": floods, "normal_date": normal}


def revision() -> str:
    """Changes when a JSON result is regenerated, so phrased answers can drop."""
    latest = 0
    if REAL.is_dir():
        for path in REAL.rglob("*.json"):
            latest = max(latest, path.stat().st_mtime_ns)
    return f"{REAL}:{latest}"   # folder too, so switching projects never reuses old answers


def normalize_date(raw: str) -> str:
    """Accept 'Apr 30', 'april 30', '2025-04-30', 'Apr 30 2025' and return YYYY-MM-DD."""
    info = list_dates()
    known = list(info["flood_dates"]) + [info["normal_date"]]
    text = raw.strip().lower().replace(",", " ")
    text = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()

    iso = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if iso:
        candidate = f"{int(iso.group(1)):04d}-{int(iso.group(2)):02d}-{int(iso.group(3)):02d}"
        if candidate in known:
            return candidate
        _unknown(raw, info)

    year = None
    month = None
    day = None
    named = re.fullmatch(r"([a-z]+)\s+(\d{1,2})(?:\s+(\d{4}))?", text)
    dmy = re.fullmatch(r"(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?", text)
    if named and named.group(1) in _MONTHS:
        month = _MONTHS[named.group(1)]
        day = int(named.group(2))
        year = int(named.group(3)) if named.group(3) else None
    elif dmy and dmy.group(2) in _MONTHS:
        day = int(dmy.group(1))
        month = _MONTHS[dmy.group(2)]
        year = int(dmy.group(3)) if dmy.group(3) else None
    else:
        _unknown(raw, info)

    matches = []
    for iso_date in known:
        y, m, d = (int(part) for part in iso_date.split("-"))
        if m == month and d == day and (year is None or y == year):
            matches.append(iso_date)
    if len(matches) == 1:
        return matches[0]
    _unknown(raw, info)


def resolve_flood_date(raw: str) -> str:
    info = list_dates()
    iso = normalize_date(raw)
    if iso == info["normal_date"]:
        raise DataError(
            f"{iso} is the normal baseline, not a flood date. "
            f"Valid flood dates: {', '.join(info['flood_dates'])}."
        )
    if iso not in info["flood_dates"]:
        _unknown(raw, info)
    return iso


def get_stats(date: str) -> dict:
    iso = resolve_flood_date(date)
    return _read_json(REAL / iso / "stats.json")


def get_lifelines(date: str) -> list:
    iso = resolve_flood_date(date)
    return _read_json(REAL / iso / "lifelines_status.json")


def get_ice(date: str):
    iso = resolve_flood_date(date)
    path = REAL / iso / "ice_stats.json"
    if not path.is_file():
        return None
    return _read_json(path)


def get_alert(date: str):
    iso = resolve_flood_date(date)
    path = REAL / iso / "alert.json"
    if not path.is_file():
        return None
    return _read_json(path)


def compare(date_a: str, date_b: str) -> dict:
    a = resolve_flood_date(date_a)
    b = resolve_flood_date(date_b)
    stats_a, stats_b = get_stats(a), get_stats(b)
    lines_a = {item["id"]: item for item in get_lifelines(a)}
    lines_b = {item["id"]: item for item in get_lifelines(b)}
    ice_a, ice_b = get_ice(a), get_ice(b)

    lifelines = []
    for key, left in lines_a.items():
        right = lines_b.get(key)
        if right is None:
            continue
        dist_a = left.get("dist_flood_m")
        dist_b = right.get("dist_flood_m")
        lifelines.append({
            "id": key,
            "name": left["name"],
            "type": left["type"],
            "verified": left.get("verified", False),
            "dist_normal_m": left.get("dist_normal_m"),
            "dist_flood_m": {"date_a": dist_a, "date_b": dist_b},
            "change_m": None if dist_a is None or dist_b is None else dist_b - dist_a,
            "status": {"date_a": left.get("status"), "date_b": right.get("status")},
        })

    ice = None
    if ice_a and ice_b:
        ice = {
            "pct_frozen_overall": {
                "date_a": ice_a.get("pct_frozen_overall"),
                "date_b": ice_b.get("pct_frozen_overall"),
            },
            "upstream_pct_frozen": {
                "date_a": ice_a.get("upstream_pct_frozen"),
                "date_b": ice_b.get("upstream_pct_frozen"),
            },
            "near_towns_pct_frozen": {
                "date_a": _town_pct(ice_a),
                "date_b": _town_pct(ice_b),
            },
            "jam_risk": {"date_a": ice_a.get("jam_risk"), "date_b": ice_b.get("jam_risk")},
            "jam_towns": {"date_a": ice_a.get("jam_towns") or [], "date_b": ice_b.get("jam_towns") or []},
        }

    return {
        "date_a": a,
        "date_b": b,
        "normal_date": stats_a.get("normal_date"),
        "extra_water_km2": {
            "date_a": stats_a.get("extra_water_km2"),
            "date_b": stats_b.get("extra_water_km2"),
            "change_b_minus_a": _subtract(stats_b.get("extra_water_km2"), stats_a.get("extra_water_km2")),
        },
        "flood_water_km2": {
            "date_a": stats_a.get("flood_water_km2"),
            "date_b": stats_b.get("flood_water_km2"),
        },
        "lifelines": lifelines,
        "ice": ice,
    }


def get_layer(name: str, date: str | None = None) -> dict:
    path = _layer_path(name, date)
    if not path.is_file():
        raise DataError(f"Layer file is missing: {path.name}", 404)
    mtime = path.stat().st_mtime_ns
    key = f"layer:{path}:{mtime}:{SIMPLIFY_TOL}"
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            return hit[0]
    with path.open() as handle:
        collection = json.load(handle)
    simplified = _simplify(collection, SIMPLIFY_TOL)
    with _lock:
        _cache[key] = (simplified,)
    return simplified


def _layer_path(name: str, date: str | None) -> Path:
    if name == "normal":
        matches = sorted(REAL.glob("normal_*_water.geojson"))
        if not matches:
            raise DataError("Normal water layer is missing.", 404)
        return matches[0]
    if name not in {"extra", "ice", "water"}:
        raise DataError(f"Unknown layer '{name}'. Use normal, extra, ice, or water.")
    if not date:
        raise DataError(f"Layer '{name}' needs a flood date.")
    iso = resolve_flood_date(date)
    if name == "extra":
        return REAL / iso / "flood_extra.geojson"
    if name == "ice":
        return REAL / iso / "river_ice.geojson"
    return REAL / f"flood_{iso}_water.geojson"


def _read_json(path: Path):
    if not path.is_file():
        raise DataError(f"Missing data file: {path.name}", 404)
    mtime = path.stat().st_mtime_ns
    key = f"json:{path}"
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    with path.open() as handle:
        data = json.load(handle)
    with _lock:
        _cache[key] = (mtime, data)
    return data


def _simplify(collection: dict, tolerance: float) -> dict:
    features = []
    for feature in collection.get("features") or []:
        geometry = feature.get("geometry")
        if not geometry:
            continue
        simplified = shape(geometry).simplify(tolerance, preserve_topology=True)
        if simplified.is_empty:
            continue
        features.append({
            "type": "Feature",
            "properties": feature.get("properties") or {},
            "geometry": mapping(simplified),
        })
    return {"type": "FeatureCollection", "features": features}


def _town_pct(ice: dict) -> dict:
    out = {}
    for name, value in (ice.get("near_towns") or {}).items():
        out[name] = None if not isinstance(value, dict) else value.get("pct_frozen")
    return out


def _subtract(right, left):
    if right is None or left is None:
        return None
    return round(right - left, 2)


def _unknown(raw: str, info: dict):
    raise DataError(
        f"Unknown date '{raw}'. Valid flood dates: {', '.join(info['flood_dates'])}. "
        f"Normal baseline: {info['normal_date']}."
    )
