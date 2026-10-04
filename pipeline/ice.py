"""
Cut Off - ice-jam detector.

Idea: ice jams cause these floods. On radar, open water is dark and river ice is
bright. So inside the river's NORMAL channels (from the summer picture), any pixel
that is not water on a flood date is most likely ice.

Warning sign we flag: river near the towns mostly frozen while the river upstream
is mostly open -> water arriving from upstream has nowhere to go.

Usage:
  ARD dates:  python pipeline/ice.py data/real/normal_2025-08-07_mask.tif data/real/flood_2025-05-07_mask.tif data/lifelines.json data/real/2025-05-07
  Apr 30 GRD: python pipeline/ice.py data/real/normal_2025-08-07_mask.tif data/real/flood_2025-04-30_mask.tif data/lifelines.json data/real/2025-04-30 \
                  --db data/real/flood_2025-04-30_db.tif --ice-threshold 49.5 --median 7
Robustness check (Apr 30): river near the towns is 93-100% frozen for any cutoff 47.5-49.5 and smoothing 3-7;
only the upstream figure moves (12-31%).
Outputs (in OUT_DIR):
  river_ice.geojson   frozen river stretches
  ice_stats.json      % frozen overall / near each town / upstream + jam_risk flag
"""
import json, argparse
import numpy as np
import rasterio
import geopandas as gpd
from rasterio.features import shapes
from scipy.ndimage import label, binary_erosion
from shapely.geometry import shape
from pyproj import Transformer

CRS = "EPSG:32617"
COAST_X = 461000          # metres east (UTM 17N); east of this is James Bay, whose sea ice is not river ice
TOWN_RADIUS_M = 5000      # "near the town" zone
UPSTREAM_M = 15000        # river further than this from every town = upstream
JAM_NEAR_MIN = 70         # % frozen near a town to count as jammed
JAM_UP_MAX = 40           # % frozen upstream to count as "open, water still coming"


def configure(crs=None, coast_x="keep"):
    """Used by run_project.py. coast_x=None turns the James Bay clip off."""
    global CRS, COAST_X
    if crs: CRS = crs
    if coast_x != "keep": COAST_X = coast_x


def main(normal_mask, flood_mask, lifelines_p, out_dir, db=None, ice_threshold=None, median=7):
    with rasterio.open(normal_mask) as src:
        nm = src.read(1); T = src.transform; px = abs(T.a * T.e)
    fm = rasterio.open(flood_mask).read(1)
    if db and ice_threshold is not None:
        # Uncalibrated scenes (Apr 30 GRD) are noisier: inside the known channels, re-classify
        # open water vs ice with heavier smoothing and their own cutoff. Flood numbers are unaffected.
        from scipy.ndimage import median_filter
        a = rasterio.open(db).read(1)
        sm = median_filter(np.where(np.isfinite(a), a, np.nanmax(a)), median)
        fm = np.where(np.isfinite(a), (sm < ice_threshold).astype("uint8"), 255)

    # 1. the river system on a normal day: big connected water, a pixel inside the banks, west of the coast
    lab, _ = label(nm == 1)
    sizes = np.bincount(lab.ravel()); sizes[0] = 0
    river = np.isin(lab, np.where(sizes * px > 1e6)[0])
    river = binary_erosion(river, iterations=1)
    rows, cols = np.indices(river.shape)
    X = T.c + (cols + 0.5) * T.a; Y = T.f + (rows + 0.5) * T.e
    if COAST_X is not None:
        river &= X < COAST_X

    # 2. on the flood date: inside the river, not water = ice
    seen = river & (fm != 255)
    ice = seen & (fm != 1)

    # 3. zones
    tr = Transformer.from_crs(4326, CRS, always_xy=True)
    towns = [l for l in json.load(open(lifelines_p)) if l["type"] == "community"]
    dist_to_any = np.full(river.shape, np.inf)
    zones = {}
    for t in towns:
        x, y = tr.transform(t["lon"], t["lat"])
        d = np.hypot(X - x, Y - y); dist_to_any = np.minimum(dist_to_any, d)
        near = seen & (d < TOWN_RADIUS_M)
        zones[t["name"]] = {"river_km2_seen": float(round(near.sum() * px / 1e6, 2)),
                            "pct_frozen": int(round(100 * (ice & near).sum() / near.sum())) if near.sum() else None}
    up = seen & (dist_to_any > UPSTREAM_M)
    up_pct = int(round(100 * (ice & up).sum() / up.sum())) if towns and up.sum() else None

    jam_towns = [n for n, z in zones.items() if z["pct_frozen"] is not None and z["pct_frozen"] >= JAM_NEAR_MIN]
    jam = bool(jam_towns and up_pct is not None and up_pct <= JAM_UP_MAX) if towns else None   # no towns = no verdict
    stats = {
        "river_km2_seen": float(round(seen.sum() * px / 1e6, 1)),
        "pct_frozen_overall": int(round(100 * ice.sum() / seen.sum())) if seen.sum() else None,
        "near_towns": zones,
        "upstream_pct_frozen": up_pct,
        "jam_risk": jam,
        "jam_towns": jam_towns if jam else [],
        "rule": f"jam risk = river within {TOWN_RADIUS_M/1000:.0f} km of a town >= {JAM_NEAR_MIN}% frozen "
                f"while river > {UPSTREAM_M/1000:.0f} km away <= {JAM_UP_MAX}% frozen",
    }
    json.dump(stats, open(f"{out_dir}/ice_stats.json", "w"), indent=2)

    geoms = [shape(g) for g, v in shapes(ice.astype("uint8"), mask=ice, transform=T) if v == 1]
    gdf = gpd.GeoDataFrame(geometry=geoms, crs=CRS)
    gdf = gdf[gdf.area >= 2 * px]
    gdf["geometry"] = gdf.simplify(10)
    gdf.to_crs(4326).to_file(f"{out_dir}/river_ice.geojson", driver="GeoJSON")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    for a in ["normal_mask", "flood_mask", "lifelines", "out_dir"]:
        ap.add_argument(a)
    ap.add_argument("--db", help="flood-date dB raster, to re-classify ice with its own cutoff (use for Apr 30 GRD)")
    ap.add_argument("--ice-threshold", type=float)
    ap.add_argument("--median", type=int, default=7)
    a = ap.parse_args()
    main(a.normal_mask, a.flood_mask, a.lifelines, a.out_dir, a.db, a.ice_threshold, a.median)
