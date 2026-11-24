"""Q3: how much of the EMS-GFM gap does the simple baseline also show?

The gap is the area where GFM disagrees with EMS. For each direction of the gap, the script measures the
share in which the baseline disagrees with EMS in the same cells and in the same direction:
  EMS flood, GFM dry   -> baseline is dry there as well   (both miss flooding that EMS shows)
  GFM flood, EMS dry   -> baseline is flooded there too   (both show flooding that EMS does not)

Comparison area: inside the AOI, all three maps have data, outside the GFM exclusion mask.
Extra column (description only): the part of each gap that lies on GFM reference water.

Usage:  python Scripts/05_gap_overlap.py                         (pilot: EMSR866 AOI01)
        python Scripts/05_gap_overlap.py --event EMSR788 --aoi AOI01
        python Scripts/05_gap_overlap.py --all                    (all main-study AOIs)
"""
import os, sys
import numpy as np
import pandas as pd
import rasterio

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aoi_paths
import provenance

STAMP = provenance.stamp()
NODATA = 255


def process(area):
    EVENT, AOI, GRID_DIR = area.event, area.aoi, area.grid_dir
    print('\n=== %s ===' % area)

    def load_tif(name):
        with rasterio.open(os.path.join(GRID_DIR, name)) as src:
            return src.read(1), abs(src.transform.a * src.transform.e) / 10000.0


    print('Loading maps for Q3...')
    aoi, CELL_HA = load_tif('aoi.tif')
    ems = load_tif('ems_flood.tif')[0]
    gfm = load_tif('gfm_flood.tif')[0]
    baseline = load_tif('baseline_flood.tif')[0]
    gfm_excl = load_tif('gfm_excl.tif')[0]
    gfm_water = load_tif('gfm_refwater.tif')[0]          # 1 = permanent, 2 = seasonal reference water

    # comparison area: all three maps must have data (a cell without baseline data is not "dry")
    valid = (aoi == 1) & (ems != NODATA) & (gfm != NODATA) & (baseline != NODATA) & (gfm_excl == 0)
    E, G, B = (ems == 1) & valid, (gfm == 1) & valid, (baseline == 1) & valid
    ref_water = (gfm_water == 1) | (gfm_water == 2)

    rows = []
    for direction, gap, same in [('EMS flood, GFM dry', E & ~G, ~B),      # baseline also dry
                                 ('GFM flood, EMS dry', G & ~E, B)]:       # baseline also flooded
        n_gap = int(gap.sum())
        n_same = int((gap & same).sum())
        n_ref = int((gap & ref_water).sum())
        rows.append({'event': EVENT, 'aoi': AOI, 'gap_direction': direction,
                     'comparison_area_ha': round(int(valid.sum()) * CELL_HA, 2),
                     'gap_ha': round(n_gap * CELL_HA, 2),
                     'baseline_same_direction_ha': round(n_same * CELL_HA, 2),
                     'baseline_same_direction_share': round(n_same / n_gap, 4) if n_gap else np.nan,
                     'gap_on_gfm_reference_water_ha': round(n_ref * CELL_HA, 2),
                     'gap_on_gfm_reference_water_share': round(n_ref / n_gap, 4) if n_gap else np.nan})
    df = pd.DataFrame(rows)
    # both directions together
    tot_gap, tot_same = df['gap_ha'].sum(), df['baseline_same_direction_ha'].sum()
    for k, v in STAMP.items():
        df[k] = v
    OUT_CSV = aoi_paths.save_rows(area, 'Q3_gap_overlap', df)

    print('\n--- Q3: baseline inside the EMS-GFM gap ---')
    print('comparison area: %.1f ha' % (int(valid.sum()) * CELL_HA))
    for r in rows:
        print('\n%s: %.1f ha' % (r['gap_direction'], r['gap_ha']))
        print('  baseline disagrees with EMS in the same direction: %.1f ha (%.2f%%)'
              % (r['baseline_same_direction_ha'], 100 * r['baseline_same_direction_share']))
        print('  on GFM reference water (description only)        : %.1f ha (%.2f%%)'
              % (r['gap_on_gfm_reference_water_ha'], 100 * r['gap_on_gfm_reference_water_share']))
    print('\nwhole gap, both directions: %.1f ha, of which the baseline shows %.1f ha (%.2f%%)'
          % (tot_gap, tot_same, 100 * tot_same / tot_gap if tot_gap else float('nan')))
    print('\nsaved', OUT_CSV)


def main():
    for a in aoi_paths.from_args(__doc__):
        process(a)
    print('\ncode version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
