"""Main study, step 8: download the ESA WorldCover 2021 v200 tiles that cover the used AOIs.

WorldCover comes in 3 x 3 degree tiles named after their south-west corner (e.g. N45W003). The script
works out which tiles the AOIs touch and downloads the missing *_Map.tif files from the public ESA
WorldCover bucket to <DATA_ROOT>/01_raw/_shared/WorldCover/. Tiles that do not exist (open sea) are
reported and skipped.

Usage:  python Scripts/15_download_worldcover.py
"""
import math, os, sys
import pandas as pd
import requests
from shapely import wkt

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT

URL = 'https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_%s_Map.tif'
OUT_DIR = os.path.join(DATA_ROOT, '01_raw', '_shared', 'WorldCover')
INV_CSV = os.path.join(REPO, 'Results', 'main_aoi_inventory.csv')


def tile_name(lat, lon):
    return '%s%02d%s%03d' % ('N' if lat >= 0 else 'S', abs(lat), 'E' if lon >= 0 else 'W', abs(lon))


def main():
    inv = pd.read_csv(INV_CSV)
    inv = inv[inv['use'] == True]
    tiles = set()
    for w in inv['aoi_extent_wkt']:
        x0, y0, x1, y1 = wkt.loads(w).bounds
        for lat in range(math.floor(y0 / 3) * 3, math.floor(y1 / 3) * 3 + 1, 3):
            for lon in range(math.floor(x0 / 3) * 3, math.floor(x1 / 3) * 3 + 1, 3):
                tiles.add(tile_name(lat, lon))
    os.makedirs(OUT_DIR, exist_ok=True)
    print('%d tiles needed: %s' % (len(tiles), ', '.join(sorted(tiles))))
    for t in sorted(tiles):
        path = os.path.join(OUT_DIR, os.path.basename(URL % t))
        if os.path.exists(path):
            print('  %s  already there' % t); continue
        r = requests.get(URL % t, stream=True, timeout=300)
        if r.status_code == 404:
            print('  %s  does not exist (sea) - skipped' % t); continue
        r.raise_for_status()
        with open(path + '.part', 'wb') as f:
            for chunk in r.iter_content(8 * 1024 * 1024):
                f.write(chunk)
        os.replace(path + '.part', path)
        print('  %s  downloaded (%.0f MB)' % (t, os.path.getsize(path) / 1e6))


if __name__ == '__main__':
    main()
