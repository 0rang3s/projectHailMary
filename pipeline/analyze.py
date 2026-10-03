"""
Cut Off - analysis step (owned by the analysis person).

Inputs (data contract):
  <normal>_water.geojson   water on a normal day
  <flood>_water.geojson    water on the flood day
  <flood>_mask.tif         used only to know where the scene has data
  lifelines.json           points we care about (name, type, lat, lon)

Outputs (data contract):
  flood_extra.geojson      water on flood day that was NOT water on the normal day
  lifelines_status.json    distance to water + red/yellow/green per lifeline
  stats.json               headline numbers for the side panel and the AI alert

Usage:
  python pipeline/analyze.py NORMAL_water.geojson FLOOD_water.geojson FLOOD_mask.tif lifelines.json OUT_DIR [--mock]
"""
import json, os, sys, argparse
import geopandas as gpd
import rasterio
from shapely.geometry import Point
from shapely.ops import unary_union

CRS = "EPSG:32617"
RED_M, YELLOW_M = 200, 1000          # status thresholds, metres to nearest water
COAST_X = 461000                     # UTM 17N easting; east of this is James Bay coast/sea ice, not river flooding



def has_data(mask_path, x, y):
    with rasterio.open(mask_path) as src:
        r, c = src.index(x, y)
        if not (0 <= r < src.height and 0 <= c < src.width):
            return False
        return src.read(1)[r, c] != src.nodata


def status_for(dist_m):
    if dist_m <= RED_M:
        return "red"
    if dist_m <= YELLOW_M:
        return "yellow"
    return "green"


def main(normal_p, flood_p, mask_p, lifelines_p, out_dir, mock=False):
    normal = gpd.read_file(normal_p).to_crs(CRS)
    flood = gpd.read_file(flood_p).to_crs(CRS)
    n_u, f_u = unary_union(normal.geometry), unary_union(flood.geometry)

    extra = f_u.difference(n_u.buffer(20))        # 25 m tolerance for co-registration wobble
    extra_gdf = gpd.GeoDataFrame(geometry=[extra], crs=CRS).explode(index_parts=False)
    extra_gdf = extra_gdf[extra_gdf.area > 4000]
    extra_incl_coast_km2 = round(extra_gdf.area.sum() / 1e6, 1)
    # Leave James Bay out: coastal flats and breaking sea ice there are not river flooding.
    from shapely.geometry import box
    xmin, ymin, xmax, ymax = extra_gdf.total_bounds if len(extra_gdf) else (0, 0, 1, 1)
    extra_gdf["geometry"] = extra_gdf.intersection(box(min(xmin, 0), min(ymin, 0), COAST_X, max(ymax, 1e8)))
    extra_gdf = extra_gdf[~extra_gdf.is_empty & (extra_gdf.area > 4000)]
    extra_gdf["area_km2"] = extra_gdf.area / 1e6
    extra_gdf["mock"] = mock
    extra_gdf.to_crs(4326).to_file(f"{out_dir}/flood_extra.geojson", driver="GeoJSON")

    # Distances count open water, river ice and the normal river channel.
    # A frozen river is still the river, and the river doesn't disappear during a flood.
    # (Run pipeline/ice.py first so river_ice.geojson exists.)
    ice_p = f"{out_dir}/river_ice.geojson"
    ice_u = unary_union(gpd.read_file(ice_p).to_crs(CRS).geometry) if os.path.exists(ice_p) else None
    water_now = unary_union([g for g in (f_u, n_u, ice_u) if g is not None and not g.is_empty])

    lifelines = json.load(open(lifelines_p))
    out = []
    for L in lifelines:
        pt = gpd.GeoSeries([Point(L["lon"], L["lat"])], crs=4326).to_crs(CRS).iloc[0]
        rec = dict(L)
        if not has_data(mask_p, pt.x, pt.y):
            rec.update(status="no_data", dist_flood_m=None, dist_normal_m=None,
                       note="Outside this radar scene - need another scene to assess")
        else:
            d_open = round(pt.distance(f_u))          # open water only, kept for transparency
            d_f = round(pt.distance(water_now))        # open water + ice + normal river: what we show
            d_n = round(pt.distance(n_u))
            rec.update(status=status_for(d_f), dist_flood_m=d_f, dist_open_water_m=d_open,
                       dist_normal_m=d_n, closer_by_m=d_n - d_f)
        out.append(rec)
    json.dump(out, open(f"{out_dir}/lifelines_status.json", "w"), indent=2)

    stats = {
        "mock": mock,
        "normal_date": normal_p.split("/")[-1].split("_")[1] if "_" in normal_p else "unknown",
        "flood_date": flood_p.split("/")[-1].split("_")[1] if "_" in flood_p else "unknown",
        "normal_water_km2": round(n_u.area / 1e6, 1),
        "flood_water_km2": round(f_u.area / 1e6, 1),
        "extra_water_km2": round(extra_gdf.area.sum() / 1e6, 1),
        "extra_water_incl_coast_km2": extra_incl_coast_km2,
        "notes": "extra water excludes James Bay east of the coast line; lifeline distances count open water, river ice and the normal channel",
        "lifelines_red": sum(r["status"] == "red" for r in out),
        "lifelines_yellow": sum(r["status"] == "yellow" for r in out),
        "lifelines_no_data": sum(r["status"] == "no_data" for r in out),
    }
    json.dump(stats, open(f"{out_dir}/stats.json", "w"), indent=2)
    print(json.dumps(stats, indent=2))
    for r in out:
        print(r["name"], r["status"], r.get("dist_flood_m"), r.get("dist_normal_m"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    for a in ["normal", "flood", "mask", "lifelines", "out_dir"]:
        ap.add_argument(a)
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    main(a.normal, a.flood, a.mask, a.lifelines, a.out_dir, a.mock)
