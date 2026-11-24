"""Main study: summary tables from the per-AOI results (descriptive, no statistical tests; RULES.md rule 14).

Reads the main-study tables of scripts 03-07 and 16 and writes:
  summary_per_aoi.csv          one row per AOI: flood mechanism, wind, Q1 per pair, Q2 shares, Q3, flag share
  summary_Q1_groups.csv        IoU / omission / commission: median, min, max, n per pair for all AOIs,
                               per event, per flood mechanism and per wind label
  summary_Q2_groups.csv        label shares of the disagreeing area (median, min, max per AOI) and the
                               area-weighted share over all AOIs ("in total"), per pair and direction,
                               for all AOIs, per flood mechanism and per wind label
  summary_Q3_groups.csv        share of the EMS-GFM gap the baseline also shows, same groups
  summary_Q4_flag.csv          rough-water flag share per wind label and per EMS-GFM class
All outputs go to Results/ with the prefix main_.

Usage:  python Scripts/17_summary_tables.py
"""
import os, sys
import numpy as np
import pandas as pd

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aoi_paths
import provenance

STAMP = provenance.stamp()
R = aoi_paths.RESULTS
read = lambda name: pd.read_csv(os.path.join(R, 'main_%s.csv' % name))


def stats(x):
    x = pd.Series(x).dropna()
    return pd.Series({'n': len(x), 'median': x.median() if len(x) else np.nan,
                      'min': x.min() if len(x) else np.nan, 'max': x.max() if len(x) else np.nan})


def grouped(df, value_cols, keys, extra_groups):
    """Median/min/max/n of value_cols for: all AOIs, and every group in extra_groups (list of column names)."""
    out = []
    for gcol in [None] + extra_groups:
        groups = [('all AOIs', df)] if gcol is None else list(df.groupby(gcol))
        for gname, g in groups:
            for kv, gg in (g.groupby(keys) if keys else [((), g)]):
                kv = kv if isinstance(kv, tuple) else (kv,)
                for col in value_cols:
                    row = dict(zip(keys, kv))
                    row.update({'grouping': gcol or 'all', 'group': gname, 'measure': col})
                    row.update(stats(gg[col]).to_dict())
                    out.append(row)
    return pd.DataFrame(out)


def save(df, name):
    for k, v in STAMP.items():
        df[k] = v
    path = os.path.join(R, 'main_%s.csv' % name)
    df.to_csv(path, index=False)
    return path


def main():
    mech = read('flood_mechanism')[['event', 'mechanism', 'source']]
    wind = read('Q4_wind')[['event', 'aoi', 'wind_mean_ms', 'wind_label']]
    q1 = read('Q1_agreement')
    q1['pair'] = q1['first_map'] + ' vs ' + q1['second_map']
    q2 = read('Q2_summary')
    q3 = read('Q3_gap_overlap')
    flag = read('Q4_roughwater_aoi')
    aois = wind[['event', 'aoi']]
    n_aoi, n_ev = len(aois), aois['event'].nunique()
    for name, t in [('Q1', q1), ('Q2', q2), ('Q3', q3), ('flag', flag), ('wind', wind)]:
        if t[['event', 'aoi']].drop_duplicates().shape[0] != n_aoi:
            sys.exit('ERROR: %s does not cover the same %d AOIs' % (name, n_aoi))
    base = aois.merge(mech, on='event', how='left').merge(wind, on=['event', 'aoi'])
    if base['mechanism'].isna().any() or (base['mechanism'] == '').any():
        sys.exit('ERROR: flood mechanism missing for some events - run 16_flood_mechanism.py')

    # ---- per AOI ----
    per = base.copy()
    for pair, g in q1.groupby('pair'):
        g = g.set_index(['event', 'aoi'])
        tag = pair.replace(' vs ', '_').replace('Baseline', 'Base')
        for c in ('iou', 'omission', 'commission', 'first_flood_ha', 'second_flood_ha', 'comparison_area_ha'):
            per = per.merge(g[[c]].rename(columns={c: '%s_%s' % (tag, c)}), left_on=['event', 'aoi'], right_index=True)
    main_dirs = {('EMS vs GFM', 'EMS only'): 'EG_EMSonly', ('EMS vs Baseline', 'EMS only'): 'EB_EMSonly',
                 ('GFM vs Baseline', 'GFM only'): 'GB_GFMonly'}
    for (pair, direction), tag in main_dirs.items():
        g = q2[(q2['pair'] == pair) & (q2['direction'] == direction)].pivot_table(
            index=['event', 'aoi'], columns='label', values='percent')
        g.columns = ['%s_pct_%s' % (tag, c.replace('/', '_').replace(' ', '_')) for c in g.columns]
        per = per.merge(g, left_on=['event', 'aoi'], right_index=True, how='left')
    g = q3[q3['gap_direction'] == 'EMS flood, GFM dry'].set_index(['event', 'aoi'])
    per = per.merge(g[['gap_ha', 'baseline_same_direction_share']].rename(
        columns={'gap_ha': 'Q3_gap_EMSflood_GFMdry_ha', 'baseline_same_direction_share': 'Q3_baseline_also_dry_share'}),
        left_on=['event', 'aoi'], right_index=True)
    per = per.merge(flag.set_index(['event', 'aoi'])[['rough_flag_share', 'ems_only_rough_flag_share']],
                    left_on=['event', 'aoi'], right_index=True)
    p_per = save(per.round(4), 'summary_per_aoi')

    # ---- Q1 groups ----
    q1g = q1.merge(base, on=['event', 'aoi'])
    s1 = grouped(q1g, ['iou', 'omission', 'commission'], ['pair'], ['event', 'mechanism', 'wind_label'])
    save(s1.round(4), 'summary_Q1_groups')

    # ---- Q2 groups: per-AOI shares and area-weighted totals ----
    q2g = q2.merge(base, on=['event', 'aoi'])
    s2 = grouped(q2g, ['percent'], ['pair', 'direction', 'label'], ['mechanism', 'wind_label'])
    tot = []
    for gcol in [None, 'mechanism', 'wind_label']:
        groups = [('all AOIs', q2g)] if gcol is None else list(q2g.groupby(gcol))
        for gname, g in groups:
            a = g.groupby(['pair', 'direction', 'label'])['area_ha'].sum().reset_index()
            a['total_pct'] = 100 * a['area_ha'] / a.groupby(['pair', 'direction'])['area_ha'].transform('sum')
            a['grouping'], a['group'] = gcol or 'all', gname
            tot.append(a)
    tot = pd.concat(tot, ignore_index=True)
    s2 = s2.merge(tot.rename(columns={'area_ha': 'total_area_ha'}), on=['grouping', 'group', 'pair', 'direction', 'label'], how='left')
    save(s2.round(4), 'summary_Q2_groups')

    # ---- Q3 groups ----
    q3g = q3.merge(base, on=['event', 'aoi'])
    s3 = grouped(q3g, ['baseline_same_direction_share'], ['gap_direction'], ['mechanism', 'wind_label'])
    tot3 = q3g.groupby('gap_direction')[['gap_ha', 'baseline_same_direction_ha']].sum()
    print_tot3 = (100 * tot3['baseline_same_direction_ha'] / tot3['gap_ha']).round(2)
    save(s3.round(4), 'summary_Q3_groups')

    # ---- Q4 flag ----
    fg = flag.merge(base[['event', 'aoi', 'mechanism']], on=['event', 'aoi'])
    cols = ['rough_flag_share', 'both_flood_rough_flag_share', 'ems_only_rough_flag_share',
            'gfm_only_rough_flag_share', 'both_dry_rough_flag_share']
    s4 = grouped(fg, cols, [], ['wind_label'])
    s4['aois_with_any_flag'] = [int((fg if r['group'] == 'all AOIs' else fg[fg['wind_label'] == r['group']])['rough_flag_share'].gt(0).sum())
                                for _, r in s4.iterrows()]
    save(s4.round(4), 'summary_Q4_flag')

    # ---- printout ----
    pd.set_option('display.width', 220)
    print('%d AOIs in %d events | flood mechanism (events): %s | wind (AOIs): %s'
          % (n_aoi, n_ev, mech['mechanism'].value_counts().to_dict(), wind['wind_label'].value_counts().to_dict()))
    show = s1[s1['measure'] == 'iou']
    print('\nQ1 IoU, all AOIs:')
    print(show[show['grouping'] == 'all'][['pair', 'n', 'median', 'min', 'max']].round(3).to_string(index=False))
    print('\nQ1 IoU by flood mechanism and by wind:')
    print(show[show['grouping'].isin(['mechanism', 'wind_label'])][['pair', 'grouping', 'group', 'n', 'median', 'min', 'max']].round(3).to_string(index=False))
    s2a = s2[(s2['grouping'] == 'all')]
    print('\nQ2, all AOIs: median share per AOI and share in total (area-weighted), main directions:')
    for (pair, direction) in main_dirs:
        t = s2a[(s2a['pair'] == pair) & (s2a['direction'] == direction)][['label', 'median', 'min', 'max', 'total_pct']].round(1)
        print('  %s, %s' % (pair, direction)); print(t.to_string(index=False))
    print('\nQ3: share of the gap the baseline also shows (median per AOI | in total):')
    for _, r in s3[s3['grouping'] == 'all'].iterrows():
        print('  %-20s median %.3f (min %.3f, max %.3f) | in total %.2f%%' % (r['gap_direction'], r['median'], r['min'], r['max'], print_tot3[r['gap_direction']]))
    print('\nQ4 rough-water flag share of the AOI by wind label:')
    print(s4[s4['measure'] == 'rough_flag_share'][['group', 'n', 'median', 'min', 'max', 'aois_with_any_flag']].round(3).to_string(index=False))
    print('\nsaved 5 tables to', R)
    print('code version: %(git_commit)s | run: %(run_utc)s' % STAMP)


if __name__ == '__main__':
    main()
