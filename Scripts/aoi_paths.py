"""Where the files of one AOI are, for the pilot (EMSR866 AOI01) and for the main study.

All analysis scripts (01-07) take the AOI from the command line:
    --event EMSR788 --aoi AOI01     one AOI of the main study
    --all                           every main-study AOI with status 'ok' in Results/main_s1_scenes.csv
    (nothing)                       the pilot, with its original file layout
and get their input and output paths from AOI(event, aoi).
"""
import argparse, glob, os, sys
import pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT

PILOT = ('EMSR866_pilot', 'AOI01')
SCENES_CSV = os.path.join(REPO, 'Results', 'main_s1_scenes.csv')
RESULTS = os.environ.get('THESIS_RESULTS_DIR', os.path.join(REPO, 'Results'))   # override only for tests
WORLDCOVER_DIR = os.path.join(DATA_ROOT, '01_raw', '_shared', 'WorldCover')
ERA5_DIR = os.path.join(DATA_ROOT, '01_raw', '_shared', 'ERA5')

# GFM layer -> file pattern (pilot: GFM portal names; main study: <asset key>__<item id>[__portal].tif)
GFM_PILOT = {'flood': '*_ENSEMBLE_FLOOD_*.tif', 'excl': '*_ENSEMBLE_EXCLAYER_*.tif',
             'advflag': '*_ADVFLAG_*.tif', 'refwater': '*_REFERENCE_WATER_*.tif'}
GFM_MAIN = {'flood': 'ensemble_flood_extent', 'excl': 'exclusion_mask',
            'advflag': 'advisory_flags', 'refwater': 'reference_water_mask'}


def _one(pattern, what):
    hits = sorted(glob.glob(pattern, recursive=True))
    if len(hits) != 1:
        sys.exit('ERROR: expected one %s, found %d: %s' % (what, len(hits), pattern))
    return hits[0]


class AOI:
    def __init__(self, event, aoi):
        self.event, self.aoi = event, aoi
        self.pilot = (event, aoi) == PILOT
        self.snap_dir = os.path.join(DATA_ROOT, '02_snap_out', event, aoi)
        self.grid_dir = os.path.join(DATA_ROOT, '03_grid20m', event, aoi)
        self.baseline_10m = os.path.join(self.snap_dir, 'baseline_flood_10m.tif')
        if self.pilot:
            raw = os.path.join(DATA_ROOT, '01_raw', event)
            self.ems_dir = os.path.join(raw, 'EMS')
            self.ems_aoi = os.path.join(self.ems_dir, 'EMSR866_AOI01_DEL_PRODUCT_areaOfInterestA_v2.json')
            self.ems_flood = os.path.join(self.ems_dir, 'EMSR866_AOI01_DEL_PRODUCT_observedEventA_v2.json')
            self.post_date, self.pre_date = '20260212', '20260131'
            self.acquisition_utc = pd.Timestamp('2026-02-12 17:55')       # EMS acquisition time
            self.post_scenes = ['20260212T175504', '20260212T175529']
            self.gfm_dir = os.path.join(raw, 'GFM', 'extracted')
            self.prefix = 'pilot'
        else:
            s = pd.read_csv(SCENES_CSV)
            s = s[(s['event'] == event) & (s['aoi'] == aoi)]
            if len(s) != 1 or s['status'].iloc[0] != 'ok':
                sys.exit('ERROR: %s %s is not an AOI with status ok in %s' % (event, aoi, SCENES_CSV))
            s = s.iloc[0]
            self.ems_dir = os.path.join(DATA_ROOT, '01_raw', event, aoi, 'EMS')
            self.ems_aoi = _one(os.path.join(self.ems_dir, '**', '*_areaOfInterestA_v*.json'), 'EMS AOI outline')
            self.ems_flood = _one(os.path.join(self.ems_dir, '**', '*_observedEventA_v*.json'), 'EMS observed-flood layer')
            self.post_date = pd.Timestamp(s['post_start_utc']).strftime('%Y%m%d')
            self.pre_date = pd.Timestamp(s['pre_start_utc']).strftime('%Y%m%d')
            self.acquisition_utc = pd.Timestamp(s['post_start_utc'])          # start of the post-flood pass
            self.post_scenes = [f.strip().split('_')[4] for f in s['post_frames'].split(';')]
            self.gfm_dir = os.path.join(DATA_ROOT, '01_raw', event, 'GFM')
            self.prefix = 'main'
        self.post_data = os.path.join(self.snap_dir, 'S1_%s_TC.data' % self.post_date)
        self.pre_data = os.path.join(self.snap_dir, 'S1_%s_TC.data' % self.pre_date)

    def gfm_files(self, layer):
        """GFM files of one layer ('flood', 'excl', 'advflag', 'refwater') for the post-flood scene(s)."""
        if self.pilot:
            return sorted(glob.glob(os.path.join(self.gfm_dir, GFM_PILOT[layer])))
        files = []
        for scene in self.post_scenes:
            files += glob.glob(os.path.join(self.gfm_dir, '%s__ENSEMBLE_FLOOD_%s_*.tif' % (GFM_MAIN[layer], scene)))
        return sorted(files)

    def __str__(self):
        return '%s %s' % (self.event, self.aoi)


def main_aois():
    s = pd.read_csv(SCENES_CSV)
    s = s[s['status'] == 'ok']
    return [AOI(e, a) for e, a in zip(s['event'], s['aoi'])]


def from_args(description=''):
    """Parse --event/--aoi/--all and return the list of AOIs to process."""
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument('--event')
    ap.add_argument('--aoi')
    ap.add_argument('--all', action='store_true', help='all main-study AOIs')
    args = ap.parse_args()
    if args.all:
        aois = main_aois()
        if args.event:
            aois = [a for a in aois if a.event == args.event]
        ready = [a for a in aois if os.path.exists(a.post_data) and os.path.exists(a.pre_data)]
        missing = [str(a) for a in aois if a not in ready]
        if missing:
            print('skipped (SNAP outputs not there yet): %s' % ', '.join(missing))
        return ready
    if args.event and args.aoi:
        return [AOI(args.event, args.aoi)]
    if args.event:
        return [a for a in main_aois() if a.event == args.event]
    return [AOI(*PILOT)]


def result_csv(a, name):
    """Pilot: Results/pilot_<name>_EMSR866_pilot_AOI01.csv; main study: Results/main_<name>.csv (all AOIs)."""
    if a.pilot:
        return os.path.join(RESULTS, 'pilot_%s_%s_%s.csv' % (name, a.event, a.aoi))
    return os.path.join(RESULTS, 'main_%s.csv' % name)


def save_rows(a, name, df):
    """Write the rows of one AOI. For the main study the AOI's old rows in the shared table are replaced."""
    path = result_csv(a, name)
    os.makedirs(RESULTS, exist_ok=True)
    if not a.pilot and os.path.exists(path):
        old = pd.read_csv(path)
        old = old[~((old['event'] == a.event) & (old['aoi'] == a.aoi))]
        df = pd.concat([old, df], ignore_index=True).sort_values(['event', 'aoi'], kind='stable')
    df.to_csv(path, index=False)
    return path
