"""Main study, step 3: find the Sentinel-1 GRD frames for every used AOI (post-flood and pre-flood).

Searches the public Copernicus Data Space catalogue (OData, no login needed) for each AOI of
Results/main_aoi_inventory.csv with use = True:
  post-flood: IW GRDH frames that intersect the AOI and were acquired within POST_WINDOW_MIN minutes of
              the EMS acquisition time (the image EMS used);
  pre-flood:  the latest pass of the same satellite and the same relative orbit, acquired strictly before
              the EMS event time (and before the post-flood pass) and within PRE_MAX_DAYS days
              (RULES.md, rule 7). All frames of that pass that intersect the AOI are taken.
The share of the AOI covered by the frames of each pass is recorded. AOIs without a post-flood scene or
without a pre-flood image are marked (RULES.md, rule 29 b and c).

Outputs: Results/main_s1_scenes.csv     one row per AOI
         Results/main_s1_downloads.csv  one row per frame to download (each frame once)
Usage:   python Scripts/10_find_s1_scenes.py
"""
import datetime as dt, json, os, sys, time, urllib.parse, urllib.request
import pandas as pd
from shapely import wkt
from shapely.geometry import shape
from shapely.ops import unary_union

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
import provenance

STAMP = provenance.stamp()

# ---- fixed rules (RULES.md) ----
PRE_MAX_DAYS = 24          # rule 7
POST_WINDOW_MIN = 5        # EMS gives the acquisition time to the minute; frames of one pass span ~1 min
PASS_GAP_MIN = 10          # frames of one pass start within this many minutes of each other
PRODUCT_TYPE = 'IW_GRDH_1S'

ODATA = 'https://catalogue.dataspace.copernicus.eu/odata/v1/Products'
INV_CSV = os.path.join(REPO, 'Results', 'main_aoi_inventory.csv')
OUT_SCENES = os.path.join(REPO, 'Results', 'main_s1_scenes.csv')
OUT_DOWNLOADS = os.path.join(REPO, 'Results', 'main_s1_downloads.csv')


def iso(t):
    return t.strftime('%Y-%m-%dT%H:%M:%S.000Z')


def search(area, start, end):
    """All IW GRDH products (not the COG copies) intersecting `area` with start time in [start, end)."""
    flt = ("Collection/Name eq 'SENTINEL-1' and "
           "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
           "att/OData.CSC.StringAttribute/Value eq '%s') and "
           "OData.CSC.Intersects(area=geography'SRID=4326;%s') and "
           "ContentDate/Start ge %s and ContentDate/Start lt %s") % (PRODUCT_TYPE, area.wkt, iso(start), iso(end))
    url = ODATA + '?' + urllib.parse.urlencode({'$filter': flt, '$expand': 'Attributes', '$top': '200',
                                                '$orderby': 'ContentDate/Start asc'})
    out = []
    while url:
        req = urllib.request.Request(url, headers={'User-Agent': 'msc-thesis-flood-mapping'})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.loads(r.read().decode('utf-8'))
                break
            except Exception as e:
                if attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
        for p in data.get('value', []):
            if '_COG' in p['Name']:
                continue
            attrs = {a['Name']: a.get('Value') for a in p.get('Attributes', [])}
            out.append({'id': p['Id'], 'name': p['Name'],
                        'start': pd.Timestamp(p['ContentDate']['Start']).tz_convert(None),
                        'platform': attrs.get('platformSerialIdentifier') or p['Name'][:3],
                        'relative_orbit': attrs.get('relativeOrbitNumber'),
                        'orbit_direction': attrs.get('orbitDirection'),
                        'online': p.get('Online'), 'size_bytes': p.get('ContentLength'),
                        'footprint': shape(p['GeoFootprint']) if p.get('GeoFootprint') else None})
        url = data.get('@odata.nextLink')
        time.sleep(0.5)
    return out


def coverage(frames, aoi):
    fps = [f['footprint'] for f in frames if f['footprint'] is not None]
    return round(unary_union(fps).intersection(aoi).area / aoi.area, 4) if fps else 0.0


def main():
    inv = pd.read_csv(INV_CSV)
    inv = inv[inv['use'] == True]
    rows, downloads = [], {}
    for _, a in inv.iterrows():
        aoi = wkt.loads(a['aoi_extent_wkt']).buffer(0)
        box = aoi.envelope                                   # short query polygon; exact test below
        acq = [pd.Timestamp(t.strip()) for t in str(a['acquisition_utc']).split(';')]
        event_time = pd.Timestamp(a['event_time_utc'])
        row = {'event': a['event'], 'aoi': a['aoi'], 'aoi_name': a['aoi_name'],
               'ems_acquisition_utc': a['acquisition_utc'], 'event_time_utc': a['event_time_utc']}

        # post-flood frames: the pass EMS used
        cand = search(box, min(acq) - pd.Timedelta(minutes=POST_WINDOW_MIN), max(acq) + pd.Timedelta(minutes=POST_WINDOW_MIN))
        post = [f for f in cand if f['footprint'] is not None and f['footprint'].intersects(aoi)]
        tracks = sorted({(f['platform'], f['relative_orbit']) for f in post})
        if not post:
            row.update(status='left out', reason='rule 29b: no Sentinel-1 GRD frame of the EMS acquisition found')
            rows.append(row); print(a['event'], a['aoi'], row['reason']); continue
        if len(tracks) > 1:
            row.update(status='check', reason='post-flood frames from more than one track: %s' % tracks)
            rows.append(row); print(a['event'], a['aoi'], row['reason']); continue
        platform, rel_orbit = tracks[0]
        post_start = min(f['start'] for f in post)

        # pre-flood frames: latest pass of the same track, strictly before event time and post pass
        end = min(event_time, post_start - pd.Timedelta(hours=1))
        cand = search(box, end - pd.Timedelta(days=PRE_MAX_DAYS), end)
        same = [f for f in cand if f['platform'] == platform and f['relative_orbit'] == rel_orbit
                and f['footprint'] is not None and f['footprint'].intersects(aoi)]
        if not same:
            row.update(platform=platform, relative_orbit=rel_orbit, post_frames='; '.join(f['name'] for f in post),
                       post_coverage=coverage(post, aoi), status='left out',
                       reason='rule 29c: no pre-flood image of the same track within %d days' % PRE_MAX_DAYS)
            rows.append(row); print(a['event'], a['aoi'], row['reason']); continue
        latest = max(f['start'] for f in same)
        pre = [f for f in same if latest - f['start'] <= pd.Timedelta(minutes=PASS_GAP_MIN)]
        pre_start = min(f['start'] for f in pre)

        row.update(platform=platform, relative_orbit=rel_orbit, orbit_direction=post[0]['orbit_direction'],
                   post_start_utc=str(post_start), post_frames='; '.join(f['name'] for f in post),
                   post_coverage=coverage(post, aoi),
                   pre_start_utc=str(pre_start), pre_frames='; '.join(f['name'] for f in pre),
                   pre_coverage=coverage(pre, aoi),
                   days_pre_before_post=round((post_start - pre_start).total_seconds() / 86400, 2),
                   pre_search_end_utc=str(end), status='ok', reason='')
        rows.append(row)
        for role, frames in (('post', post), ('pre', pre)):
            for f in frames:
                d = downloads.setdefault(f['name'], {'name': f['name'], 'id': f['id'], 'start_utc': str(f['start']),
                                                     'platform': f['platform'], 'relative_orbit': f['relative_orbit'],
                                                     'online': f['online'], 'size_gb': round((f['size_bytes'] or 0) / 1e9, 2),
                                                     'used_by': set()})
                d['used_by'].add('%s_%s_%s' % (a['event'], a['aoi'], role))
        print('%s %s  post %s (%d frames, %.0f%% of AOI) | pre %s (%d frames, %.0f%%) | %s%s rel. orbit %s'
              % (a['event'], a['aoi'], post_start.date(), len(post), 100 * row['post_coverage'],
                 pre_start.date(), len(pre), 100 * row['pre_coverage'], platform, '', rel_orbit))

    scenes = pd.DataFrame(rows)
    dl = pd.DataFrame([{**d, 'used_by': '; '.join(sorted(d['used_by']))} for d in downloads.values()])
    for df in (scenes, dl):
        for k, v in STAMP.items():
            df[k] = v
    scenes.to_csv(OUT_SCENES, index=False)
    dl.sort_values('start_utc').to_csv(OUT_DOWNLOADS, index=False)
    ok = scenes[scenes['status'] == 'ok']
    print('\nAOIs ok: %d of %d (events: %d) | frames to download: %d, about %.0f GB'
          % (len(ok), len(scenes), ok['event'].nunique(), len(dl), dl['size_gb'].sum() if len(dl) else 0))
    low = ok[(ok['post_coverage'] < 0.99) | (ok['pre_coverage'] < 0.99)]
    if len(low):
        print('AOIs where the frames cover less than 99% of the AOI:')
        print(low[['event', 'aoi', 'post_coverage', 'pre_coverage']].to_string(index=False))
    print('saved', OUT_SCENES, 'and', OUT_DOWNLOADS)
    print('code version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
