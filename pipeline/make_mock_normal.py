"""
TEMPORARY. Makes a FAKE 'normal day' water layer from the real flood-day mask so the
team can build the app before the real Aug 5 2024 scene arrives.
Fake normal = flood-day water, shrunk by ~100 m, minus the small/isolated patches.
Delete this file once data/real/normal_2024-08-05_water.geojson exists.
"""
import numpy as np, rasterio
from scipy.ndimage import binary_erosion, label
import sys; sys.path.insert(0, "pipeline")
from water_mask import to_geojson

with rasterio.open("data/real/flood_2025-04-30_mask.tif") as src:
    m = src.read(1); t = src.transform
water = m == 1
normal = binary_erosion(water, iterations=1)
lab, n = label(normal)
sizes = np.bincount(lab.ravel()); sizes[0] = 0
keep = np.isin(lab, np.where(sizes * 50 * 50 > 5e5)[0])    # only big connected water (the river)
to_geojson(keep, t, "data/mock/normal_MOCK-2024-08-05_water.geojson")
print("mock normal water km2:", keep.sum() * 2500 / 1e6)
