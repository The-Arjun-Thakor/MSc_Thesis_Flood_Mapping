"""Main study, step 6: download the GFM layers for every used AOI from the public EODC STAC catalogue.

For each AOI with status 'ok' in Results/main_s1_scenes.csv the script searches the STAC collection 'GFM'
(https://stac.eodc.eu/api/v1, no login) for items that intersect the EMS AOI and whose time lies within
the post-flood Sentinel-1 pass (the image EMS used). GFM delivers one item per Equi7 tile and scene;
every data asset of every matching item is downloaded once to
<DATA_ROOT>/01_raw/<event>/GFM/<file name>.
AOIs without any GFM item are listed; they keep only the EMS-baseline pair (RULES.md, rule 30).

Outputs: Results/main_gfm_items.csv  one row per AOI and item, with the asset keys and file names
Usage:   python Scripts/13_download_gfm.py --list     (search only: print items and asset keys, no download)
         python Scripts/13_download_gfm.py            (search and download)
         python Scripts/13_download_gfm.py --event EMSR788
"""
import argparse, datetime as dt, json, os, sys, time
import pandas as pd
import requests
from shapely import wkt
from shapely.geometry import mapping

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT
import provenance

STAMP = provenance.stamp()
STAC_SEARCH = 'https://stac.eodc.eu/api/v1/search'
COLLECTION = 'GFM'
PASS_BEFORE_MIN, PASS_AFTER_MIN = 2, 3      # time window around the start of the post-flood pass
SCENES_CSV = os.path.join(REPO, 'Results', 'main_s1_scenes.csv')
INV_CSV = os.path.join(REPO, 'Results', 'main_aoi_inventory.csv')
OUT_CSV = os.path.join(REPO, 'Results', 'main_gfm_items.csv')


def iso(t):
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


def search(geom, start, end):
    body = {'collections': [COLLECTION], 'intersects': mapping(geom), 'datetime': '%s/%s' % (iso(start), iso(end)),
            'limit': 100}
    items, url, method = [], STAC_SEARCH, 'POST'
    while url:
        for attempt in range(4):
            try:
                r = requests.post(url, json=body, timeout=120) if method == 'POST' else requests.get(url, timeout=120)
                r.raise_for_status()
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
        page = r.json()
        items += page.get('features', [])
        nxt = [l for l in page.get('links', []) if l.get('rel') == 'next']
        url = None
        if nxt:
            url, method = nxt[0]['href'], nxt[0].get('method', 'GET')
            body = nxt[0].get('body', body)
    return items


def download(url, path):
    if os.path.exists(path):
        return 'exists'
    for attempt in range(4):
        try:
            with requests.get(url, stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(path + '.part', 'wb') as f:
                    for chunk in r.iter_content(4 * 1024 * 1024):
                        f.write(chunk)
            os.replace(path + '.part', path)
            return 'downloaded'
        except Exception:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--event')
    ap.add_argument('--list', action='store_true', help='search only, no download')
    args = ap.parse_args()

    scenes = pd.read_csv(SCENES_CSV)
    scenes = scenes[scenes['status'] == 'ok']
    if args.event:
        scenes = scenes[scenes['event'] == args.event]
    inv = pd.read_csv(INV_CSV).set_index(['event', 'aoi'])

    rows, no_gfm, asset_keys = [], [], set()
    for _, s in scenes.iterrows():
        aoi = wkt.loads(inv.loc[(s['event'], s['aoi']), 'aoi_extent_wkt']).buffer(0)
        t0 = pd.Timestamp(s['post_start_utc'])
        items = search(aoi, t0 - pd.Timedelta(minutes=PASS_BEFORE_MIN), t0 + pd.Timedelta(minutes=PASS_AFTER_MIN))
        if not items:
            no_gfm.append('%s %s' % (s['event'], s['aoi']))
            rows.append({'event': s['event'], 'aoi': s['aoi'], 'post_start_utc': s['post_start_utc'], 'item_id': '',
                         'note': 'no GFM item found (rule 30: EMS-baseline pair only)'})
            print('%s %s: no GFM item' % (s['event'], s['aoi']))
            continue
        out_dir = os.path.join(DATA_ROOT, '01_raw', s['event'], 'GFM')
        if not args.list:
            os.makedirs(out_dir, exist_ok=True)
        print('%s %s: %d GFM item(s)' % (s['event'], s['aoi'], len(items)))
        for it in items:
            data_assets = {k: a for k, a in it.get('assets', {}).items()
                           if 'data' in (a.get('roles') or []) or a.get('href', '').lower().endswith('.tif')}
            asset_keys |= set(data_assets)
            files = []
            for k, a in sorted(data_assets.items()):
                name = a['href'].split('?')[0].rstrip('/').split('/')[-1]
                files.append('%s=%s' % (k, name))
                if not args.list:
                    status = download(a['href'], os.path.join(out_dir, name))
                    if status == 'downloaded':
                        print('    %s' % name)
            rows.append({'event': s['event'], 'aoi': s['aoi'], 'post_start_utc': s['post_start_utc'],
                         'item_id': it['id'], 'item_datetime': it.get('properties', {}).get('datetime'),
                         'assets': '; '.join(sorted(data_assets)), 'files': '; '.join(files), 'note': ''})
            if args.list:
                print('    %s  %s' % (it['id'], it.get('properties', {}).get('datetime')))
                for k, a in sorted(data_assets.items()):
                    print('      %-28s %s' % (k, a.get('title', '')))

    df = pd.DataFrame(rows)
    for k, v in STAMP.items():
        df[k] = v
    if not args.list:
        df.to_csv(OUT_CSV, index=False)
        print('\nsaved', OUT_CSV)
    print('\nasset keys seen: %s' % ', '.join(sorted(asset_keys)))
    print('AOIs without GFM: %d %s' % (len(no_gfm), ('(' + ', '.join(no_gfm) + ')') if no_gfm else ''))
    print('code version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
