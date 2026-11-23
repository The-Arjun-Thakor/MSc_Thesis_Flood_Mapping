"""Main study, step 2: list every candidate AOI and decide, by the locked rules, whether it is used.

Reads the raw EMS API answers saved by 08_fetch_ems_metadata.py and keeps, for each candidate activation,
the first-delivery delineation products (type DEL, monitoring number 0) whose images are all Sentinel-1.
An AOI is used unless EMS did not produce the map or the product has no observed-flood layer
(RULES.md, rule 29a). Every AOI is written to the table, used or not, with the reason.

Output: Results/main_aoi_inventory.csv
Usage:  python Scripts/09_aoi_inventory.py
"""
import glob, json, os, sys
import pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT
import provenance

STAMP = provenance.stamp()
API_DIR = os.path.join(DATA_ROOT, '01_raw', '_shared', 'EMS_api')
OUT_CSV = os.path.join(REPO, 'Results', 'main_aoi_inventory.csv')
PILOT = 'EMSR866'


def main():
    files = sorted(glob.glob(os.path.join(API_DIR, 'EMSR*.json')))
    if not files:
        sys.exit('ERROR: no EMS API files in %s - run 08_fetch_ems_metadata.py first' % API_DIR)
    rows = []
    for f in files:
        saved = json.load(open(f, encoding='utf-8'))
        results = saved['answer']['results']
        if len(results) != 1:
            sys.exit('ERROR: %s holds %d activations, expected 1' % (f, len(results)))
        act = results[0]
        for aoi in act['aois']:
            for p in aoi['products']:
                if p['type'] != 'DEL' or p.get('monitoringNumber', 0) != 0:
                    continue                                   # only first-delivery delineation
                images = p.get('images') or []
                sensors = [i.get('sensorName', '') for i in images]
                if not images or not all('Sentinel-1' in s for s in sensors):
                    continue                                   # only products made from Sentinel-1 alone
                v = p.get('version') or {}
                layers = [l['name'].split('/')[-1] for l in p.get('layers') or []]
                observed = [l for l in p.get('layers') or [] if 'observedEvent' in l['name']]
                if act['code'] == PILOT:
                    use, reason = False, 'pilot (excluded from the main study)'
                elif v.get('statusCode') != 'F':
                    use, reason = False, 'map not produced by EMS (status %s: %s)' % (v.get('statusCode'), v.get('reason', ''))
                elif not observed:
                    use, reason = False, 'no observed-flood layer'
                else:
                    use, reason = True, ''
                flooded = ((p.get('stats') or {}).get('Flooded area') or {}).get('None', {}).get('affected')
                rows.append({
                    'event': act['code'], 'event_name': act['name'], 'continent': act.get('continent'),
                    'ems_subcategory': act.get('subCategory'), 'event_time_utc': act.get('eventTime'),
                    'aoi': 'AOI%02d' % aoi['number'], 'aoi_name': aoi['name'], 'aoi_extent_wkt': aoi.get('extent'),
                    'product_id': p['id'], 'product_version': v.get('number'), 'status': v.get('statusCode'),
                    'delivery_time_utc': v.get('deliveryTime'),
                    'images': len(images), 'sensor': '; '.join(sensors),
                    'acquisition_utc': '; '.join(i.get('acquisitionTime', '') for i in images),
                    'image_files': '; '.join(i.get('fileName', '') for i in images),
                    'observed_layer_json': observed[0].get('json', '') if observed else '',
                    'download_path': p.get('downloadPath', ''),
                    'ems_flooded_area_ha': flooded, 'layers': '; '.join(layers),
                    'use': use, 'exclusion_reason': reason,
                    'ems_api_fetched_utc': saved.get('_fetched_utc')})
    df = pd.DataFrame(rows).sort_values(['event', 'aoi']).reset_index(drop=True)
    for k, val in STAMP.items():
        df[k] = val
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    df.to_csv(OUT_CSV, index=False)

    main_df = df[df['event'] != PILOT]
    used = main_df[main_df['use']]
    print('Sentinel-1-only first-delivery products (main-study candidates): %d in %d events'
          % (len(main_df), main_df['event'].nunique()))
    print('used: %d AOIs in %d events | left out: %d' % (len(used), used['event'].nunique(), len(main_df) - len(used)))
    print('\nper event (used / listed):')
    for ev, g in main_df.groupby('event'):
        print('  %s  %2d / %2d  %s' % (ev, int(g['use'].sum()), len(g), g['event_name'].iloc[0]))
    print('\nreasons for leaving out:')
    print(main_df.loc[~main_df['use'], 'exclusion_reason'].str.split(':').str[0].value_counts().to_string())
    print('\nsaved', OUT_CSV)
    print('code version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
