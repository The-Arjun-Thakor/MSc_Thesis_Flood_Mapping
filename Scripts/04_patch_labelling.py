"""Q2: where does the disagreement between two flood maps sit?

For each pair of maps and each direction (flood only in the first map / only in the second map):
  1. take the cells where the two maps disagree, inside the comparison area of Q1;
  2. group them into connected patches (cells touching by an edge or a corner);
  3. patches smaller than MIN_PATCH_CELLS go into one "small patches" total;
  4. every other patch gets exactly one label, in this fixed order:
       layover/shadow       if at least half of its cells are layover or shadow (SNAP mask)
       built-up/tree cover  if at least half of its cells are WorldCover built-up (50) or tree cover (10)
       unexplained          otherwise
  5. the mean local incidence angle of each patch is recorded.

Outputs in Results/:
  ..._Q2_patches_...csv   one row per labelled patch
  ..._Q2_summary_...csv   area and share per pair, direction and label (shares add up to 100 %)
  ..._Q2_unexplained_landcover_...csv   description only: WorldCover classes inside the unexplained patches

Usage:  python Scripts/04_patch_labelling.py            (pilot: EMSR866 AOI01)
"""
import os, sys
import numpy as np
import pandas as pd
import rasterio
from scipy import ndimage

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT
import provenance

STAMP = provenance.stamp()

# ---- fixed rules (locked in git after the pilot) ----
MIN_PATCH_CELLS = 13          # 13 cells x 0.04 ha = 0.52 ha: every labelled patch is at least 0.5 ha
CONNECTIVITY = 8              # cells touching by an edge or a corner belong to the same patch
MIN_SHARE = 0.5               # a label needs at least half of the patch
WC_BUILTUP_TREE = [50, 10]    # ESA WorldCover classes: 50 built-up, 10 tree cover
NODATA = 255

EVENT, AOI = 'EMSR866_pilot', 'AOI01'
GRID_DIR = os.path.join(DATA_ROOT, '03_grid20m', EVENT, AOI)
OUT_DIR = os.path.join(REPO, 'Results')
LABELS = ['layover/shadow', 'built-up/tree cover', 'unexplained', 'small patches']
WC_NAMES = {10: 'tree cover', 20: 'shrubland', 30: 'grassland', 40: 'cropland', 50: 'built-up',
            60: 'bare / sparse vegetation', 70: 'snow and ice', 80: 'permanent water bodies',
            90: 'herbaceous wetland', 95: 'mangroves', 100: 'moss and lichen', 255: 'no data'}


def load_tif(name):
    with rasterio.open(os.path.join(GRID_DIR, name)) as src:
        return src.read(1), abs(src.transform.a * src.transform.e) / 10000.0


print('Loading maps...')
aoi, CELL_HA = load_tif('aoi.tif')
maps = {'EMS': load_tif('ems_flood.tif')[0], 'GFM': load_tif('gfm_flood.tif')[0],
        'Baseline': load_tif('baseline_flood.tif')[0]}
gfm_excl = load_tif('gfm_excl.tif')[0]
is_layover = load_tif('layover_shadow.tif')[0] == 1
worldcover = load_tif('worldcover.tif')[0]
is_builtup_tree = np.isin(worldcover, WC_BUILTUP_TREE)
lia = load_tif('lia.tif')[0]                 # mean local incidence angle per cell, -1 = no data
lia_ok = lia > 0
STRUCTURE = np.ones((3, 3), dtype=bool) if CONNECTIVITY == 8 else None


def comparison_area(name_a, name_b):
    """Same comparison area as in Q1."""
    valid = (aoi == 1) & (maps[name_a] != NODATA) & (maps[name_b] != NODATA)
    if 'GFM' in (name_a, name_b):
        valid &= (gfm_excl == 0)
    return valid


def label_patches(diff, pair, direction):
    """Label the patches of one disagreement mask. Returns one row per patch (small patches included)
    and the number of cells per WorldCover class inside the unexplained patches."""
    labeled, n = ndimage.label(diff, structure=STRUCTURE)
    if n == 0:
        return pd.DataFrame(), np.zeros(256, dtype=np.int64)
    ids = labeled[diff]                                   # patch id of every disagreeing cell
    count = lambda weights=None: np.bincount(ids, weights=weights, minlength=n + 1)[1:]
    cells = count()
    share_layover = count(is_layover[diff]) / cells
    share_cover = count(is_builtup_tree[diff]) / cells
    lia_n = count(lia_ok[diff])
    lia_sum = count(np.where(lia_ok[diff], lia[diff], 0.0))
    # most frequent WorldCover class per patch (description only, not used for the label)
    wc_counts = np.bincount(ids * 256 + worldcover[diff], minlength=(n + 1) * 256).reshape(n + 1, 256)[1:]
    main_wc = wc_counts.argmax(axis=1)

    label = np.full(n, 'unexplained', dtype=object)
    label[share_cover >= MIN_SHARE] = 'built-up/tree cover'
    label[share_layover >= MIN_SHARE] = 'layover/shadow'         # first in the order, so it wins
    label[cells < MIN_PATCH_CELLS] = 'small patches'
    wc_unexplained = wc_counts[label == 'unexplained'].sum(axis=0)
    return pd.DataFrame({'event': EVENT, 'aoi': AOI, 'pair': pair, 'direction': direction,
                         'patch_id': np.arange(1, n + 1), 'cells': cells.astype(int),
                         'area_ha': cells * CELL_HA, 'share_layover_shadow': share_layover,
                         'share_builtup_tree': share_cover, 'label': label,
                         'lia_cells': lia_n.astype(int), 'lia_sum': lia_sum,
                         'mean_lia_deg': np.where(lia_n > 0, lia_sum / np.maximum(lia_n, 1), np.nan),
                         'main_worldcover_class': main_wc}), wc_unexplained


patches, landcover = [], []
for name_a, name_b in [('EMS', 'GFM'), ('EMS', 'Baseline'), ('GFM', 'Baseline')]:
    valid = comparison_area(name_a, name_b)
    a = (maps[name_a] == 1) & valid
    b = (maps[name_b] == 1) & valid
    pair = '%s vs %s' % (name_a, name_b)
    for diff, direction in [(a & ~b, '%s only' % name_a), (b & ~a, '%s only' % name_b)]:
        df, wc_cells = label_patches(diff, pair, direction)
        patches.append(df)
        for cls in np.nonzero(wc_cells)[0]:
            landcover.append({'event': EVENT, 'aoi': AOI, 'pair': pair, 'direction': direction,
                              'worldcover_class': int(cls), 'class_name': WC_NAMES.get(int(cls), 'other'),
                              'area_ha': round(wc_cells[cls] * CELL_HA, 2),
                              'percent_of_unexplained': round(100.0 * wc_cells[cls] / wc_cells.sum(), 2)})
patches = pd.concat(patches, ignore_index=True)

# summary per pair, direction and label
rows = []
for (pair, direction), g in patches.groupby(['pair', 'direction'], sort=False):
    total = g['area_ha'].sum()
    for lab in LABELS:
        s = g[g['label'] == lab]
        rows.append({'event': EVENT, 'aoi': AOI, 'pair': pair, 'direction': direction, 'label': lab,
                     'patches': len(s), 'area_ha': round(s['area_ha'].sum(), 2),
                     'percent': round(100.0 * s['area_ha'].sum() / total, 2),
                     'mean_lia_deg': round(s['lia_sum'].sum() / s['lia_cells'].sum(), 2) if s['lia_cells'].sum() else np.nan,
                     'disagreement_total_ha': round(total, 2)})
summary = pd.DataFrame(rows)
# check: the labels of each pair and direction add up to the whole disagreeing area
check = summary.groupby(['pair', 'direction'])['percent'].sum()
assert (abs(check - 100.0) < 0.05).all(), 'shares do not add up to 100 %'
landcover = pd.DataFrame(landcover)
# check: the land-cover table covers exactly the unexplained area of the summary
unexpl = summary[summary['label'] == 'unexplained'].set_index(['pair', 'direction'])['area_ha']
assert (abs(landcover.groupby(['pair', 'direction'])['area_ha'].sum() - unexpl[unexpl > 0]) < 0.5).all()
for k, v in STAMP.items():
    summary[k] = v
    patches[k] = v
    landcover[k] = v

os.makedirs(OUT_DIR, exist_ok=True)
tag = '%s_%s' % (EVENT, AOI)
keep = patches[patches['label'] != 'small patches'].drop(columns=['lia_cells', 'lia_sum']).round(4)
keep.to_csv(os.path.join(OUT_DIR, 'pilot_Q2_patches_%s.csv' % tag), index=False)
summary.to_csv(os.path.join(OUT_DIR, 'pilot_Q2_summary_%s.csv' % tag), index=False)
landcover.to_csv(os.path.join(OUT_DIR, 'pilot_Q2_unexplained_landcover_%s.csv' % tag), index=False)

pd.set_option('display.width', 200)
print('\nrules: min patch %d cells (%.2f ha) | connectivity %d | min share %.0f%%'
      % (MIN_PATCH_CELLS, MIN_PATCH_CELLS * CELL_HA, CONNECTIVITY, 100 * MIN_SHARE))
print(summary[['pair', 'direction', 'label', 'patches', 'area_ha', 'percent', 'mean_lia_deg']].to_string(index=False))
print('\nLand cover inside the unexplained patches (description only, not a label):')
print(landcover[['pair', 'direction', 'class_name', 'area_ha', 'percent_of_unexplained']].to_string(index=False))
print('\nsaved 3 tables to', OUT_DIR)
print('code version: %(git_commit)s | run: %(run_utc)s' % STAMP)
