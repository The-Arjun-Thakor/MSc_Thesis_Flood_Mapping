"""Put the three flood maps and the driver layers of one AOI on one common 20 m grid.

Grid: the UTM zone of the SNAP output, 20 m cells, cell edges at 5 m + n * 20 m in easting and northing,
so that every 20 m cell holds exactly four 10 m SNAP pixels. Extent: bounding box of the EMS AOI.

Layers written to 03_grid20m/<event>/<AOI>/ (GeoTIFF, uint8 unless stated; 255 = no data):
  aoi.tif             1 inside the EMS area of interest, 0 outside
  ems_flood.tif       1 where the centre of the cell lies in an EMS observed-flood polygon
  baseline_flood.tif  1 where at least BASELINE_MIN_OF_4 of the four 10 m baseline pixels are flooded
  gfm_flood.tif       GFM ensemble flood extent (nearest neighbour; flood if any overlapping scene says flood)
  gfm_excl.tif        GFM exclusion mask (nearest neighbour; excluded if any overlapping scene says so)
  gfm_advflag.tif     GFM advisory flags (nearest neighbour; flags of overlapping scenes combined)
  gfm_refwater.tif    GFM reference water mask for the month (nearest neighbour; 1 = permanent, 2 = seasonal)
  layover_shadow.tif  1 where at least 2 of the four 10 m pixels are layover or shadow (SNAP mask)
  lia.tif             mean local incidence angle of the four 10 m pixels, degrees (float32, nodata -1)
  worldcover.tif      ESA WorldCover 2021 class (most frequent class in the cell)

Usage:  python Scripts/02_make_grid20m.py                         (pilot: EMSR866 AOI01)
        python Scripts/02_make_grid20m.py --event EMSR788 --aoi AOI01
        python Scripts/02_make_grid20m.py --all                    (all main-study AOIs)
"""
import glob, math, os, sys
import numpy as np
import geopandas as gpd
import rasterio
from rasterio import features
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
from rasterio.windows import from_bounds

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aoi_paths
import provenance

STAMP = provenance.stamp()

# ---- fixed rules (locked in git after the pilot) ----
CELL = 20.0               # grid cell size in metres
EDGE_OFFSET = 5.0         # cell edges at EDGE_OFFSET + n * CELL (nests the 10 m SNAP pixels)
BASELINE_MIN_OF_4 = 2     # a 20 m cell is flooded if at least this many of its four 10 m pixels are
NODATA = 255



def worldcover_tiles(lon0, lat0, lon1, lat1):
    """WorldCover 3 x 3 degree tiles (named after the south-west corner) that the AOI touches."""
    names = []
    for lat in range(math.floor(lat0 / 3) * 3, math.floor(lat1 / 3) * 3 + 1, 3):
        for lon in range(math.floor(lon0 / 3) * 3, math.floor(lon1 / 3) * 3 + 1, 3):
            names.append('%s%02d%s%03d' % ('N' if lat >= 0 else 'S', abs(lat), 'E' if lon >= 0 else 'W', abs(lon)))
    files = [os.path.join(aoi_paths.WORLDCOVER_DIR, 'ESA_WorldCover_10m_2021_v200_%s_Map.tif' % n) for n in names]
    return sorted(f for f in files if os.path.exists(f)), names


def save(name, arr, grid, nodata=NODATA, dtype='uint8'):
    prof = dict(driver='GTiff', height=grid['h'], width=grid['w'], count=1, dtype=dtype, crs=grid['crs'],
                transform=grid['transform'], nodata=nodata, compress='deflate', tiled=True)
    with rasterio.open(os.path.join(grid['out'], name), 'w', **prof) as dst:
        dst.write(arr.astype(dtype), 1)
        dst.update_tags(**STAMP)


def read_10m_blocks(path, grid, fill):
    """Read a 10 m SNAP raster over the grid extent and return it as (h, w, 4): the four pixels per cell."""
    with rasterio.open(path) as src:
        res = abs(src.transform.a)
        if abs(res - CELL / 2) > 1e-6:
            sys.exit('ERROR: %s is not a 10 m raster' % path)
        # the 10 m pixel edges must fall on the 20 m cell edges
        dx = (grid['x0'] - src.transform.c) / res
        dy = (src.transform.f - grid['y1']) / res
        if abs(dx - round(dx)) > 1e-3 or abs(dy - round(dy)) > 1e-3:
            sys.exit('ERROR: %s does not nest in the 20 m grid (SNAP alignToStandardGrid?)' % path)
        win = from_bounds(grid['x0'], grid['y0'], grid['x1'], grid['y1'], src.transform)
        a = src.read(1, window=win, boundless=True, fill_value=fill)
    h, w = grid['h'], grid['w']
    return a.reshape(h, 2, w, 2).transpose(0, 2, 1, 3).reshape(h, w, 4)


def warp_nearest(path, grid, resampling=Resampling.nearest):
    out = np.full((grid['h'], grid['w']), NODATA, dtype=np.uint8)
    with rasterio.open(path) as src:
        reproject(rasterio.band(src, 1), out, dst_transform=grid['transform'], dst_crs=grid['crs'],
                  src_nodata=src.nodata, dst_nodata=NODATA, resampling=resampling)
    return out


def process(a):
    print('\n=== %s ===' % a)
    os.makedirs(a.grid_dir, exist_ok=True)
    with rasterio.open(a.baseline_10m) as b:
        crs = b.crs

    # 1. the grid: bounding box of the AOI, snapped outwards to the cell edges
    aoi = gpd.read_file(a.ems_aoi).to_crs(crs)
    xmin, ymin, xmax, ymax = aoi.total_bounds
    snap_dn = lambda v: np.floor((v - EDGE_OFFSET) / CELL) * CELL + EDGE_OFFSET
    snap_up = lambda v: np.ceil((v - EDGE_OFFSET) / CELL) * CELL + EDGE_OFFSET
    x0, y0, x1, y1 = snap_dn(xmin), snap_dn(ymin), snap_up(xmax), snap_up(ymax)
    grid = dict(x0=x0, y0=y0, x1=x1, y1=y1, w=int(round((x1 - x0) / CELL)), h=int(round((y1 - y0) / CELL)),
                crs=crs, transform=from_origin(x0, y1, CELL, CELL), out=a.grid_dir)
    shape = (grid['h'], grid['w'])
    ha = CELL * CELL / 10000.0
    print('grid: %s | %d x %d cells of %.0f m | upper-left %.0f %.0f' % (crs.to_string(), grid['w'], grid['h'], CELL, x0, y1))

    # 2. EMS: AOI and observed flood (a cell counts if its centre is inside the polygon)
    aoi_r = features.rasterize(((g, 1) for g in aoi.geometry), out_shape=shape, transform=grid['transform'],
                               fill=0, all_touched=False, dtype='uint8')
    inside = aoi_r == 1
    flood = gpd.read_file(a.ems_flood).to_crs(crs)
    flood = flood[flood.geometry.notna() & ~flood.geometry.is_empty]
    ems = features.rasterize(((g, 1) for g in flood.geometry.buffer(0)), out_shape=shape,
                             transform=grid['transform'], fill=0, all_touched=False, dtype='uint8')
    ems = np.where(inside, ems, NODATA)
    save('aoi.tif', aoi_r, grid, nodata=None)
    save('ems_flood.tif', ems, grid)
    print('AOI                : %9.0f ha' % (inside.sum() * ha))
    print('EMS flood polygons : %9.0f ha (vector) -> %9.0f ha on the grid' % (flood.geometry.area.sum() / 10000.0, (ems == 1).sum() * ha))

    # 3. baseline: 10 m -> 20 m
    b4 = read_10m_blocks(a.baseline_10m, grid, NODATA)
    n_valid = (b4 != NODATA).sum(axis=2)
    n_flood = (b4 == 1).sum(axis=2)
    base = np.where(n_valid >= 2, (n_flood >= BASELINE_MIN_OF_4).astype(np.uint8), NODATA)
    base = np.where(inside, base, NODATA)
    save('baseline_flood.tif', base, grid)
    print('baseline flood     : %9.0f ha on the grid | no data inside AOI: %.2f%%'
          % ((base == 1).sum() * ha, 100.0 * ((base == NODATA) & inside).sum() / inside.sum()))

    # 4. driver layers from SNAP: layover/shadow mask and local incidence angle
    m4 = read_10m_blocks(os.path.join(a.post_data, 'layoverShadowMask.img'), grid, 0)
    ls = np.where(n_valid >= 2, ((m4 > 0).sum(axis=2) >= 2).astype(np.uint8), NODATA)
    save('layover_shadow.tif', np.where(inside, ls, NODATA), grid)
    a4 = read_10m_blocks(os.path.join(a.post_data, 'localIncidenceAngle.img'), grid, 0).astype(np.float32)
    ok = (b4 != NODATA) & (a4 > 0)
    cnt = ok.sum(axis=2)
    lia = np.where(cnt > 0, (a4 * ok).sum(axis=2) / np.maximum(cnt, 1), -1.0)
    save('lia.tif', np.where(inside, lia, -1.0), grid, nodata=-1.0, dtype='float32')
    print('layover/shadow     : %9.0f ha inside AOI' % (((ls == 1) & inside).sum() * ha))

    # 5. GFM: mosaic the tiles of all overlapping scenes
    for key, name, combine in [('flood', 'gfm_flood.tif', np.maximum),
                               ('excl', 'gfm_excl.tif', np.maximum),
                               ('advflag', 'gfm_advflag.tif', np.bitwise_or),
                               ('refwater', 'gfm_refwater.tif', np.maximum)]:
        acc = np.full(shape, NODATA, dtype=np.uint8)
        used = 0
        files = a.gfm_files(key)
        if not files:
            sys.exit('ERROR: no GFM %s files for %s in %s' % (key, a, a.gfm_dir))
        for f in files:
            t = warp_nearest(f, grid)
            v = t != NODATA
            if not v.any():
                continue
            used += 1
            both = v & (acc != NODATA)
            acc[both] = combine(acc[both], t[both])
            first = v & (acc == NODATA)
            acc[first] = t[first]
        acc = np.where(inside, acc, NODATA)
        save(name, acc, grid)
        vals, counts = np.unique(acc[inside], return_counts=True)
        print('%-19s: %d tiles used | values inside AOI (ha): %s'
              % (name, used, {int(k): int(round(c * ha)) for k, c in zip(vals, counts)}))

    # 6. WorldCover (optional until the tiles are downloaded)
    lon0, lat0, lon1, lat1 = gpd.read_file(a.ems_aoi).to_crs(4326).total_bounds
    tiles, needed = worldcover_tiles(lon0, lat0, lon1, lat1)
    if not tiles:
        print('worldcover.tif     : SKIPPED - none of the tiles %s is in %s' % (needed, aoi_paths.WORLDCOVER_DIR))
    else:
        wc = np.full(shape, NODATA, dtype=np.uint8)
        for f in tiles:
            t = np.zeros(shape, dtype=np.uint8)
            with rasterio.open(f) as src:
                reproject(rasterio.band(src, 1), t, dst_transform=grid['transform'], dst_crs=grid['crs'],
                          dst_nodata=0, resampling=Resampling.mode)
            wc[(t != 0) & (wc == NODATA)] = t[(t != 0) & (wc == NODATA)]
        wc = np.where(inside, wc, NODATA)
        save('worldcover.tif', wc, grid)
        vals, counts = np.unique(wc[inside], return_counts=True)
        print('worldcover.tif     : %d tiles | classes inside AOI (%%): %s'
              % (len(tiles), {int(k): float(round(100.0 * c / inside.sum(), 1)) for k, c in zip(vals, counts)}))
    print('saved to', a.grid_dir)


def main():
    for a in aoi_paths.from_args(__doc__):
        process(a)
    print('\ncode version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
