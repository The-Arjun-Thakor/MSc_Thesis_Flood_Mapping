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
Main study: the Climate Data Store handles requests one at a time and can queue each for a long time, so
all AOIs are served by one single request (every hour any AOI needs, over a box around all AOIs). Each AOI
then reads its own hour and its own cells from that file; the ERA5 values are the same as with one request
per AOI.
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


_ALL_FILE = []


def all_file():
    """One ERA5 file for all main-study AOIs, downloaded with a single Climate Data Store request.

    The Climate Data Store queues requests one after the other and rejects parallel ones, so a single
    request is the fastest way. It asks for every year, month, day and hour that any AOI needs (the
    request is a cross product, so it also holds hours no AOI uses), over one box around all AOIs.
    Each AOI then reads only its own hour and its own cells."""
    if _ALL_FILE:
        return _ALL_FILE[0]
    nc_path = os.path.join(ERA5_DIR, 'ERA5_wind10m_main_all.nc')
    aois = aoi_paths.main_aois()
    hours_needed = sorted({nearest_hour(a.acquisition_utc.to_pydatetime()) for a in aois})
    if os.path.exists(nc_path):
        print('using the ERA5 file already downloaded:', nc_path)
    else:
        bounds = np.array([gpd.read_file(a.ems_aoi).to_crs(4326).total_bounds for a in aois])
        north, west, south, east = era5_box(bounds[:, 0].min(), bounds[:, 1].min(), bounds[:, 2].max(), bounds[:, 3].max())
        import cdsapi
        request = {'product_type': ['reanalysis'],
                   'variable': ['10m_u_component_of_wind', '10m_v_component_of_wind'],
                   'year': sorted({'%04d' % h.year for h in hours_needed}),
                   'month': sorted({'%02d' % h.month for h in hours_needed}),
                   'day': sorted({'%02d' % h.day for h in hours_needed}),
                   'time': sorted({'%02d:00' % h.hour for h in hours_needed}),
                   'area': [float(north), float(west), float(south), float(east)],
                   'data_format': 'netcdf', 'download_format': 'unarchived'}
        print('one request for all %d main-study AOIs (%d hours needed):' % (len(aois), len(hours_needed)), request)
        os.makedirs(ERA5_DIR, exist_ok=True)
        cdsapi.Client().retrieve('reanalysis-era5-single-levels', request, nc_path + '.part')
        os.replace(nc_path + '.part', nc_path)
    _ALL_FILE.append(nc_path)
    return nc_path


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
        nc_path = all_file()

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
    for a in aois:
        process(a)
    print('\ncode version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
