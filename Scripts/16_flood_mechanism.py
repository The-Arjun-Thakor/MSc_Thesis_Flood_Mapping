"""Flood mechanism label of every main-study event (RULES.md, rule 13).

1. HANZE v3.0.1 (field "Type": River, Flash, Coastal, River/Coastal): a HANZE event matches an EMS event if
   it is in one of the EMS event's countries and its dates overlap the EMS event time (+/- MATCH_DAYS).
   Exactly one match -> its Type is used. Several matches -> reported, and the author must decide.
2. Events HANZE does not cover (no match, e.g. all 2026 events): the author's own label from the EMS event
   description, read from flood_mechanism_fallback.csv and marked as fallback. The EMS sub-category is
   not used.

Output: Results/main_flood_mechanism.csv (one row per event, with the HANZE ID or the fallback basis)
Usage:  python Scripts/16_flood_mechanism.py
"""
import glob, json, os, sys
import pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT
import provenance

STAMP = provenance.stamp()
MATCH_DAYS = 3
HANZE_CSV = os.path.join(DATA_ROOT, '01_raw', '_shared', 'HANZE', 'HANZE_events_v3_0_1b.csv')
API_DIR = os.path.join(DATA_ROOT, '01_raw', '_shared', 'EMS_api')
FALLBACK_CSV = os.path.join(REPO, 'flood_mechanism_fallback.csv')
SCENES_CSV = os.path.join(REPO, 'Results', 'main_s1_scenes.csv')
OUT_CSV = os.path.join(REPO, 'Results', 'main_flood_mechanism.csv')
COUNTRY_CODES = {'France': 'FR', 'Italy': 'IT', 'Romania': 'RO', 'Albania': 'AL', 'Montenegro': 'ME',
                 'Spain': 'ES', 'Portugal': 'PT', 'Greece': 'EL'}     # HANZE uses EL for Greece


def main():
    hanze = pd.read_csv(HANZE_CSV, encoding='utf-8-sig')
    hanze['start'] = pd.to_datetime(hanze['Start date'], errors='coerce')
    hanze['end'] = pd.to_datetime(hanze['End date'], errors='coerce').fillna(hanze['start'])
    fallback = pd.read_csv(FALLBACK_CSV).set_index('event')
    conf_col = next((c for c in ('confirmed_by_author', 'confirmed_by_me') if c in fallback.columns), None)
    if conf_col is None:
        sys.exit('ERROR: %s needs a column confirmed_by_author (yes/no)' % FALLBACK_CSV)
    events = sorted(pd.read_csv(SCENES_CSV).query("status == 'ok'")['event'].unique())
    rows = []
    for ev in events:
        act = json.load(open(os.path.join(API_DIR, ev + '.json'), encoding='utf-8'))['answer']['results'][0]
        t = pd.Timestamp(act['eventTime']).normalize()
        codes = [COUNTRY_CODES[c['name']] for c in act['countries']]
        m = hanze[hanze['Country code'].isin(codes) & (hanze['start'] <= t + pd.Timedelta(days=MATCH_DAYS))
                  & (hanze['end'] >= t - pd.Timedelta(days=MATCH_DAYS))]
        row = {'event': ev, 'event_name': act['name'], 'event_time_utc': act['eventTime'],
               'countries': '; '.join(codes), 'ems_subcategory_not_used': act.get('subCategory'),
               'hanze_matches': len(m), 'hanze_ids': '; '.join(str(i) for i in m['ID'])}
        if len(m) == 1:
            x = m.iloc[0]
            row.update(mechanism=x['Type'], source='HANZE v3.0.1',
                       basis='HANZE ID %s, %s to %s, %s; rivers: %s; NUTS3: %s'
                             % (x['ID'], x['start'].date(), x['end'].date(), x['Country code'],
                                x['Event source'] if pd.notna(x['Event source']) else '-', x['Regions affected (NUTS 3)']))
        elif len(m) > 1:
            row.update(mechanism='', source='HANZE: several matches - author must decide',
                       basis='; '.join('%s %s' % (i, ty) for i, ty in zip(m['ID'], m['Type'])))
        elif ev in fallback.index:
            f = fallback.loc[ev]
            row.update(mechanism=f['label'], source='fallback: own label from EMS description',
                       basis=f['basis'], confirmed_by_author=f[conf_col])
        else:
            row.update(mechanism='', source='MISSING: no HANZE match and no fallback label', basis='')
        rows.append(row)
    df = pd.DataFrame(rows)
    for k, v in STAMP.items():
        df[k] = v
    df.to_csv(OUT_CSV, index=False)
    pd.set_option('display.width', 220)
    print(df[['event', 'event_time_utc', 'countries', 'hanze_matches', 'mechanism', 'source']].to_string(index=False))
    n_unconf = int((df.get('confirmed_by_author', pd.Series(dtype=str)) == 'no').sum())
    if n_unconf:
        print('\n%d fallback labels are not confirmed yet - check them in flood_mechanism_fallback.csv' % n_unconf)
    print('saved', OUT_CSV)
    print('code version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
