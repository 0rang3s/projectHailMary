"""
Cut Off - run any project (uploaded radar images) end to end.

A project lives in data/projects/<slug>/ and has the same layout as data/real/, so the dashboard can open it:

  project.json                    settings + status (written by the landing page, filled in here)
  inputs/<date>.tif               one radar file per date (ARD rr.tif, or GRD HV/HH.tif)
  lifelines.json                  optional points to watch [{id, name, type, lat, lon, verified}]
  normal_<date>_water.geojson / _mask.tif / _db.tif
  flood_<date>_water.geojson  / _mask.tif / _db.tif
  <date>/ ice_stats.json river_ice.geojson flood_extra.geojson lifelines_status.json stats.json alert.json

project.json (minimum):
  {"name": "...", "images": [{"date": "2025-08-07", "role": "normal", "file": "inputs/2025-08-07.tif"},
                             {"date": "2025-05-07", "role": "flood",  "file": "inputs/2025-05-07.tif"}]}
Everything else (kind, area, projection, resolution, cutoffs, alignment) is worked out here and written back,
so it can be edited and rerun. Per-image overrides: threshold_db, shift_px, ice_threshold_db, ice_median.
Project-level overrides: aoi_lonlat [w, s, e, n], crs, res_m, coast_x.

Usage:
  python pipeline/run_project.py <slug>            # from the repo root
  from pipeline.run_project import run_project     # what the landing page calls
"""
import os, sys, json, math, traceback, datetime as dt

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from skimage.registration import phase_cross_correlation
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, ROOT)
import water_mask, ice as ice_mod, analyze  # noqa: E402
from alert import generate_alert  # noqa: E402

PROJECTS = os.path.join(ROOT, "data", "projects")
MAX_PIXELS = 4000          # max grid width/height; resolution is raised for big areas
SNOW_MONTHS = {11, 12, 1, 2, 3, 4}


# ---------------------------------------------------------------- helpers
def project_dir(slug):
    return os.path.join(PROJECTS, slug)


def load_project(slug):
    with open(os.path.join(project_dir(slug), "project.json")) as f:
        return json.load(f)


def save_project(slug, proj):
    with open(os.path.join(project_dir(slug), "project.json"), "w") as f:
        json.dump(proj, f, indent=2)


def detect_kind(path):
    """'ard' = calibrated + map-projected (AWS analysis-ready). 'grd' = raw DN located by GCPs (EODMS order)."""
    with rasterio.open(path) as src:
        if src.crs is not None and src.dtypes[0].startswith("float"):
            return "ard"
        if src.crs is None and src.gcps[0]:
            return "grd"
        if src.crs is not None:
            return "ard"   # projected integer file: treat as already-mapped backscatter
    raise ValueError(f"{os.path.basename(path)}: not a radar GeoTIFF this tool understands (no map info).")


def footprint_lonlat(path):
    with rasterio.open(path) as src:
        if src.crs is not None:
            return transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        gcps, gcrs = src.gcps
        tr = Transformer.from_crs(gcrs, "EPSG:4326", always_xy=True)
        xs, ys = zip(*[tr.transform(g.x, g.y) for g in gcps])
        return min(xs), min(ys), max(xs), max(ys)


def utm_for(lon, lat):
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


def date_of(path):
    """Acquisition date from the TIFF tag if present (EODMS GRD has it)."""
    with rasterio.open(path) as src:
        t = src.tags().get("TIFFTAG_DATETIME")
    if t:
        return t[:10].replace(":", "-")
    return None


# ---------------------------------------------------------------- main
def run_project(slug, log=print):
    pdir = project_dir(slug)
    proj = load_project(slug)
    proj["status"] = "running"; proj["error"] = None; proj["warnings"] = []
    save_project(slug, proj)
    try:
        _run(slug, pdir, proj, log)
        proj["status"] = "done"
        proj["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    except Exception as e:
        proj["status"] = "error"
        proj["error"] = str(e)
        log("ERROR: " + str(e))
        traceback.print_exc()
    save_project(slug, proj)
    return proj


def _run(slug, pdir, proj, log):
    images = proj.get("images", [])
    normals = [im for im in images if im.get("role") == "normal"]
    floods = [im for im in images if im.get("role") == "flood"]
    if len(normals) != 1:
        raise ValueError("Pick exactly one image as the normal (non-flood) day.")
    if not floods:
        raise ValueError("Add at least one flood-day image.")
    for im in images:
        im["path"] = os.path.join(pdir, im["file"])
        if not os.path.exists(im["path"]):
            raise ValueError(f"Missing file {im['file']}.")
        im.setdefault("kind", detect_kind(im["path"]))
        if not im.get("date"):
            im["date"] = date_of(im["path"])
        if not im.get("date"):
            raise ValueError(f"No date for {im['file']}. Type the date in.")
    dates = [im["date"] for im in images]
    if len(set(dates)) != len(dates):
        raise ValueError("Two images have the same date.")

    # 1. study area = where all images overlap (or the user's box)
    if proj.get("aoi_lonlat"):
        w, s, e, n = proj["aoi_lonlat"]
    else:
        fps = [footprint_lonlat(im["path"]) for im in images]
        w, s = max(f[0] for f in fps), max(f[1] for f in fps)
        e, n = min(f[2] for f in fps), min(f[3] for f in fps)
        if w >= e or s >= n:
            raise ValueError("The images don't overlap. Upload images of the same place.")
        proj["aoi_lonlat"] = [round(w, 5), round(s, 5), round(e, 5), round(n, 5)]
    crs = proj.get("crs") or utm_for((w + e) / 2, (s + n) / 2)
    proj["crs"] = crs
    if proj.get("bounds_xy"):                       # exact box in the project's crs (metres)
        xmin, ymin, xmax, ymax = proj["bounds_xy"]
    else:
        xmin, ymin, xmax, ymax = transform_bounds("EPSG:4326", crs, w, s, e, n)
    res = proj.get("res_m") or 20
    res = max(res, math.ceil(max(xmax - xmin, ymax - ymin) / MAX_PIXELS / 10) * 10)
    proj["res_m"] = res
    # Snap the grid to whole multiples of the pixel size so every run lines up pixel for pixel.
    # (Narrow channels 1-2 pixels wide otherwise appear/disappear depending on where the grid falls.)
    xmin, ymin = math.floor(xmin / res) * res, math.floor(ymin / res) * res
    xmax, ymax = math.ceil(xmax / res) * res, math.ceil(ymax / res) * res
    log(f"Area {proj['aoi_lonlat']} · {crs} · {res} m pixels · "
        f"{(xmax - xmin) / 1000:.0f} x {(ymax - ymin) / 1000:.0f} km")

    coast_x = proj.get("coast_x")
    water_mask.configure(crs=crs, bounds=(xmin, ymin, xmax, ymax), res=res)
    ice_mod.configure(crs=crs, coast_x=coast_x)
    analyze.configure(crs=crs, coast_x=coast_x)

    for im in images:
        if int(im["date"][5:7]) in SNOW_MONTHS:
            proj["warnings"].append(f"{im['date']} is in snow season. Wet snow can look like water, "
                                    "so extra water may be too high. The river-ice check still works.")

    # 2. water map for every image
    def make(im, shift=(0, 0)):
        role = "normal" if im["role"] == "normal" else "flood"
        prefix = os.path.join(pdir, f"{role}_{im['date']}")
        db, t = water_mask.load_db(im["path"], im["kind"])
        if np.isfinite(db).mean() < 0.05:
            raise ValueError(f"{im['date']}: image has almost no data inside the shared area.")
        if any(shift):
            from scipy.ndimage import shift as ndshift
            db = ndshift(db, shift, order=0, mode="constant", cval=np.nan)
        if im.get("threshold_db") is None:
            im["threshold_db"] = round(water_mask.auto_threshold(db, im["kind"]), 2)
        mask = water_mask.make_mask(db, im["threshold_db"])
        with rasterio.open(prefix + "_mask.tif", "w", driver="GTiff", height=mask.shape[0], width=mask.shape[1],
                           count=1, dtype="uint8", crs=crs, transform=t, nodata=255) as dst:
            out = mask.astype("uint8"); out[np.isnan(db)] = 255; dst.write(out, 1)
        with rasterio.open(prefix + "_db.tif", "w", driver="GTiff", height=db.shape[0], width=db.shape[1],
                           count=1, dtype="float32", crs=crs, transform=t, nodata=np.nan) as dst:
            dst.write(db.astype("float32"), 1)
        gdf = water_mask.to_geojson(mask, t, prefix + "_water.geojson")
        im["water_km2"] = round(float(gdf.area.sum() / 1e6), 2)
        return mask, prefix

    normal = normals[0]
    log(f"Water map: normal day {normal['date']} ({normal['kind']})")
    n_mask, n_prefix = make(normal)

    for im in sorted(floods, key=lambda x: x["date"]):
        log(f"Water map: {im['date']} ({im['kind']})")
        f_mask, f_prefix = make(im, tuple(im.get("shift_px") or (0, 0)))
        # 3. line the image up with the normal day (raw GRD placement can be tens of metres off)
        if "shift_px" not in im:
            both = (n_mask.astype(float), f_mask.astype(float))
            shift, _, _ = phase_cross_correlation(*both, upsample_factor=10)
            shift = [int(round(v)) for v in shift]
            if 1 <= max(abs(v) for v in shift) <= 5:
                log(f"  lining up: shifting {im['date']} by {shift} pixels")
                im["shift_px"] = shift
                f_mask, f_prefix = make(im, tuple(shift))
            else:
                im["shift_px"] = [0, 0]

        out_dir = os.path.join(pdir, im["date"]); os.makedirs(out_dir, exist_ok=True)
        lifelines = os.path.join(pdir, "lifelines.json")
        if not os.path.exists(lifelines):
            json.dump([], open(lifelines, "w"))

        # 4. ice, then flood + distances, then alert
        log(f"River ice: {im['date']}")
        ice_kwargs = {}
        if im.get("ice_threshold_db") is not None:
            ice_kwargs = dict(db=f_prefix + "_db.tif", ice_threshold=im["ice_threshold_db"],
                              median=im.get("ice_median", 7))
        ice_mod.main(n_prefix + "_mask.tif", f_prefix + "_mask.tif", lifelines, out_dir, **ice_kwargs)
        log(f"Flood + lifelines: {im['date']}")
        analyze.main(n_prefix + "_water.geojson", f_prefix + "_water.geojson", f_prefix + "_mask.tif",
                     lifelines, out_dir)
        generate_alert.main(out_dir)

    proj["normal_date"] = normal["date"]
    proj["flood_dates"] = sorted(im["date"] for im in floods)
    for im in images:
        im.pop("path", None)
    log("Done.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python pipeline/run_project.py <slug>")
    p = run_project(sys.argv[1])
    print(json.dumps({k: p.get(k) for k in ("status", "error", "warnings", "aoi_lonlat", "crs", "res_m")}, indent=2))
