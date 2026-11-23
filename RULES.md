# Locked rules

This file fixes every rule of the study **before the main events are processed**. The git commit that
adds this file is the lock: its date shows that the rules were set after the pilot (EMSR866, AOI 1) and
before any main-study data was processed.

- Rules proposed to the supervisor in Weekly Report 1 (15 November 2026), Sections 5 and 8.
- Follow-up sent on 23 November 2026. No reply had arrived when the rules were locked.
- Locked on: 23 November 2026 (date of the commit that adds this file).
- Any change after the lock (for example after supervisor feedback) is added below under
  "Changes after the lock", with the date, the reason, and the affected results re-run.

## A. Rules taken from the thesis proposal (unchanged)

**Event selection**
1. Unit of analysis: one EMS area of interest (AOI). Results are also reported per event.
2. Candidates: European flood activations of 2025–2026 with at least one first-delivery delineation
   product made from Sentinel-1 alone, as listed from the public EMS API on 1 November 2026.
3. The pilot EMSR866 is left out of all main-study numbers.

**Baseline pipeline (one fixed SNAP graph, `Scripts/s1_baseline_2frames.xml`, SNAP 14)**
4. Precise orbit file, thermal noise removal, calibration to sigma nought (VV), 7x7 Lee filter,
   Range-Doppler terrain correction on the Copernicus DEM GLO-30 at 10 m; the layover/shadow mask and the
   local incidence angle are saved.
5. A pixel is flooded if VV is below -16.5 dB after the flood and at or above -16.5 dB before it.
6. Flooded patches smaller than 0.5 ha are removed.
7. Pre-flood image: the latest image of the same satellite and the same relative orbit, taken strictly
   before the EMS event time and within 24 days. No other information is used to choose it.

**Comparison**
8. All maps on a common 20 m grid. Comparison area: inside the AOI and outside EMS "not analysed" areas;
   for the two pairs with GFM also outside the GFM exclusion mask.
9. Q1: IoU, omission and commission for each pair (EMS-GFM, EMS-baseline, GFM-baseline).
10. Q2: disagreeing areas are cut into patches; each patch gets one label in this order:
    layover/shadow, then built-up or tree cover (WorldCover 50 and 10), then unexplained.
    A label needs at least half of the patch. Patches under 0.5 ha form one "small patches" total.
    The mean local incidence angle of each patch is recorded.
11. Q3: share of the EMS-GFM gap in which the baseline disagrees with EMS in the same cells and in the
    same direction, for both directions.
12. Q4: an AOI is "windy" if the area-average ERA5 10 m wind at the hour nearest to the acquisition is
    above 3.3 m/s, otherwise "calm". EMS polarisation is VV, VH or "unknown" if not stated.
    Extra check: GFM rough-water flag against ERA5 wind.
13. Flood mechanism: field "Type" of HANZE v3.0.1; for events HANZE does not cover, an own label from
    the EMS event description, marked as fallback. The EMS sub-category is not used.
14. Analysis is descriptive: per AOI, per event, and per flood mechanism with medians and ranges.
    No statistical tests between groups.

## B. Implementation rules fixed in the pilot (not stated in the proposal)

15. The 20 m grid lies in the UTM zone of the SNAP output; cell edges at 5 m + n x 20 m, so that each
    20 m cell holds exactly four 10 m SNAP pixels.
16. Baseline from 10 m to 20 m: a cell is flooded if at least 2 of its 4 pixels are flooded.
17. EMS polygons: a cell counts if its centre lies inside the polygon.
18. Overlapping GFM scenes or tiles: a cell is flooded (or excluded, or flagged) if either says so.
19. Pre and post images are terrain-corrected onto the same standard pixel grid.
20. Orbit file and thermal noise removal are applied to each frame, then the frames are joined.
21. The decibel conversion, threshold, before-flood test and patch filter run in Python
    (`Scripts/01_threshold_and_mask.py`), not in SNAP.
22. Patch connectivity is 8 (edge or corner) for the baseline patch filter and for Q2.
    "Smaller than 0.5 ha" on the 20 m grid means fewer than 13 cells.
23. ERA5 wind is averaged over the ERA5 cells, each weighted by the part of the AOI inside it.
24. GFM rough-water flag = advisory flag values 2 and 3.

## C. Descriptive extras (reported, never used as labels)

25. WorldCover classes inside the unexplained patches.
26. Share of the EMS-GFM gap on GFM reference water (permanent or seasonal).
27. Rough-water flag share per ERA5 cell and per EMS-GFM class.

## D. Main-study event list

28. All 14 candidate activations are taken (all their Sentinel-1-only first-delivery AOIs, 51 on
    1 November 2026): EMSR788, EMSR792, EMSR795, EMSR800, EMSR802, EMSR850, EMSR855, EMSR856, EMSR858,
    EMSR861, EMSR864, EMSR868, EMSR871, EMSR933. No event is chosen or dropped by hand.
29. An AOI is left out only for one of these reasons, each logged with the reason:
    a) EMS did not produce the map (status "not produced", e.g. because of remote sensing
       limitations), or the product has no observed-flood layer;
    b) the Sentinel-1 GRD scene of the EMS acquisition is not in the Copernicus Data Space;
    c) no pre-flood image meets rule 7.
30. If GFM has no map for an AOI, the AOI keeps the EMS-baseline pair; the number of such AOIs is
    reported (proposal, risk table).
31. If processing all AOIs is too heavy, the fallback of the proposal applies (EMS against GFM with the
    same driver analysis); this would be recorded below.

32. The AOI list, with the reason for every AOI left out, is written by `Scripts/09_aoi_inventory.py`
    to `Results/main_aoi_inventory.csv`. On 23 November 2026 this gave 37 AOIs in 11 events
    (14 of the 51 listed products were not produced by EMS).

## Changes after the lock

(none)
