"""
Cut Off - find and download RCM radar for any place, straight from the public archive.

Uses the same source as get_ard_baseline.py: RCM Analysis-Ready Data (ARD) on AWS, searched through the
EODMS STAC catalogue. No account, no ordering. Only the box you ask for is downloaded, so files stay small.
The free archive starts in 2025.

    from pipeline.archive import search, download, geocode
    scenes = search((-97.85, 51.15, -97.25, 51.50), "2026-04-15", "2026-05-10")
    download(scenes[0], (-97.85, 51.15, -97.25, 51.50), "data/projects/x/inputs/2026-04-24.tif")

Offline demo mode: set CUTOFF_FAKE_ARCHIVE=<folder> and search() returns the *_YYYY-MM-DD_rr.tif files in
that folder instead of asking the internet (used for testing the app without a connection).
"""
import glob
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime

os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds
from shapely.geometry import box, shape

CATALOG = "https://www.eodms-sgdot.nrcan-rncan.gc.ca/search/"
COLLECTION = "rcm-ard"
# Which band to keep, in order. rr = compact-pol "water looks dark" band the pipeline is tuned for.
BAND_ORDER = ["rr", "hv", "vh", "hh", "vv", "rl"]
MAX_BOX_DEG = 1.6          # keeps a download to a few tens of MB and the grid under ~4000 px


def box_around(lat, lon, size_km):
    """A square box (west, south, east, north) of size_km centred on a point."""
    half_lat = size_km / 2 / 111.0
    half_lon = size_km / 2 / (111.0 * max(np.cos(np.radians(lat)), 0.05))
    return (round(lon - half_lon, 4), round(lat - half_lat, 4), round(lon + half_lon, 4), round(lat + half_lat, 4))


def check_box(bbox):
    w, s, e, n = bbox
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("The box should be west, south, east, north, with west < east and south < north.")
    if e - w > MAX_BOX_DEG or n - s > MAX_BOX_DEG:
        raise ValueError(f"That area is too big. Keep it under about {MAX_BOX_DEG}° (roughly 100 km) on each side.")


def geocode(text):
    """Place name -> (lat, lon, label) using OpenStreetMap. Returns None if nothing is found."""
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": text, "format": "json", "limit": 1, "countrycodes": "ca"})
    req = urllib.request.Request(url, headers={"User-Agent": "CutOff-hackathon/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        hits = json.load(r)
    if not hits:
        return None
    h = hits[0]
    return float(h["lat"]), float(h["lon"]), h.get("display_name", text)


def _band(assets):
    """Pick the radar band to use from an item's assets: {key: href}."""
    keys = {k.lower(): k for k, href in assets.items() if href.lower().endswith(".tif")}
    for want in BAND_ORDER:
        for low, k in keys.items():
            if low == want or low.endswith("_" + want) or low.endswith("-" + want):
                return want, assets[k]
    return None, None


def search(bbox, start, end, limit=200):
    """Scenes over the box between two dates (YYYY-MM-DD), oldest first.
    Each scene: {id, when, date, orbit, coverage, band, href, footprint}."""
    check_box(bbox)
    fake = os.environ.get("CUTOFF_FAKE_ARCHIVE")
    if fake:
        return _fake_search(fake, bbox, start, end)
    from pystac_client import Client
    cat = Client.open(CATALOG)
    items = cat.search(collections=[COLLECTION], bbox=list(bbox), datetime=f"{start}/{end}",
                       limit=limit, method="GET").items()
    aoi = box(*bbox)
    out = []
    for it in items:
        band, href = _band({k: a.href for k, a in it.assets.items()})
        if not href:
            continue
        geom = shape(it.geometry)
        when = it.datetime or datetime.fromisoformat(it.properties["start_datetime"].replace("Z", "+00:00"))
        out.append({
            "id": it.id, "when": when.strftime("%Y-%m-%d %H:%M"), "date": when.strftime("%Y-%m-%d"),
            "orbit": str(it.properties.get("sat:orbit_state", "")).lower(),
            "coverage": round(100 * geom.intersection(aoi).area / aoi.area, 1),
            "band": band, "href": href,
        })
    return sorted(out, key=lambda s: s["when"])


def download(scene, bbox, out_path):
    """Crop the scene's radar band to the box and save it as a GeoTIFF. Returns the share of the box with data."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with rasterio.open(scene["href"]) as src:
        b = transform_bounds("EPSG:4326", src.crs, *bbox)
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        data = src.read(1, window=win, boundless=True, fill_value=0)
        prof = src.profile.copy()
        prof.update(width=data.shape[1], height=data.shape[0], count=1,
                    transform=src.window_transform(win), driver="GTiff", compress="deflate")
        for k in ("blockxsize", "blockysize", "tiled"):
            prof.pop(k, None)
        with rasterio.open(out_path, "w", **prof) as dst:
            dst.write(data, 1)
            dst.update_tags(TIFFTAG_DATETIME=scene["when"].replace("-", ":") + ":00", SCENE_ID=scene["id"])
    valid = np.isfinite(data) & (data > 0)
    return float(valid.mean())


def _fake_search(folder, bbox, start, end):
    aoi = box(*bbox)
    out = []
    for path in sorted(glob.glob(os.path.join(folder, "*.tif"))):
        m = re.search(r"(20\d\d-\d\d-\d\d)", os.path.basename(path))
        if not m or not (start <= m[1] <= end):
            continue
        with rasterio.open(path) as src:
            fp = box(*transform_bounds(src.crs, "EPSG:4326", *src.bounds))
        cov = round(100 * fp.intersection(aoi).area / aoi.area, 1)
        if cov <= 0:
            continue
        out.append({"id": os.path.basename(path), "when": m[1] + " 23:30", "date": m[1], "orbit": "ascending",
                    "coverage": cov, "band": "rr", "href": path})
    return out
