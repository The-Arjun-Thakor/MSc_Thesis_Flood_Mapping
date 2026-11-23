"""Main study, step 1: download the public EMS Rapid Mapping metadata of every candidate activation.

Saves the raw answer of the public EMS API, one JSON file per activation, to
<DATA_ROOT>/01_raw/_shared/EMS_api/<code>.json, and prints the structure of the answer.
The files are only read later; this script does not choose anything.

Candidate activations: the European flood activations of 2025-2026 with at least one first-delivery
delineation product made from Sentinel-1 alone, as listed in the data check of 1 November 2026
(Topic2_data_check_2026-11-01.md). EMSR866 is the pilot and is kept only for comparison.

Usage:  python Scripts/08_fetch_ems_metadata.py
"""
import datetime, json, os, sys, time, urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT
import provenance

STAMP = provenance.stamp()
API = 'https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/?code=%s'
CANDIDATES = ['EMSR788', 'EMSR792', 'EMSR795', 'EMSR800', 'EMSR802', 'EMSR850', 'EMSR855', 'EMSR856',
              'EMSR858', 'EMSR861', 'EMSR864', 'EMSR868', 'EMSR871', 'EMSR933']
PILOT = ['EMSR866']
OUT_DIR = os.path.join(DATA_ROOT, '01_raw', '_shared', 'EMS_api')


def structure(obj, depth=0, max_depth=4):
    """Short outline of a JSON answer: keys and value types, first list item only."""
    pad = '  ' * depth
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            kind = type(v).__name__ + ('[%d]' % len(v) if isinstance(v, (list, dict)) else '')
            sample = '' if isinstance(v, (list, dict)) else ' = %r' % (str(v)[:60],)
            print('%s%s: %s%s' % (pad, k, kind, sample))
            structure(v, depth + 1, max_depth)
    elif isinstance(obj, list) and obj:
        structure(obj[0], depth, max_depth)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    fetched = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    for i, code in enumerate(CANDIDATES + PILOT):
        req = urllib.request.Request(API % code, headers={'User-Agent': 'msc-thesis-flood-mapping'})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode('utf-8'))
        with open(os.path.join(OUT_DIR, '%s.json' % code), 'w', encoding='utf-8') as f:
            json.dump({'_fetched_utc': fetched, '_url': API % code, '_code_version': STAMP['git_commit'],
                       'answer': data}, f, ensure_ascii=False, indent=1)
        print('saved %s.json' % code)
        if i == 0:
            print('\nstructure of the answer (first activation):')
            structure(data)
            print()
        time.sleep(1)
    print('\nsaved %d files to %s' % (len(CANDIDATES) + len(PILOT), OUT_DIR))
    print('code version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
