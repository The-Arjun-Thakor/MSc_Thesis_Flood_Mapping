"""Main study, step 5: run the fixed SNAP graph for every used AOI and both dates.

For each AOI with status 'ok' in Results/main_s1_scenes.csv and each date (post-flood, pre-flood) the
script calls SNAP's gpt with the one-frame or two-frame graph, depending on how many frames the pass
needs. Both graphs have identical settings (RULES.md, rule 4). Per AOI:
  geoRegion: bounding box of the EMS AOI, widened by MARGIN_DEG on every side
  crs:       the UTM zone (north) of the AOI centre, e.g. EPSG:32630
  output:    <DATA_ROOT>/02_snap_out/<event>/<aoi>/S1_<yyyymmdd>_TC.dim
Outputs that already exist are skipped, so the script can be stopped and started again.
Every run is logged in Results/main_snap_log.csv (command, return code, run time, code version).

SNAP's gpt is taken from the environment variable SNAP_GPT, else from the default Windows install path,
else from the PATH.
Usage:  python Scripts/12_run_snap.py                  (all AOIs)
        python Scripts/12_run_snap.py --event EMSR788  (one event)
        python Scripts/12_run_snap.py --dry-run        (print the commands only)
"""
import argparse, csv, datetime, os, shutil, subprocess, sys, time
import pandas as pd
from shapely import wkt
from shapely.geometry import box

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT
import provenance

STAMP = provenance.stamp()
MARGIN_DEG = 0.05
GRAPHS = {1: os.path.join(REPO, 'Scripts', 's1_baseline_1frame.xml'),
          2: os.path.join(REPO, 'Scripts', 's1_baseline_2frames.xml')}
S1_DIR = os.path.join(DATA_ROOT, '01_raw', '_shared', 'S1')
SCENES_CSV = os.path.join(REPO, 'Results', 'main_s1_scenes.csv')
INV_CSV = os.path.join(REPO, 'Results', 'main_aoi_inventory.csv')
LOG_CSV = os.path.join(REPO, 'Results', 'main_snap_log.csv')


def find_gpt():
    for c in (os.environ.get('SNAP_GPT'), r'C:\Program Files\esa-snap\bin\gpt.exe', shutil.which('gpt')):
        if c and os.path.exists(c):
            return c
    sys.exit('ERROR: SNAP gpt not found - set the environment variable SNAP_GPT to the full path of gpt.exe')


def utm_epsg(lon, lat):
    zone = int((lon + 180) // 6) + 1
    return 'EPSG:%d' % ((32600 if lat >= 0 else 32700) + zone)


def log(row):
    new = not os.path.exists(LOG_CSV)
    with open(LOG_CSV, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--event')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    scenes = pd.read_csv(SCENES_CSV)
    scenes = scenes[scenes['status'] == 'ok']
    if args.event:
        scenes = scenes[scenes['event'] == args.event]
    inv = pd.read_csv(INV_CSV).set_index(['event', 'aoi'])
    gpt = 'gpt' if args.dry_run else find_gpt()

    jobs = []
    for _, s in scenes.iterrows():
        aoi = wkt.loads(inv.loc[(s['event'], s['aoi']), 'aoi_extent_wkt']).buffer(0)
        x0, y0, x1, y1 = aoi.bounds
        region = box(x0 - MARGIN_DEG, y0 - MARGIN_DEG, x1 + MARGIN_DEG, y1 + MARGIN_DEG)
        c = aoi.centroid
        crs = utm_epsg(c.x, c.y)
        for role in ('post', 'pre'):
            frames = sorted(f.strip() for f in s['%s_frames' % role].split(';'))
            date = pd.Timestamp(s['%s_start_utc' % role]).strftime('%Y%m%d')
            out = os.path.join(DATA_ROOT, '02_snap_out', s['event'], s['aoi'], 'S1_%s_TC.dim' % date)
            if len(frames) not in GRAPHS:
                sys.exit('ERROR: %s %s %s needs %d frames - no graph for that' % (s['event'], s['aoi'], role, len(frames)))
            cmd = [gpt, GRAPHS[len(frames)]]
            for i, f in enumerate(frames, 1):
                cmd.append('-Pin%d=%s' % (i, os.path.join(S1_DIR, f + '.zip')))
            cmd += ['-PgeoRegion=%s' % region.wkt, '-Pcrs=%s' % crs, '-Pout=%s' % out]
            jobs.append((s['event'], s['aoi'], role, date, frames, crs, out, cmd))

    todo = [j for j in jobs if not os.path.exists(j[6])]
    print('%d SNAP runs listed, %d already done, %d to go' % (len(jobs), len(jobs) - len(todo), len(todo)))
    for k, (event, aoi, role, date, frames, crs, out, cmd) in enumerate(todo, 1):
        print('\n[%d/%d] %s %s %s %s (%d frame%s, %s)' % (k, len(todo), event, aoi, role, date, len(frames),
                                                       's' if len(frames) > 1 else '', crs))
        if args.dry_run:
            print('  ' + ' '.join('"%s"' % c if ' ' in c else c for c in cmd))
            continue
        missing = [f for f in frames if not os.path.exists(os.path.join(S1_DIR, f + '.zip'))]
        if missing:
            print('  skipped - frame not downloaded yet:', ', '.join(missing))
            continue
        os.makedirs(os.path.dirname(out), exist_ok=True)
        t0 = time.time()
        res = subprocess.run(cmd, capture_output=True, text=True)
        minutes = (time.time() - t0) / 60
        ok = res.returncode == 0 and os.path.exists(out)
        print('  %s in %.1f min' % ('done' if ok else 'FAILED (return code %d)' % res.returncode, minutes))
        if not ok:
            print('  last lines of the SNAP output:\n  ' + '\n  '.join((res.stdout + res.stderr).strip().splitlines()[-8:]))
        log({'event': event, 'aoi': aoi, 'role': role, 'date': date, 'frames': '; '.join(frames), 'crs': crs,
             'graph': os.path.basename(cmd[1]), 'output': os.path.relpath(out, DATA_ROOT).replace('\\', '/'),
             'return_code': res.returncode, 'ok': ok, 'minutes': round(minutes, 1),
             'started_utc': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), **STAMP})
    print('\ncode version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
