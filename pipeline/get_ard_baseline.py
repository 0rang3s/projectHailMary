"""
Backup plan for the normal-day picture: RCM Analysis-Ready Data (ARD).
No ordering, no waiting. Pulled straight from the public AWS copy.

Run on your laptop (needs internet):
    pip install pystac-client rasterio
    python pipeline/get_ard_baseline.py            # lists scenes
    python pipeline/get_ard_baseline.py 3          # downloads scene #3, cropped to our area

Downloads only area (~65 x 50 km), so files are small (tens of MB).
Output: data/ard/<date>/<asset>.tif  -> upload those .tif files to Claude.
"""
import os, sys
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds
from pystac_client import Client
from shapely.geometry import shape, box

CAT = "https://www.eodms-sgdot.nrcan-rncan.gc.ca/search/"
BBOX = (-82.40, 52.00, -81.45, 52.45)          # Albany River mouth: Fort Albany + Kashechewan
WINDOWS = ["2025-07-01/2025-09-30",            # normal summer (baseline)
           "2025-04-15/2025-05-20"]            # spring 2025 flood season (bonus)


def search():
    cat = Client.open(CAT)
    items = []
    for w in WINDOWS:
        items += list(cat.search(collections=["rcm-ard"], bbox=BBOX, datetime=w,
                                 limit=200, method="GET").items())
    return sorted(items, key=lambda i: i.datetime)


def main():
    items = search()
    if len(sys.argv) == 1:
        print(f"{len(items)} scenes over our area:")
        for n, it in enumerate(items):
            p = it.properties
            tifs = [k for k, a in it.assets.items() if a.href.endswith(".tif")]
            aoi = box(*BBOX)
            cov = 100 * shape(it.geometry).intersection(aoi).area / aoi.area
            flag = "  <-- good" if cov > 90 and str(p.get('sat:orbit_state','')).lower() == 'ascending' and it.datetime.month in (7, 8, 9) else ""
            print(f"[{n:2d}] {it.datetime:%Y-%m-%d %H:%M}  {p.get('sat:orbit_state',''):10s} covers {cov:5.1f}%{flag}")
        print("\nPick a '<-- good' one (summer, ascending, >90% coverage) and rerun with its number.")
        return
    it = items[int(sys.argv[1])]
    out = f"data/ard/{it.datetime:%Y-%m-%d}"
    os.makedirs(out, exist_ok=True)
    for k, a in it.assets.items():
        if not a.href.endswith(".tif"):
            continue
        with rasterio.open(a.href) as src:
            b = transform_bounds("EPSG:4326", src.crs, *BBOX)
            win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
            data = src.read(window=win, boundless=True, fill_value=0)
            prof = src.profile.copy()
            prof.update(width=data.shape[2], height=data.shape[1],
                        transform=src.window_transform(win), driver="GTiff", compress="deflate")
            prof.pop("blockxsize", None); prof.pop("blockysize", None); prof.pop("tiled", None)
            with rasterio.open(f"{out}/{k}.tif", "w", **prof) as dst:
                dst.write(data)
        print("saved", f"{out}/{k}.tif")
    print("Done. Upload the .tif files in", out)


if __name__ == "__main__":
    main()
