"""Baseline flood mask (steps 5 and 6 of the baseline pipeline) from the two SNAP outputs of one AOI.

A pixel is flooded if its VV sigma0 is below THRESHOLD_DB after the flood and at or above THRESHOLD_DB
before it. Flooded patches smaller than MIN_PATCH_HA are removed. Output: one GeoTIFF on the 10 m SNAP grid
with 1 = flooded, 0 = not flooded, 255 = no data.

The pre- and post-flood images lie on the same standard 10 m grid (RULES.md, rule 19) but may cover
slightly different areas; only the area both cover is used.

Usage:  python Scripts/01_threshold_and_mask.py                         (pilot: EMSR866 AOI01)
        python Scripts/01_threshold_and_mask.py --event EMSR788 --aoi AOI01
        python Scripts/01_threshold_and_mask.py --all                    (all main-study AOIs)
"""
import os, sys
import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.windows import Window
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aoi_paths
import provenance

STAMP = provenance.stamp()

# ---- fixed rules (locked in git after the pilot) ----
THRESHOLD_DB = -16.5      # UN-SPIDER tutorial threshold, applied to VV sigma0 in dB
MIN_PATCH_HA = 0.5        # flooded patches smaller than this are removed
CONNECTIVITY = 8          # pixels touching by an edge or a corner belong to the same patch
NODATA = 255


def to_db(lin):
    """Linear sigma0 -> dB. Zero or negative values (no data) become NaN."""
    out = np.full(lin.shape, np.nan, dtype=np.float32)
    ok = lin > 0
    out[ok] = 10.0 * np.log10(lin[ok])
    return out


def common_area(tp, tq, wp, hp, wq, hq):
    """Pixel offsets of the area covered by both images. Stops if the grids are not the same."""
    if abs(tp.a - tq.a) > 1e-6 or abs(tp.e - tq.e) > 1e-6:
        sys.exit('ERROR: pre and post image have different pixel sizes')
    dx = (tq.c - tp.c) / tp.a                  # column of the pre image's left edge in the post image
    dy = (tq.f - tp.f) / tp.e                  # row of the pre image's top edge in the post image
    if abs(dx - round(dx)) > 1e-3 or abs(dy - round(dy)) > 1e-3:
        sys.exit('ERROR: pre and post image are not on the same pixel grid - check the SNAP graph '
                 '(alignToStandardGrid) before going on.')
    dx, dy = int(round(dx)), int(round(dy))
    c0, r0 = max(0, dx), max(0, dy)                          # in post-image pixels
    c1, r1 = min(wp, dx + wq), min(hp, dy + hq)
    if c1 <= c0 or r1 <= r0:
        sys.exit('ERROR: pre and post image do not overlap')
    return c0, r0, c1 - c0, r1 - r0, c0 - dx, r0 - dy        # post col/row, width, height, pre col/row


def process(a):
    post_path = os.path.join(a.post_data, 'Sigma0_VV.img')
    pre_path = os.path.join(a.pre_data, 'Sigma0_VV.img')
    print('\n=== %s ===' % a)
    with rasterio.open(post_path) as post, rasterio.open(pre_path) as pre:
        tp, tq = post.transform, pre.transform
        print('post: %d x %d px, origin %.2f %.2f' % (post.width, post.height, tp.c, tp.f))
        print('pre : %d x %d px, origin %.2f %.2f' % (pre.width, pre.height, tq.c, tq.f))
        pc, pr, W, H, qc, qr = common_area(tp, tq, post.width, post.height, pre.width, pre.height)
        print('same grid: yes | common area %d x %d px (pre image offset %+d, %+d px)' % (W, H, qc - pc, qr - pr))
        out_transform = tp * Affine.translation(pc, pr)
        px_area_m2 = abs(tp.a * tp.e)
        min_px = int(np.ceil(MIN_PATCH_HA * 10000.0 / px_area_m2))

        # threshold + pre-flood test, in blocks of rows to keep memory low
        flood = np.zeros((H, W), dtype=bool)
        valid = np.zeros((H, W), dtype=bool)
        n_post_low = n_both_low = 0
        for r0 in range(0, H, 2048):
            h = min(2048, H - r0)
            b_post = to_db(post.read(1, window=Window(pc, pr + r0, W, h)))
            b_pre = to_db(pre.read(1, window=Window(qc, qr + r0, W, h)))
            ok = ~np.isnan(b_post) & ~np.isnan(b_pre)
            with np.errstate(invalid='ignore'):
                post_low = ok & (b_post < THRESHOLD_DB)
                pre_low = ok & (b_pre < THRESHOLD_DB)
            valid[r0:r0 + h] = ok
            flood[r0:r0 + h] = post_low & ~pre_low
            n_post_low += int(post_low.sum()); n_both_low += int((post_low & pre_low).sum())
        profile = dict(driver='GTiff', height=H, width=W, count=1, dtype='uint8', crs=post.crs,
                       transform=out_transform, nodata=NODATA, compress='deflate', tiled=True)

    # remove flooded patches smaller than MIN_PATCH_HA
    structure = np.ones((3, 3), dtype=bool) if CONNECTIVITY == 8 else None
    n_before = int(flood.sum())
    labels, n_patches = ndimage.label(flood, structure=structure)
    sizes = np.bincount(labels.ravel())
    keep = sizes >= min_px
    keep[0] = False
    flood = keep[labels]
    del labels
    n_after = int(flood.sum())

    out = np.where(valid, flood.astype(np.uint8), NODATA).astype(np.uint8)
    with rasterio.open(a.baseline_10m, 'w', **profile) as dst:
        dst.write(out, 1)
        dst.update_tags(threshold_db=str(THRESHOLD_DB), min_patch_ha=str(MIN_PATCH_HA),
                        connectivity=str(CONNECTIVITY), post=os.path.basename(a.post_data),
                        pre=os.path.basename(a.pre_data), **STAMP)

    ha = px_area_m2 / 10000.0
    print('rules: threshold %.1f dB | min patch %.1f ha = %d px | connectivity %d'
          % (THRESHOLD_DB, MIN_PATCH_HA, min_px, CONNECTIVITY))
    print('valid pixels                         : %12d  (%.0f ha)' % (valid.sum(), valid.sum() * ha))
    print('post below threshold                 : %12d  (%.0f ha)' % (n_post_low, n_post_low * ha))
    print('  of these also below before (water) : %12d  (%.0f ha)' % (n_both_low, n_both_low * ha))
    print('flooded before patch filter          : %12d  (%.0f ha) in %d patches' % (n_before, n_before * ha, n_patches))
    print('flooded after patch filter           : %12d  (%.0f ha) in %d patches' % (n_after, n_after * ha, int(keep.sum())))
    print('saved', a.baseline_10m)


def main():
    for a in aoi_paths.from_args(__doc__):
        process(a)
    print('\ncode version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
