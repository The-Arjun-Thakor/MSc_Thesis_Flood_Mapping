"""Quick-look: both dates' Sentinel-1 VV backscatter (dB, subsampled) in lon/lat with the official EMS flood polygons on top."""
import json, os
import numpy as np, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from shapely.geometry import shape
from scipy.interpolate import RegularGridInterpolator
import s1_safe
STEP = 12
ref = json.load(open(s1_safe.EMS_FLOOD, encoding='utf-8'))
polys = []
for f in ref['features']:
    g = shape(f['geometry'])
    for p in getattr(g, 'geoms', [g]): polys.append(np.asarray(p.exterior.coords))
fig, axes = plt.subplots(1, 2, figsize=(14, 7.2), dpi=110)
for ax, (title, folder) in zip(axes, [('Pre-event 2026-01-31 17:55 UTC (S1C, orbit 006151)', 'S1_pre'),
                                       ('Post-event 2026-02-12 17:55 UTC (S1C, orbit 006326)', 'S1_post')]):
    for s in s1_safe.frames(folder):
        G = s1_safe.geolocation_grid(s)
        lines, pixels = np.unique(G[:, 0]), np.unique(G[:, 1])
        LAT = G[:, 2].reshape(len(lines), len(pixels)); LON = G[:, 3].reshape(len(lines), len(pixels))
        with s1_safe.vv_image(s) as img:
            shp = img.shape
            sub = np.asarray(img[::STEP, ::STEP], dtype=np.float32)
        r = np.arange(0, shp[0], STEP); c = np.arange(0, shp[1], STEP)
        R, C = np.meshgrid(r, c, indexing='ij'); q = np.c_[R.ravel(), C.ravel()]
        lat = RegularGridInterpolator((lines, pixels), LAT, bounds_error=False, fill_value=None)(q).reshape(R.shape)
        lon = RegularGridInterpolator((lines, pixels), LON, bounds_error=False, fill_value=None)(q).reshape(R.shape)
        db = np.where(sub > 0, 20 * np.log10(np.maximum(sub, 1)), np.nan)  # uncalibrated DN in dB, for display only
        ax.pcolormesh(lon, lat, db, cmap='gray', vmin=np.nanpercentile(db, 2), vmax=np.nanpercentile(db, 98), shading='auto', rasterized=True)
    ax.add_collection(PolyCollection(polys, facecolor=(1, 0.1, 0.1, 0.55), edgecolor='red', linewidth=0.2))
    ax.set_xlim(-1.35, 0.25); ax.set_ylim(45.2, 46.2); ax.set_aspect(1 / np.cos(np.radians(45.7)))
    ax.set_title(title, fontsize=10); ax.set_xlabel('Longitude (°E)'); ax.set_ylabel('Latitude (°N)')
fig.suptitle('EMSR866 AOI01 (Cognac): official EMS observed flood layer (red) on the downloaded Sentinel-1 frames (VV, display only)', fontsize=11)
plt.tight_layout(); os.makedirs(s1_safe.RESULTS, exist_ok=True); out = os.path.join(s1_safe.RESULTS, 'EMSR866_alignment_check.png'); plt.savefig(out); print('saved', out)
