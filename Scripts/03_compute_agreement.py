"""Q1: how well do the three flood maps of one AOI agree?

For each pair (first map, second map) on the common 20 m grid:
  IoU        = area flooded in both maps / area flooded in at least one of them
  omission   = share of the first map's flood area that the second map calls dry
  commission = share of the second map's flood area that the first map calls dry

Comparison area: inside the EMS AOI, where both maps have data. For the two pairs with GFM, cells inside
the GFM exclusion mask are left out as well. The result is printed and saved as a CSV table.

Usage:  python Scripts/03_compute_agreement.py            (pilot: EMSR866 AOI01)
"""
import csv, os, sys
import numpy as np
import rasterio

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT

EVENT, AOI = 'EMSR866_pilot', 'AOI01'
GRID_DIR = os.path.join(DATA_ROOT, '03_grid20m', EVENT, AOI)
OUT_CSV = os.path.join(REPO, 'Results', 'pilot_Q1_agreement_%s_%s.csv' % (EVENT, AOI))
NODATA = 255


def load_tif(name):
    with rasterio.open(os.path.join(GRID_DIR, name)) as src:
        return src.read(1), abs(src.transform.a * src.transform.e) / 10000.0   # array, cell area in ha


aoi, CELL_HA = load_tif('aoi.tif')
maps = {'EMS': load_tif('ems_flood.tif')[0],
        'GFM': load_tif('gfm_flood.tif')[0],
        'Baseline': load_tif('baseline_flood.tif')[0]}
gfm_excl = load_tif('gfm_excl.tif')[0]


def compute_metrics(name_a, name_b):
    map_a, map_b = maps[name_a], maps[name_b]
    # comparison area: inside the AOI and both maps have data
    valid = (aoi == 1) & (map_a != NODATA) & (map_b != NODATA)
    # pairs with GFM: also leave out the GFM exclusion mask (and cells where the mask has no data)
    uses_gfm = 'GFM' in (name_a, name_b)
    if uses_gfm:
        valid &= (gfm_excl == 0)
    a = (map_a == 1) & valid
    b = (map_b == 1) & valid

    n_a, n_b = int(a.sum()), int(b.sum())
    n_both, n_any = int((a & b).sum()), int((a | b).sum())
    iou = n_both / n_any if n_any else float('nan')
    omission = (n_a - n_both) / n_a if n_a else float('nan')        # in A, dry in B
    commission = (n_b - n_both) / n_b if n_b else float('nan')      # in B, dry in A
    row = {'event': EVENT, 'aoi': AOI, 'first_map': name_a, 'second_map': name_b,
           'gfm_exclusion_applied': uses_gfm,
           'comparison_area_ha': round(int(valid.sum()) * CELL_HA, 2),
           'first_flood_ha': round(n_a * CELL_HA, 2), 'second_flood_ha': round(n_b * CELL_HA, 2),
           'both_ha': round(n_both * CELL_HA, 2),
           'first_only_ha': round((n_a - n_both) * CELL_HA, 2),
           'second_only_ha': round((n_b - n_both) * CELL_HA, 2),
           'iou': round(iou, 4), 'omission': round(omission, 4), 'commission': round(commission, 4)}

    print('\n--- %s vs %s ---%s' % (name_a, name_b, '  (GFM exclusion mask left out)' if uses_gfm else ''))
    print('comparison area : %10.1f ha' % row['comparison_area_ha'])
    print('%-8s flood  : %10.1f ha' % (name_a, row['first_flood_ha']))
    print('%-8s flood  : %10.1f ha' % (name_b, row['second_flood_ha']))
    print('both            : %10.1f ha' % row['both_ha'])
    print('IoU             : %.4f' % iou)
    print('omission   (%s flood that %s calls dry): %.2f%%' % (name_a, name_b, 100 * omission))
    print('commission (%s flood that %s calls dry): %.2f%%' % (name_b, name_a, 100 * commission))
    return row


rows = [compute_metrics('EMS', 'GFM'), compute_metrics('EMS', 'Baseline'), compute_metrics('GFM', 'Baseline')]
os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
with open(OUT_CSV, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)
print('\nsaved', OUT_CSV)
