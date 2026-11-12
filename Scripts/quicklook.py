"""Quick-look: both dates' Sentinel-1 VV backscatter (dB, subsampled) in lon/lat with the official EMS flood polygons on top."""
import json, glob, os, xml.etree.ElementTree as ET
import numpy as np, tifffile, matplotlib
matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from shapely.geometry import shape
from scipy.interpolate import RegularGridInterpolator
B = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Data_EMSR866'); STEP = 12
ref = json.load(open(os.path.join(B, 'reference', 'EMSR866_Official_Flood.json')))
polys = []
for f in ref['features']:
    g = shape(f['geometry'])
    for p in getattr(g, 'geoms', [g]): polys.append(np.asarray(p.exterior.coords))
fig, axes = plt.subplots(1, 2, figsize=(14, 7.2), dpi=110)
for ax, (title, folder) in zip(axes, [('Pre-event 2026-01-31 17:55 UTC (S1C, orbit 006151)', 'pre_event'),
                                       ('Post-event 2026-02-12 17:55 UTC (S1C, orbit 006326)', 'post_event')]):
    for s in sorted(glob.glob(os.path.join(B, folder, '*.SAFE'))):
        root = ET.parse(sorted(glob.glob(os.path.join(s, 'annotation', 's1*-vv-*.xml')))[0]).getroot()
        G = np.array([[float(q.find(t).text) for t in ('line', 'pixel', 'latitude', 'longitude')] for q in root.iter('geolocationGridPoint')])
        lines, pixels = np.unique(G[:, 0]), np.unique(G[:, 1])
        LAT = G[:, 2].reshape(len(lines), len(pixels)); LON = G[:, 3].reshape(len(lines), len(pixels))
        img = tifffile.TiffFile(sorted(glob.glob(os.path.join(s, 'measurement', 's1*-vv-*.tiff')))[0]).pages[0].asarray(out='memmap')
        r = np.arange(0, img.shape[0], STEP); c = np.arange(0, img.shape[1], STEP)
        sub = np.asarray(img[::STEP, ::STEP], dtype=np.float32)
        R, C = np.meshgrid(r, c, indexing='ij'); q = np.c_[R.ravel(), C.ravel()]
        lat = RegularGridInterpolator((lines, pixels), LAT, bounds_error=False, fill_value=None)(q).reshape(R.shape)
        lon = RegularGridInterpolator((lines, pixels), LON, bounds_error=False, fill_value=None)(q).reshape(R.shape)
        db = np.where(sub > 0, 20 * np.log10(np.maximum(sub, 1)), np.nan)  # uncalibrated DN in dB, for display only
        ax.pcolormesh(lon, lat, db, cmap='gray', vmin=np.nanpercentile(db, 2), vmax=np.nanpercentile(db, 98), shading='auto', rasterized=True)
    ax.add_collection(PolyCollection(polys, facecolor=(1, 0.1, 0.1, 0.55), edgecolor='red', linewidth=0.2))
    ax.set_xlim(-1.35, 0.25); ax.set_ylim(45.2, 46.2); ax.set_aspect(1 / np.cos(np.radians(45.7)))
    ax.set_title(title, fontsize=10); ax.set_xlabel('Longitude (°E)'); ax.set_ylabel('Latitude (°N)')
fig.suptitle('EMSR866 AOI01 (Cognac): official EMS observed flood layer (red) on the downloaded Sentinel-1 frames (VV, display only)', fontsize=11)
plt.tight_layout(); out = os.path.join(B, 'EMSR866_alignment_check.png'); plt.savefig(out); print('saved', out)
