"""Baseline flood mask (steps 5 and 6 of the baseline pipeline) from the two SNAP outputs of one AOI.

A pixel is flooded if its VV sigma0 is below THRESHOLD_DB after the flood and at or above THRESHOLD_DB
before it. Flooded patches smaller than MIN_PATCH_HA are removed. Output: one GeoTIFF on the 10 m SNAP grid
with 1 = flooded, 0 = not flooded, 255 = no data.

Usage:  python Scripts/01_threshold_and_mask.py            (pilot: EMSR866 AOI01)
"""
import os, sys
import numpy as np
import rasterio
from rasterio.windows import Window
from scipy import ndimage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')))
from config import DATA_ROOT

# ---- fixed rules (locked in git after the pilot) ----
THRESHOLD_DB = -16.5      # UN-SPIDER tutorial threshold, applied to VV sigma0 in dB
MIN_PATCH_HA = 0.5        # flooded patches smaller than this are removed
CONNECTIVITY = 8          # pixels touching by an edge or a corner belong to the same patch
NODATA = 255

# ---- inputs / output (pilot) ----
BASE = os.path.join(DATA_ROOT, '02_snap_out', 'EMSR866_pilot', 'AOI01')
POST = os.path.join(BASE, 'S1_20260212_TC.data', 'Sigma0_VV.img')
PRE = os.path.join(BASE, 'S1_20260131_TC.data', 'Sigma0_VV.img')
OUT = os.path.join(BASE, 'baseline_flood_10m.tif')


def to_db(lin):
    """Linear sigma0 -> dB. Zero or negative values (no data) become NaN."""
    out = np.full(lin.shape, np.nan, dtype=np.float32)
    ok = lin > 0
    out[ok] = 10.0 * np.log10(lin[ok])
    return out


def main():
    with rasterio.open(POST) as post, rasterio.open(PRE) as pre:
        # 1. the two images must sit on the same pixel grid (same pixel size, same upper-left corner)
        tp, tq = post.transform, pre.transform
        same_grid = (abs(tp.a - tq.a) < 1e-6 and abs(tp.e - tq.e) < 1e-6 and
                     abs(tp.c - tq.c) < 1e-3 and abs(tp.f - tq.f) < 1e-3)
        print('post: %d x %d px, origin %.2f %.2f' % (post.width, post.height, tp.c, tp.f))
        print('pre : %d x %d px, origin %.2f %.2f' % (pre.width, pre.height, tq.c, tq.f))
        if not same_grid:
            sys.exit('ERROR: pre and post image are not on the same grid - check the SNAP graph '
                     '(alignToStandardGrid) before going on.')
        # the images may differ by a row/column at the far edge: use the part both cover
        W, H = min(post.width, pre.width), min(post.height, pre.height)
        print('same grid: yes | common area %d x %d px' % (W, H))
        px_area_m2 = abs(tp.a * tp.e)
        min_px = int(np.ceil(MIN_PATCH_HA * 10000.0 / px_area_m2))

        # 2. threshold + pre-flood test, in blocks of rows to keep memory low
        flood = np.zeros((H, W), dtype=bool)
        valid = np.zeros((H, W), dtype=bool)
        n_post_low = n_both_low = 0
        for r0 in range(0, H, 2048):
            win = Window(0, r0, W, min(2048, H - r0))
            a = to_db(post.read(1, window=win))
            b = to_db(pre.read(1, window=win))
            ok = ~np.isnan(a) & ~np.isnan(b)
            with np.errstate(invalid='ignore'):
                post_low = ok & (a < THRESHOLD_DB)
                pre_low = ok & (b < THRESHOLD_DB)
            sl = slice(r0, r0 + win.height)
            valid[sl] = ok
            flood[sl] = post_low & ~pre_low
            n_post_low += int(post_low.sum()); n_both_low += int((post_low & pre_low).sum())
        profile = dict(driver='GTiff', height=H, width=W, count=1, dtype='uint8', crs=post.crs,
                       transform=tp, nodata=NODATA, compress='deflate', tiled=True)

    # 3. remove flooded patches smaller than MIN_PATCH_HA
    structure = np.ones((3, 3), dtype=bool) if CONNECTIVITY == 8 else None
    n_before = int(flood.sum())
    labels, n_patches = ndimage.label(flood, structure=structure)
    sizes = np.bincount(labels.ravel())
    keep = sizes >= min_px
    keep[0] = False
    flood = keep[labels]
    del labels
    n_after = int(flood.sum())

    # 4. write
    out = np.where(valid, flood.astype(np.uint8), NODATA).astype(np.uint8)
    with rasterio.open(OUT, 'w', **profile) as dst:
        dst.write(out, 1)
        dst.update_tags(threshold_db=str(THRESHOLD_DB), min_patch_ha=str(MIN_PATCH_HA),
                        connectivity=str(CONNECTIVITY), post=os.path.basename(os.path.dirname(POST)),
                        pre=os.path.basename(os.path.dirname(PRE)))

    ha = px_area_m2 / 10000.0
    print('\nrules: threshold %.1f dB | min patch %.1f ha = %d px | connectivity %d'
          % (THRESHOLD_DB, MIN_PATCH_HA, min_px, CONNECTIVITY))
    print('valid pixels                         : %12d  (%.0f ha)' % (valid.sum(), valid.sum() * ha))
    print('post below threshold                 : %12d  (%.0f ha)' % (n_post_low, n_post_low * ha))
    print('  of these also below before (water) : %12d  (%.0f ha)' % (n_both_low, n_both_low * ha))
    print('flooded before patch filter          : %12d  (%.0f ha) in %d patches' % (n_before, n_before * ha, n_patches))
    print('flooded after patch filter           : %12d  (%.0f ha) in %d patches' % (n_after, n_after * ha, int(keep.sum())))
    print('saved', OUT)


if __name__ == '__main__':
    main()
