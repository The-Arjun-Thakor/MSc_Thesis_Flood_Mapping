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
Main study: to keep the number of Climate Data Store requests small, one file is requested per month for
all AOIs of that month (their days and hours, over a box around all of them). Each AOI then reads its own
hour and its own cells from that file; the ERA5 values are the same as with one request per AOI.
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


def era5_box(xmin, ymin, xmax, ymax):
    """Bounding box widened to whole ERA5 cells plus one cell around it: north, west, south, east."""
    return (np.ceil(ymax / ERA5_STEP) * ERA5_STEP + ERA5_STEP, np.floor(xmin / ERA5_STEP) * ERA5_STEP - ERA5_STEP,
            np.floor(ymin / ERA5_STEP) * ERA5_STEP - ERA5_STEP, np.ceil(xmax / ERA5_STEP) * ERA5_STEP + ERA5_STEP)


def download(nc_path, hour, north, west, south, east, days=None, hours=None):
    import cdsapi
    request = {'product_type': ['reanalysis'],
               'variable': ['10m_u_component_of_wind', '10m_v_component_of_wind'],
               'year': ['%04d' % hour.year], 'month': ['%02d' % hour.month],
               'day': ['%02d' % d for d in (days or [hour.day])],
               'time': ['%02d:00' % h for h in (hours or [hour.hour])],
               'area': [float(north), float(west), float(south), float(east)],    # north, west, south, east
               'data_format': 'netcdf', 'download_format': 'unarchived'}
    print('requesting ERA5 from the Climate Data Store:', request)
    cdsapi.Client().retrieve('reanalysis-era5-single-levels', request, nc_path)


_MONTH_DONE = {}


def month_request(key):
    """Request of one month for all main-study AOIs of that month: file path and download arguments."""
    group = [a for a in aoi_paths.main_aois() if nearest_hour(a.acquisition_utc.to_pydatetime()).strftime('%Y%m') == key]
    hours_needed = sorted({nearest_hour(a.acquisition_utc.to_pydatetime()) for a in group})
    bounds = np.array([gpd.read_file(a.ems_aoi).to_crs(4326).total_bounds for a in group])
    north, west, south, east = era5_box(bounds[:, 0].min(), bounds[:, 1].min(), bounds[:, 2].max(), bounds[:, 3].max())
    nc_path = os.path.join(ERA5_DIR, 'ERA5_wind10m_main_%s.nc' % key)
    return nc_path, len(group), (hours_needed[0], north, west, south, east,
                                 sorted({h.day for h in hours_needed}), sorted({h.hour for h in hours_needed}))


def month_file(hour):
    """ERA5 file of one month for all main-study AOIs of that month (downloaded once)."""
    key = hour.strftime('%Y%m')
    if key in _MONTH_DONE:
        return _MONTH_DONE[key]
    nc_path, n, args = month_request(key)
    if not os.path.exists(nc_path):
        print('one request for %d AOIs of %s (%d hours)' % (n, key, len(args[6])))
        download(nc_path, *args[:5], days=args[5], hours=args[6])
    else:
        print('using the ERA5 file already downloaded:', nc_path)
    _MONTH_DONE[key] = nc_path
    return nc_path


def prefetch(aois):
    """Send the requests of all months that are still missing at the same time, so they wait in the
    Climate Data Store queue in parallel instead of one after the other."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    keys = sorted({nearest_hour(a.acquisition_utc.to_pydatetime()).strftime('%Y%m') for a in aois if not a.pilot})
    todo = []
    for k in keys:
        nc_path, n, args = month_request(k)
        if not os.path.exists(nc_path):
            todo.append((k, nc_path, n, args))
    if not todo:
        return
    print('sending %d monthly ERA5 requests at the same time: %s' % (len(todo), ', '.join(t[0] for t in todo)))
    os.makedirs(ERA5_DIR, exist_ok=True)

    def get(t):
        k, nc_path, n, args = t
        download(nc_path + '.part', *args[:5], days=args[5], hours=args[6])
        os.replace(nc_path + '.part', nc_path)
        return k, n

    with ThreadPoolExecutor(max_workers=len(todo)) as ex:
        futures = [ex.submit(get, t) for t in todo]
        for f in as_completed(futures):
            try:
                k, n = f.result()
                print('>>> ERA5 file for %s arrived (%d AOIs)' % (k, n))
            except Exception as e:
                print('>>> an ERA5 request failed: %s' % e)


def process(area):
    EVENT, AOI = area.event, area.aoi
    ACQUISITION_UTC = area.acquisition_utc.to_pydatetime()
    print('\n=== %s ===' % area)
    hour = nearest_hour(ACQUISITION_UTC)
    aoi = gpd.read_file(area.ems_aoi).to_crs(4326)
    shape = aoi.union_all() if hasattr(aoi, 'union_all') else aoi.unary_union
    xmin, ymin, xmax, ymax = shape.bounds
    north, west, south, east = era5_box(xmin, ymin, xmax, ymax)

    os.makedirs(ERA5_DIR, exist_ok=True)
    if area.pilot:
        nc_path = os.path.join(ERA5_DIR, 'ERA5_wind10m_%s_%s_%s.nc' % (EVENT, AOI, hour.strftime('%Y%m%dT%H00Z')))
        if os.path.exists(nc_path):
            print('using the ERA5 file already downloaded:', nc_path)
        else:
            download(nc_path, hour, north, west, south, east)
    else:
        nc_path = month_file(hour)

    ds = xr.open_dataset(nc_path)
    tname = 'valid_time' if 'valid_time' in ds.dims else ('time' if 'time' in ds.dims else None)
    if tname:                                            # monthly file: take this AOI's hour
        times = pd.to_datetime(ds[tname].values)
        if pd.Timestamp(hour) not in times:
            sys.exit('ERROR: %s does not contain %s - delete the file and run again' % (nc_path, hour))
        ds = ds.sel({tname: pd.Timestamp(hour)})
    # only the ERA5 cells around this AOI
    ds = ds.sel(latitude=slice(north, south), longitude=slice(west, east))
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
    aois = aoi_paths.from_args(__doc__)
    if len(aois) > 1:
        prefetch(aois)
    for a in aois:
        process(a)
    print('\ncode version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
