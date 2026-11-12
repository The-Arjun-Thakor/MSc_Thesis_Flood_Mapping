"""Helpers shared by the Stage 0 scripts: locate the pilot data on the data drive (config.DATA_ROOT)
and read Sentinel-1 GRD products straight from their .SAFE.zip files (no unzipped copy needed)."""
import glob, os, re, sys, tempfile, zipfile, contextlib, shutil
import xml.etree.ElementTree as ET
import numpy as np, tifffile

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, REPO)
from config import DATA_ROOT

PILOT = os.path.join(DATA_ROOT, '01_raw', 'EMSR866_pilot')
EMS_FLOOD = os.path.join(PILOT, 'EMS', 'EMSR866_Official_Flood.json')
RESULTS = os.path.join(REPO, 'Results')
DATES = [('2026-02-12 post', 'S1_post'), ('2026-01-31 pre', 'S1_pre')]


def frames(folder):
    """Sorted list of the .SAFE.zip frames of one date ('S1_post' or 'S1_pre')."""
    z = sorted(glob.glob(os.path.join(PILOT, folder, '*.SAFE.zip')))
    if not z:
        sys.exit('No .SAFE.zip found in %s - is the data drive connected and config.DATA_ROOT right?'
                 % os.path.join(PILOT, folder))
    return z


def _member(zf, pattern):
    names = sorted(n for n in zf.namelist() if re.search(pattern, n))
    if not names:
        raise FileNotFoundError('%s not found in %s' % (pattern, zf.filename))
    return names[0]


def footprint_coords(zip_path):
    """Frame footprint from manifest.safe as a list of (lon, lat)."""
    with zipfile.ZipFile(zip_path) as zf:
        txt = zf.read(_member(zf, r'\.SAFE/manifest\.safe$')).decode('utf-8')
    c = re.search(r'<gml:coordinates>([^<]+)', txt).group(1).split()
    return [(float(p.split(',')[1]), float(p.split(',')[0])) for p in c]  # lat,lon -> lon,lat


def geolocation_grid(zip_path):
    """Geolocation grid of the VV band: array of rows (line, pixel, latitude, longitude)."""
    with zipfile.ZipFile(zip_path) as zf:
        root = ET.fromstring(zf.read(_member(zf, r'\.SAFE/annotation/s1[^/]*-vv-[^/]*\.xml$')))
    return np.array([[float(p.find(t).text) for t in ('line', 'pixel', 'latitude', 'longitude')]
                     for p in root.iter('geolocationGridPoint')])


@contextlib.contextmanager
def vv_image(zip_path):
    """VV measurement image as a read-only memmap. The .tiff is extracted from the zip to a temporary
    folder (about 1 GB) and removed again when the with-block ends."""
    tmp = tempfile.mkdtemp(prefix='s1vv_')
    tf = None
    try:
        with zipfile.ZipFile(zip_path) as zf:
            name = _member(zf, r'\.SAFE/measurement/s1[^/]*-vv-[^/]*\.tiff$')
            out = os.path.join(tmp, os.path.basename(name))
            with zf.open(name) as src, open(out, 'wb') as dst:
                shutil.copyfileobj(src, dst, 16 * 1024 * 1024)
        tf = tifffile.TiffFile(out)
        try:
            img = tf.pages[0].asarray(out='memmap')
        except Exception:            # compressed tiff: cannot be memory-mapped, read it normally
            img = tf.pages[0].asarray()
        yield img
        del img
    finally:
        if tf is not None:
            tf.close()
        shutil.rmtree(tmp, ignore_errors=True)
