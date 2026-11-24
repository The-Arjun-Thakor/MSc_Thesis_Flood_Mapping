# MSc_Thesis_Flood_Mapping

Code and result tables for the M.Sc. thesis
**"Where Sentinel-1 flood maps disagree: a driver-attributed comparison of expert, automated and baseline maps"**
(Arjunsinh Thakor, 100001862, SRH University of Applied Sciences Heidelberg, Campus Leipzig;
supervisor Prof. Dr. Klaus Dieter Schwarz).

The thesis compares three flood maps of the same Sentinel-1 image: the Copernicus EMS expert map, the
Copernicus GFM automatic map and a fixed baseline pipeline, and measures where they disagree.

## Status (15 November 2026)

- The pipeline runs end to end on the **pilot** (EMSR866, AOI 1, Cognac, flood of February 2026).
- All tables in `Results/` are **pilot outputs** (file names start with `pilot_`). They test the pipeline
  and are not results of the thesis.
- The rules are **not locked yet**. The event list and a rules file will be committed before the main
  events are processed.

## Folders

| Path | Content |
|---|---|
| `Scripts/` | SNAP processing graph and Python scripts (see below) |
| `Results/` | Result tables (CSV) and figures |
| `config.py` | One setting: the folder that holds the data (`DATA_ROOT`) |
| `Thesis_Docs/` | Thesis documents |

The data is not in this repository. It is kept on a separate drive in three folders:
`01_raw` (downloads), `02_snap_out` (SNAP outputs, 10 m) and `03_grid20m` (all layers on the common 20 m grid).

## Pipeline

| Step | File | What it does |
|---|---|---|
| 0 | `check_alignment.py`, `quicklook.py`, `s1_safe.py` | Check that the Sentinel-1 frames cover the EMS flood layer |
| 1 | `s1_baseline_2frames.xml` | SNAP graph: orbit file, thermal noise removal, slice assembly, calibration (sigma0, VV), subset, Lee filter 7x7, terrain correction (Copernicus DEM GLO-30, 10 m) |
| 2 | `01_threshold_and_mask.py` | Baseline flood mask: below -16.5 dB after the flood and not below before it; patches under 0.5 ha removed |
| 3 | `02_make_grid20m.py` | EMS, GFM, baseline and driver layers on one 20 m grid |
| 4 | `03_compute_agreement.py` | Q1: IoU, omission and commission per pair of maps |
| 5 | `04_patch_labelling.py` | Q2: patches of the disagreeing area and their labels |
| 6 | `05_gap_overlap.py` | Q3: the baseline inside the EMS-GFM gap |
| 7 | `06_era5_wind.py` | Q4: ERA5 wind over the AOI |
| 8 | `07_roughwater_flag.py` | Q4: GFM rough-water flag against ERA5 wind |
| - | `provenance.py` | Writes the git commit and run time into every output |
| - | `aoi_paths.py` | Input and output paths of one AOI (pilot or main study); command-line options `--event`, `--aoi`, `--all` |

### Main study: data preparation

| Step | File | What it does |
|---|---|---|
| 1 | `08_fetch_ems_metadata.py` | Saves the public EMS API answer of every candidate activation |
| 2 | `09_aoi_inventory.py` | Lists the AOIs and applies the selection rules -> `Results/main_aoi_inventory.csv` |
| 3 | `10_find_s1_scenes.py` | Finds the post- and pre-flood Sentinel-1 frames -> `Results/main_s1_scenes.csv`, `main_s1_downloads.csv` |
| 4 | `11_download_s1.py` | Downloads the frames (Copernicus Data Space login), checks MD5 |
| 5 | `12_run_snap.py` | Runs `s1_baseline_1frame.xml` / `s1_baseline_2frames.xml` with SNAP gpt for every AOI and date |
| 6 | `13_download_gfm.py` | GFM layers of the post-flood scenes from the EODC STAC catalogue |
| 7 | `14_download_ems.py` | EMS delineation packages |
| 8 | `15_download_worldcover.py` | ESA WorldCover tiles |

The analysis scripts 01-07 run for the pilot without options, and for the main study with `--all`
(or `--event EMSRxxx --aoi AOIyy` for one AOI). Main-study tables are `Results/main_<name>.csv`.

## How to run the pilot

1. Software: ESA SNAP 14 and Python with `numpy`, `scipy`, `pandas`, `rasterio`, `geopandas`, `shapely`,
   `tifffile`, `matplotlib`, `xarray`, `netCDF4`, `cdsapi`.
2. Set `DATA_ROOT` in `config.py` (or the environment variable `THESIS_DATA_ROOT`) to the data folder.
3. Run the SNAP graph once per date with `gpt` (the command is in the first lines of the `.xml` file).
4. Run the scripts in order: `python Scripts/01_threshold_and_mask.py`, then `02` to `07`
   (add `--all` for the main study).
   `06_era5_wind.py` needs a Climate Data Store key in the file `.cdsapirc` in the user's home folder.

Every result table has the columns `git_commit` and `run_utc`. They show which version of the code
produced the numbers. A commit id ending in `-dirty` means the code had uncommitted changes.

## Data sources

Sentinel-1 GRD (Copernicus Data Space Ecosystem), Copernicus EMS Rapid Mapping products,
Copernicus GFM layers (GloFAS portal), Copernicus DEM GLO-30, ESA WorldCover 2021 v200, ERA5 (Copernicus
Climate Data Store).
