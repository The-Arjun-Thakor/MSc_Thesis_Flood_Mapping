# Data sources and how they were obtained

The data is not stored in this repository. This file records where every input came from, when it was
obtained and how, so that it can be obtained again. Frame-level checksums are in `download_manifest.csv`
on the data drive.

## Pilot: EMSR866, AOI 1 (Cognac)

| Data | How it was obtained | When |
|---|---|---|
| EMS observed flood layer, product version 2 (`EMSR866_AOI01_DEL_PRODUCT_observedEventA_v2.json`) | Downloaded from the public EMS Rapid Mapping viewer bucket (`rapidmapping-viewer.s3.eu-west-1.amazonaws.com/EMSR866/AOI01/DEL_PRODUCT/`). The copy `EMSR866_Official_Flood.json` is byte-identical. | 1 Nov 2026 |
| EMS full vector package, version 2 (`EMSR866_AOI01_DEL_PRODUCT_v2.zip`: AOI outline, observed and modelled flood, flood depth, image footprints, source table, PDF map) | Downloaded by hand from the EMS Rapid Mapping page of EMSR866, AOI01, delineation product | 12 Nov 2026 |
| Sentinel-1C IW GRDH frames, post-flood 12 Feb 2026 17:55 UTC (`..._22D8`, `..._678C`) and pre-flood 31 Jan 2026 (`..._8554`, `..._B14A`) | Downloaded by hand from the Copernicus Data Space Ecosystem (free account). SHA-256 in `download_manifest.csv`. | 1 Nov 2026 |
| GFM ensemble flood extent, exclusion mask and advisory flags, scenes 2026-02-12 17:55:04 and 17:55:29 UTC | GFM portal (`portal.gfm.eodc.eu`, reached through GloFAS): an area of interest was drawn by hand as a rectangle around Cognac, named `EMSR866_Cognac`, and the layers were downloaded for it. The portal delivers whole Equi7 tiles (EU020M grid). Six zip files, named `emsr866_cognac_<scene time>_<layer>_<download time>.zip`. | 2 Nov 2026, 09:22 UTC |
| GFM reference water mask (monthly, February) for the same two scenes | Same portal and same drawn area | 13 Nov 2026, 22:57 UTC |
| ESA WorldCover 2021 v200, tiles N45W003 and N45E000 (`*_Map.tif`) | Downloaded by hand from the ESA WorldCover website (worldcover.org) | 13 Nov 2026 |
| ERA5 10 m wind (u, v), 12 Feb 2026 18:00 UTC | Climate Data Store API, by `Scripts/06_era5_wind.py` | 13 Nov 2026, 23:59 UTC |
| Copernicus DEM GLO-30, precise orbit files | Downloaded automatically by SNAP during processing | 12 Nov 2026 |

Because the GFM area for the pilot was drawn by hand, its exact outline is not recorded. It does not
affect the results: the portal delivers whole tiles, and every layer is clipped to the EMS AOI on the
20 m grid (`Scripts/02_make_grid20m.py`). The pilot is not part of the main-study results.

## Main study

| Data | How it is obtained |
|---|---|
| EMS activation and product metadata | Public EMS API, by `Scripts/08_fetch_ems_metadata.py` (saved raw, with the fetch time) |
| AOI list and reasons for leaving AOIs out | `Scripts/09_aoi_inventory.py` -> `Results/main_aoi_inventory.csv` |
| Sentinel-1 frame selection (post-flood and pre-flood) | Copernicus Data Space catalogue, by `Scripts/10_find_s1_scenes.py` -> `Results/main_s1_scenes.csv`, `Results/main_s1_downloads.csv` |
| Sentinel-1 frames | Copernicus Data Space, by `Scripts/11_download_s1.py` (MD5 checked against the catalogue, SHA-256 recorded) |
| GFM layers | EODC STAC catalogue, by script (to follow) |
| EMS vector packages, WorldCover tiles, ERA5, HANZE | to be added |
