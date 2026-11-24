"""Q4 (extra check): does GFM set its rough-water advisory flag where ERA5 shows wind?

GFM advisory flag values: 1 = low regional backscatter, 2 = rough water surface (wind), 3 = both.
"Rough-water flag" below means the values 2 and 3.

Two tables in Results/:
  ..._Q4_roughwater_aoi_...csv     one row for the AOI: flagged area and share, next to the ERA5 wind label
  ..._Q4_roughwater_cells_...csv   one row per ERA5 cell: wind speed and share of the AOI part of the cell
                                   that carries the flag
The first table also gives the share of flagged cells inside the EMS-GFM comparison classes of Q1.

Needs the outputs of 02_make_grid20m.py and 06_era5_wind.py.
Usage:  python Scripts/07_roughwater_flag.py                         (pilot: EMSR866 AOI01)
        python Scripts/07_roughwater_flag.py --event EMSR788 --aoi AOI01
        python Scripts/07_roughwater_flag.py --all                    (all main-study AOIs)
"""
import glob, os, sys
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
import xarray as xr
from rasterio import features
from shapely.geometry import box

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aoi_paths
import provenance

STAMP = provenance.stamp()
ROUGH_VALUES = [2, 3]     # advisory flag values that include "rough water surface"
ERA5_STEP = 0.25
NODATA = 255

ERA5_DIR = aoi_paths.ERA5_DIR


def process(area):
    EVENT, AOI, GRID_DIR = area.event, area.aoi, area.grid_dir
    print('\n=== %s ===' % area)

    def load_tif(name):
        with rasterio.open(os.path.join(GRID_DIR, name)) as src:
            return src.read(1), src.transform, src.crs


    aoi, transform, crs = load_tif('aoi.tif')
    CELL_HA = abs(transform.a * transform.e) / 10000.0
    flag = load_tif('gfm_advflag.tif')[0]
    ems = load_tif('ems_flood.tif')[0]
    gfm = load_tif('gfm_flood.tif')[0]
    gfm_excl = load_tif('gfm_excl.tif')[0]
    wind = pd.read_csv(aoi_paths.result_csv(area, 'Q4_wind'))
    wind = wind[(wind['event'] == EVENT) & (wind['aoi'] == AOI)]
    if len(wind) != 1:
        sys.exit('ERROR: no wind row for %s - run 06_era5_wind.py first' % area)
    wind = wind.iloc[0]

    inside = (aoi == 1) & (flag != NODATA)          # AOI cells where the advisory layer has data
    rough = np.isin(flag, ROUGH_VALUES) & inside

    # ---- table 1: the AOI as a whole ----
    row = {'event': EVENT, 'aoi': AOI, 'era5_hour_utc': wind['era5_hour_utc'],
           'wind_mean_ms': wind['wind_mean_ms'], 'wind_label': wind['wind_label'],
           'aoi_with_flag_data_ha': round(int(inside.sum()) * CELL_HA, 2),
           'rough_flag_ha': round(int(rough.sum()) * CELL_HA, 2),
           'rough_flag_share': round(rough.sum() / inside.sum(), 4)}
    for v in (1, 2, 3):
        row['flag_value_%d_ha' % v] = round(int(((flag == v) & inside).sum()) * CELL_HA, 2)
    # share of flagged cells inside the EMS-GFM comparison classes (comparison area as in Q1)
    valid = (aoi == 1) & (ems != NODATA) & (gfm != NODATA) & (gfm_excl == 0)
    E, G = (ems == 1) & valid, (gfm == 1) & valid
    for name, cls in [('both_flood', E & G), ('ems_only', E & ~G), ('gfm_only', G & ~E), ('both_dry', valid & ~E & ~G)]:
        n = int(cls.sum())
        row['%s_ha' % name] = round(n * CELL_HA, 2)
        row['%s_rough_flag_share' % name] = round((cls & rough).sum() / n, 4) if n else np.nan
    row.update(STAMP)

    # ---- table 2: per ERA5 cell ----
    nc = sorted(glob.glob(os.path.join(ERA5_DIR, wind['era5_file'])))
    if not nc:
        sys.exit('ERROR: %s not found in %s - run 06_era5_wind.py first' % (wind['era5_file'], ERA5_DIR))
    ds = xr.open_dataset(nc[0])
    u, v = ds['u10'].squeeze(), ds['v10'].squeeze()
    speed = np.sqrt(u ** 2 + v ** 2)
    cells = []
    for lat in speed['latitude'].values:
        for lon in speed['longitude'].values:
            cells.append({'lat': float(lat), 'lon': float(lon), 'wind_ms': float(speed.sel(latitude=lat, longitude=lon)),
                          'geometry': box(lon - ERA5_STEP / 2, lat - ERA5_STEP / 2, lon + ERA5_STEP / 2, lat + ERA5_STEP / 2)})
    cells = gpd.GeoDataFrame(cells, crs=4326).to_crs(crs)
    cells['id'] = np.arange(1, len(cells) + 1)
    # every 20 m cell gets the id of the ERA5 cell its centre lies in
    cell_id = features.rasterize(zip(cells.geometry, cells['id']), out_shape=aoi.shape, transform=transform,
                                 fill=0, all_touched=False, dtype='int32')
    n_inside = np.bincount(cell_id[inside], minlength=len(cells) + 1)[1:]
    n_rough = np.bincount(cell_id[rough], minlength=len(cells) + 1)[1:]
    cells['aoi_with_flag_data_ha'] = n_inside * CELL_HA
    cells['rough_flag_ha'] = n_rough * CELL_HA
    cells = cells[n_inside > 0].copy()
    cells['rough_flag_share'] = cells['rough_flag_ha'] / cells['aoi_with_flag_data_ha']
    per_cell = cells[['lat', 'lon', 'wind_ms', 'aoi_with_flag_data_ha', 'rough_flag_ha', 'rough_flag_share']].round(4)
    per_cell.insert(0, 'aoi', AOI)
    per_cell.insert(0, 'event', EVENT)
    for k, val in STAMP.items():
        per_cell[k] = val
    assert abs(per_cell['aoi_with_flag_data_ha'].sum() - row['aoi_with_flag_data_ha']) < 1.0, 'ERA5 cells do not cover the AOI'

    aoi_paths.save_rows(area, 'Q4_roughwater_aoi', pd.DataFrame([row]))
    aoi_paths.save_rows(area, 'Q4_roughwater_cells', per_cell)

    print('ERA5 %s: area-average wind %.2f m/s -> %s' % (row['era5_hour_utc'], row['wind_mean_ms'], row['wind_label']))
    print('AOI with advisory-flag data : %10.1f ha' % row['aoi_with_flag_data_ha'])
    print('rough-water flag (2 or 3)   : %10.1f ha (%.2f%%)' % (row['rough_flag_ha'], 100 * row['rough_flag_share']))
    print('flag values (ha)            : 1 = %.1f | 2 = %.1f | 3 = %.1f'
          % (row['flag_value_1_ha'], row['flag_value_2_ha'], row['flag_value_3_ha']))
    print('\nshare of cells with the rough-water flag, by EMS-GFM class:')
    for name in ('both_flood', 'ems_only', 'gfm_only', 'both_dry'):
        print('  %-10s %10.1f ha : %6.2f%%' % (name, row['%s_ha' % name], 100 * row['%s_rough_flag_share' % name]))
    print('\nper ERA5 cell:')
    print(per_cell[['lat', 'lon', 'wind_ms', 'aoi_with_flag_data_ha', 'rough_flag_share']].round(3).to_string(index=False))
    if len(per_cell) > 2 and per_cell['wind_ms'].std() > 0 and per_cell['rough_flag_share'].std() > 0:
        print('\ncorrelation between wind speed and flag share over %d ERA5 cells: %.2f (description only)'
              % (len(per_cell), np.corrcoef(per_cell['wind_ms'], per_cell['rough_flag_share'])[0, 1]))
    print('\nsaved 2 tables to', aoi_paths.RESULTS)


def main():
    for a in aoi_paths.from_args(__doc__):
        process(a)
    print('\ncode version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
