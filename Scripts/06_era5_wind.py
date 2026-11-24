"""Q4 (wind): ERA5 10 m wind over one AOI at the hour nearest to the Sentinel-1 acquisition.

1. Downloads the ERA5 u and v wind components for that hour from the Climate Data Store (once; the file
   is kept on the data drive). Needs the cdsapi package and the CDS key in the file .cdsapirc in the
   user's home folder. The key is never written into this repository.
2. Computes the wind speed sqrt(u^2 + v^2) of every ERA5 cell (0.25 degree) and averages it over the AOI,
   each cell weighted by the area of the AOI that lies in it.
3. Labels the AOI 'windy' if the area-average speed is above WIND_LIMIT_MS, otherwise 'calm'.

Usage:  python Scripts/06_era5_wind.py                         (pilot: EMSR866 AOI01)
        python Scripts/06_era5_wind.py --event EMSR788 --aoi AOI01
        python Scripts/06_era5_wind.py --all                    (all main-study AOIs)
The acquisition time is the EMS time for the pilot and the start of the post-flood pass for the main study.
"""
import datetime, os, sys
import numpy as np
import pandas as pd
import geopandas as gpd
import xarray as xr
from shapely.geometry import box

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aoi_paths
import provenance

STAMP = provenance.stamp()

# ---- fixed rules (locked in git after the pilot) ----
WIND_LIMIT_MS = 3.3       # upper limit of a light breeze (Beaufort 2); above it the AOI counts as windy
ERA5_STEP = 0.25          # ERA5 grid spacing in degrees

ERA5_DIR = aoi_paths.ERA5_DIR


def nearest_hour(t):
    return (t + datetime.timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)


def download(nc_path, hour, north, west, south, east):
    import cdsapi
    request = {'product_type': ['reanalysis'],
               'variable': ['10m_u_component_of_wind', '10m_v_component_of_wind'],
               'year': ['%04d' % hour.year], 'month': ['%02d' % hour.month], 'day': ['%02d' % hour.day],
               'time': ['%02d:00' % hour.hour],
               'area': [north, west, south, east],           # north, west, south, east
               'data_format': 'netcdf', 'download_format': 'unarchived'}
    print('requesting ERA5 from the Climate Data Store:', request)
    cdsapi.Client().retrieve('reanalysis-era5-single-levels', request, nc_path)


def process(area):
    EVENT, AOI = area.event, area.aoi
    ACQUISITION_UTC = area.acquisition_utc.to_pydatetime()
    print('\n=== %s ===' % area)
    hour = nearest_hour(ACQUISITION_UTC)
    aoi = gpd.read_file(area.ems_aoi).to_crs(4326)
    shape = aoi.union_all() if hasattr(aoi, 'union_all') else aoi.unary_union
    xmin, ymin, xmax, ymax = shape.bounds
    # request box: the AOI bounding box, widened to whole ERA5 cells plus one cell around it
    west = np.floor(xmin / ERA5_STEP) * ERA5_STEP - ERA5_STEP
    east = np.ceil(xmax / ERA5_STEP) * ERA5_STEP + ERA5_STEP
    south = np.floor(ymin / ERA5_STEP) * ERA5_STEP - ERA5_STEP
    north = np.ceil(ymax / ERA5_STEP) * ERA5_STEP + ERA5_STEP

    os.makedirs(ERA5_DIR, exist_ok=True)
    nc_path = os.path.join(ERA5_DIR, 'ERA5_wind10m_%s_%s_%s.nc' % (EVENT, AOI, hour.strftime('%Y%m%dT%H00Z')))
    if os.path.exists(nc_path):
        print('using the ERA5 file already downloaded:', nc_path)
    else:
        download(nc_path, hour, north, west, south, east)

    ds = xr.open_dataset(nc_path)
    u, v = ds['u10'].squeeze(), ds['v10'].squeeze()
    if set(u.dims) != {'latitude', 'longitude'}:
        sys.exit('ERROR: expected one time step with latitude/longitude, got %s' % (u.dims,))
    file_time = None
    for name in ('valid_time', 'time'):
        if name in ds.coords:
            file_time = pd.Timestamp(np.atleast_1d(ds[name].values)[0]).to_pydatetime()
    if file_time is not None and file_time != hour:
        sys.exit('ERROR: the file holds %s, expected %s' % (file_time, hour))
    speed = np.sqrt(u ** 2 + v ** 2)

    # weight of each ERA5 cell = area of the AOI inside the cell (the cell is centred on the grid point)
    utm = aoi.estimate_utm_crs()
    cells = []
    for lat in speed['latitude'].values:
        for lon in speed['longitude'].values:
            cell = box(lon - ERA5_STEP / 2, lat - ERA5_STEP / 2, lon + ERA5_STEP / 2, lat + ERA5_STEP / 2)
            part = cell.intersection(shape)
            if not part.is_empty:
                cells.append({'lat': float(lat), 'lon': float(lon), 'geometry': part,
                              'speed': float(speed.sel(latitude=lat, longitude=lon)),
                              'u10': float(u.sel(latitude=lat, longitude=lon)),
                              'v10': float(v.sel(latitude=lat, longitude=lon))})
    cells = gpd.GeoDataFrame(cells, crs=4326)
    cells['aoi_area_ha'] = cells.to_crs(utm).area / 10000.0
    covered = cells['aoi_area_ha'].sum() / (aoi.to_crs(utm).area.sum() / 10000.0)
    if abs(covered - 1.0) > 0.001:
        sys.exit('ERROR: the ERA5 cells cover only %.1f%% of the AOI' % (100 * covered))
    mean_speed = float((cells['speed'] * cells['aoi_area_ha']).sum() / cells['aoi_area_ha'].sum())
    label = 'windy' if mean_speed > WIND_LIMIT_MS else 'calm'

    row = {'event': EVENT, 'aoi': AOI, 'acquisition_utc': ACQUISITION_UTC.strftime('%Y-%m-%dT%H:%MZ'),
           'era5_hour_utc': hour.strftime('%Y-%m-%dT%H:%MZ'), 'era5_cells': len(cells),
           'wind_mean_ms': round(mean_speed, 2), 'wind_min_ms': round(float(cells['speed'].min()), 2),
           'wind_max_ms': round(float(cells['speed'].max()), 2), 'wind_limit_ms': WIND_LIMIT_MS,
           'wind_label': label, 'era5_file': os.path.basename(nc_path)}
    row.update(STAMP)
    OUT_CSV = aoi_paths.save_rows(area, 'Q4_wind', pd.DataFrame([row]))

    print('\nERA5 hour %s (acquisition %s)' % (row['era5_hour_utc'], row['acquisition_utc']))
    print(cells[['lat', 'lon', 'aoi_area_ha', 'u10', 'v10', 'speed']].round(2).to_string(index=False))
    print('\narea-average wind speed over the AOI: %.2f m/s (cells: min %.2f, max %.2f) -> %s (limit %.1f m/s)'
          % (mean_speed, row['wind_min_ms'], row['wind_max_ms'], label, WIND_LIMIT_MS))
    print('saved', OUT_CSV)


def main():
    for a in aoi_paths.from_args(__doc__):
        process(a)
    print('\ncode version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
