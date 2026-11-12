"""Check that the downloaded Sentinel-1 GRD frames cover the official EMS flood polygons.
1. CRS of the GeoJSON, 2. footprints from manifest.safe, 3. polygon coverage by each date's frames,
4. valid (non-zero) radar pixels under the flood polygons, using the geolocation grid in the annotation XML.
Data is read from the data drive (config.DATA_ROOT), the Sentinel-1 frames straight from their .SAFE.zip."""
import json, os
import numpy as np
from shapely.geometry import shape, Polygon
from shapely.ops import unary_union
import s1_safe

ref = json.load(open(s1_safe.EMS_FLOOD, encoding='utf-8'))
print('GeoJSON CRS:', ref.get('crs', {}).get('properties', {}).get('name'))
flood = unary_union([shape(f['geometry']).buffer(0) for f in ref['features']])
print('Flood features:', len(ref['features']), '| bounds lon/lat:', [round(v, 4) for v in flood.bounds],
      '| area deg2 %.5f' % flood.area)

def footprint(safe):
    return Polygon(s1_safe.footprint_coords(safe))

for date, folder in s1_safe.DATES:
    safes = s1_safe.frames(folder)
    fps = [footprint(s) for s in safes]
    union = unary_union(fps)
    inside = flood.difference(union).area / flood.area
    print(f'\n{date}: {len(safes)} frames')
    for s, fp in zip(safes, fps):
        print('  ', os.path.basename(s)[17:48], 'lat %.2f-%.2f' % (fp.bounds[1], fp.bounds[3]),
              '| share of flood area in this frame: %.1f%%' % (100 * flood.intersection(fp).area / flood.area))
    print('   flood area outside both footprints: %.4f%%' % (100 * inside))

    # valid-data check: sample flood polygon interior points, map lon/lat -> pixel via geolocation grid
    pts = []
    for g in getattr(flood, 'geoms', [flood]):
        pts.append(g.representative_point())
    rng = np.random.default_rng(0)
    pts = [pts[i] for i in rng.choice(len(pts), size=min(400, len(pts)), replace=False)]
    zero = 0; total = 0
    for s in safes:
        G = s1_safe.geolocation_grid(s)
        fp = footprint(s)
        with s1_safe.vv_image(s) as img:
            for p in pts:
                if not fp.contains(p): continue
                # nearest-neighbour inverse mapping on the grid, refined linearly with the 3 closest grid points
                d = (G[:, 2] - p.y) ** 2 + (G[:, 3] - p.x) ** 2
                idx = np.argsort(d)[:3]
                A = np.c_[G[idx, 3], G[idx, 2], np.ones(3)]
                try:
                    line = np.linalg.solve(A, G[idx, 0]) @ [p.x, p.y, 1]
                    pix = np.linalg.solve(A, G[idx, 1]) @ [p.x, p.y, 1]
                except np.linalg.LinAlgError:
                    line, pix = G[idx[0], 0], G[idx[0], 1]
                r, c = int(round(line)), int(round(pix))
                if 0 <= r < img.shape[0] and 0 <= c < img.shape[1]:
                    total += 1; zero += int(img[r, c] == 0)
    print('   sampled flood points inside frames: %d | on no-data (zero) pixels: %d' % (total, zero))
