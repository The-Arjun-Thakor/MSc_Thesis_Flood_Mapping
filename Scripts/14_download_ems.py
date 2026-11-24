"""Main study, step 7: download the EMS delineation package (vector layers) of every used AOI.

For each AOI with use = True in Results/main_aoi_inventory.csv the product zip given by the EMS API
(download_path, current product version) is downloaded to <DATA_ROOT>/01_raw/<event>/<aoi>/EMS/ and
extracted there. The script records which layers the package holds: the observed flood, the AOI outline
and any "not analysed" layer (RULES.md, rule 8). The zip is added to <DATA_ROOT>/download_manifest.csv.

Output: Results/main_ems_products.csv
Usage:  python Scripts/14_download_ems.py  [--event EMSR861]
"""
import argparse, csv, datetime, glob, hashlib, os, sys, time, zipfile
import pandas as pd
import requests

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT
import provenance

STAMP = provenance.stamp()
INV_CSV = os.path.join(REPO, 'Results', 'main_aoi_inventory.csv')
OUT_CSV = os.path.join(REPO, 'Results', 'main_ems_products.csv')
MANIFEST = os.path.join(DATA_ROOT, 'download_manifest.csv')


def manifest_add(path):
    sha = hashlib.sha256(open(path, 'rb').read()).hexdigest()
    new = not os.path.exists(MANIFEST)
    with open(MANIFEST, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['file', 'relative_path', 'bytes', 'sha256', 'downloaded'])
        if new:
            w.writeheader()
        w.writerow({'file': os.path.basename(path), 'relative_path': os.path.relpath(path, DATA_ROOT).replace('\\', '/'),
                    'bytes': os.path.getsize(path), 'sha256': sha, 'downloaded': datetime.date.today().isoformat()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--event')
    args = ap.parse_args()
    inv = pd.read_csv(INV_CSV)
    inv = inv[inv['use'] == True]
    if args.event:
        inv = inv[inv['event'] == args.event]
    rows = []
    for _, a in inv.iterrows():
        out_dir = os.path.join(DATA_ROOT, '01_raw', a['event'], a['aoi'], 'EMS')
        os.makedirs(out_dir, exist_ok=True)
        url = a['download_path']
        zpath = os.path.join(out_dir, url.rstrip('/').split('/')[-1])
        status = 'exists'
        if not os.path.exists(zpath):
            for attempt in range(4):
                try:
                    with requests.get(url, stream=True, timeout=300, headers={'User-Agent': 'msc-thesis-flood-mapping'}) as r:
                        r.raise_for_status()
                        with open(zpath + '.part', 'wb') as f:
                            for chunk in r.iter_content(4 * 1024 * 1024):
                                f.write(chunk)
                    os.replace(zpath + '.part', zpath)
                    manifest_add(zpath)
                    status = 'downloaded'
                    break
                except Exception as e:
                    if attempt == 3:
                        status = 'FAILED: %s' % e
                    time.sleep(5 * (attempt + 1))
        row = {'event': a['event'], 'aoi': a['aoi'], 'zip': os.path.basename(zpath), 'status': status}
        if os.path.exists(zpath):
            with zipfile.ZipFile(zpath) as z:
                z.extractall(out_dir)
                names = z.namelist()
            pick = lambda key, ext: '; '.join(sorted(os.path.basename(n) for n in names if key.lower() in n.lower() and n.lower().endswith(ext)))
            row.update(observed_json=pick('observedEvent', '.json'), observed_shp=pick('observedEvent', '.shp'),
                       aoi_json=pick('areaOfInterest', '.json'), aoi_shp=pick('areaOfInterest', '.shp'),
                       not_analysed=pick('notAnalysed', '.shp') or pick('notAnalysed', '.json'),
                       image_footprint=pick('imageFootprint', '.shp'), n_files=len(names))
        rows.append(row)
        print('%s %s  %-10s  observed: %s | AOI outline: %s | not analysed: %s'
              % (a['event'], a['aoi'], status[:10], 'yes' if row.get('observed_json') or row.get('observed_shp') else 'NO',
                 'yes' if row.get('aoi_json') or row.get('aoi_shp') else 'NO', 'yes' if row.get('not_analysed') else 'none'))
        time.sleep(0.5)
    df = pd.DataFrame(rows)
    for k, v in STAMP.items():
        df[k] = v
    if args.event and os.path.exists(OUT_CSV):
        old = pd.read_csv(OUT_CSV)
        df = pd.concat([old[old['event'] != args.event], df], ignore_index=True)
    df.to_csv(OUT_CSV, index=False)
    print('\nsaved', OUT_CSV)
    print('code version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
