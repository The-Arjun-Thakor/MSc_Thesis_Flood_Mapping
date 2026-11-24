"""Main study, step 4: download the Sentinel-1 GRD frames listed in Results/main_s1_downloads.csv.

Each frame is downloaded once from the Copernicus Data Space to <DATA_ROOT>/01_raw/_shared/S1/<name>.zip,
checked against the MD5 checksum published in the catalogue, and recorded with its SHA-256 in
<DATA_ROOT>/download_manifest.csv. Frames that are already there and complete are skipped, so the
script can be stopped and started again at any time. An interrupted frame is resumed from where it
stopped (the partial file is kept as <name>.zip.part), and each frame is tried up to ATTEMPTS times.

Login: a free Copernicus Data Space account. The user name and password are read from the environment
variables CDSE_USER and CDSE_PASSWORD, or asked for when the script starts. They are never stored.

Usage:  python Scripts/11_download_s1.py                 (all frames)
        python Scripts/11_download_s1.py --event EMSR861  (only the frames of one event)
        python Scripts/11_download_s1.py --dry-run        (list what would be downloaded)
"""
import argparse, csv, datetime, getpass, hashlib, os, sys, time
import pandas as pd
import requests

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT

TOKEN_URL = 'https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token'
CATALOGUE = 'https://catalogue.dataspace.copernicus.eu/odata/v1/Products(%s)'
DOWNLOAD = 'https://download.dataspace.copernicus.eu/odata/v1/Products(%s)/$value'
LIST_CSV = os.path.join(REPO, 'Results', 'main_s1_downloads.csv')
OUT_DIR = os.path.join(DATA_ROOT, '01_raw', '_shared', 'S1')
MANIFEST = os.path.join(DATA_ROOT, 'download_manifest.csv')
CHUNK = 8 * 1024 * 1024
ATTEMPTS = 6


def token(user, password):
    r = requests.post(TOKEN_URL, data={'grant_type': 'password', 'username': user, 'password': password,
                                       'client_id': 'cdse-public'}, timeout=60)
    if r.status_code != 200:
        sys.exit('ERROR: login to the Copernicus Data Space failed (%d): %s' % (r.status_code, r.text[:200]))
    return r.json()['access_token']


def catalogue_md5(product_id):
    """MD5 checksum and size in bytes published in the catalogue (None if not published)."""
    r = requests.get(CATALOGUE % product_id, timeout=60)
    r.raise_for_status()
    meta = r.json()
    md5 = next((c['Value'].lower() for c in meta.get('Checksum') or [] if c.get('Algorithm', '').upper() == 'MD5'), None)
    return md5, meta.get('ContentLength')


def in_manifest():
    if not os.path.exists(MANIFEST):
        return set()
    with open(MANIFEST, newline='', encoding='utf-8') as f:
        return {row['file'] for row in csv.DictReader(f)}


def add_to_manifest(row):
    new = not os.path.exists(MANIFEST)
    with open(MANIFEST, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['file', 'relative_path', 'bytes', 'sha256', 'downloaded'])
        if new:
            w.writeheader()
        w.writerow(row)


def resolve(s, product_id):
    """Follow the redirects of the download URL by hand, keeping the login header."""
    url = DOWNLOAD % product_id
    r = s.get(url, allow_redirects=False, timeout=120)
    while r.status_code in (301, 302, 303, 307, 308):
        url = r.headers['Location']
        r = s.get(url, allow_redirects=False, timeout=120)
    r.close()
    return url


def download(product_id, path, tok, expected_size):
    """Download one product to path + '.part', resuming a partial file if the server allows it."""
    part = path + '.part'
    s = requests.Session()
    s.headers['Authorization'] = 'Bearer ' + tok
    url = resolve(s, product_id)
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {'Range': 'bytes=%d-' % have} if have else {}
    t0, done = time.time(), 0
    with s.get(url, stream=True, timeout=(60, 120), headers=headers) as r:
        if have and r.status_code == 206:
            mode = 'ab'
            print('    resuming at %.2f GB' % (have / 1e9))
        elif r.status_code == 200:
            mode, have = 'wb', 0
        else:
            raise RuntimeError('download failed (%d): %s' % (r.status_code, r.text[:200]))
        total = have + int(r.headers.get('Content-Length', 0))
        with open(part, mode) as f:
            for chunk in r.iter_content(CHUNK):
                f.write(chunk); done += len(chunk)
                if total:
                    print('\r    %5.1f%%  %.2f of %.2f GB  %.1f MB/s   ' % (100 * (have + done) / total, (have + done) / 1e9,
                          total / 1e9, done / 1e6 / max(time.time() - t0, 1)), end='', flush=True)
    print()
    size = os.path.getsize(part)
    if expected_size and size != expected_size:
        raise RuntimeError('incomplete: %d of %d bytes' % (size, expected_size))
    md5, sha = hashlib.md5(), hashlib.sha256()
    with open(part, 'rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            md5.update(chunk); sha.update(chunk)
    return size, md5.hexdigest(), sha.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--event', help='only frames used by this event, e.g. EMSR861')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    todo = pd.read_csv(LIST_CSV)
    if args.event:
        todo = todo[todo['used_by'].str.contains(args.event + '_')]
    os.makedirs(OUT_DIR, exist_ok=True)
    have = in_manifest()
    todo = todo.assign(zip=todo['name'] + '.zip')
    todo['done'] = todo['zip'].apply(lambda z: z in have and os.path.exists(os.path.join(OUT_DIR, z)))
    print('%d frames listed, %d already downloaded, %d to go (about %.0f GB)'
          % (len(todo), int(todo['done'].sum()), int((~todo['done']).sum()), todo.loc[~todo['done'], 'size_gb'].sum()))
    if args.dry_run:
        print(todo.loc[~todo['done'], ['name', 'size_gb', 'used_by']].to_string(index=False))
        return
    todo = todo[~todo['done']]
    if todo.empty:
        return
    user = os.environ.get('CDSE_USER') or input('Copernicus Data Space user (e-mail): ')
    password = os.environ.get('CDSE_PASSWORD') or getpass.getpass('Password: ')

    failed = []
    for i, (_, row) in enumerate(todo.iterrows(), 1):
        path = os.path.join(OUT_DIR, row['zip'])
        print('[%d/%d] %s' % (i, len(todo), row['name']))
        try:
            expected, expected_size = catalogue_md5(row['id'])
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    size, md5, sha = download(row['id'], path, token(user, password), expected_size)  # fresh login
                    break
                except Exception as e:
                    print('\n    attempt %d of %d failed: %s' % (attempt, ATTEMPTS, str(e)[:120]))
                    if attempt == ATTEMPTS:
                        raise
                    time.sleep(15 * attempt)
            if expected and md5 != expected:
                os.remove(path + '.part')                    # a corrupt file must not be resumed
                raise RuntimeError('MD5 mismatch (got %s, catalogue %s) - partial file deleted' % (md5, expected))
            os.replace(path + '.part', path)
            add_to_manifest({'file': row['zip'], 'relative_path': os.path.relpath(path, DATA_ROOT).replace('\\', '/'),
                             'bytes': size, 'sha256': sha,
                             'downloaded': datetime.date.today().isoformat()})
            print('    ok, MD5 %s' % ('checked' if expected else 'not published - not checked'))
        except Exception as e:
            failed.append(row['name'])
            print('    FAILED (partial file kept, it will be resumed next time):', e)
    print('\nfinished: %d downloaded, %d failed' % (len(todo) - len(failed), len(failed)))
    if failed:
        print('run the script again to retry:\n  ' + '\n  '.join(failed))


if __name__ == '__main__':
    main()
