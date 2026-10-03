"""
Cut Off - radar water mask pipeline.

Turns one RCM GRD scene (HH + HV GeoTIFFs with embedded GCPs) into:
  - a georeferenced dB raster clipped to our area of interest (AOI)
  - a water / not-water mask
  - water polygons as GeoJSON

Usage:
  GRD (EODMS order):  python pipeline/water_mask.py HH.tif HV.tif out_prefix --band HV --threshold 47.5
  ARD (AWS):          python pipeline/water_mask.py rl.tif rr.tif out_prefix --band HV --kind ard --threshold -20

Same code runs on the flood-day scene and the normal-day scene.
NOTE: values are uncalibrated DN converted to dB. Fine for thresholding one
scene at a time; swap in sigma0 using product.xml LUTs once we have the zip.
"""
import os, sys, json, argparse
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
from rasterio.features import shapes
from scipy.ndimage import median_filter, binary_opening, binary_closing
from skimage.filters import threshold_otsu
import geopandas as gpd
from shapely.geometry import shape

# AOI: Albany River mouth, Fort Albany + Kashechewan, in UTM 17N metres
CRS = "EPSG:32617"
RES = float(os.environ.get("CUTOFF_RES", 20))   # metres; 20 = native ARD pixel size
# bounds roughly lon -82.40..-81.45, lat 52.00..52.45
XMIN, YMIN, XMAX, YMAX = 405000, 5762000, 470000, 5812000


def load_db(path, kind="grd"):
    """Read one band, warp to the AOI grid, return dB.
    kind="grd": EODMS Level-1 GRD (raw DN, located by GCPs)  -> dB of DN^2 (uncalibrated)
    kind="ard": RCM analysis-ready data (calibrated backscatter, already map-projected) -> dB
    """
    with rasterio.open(path) as src:
        w = int((XMAX - XMIN) / RES); h = int((YMAX - YMIN) / RES)
        dst = np.full((h, w), np.nan, dtype="float32")
        transform = from_origin(XMIN, YMAX, RES, RES)
        kw = dict(src_crs=src.crs) if src.crs else dict(gcps=src.gcps[0], src_crs=src.gcps[1])
        reproject(source=rasterio.band(src, 1), destination=dst, dst_transform=transform,
                  dst_crs=CRS, src_nodata=0, dst_nodata=np.nan,
                  resampling=Resampling.average, **kw)
    pos = np.where(dst > 0, dst, np.nan)
    db = 10 * np.log10(pos ** 2) if kind == "grd" else 10 * np.log10(pos)
    return db, transform


def water_threshold(db):
    """Otsu on the AOI. AOI is chosen to hold lots of river so the histogram is bimodal."""
    v = db[~np.isnan(db)]
    return float(threshold_otsu(v))


def make_mask(db, thr):
    sm = median_filter(np.nan_to_num(db, nan=np.nanmax(db)), size=3)   # speckle
    m = sm < thr
    m = binary_opening(m, iterations=1)    # drop salt noise
    m = binary_closing(m, iterations=1)    # fill pinholes
    m[np.isnan(db)] = False
    return m


def to_geojson(mask, transform, out_path, min_area_m2=4000):
    geoms = [shape(g) for g, v in shapes(mask.astype("uint8"), mask=mask, transform=transform) if v == 1]
    gdf = gpd.GeoDataFrame(geometry=geoms, crs=CRS)
    gdf = gdf[gdf.area >= min_area_m2]
    gdf["geometry"] = gdf.simplify(RES / 2)
    gdf["area_km2"] = gdf.area / 1e6
    gdf.to_crs(4326).to_file(out_path, driver="GeoJSON")
    return gdf


def run(hh, hv, prefix, threshold=None, band="HH", kind="grd", shift_px=(0, 0)):
    """hh/hv = the two band files (for ARD pass rl as 'hh' and rr as 'hv'; band=HV picks the second).
    shift_px = (rows, cols) nudge to line this scene up with the baseline (GRD placement can be off by tens of m)."""
    db, t = load_db(hv if band == "HV" else hh, kind)
    if any(shift_px):
        from scipy.ndimage import shift as ndshift
        db = ndshift(db, shift_px, order=0, mode="constant", cval=np.nan)
    thr = threshold if threshold is not None else water_threshold(db)
    mask = make_mask(db, thr)
    with rasterio.open(prefix + "_mask.tif", "w", driver="GTiff", height=mask.shape[0], width=mask.shape[1],
                       count=1, dtype="uint8", crs=CRS, transform=t, nodata=255) as dst:
        out = mask.astype("uint8"); out[np.isnan(db)] = 255; dst.write(out, 1)
    with rasterio.open(prefix + "_db.tif", "w", driver="GTiff", height=db.shape[0], width=db.shape[1],
                       count=1, dtype="float32", crs=CRS, transform=t, nodata=np.nan) as dst:
        dst.write(db.astype("float32"), 1)
    gdf = to_geojson(mask, t, prefix + "_water.geojson")
    info = {"kind": kind, "band": band, "shift_px": list(shift_px), "threshold_db": thr, "water_km2": round(float(gdf.area.sum() / 1e6), 2),
            "valid_km2": round(float((~np.isnan(db)).sum() * RES * RES / 1e6), 1)}
    json.dump(info, open(prefix + "_info.json", "w"), indent=2)
    print(info)
    return db, mask, t


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("hh"); ap.add_argument("hv"); ap.add_argument("prefix")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--band", default="HH", choices=["HH", "HV"])
    ap.add_argument("--kind", default="grd", choices=["grd", "ard"])
    ap.add_argument("--shift-px", default="0,0", help="rows,cols to nudge the scene (Apr 30 GRD: 2,0 = 40 m south)")
    a = ap.parse_args()
    run(a.hh, a.hv, a.prefix, a.threshold, a.band, a.kind, tuple(float(v) for v in a.shift_px.split(",")))
