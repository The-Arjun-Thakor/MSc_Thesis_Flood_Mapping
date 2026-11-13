"""Record which code produced a result: the git commit of the repository and the time of the run.

Every script writes these two values into its outputs (CSV columns or GeoTIFF tags), so each number in
the thesis can be traced back to the exact version of the code. If code files (Scripts/, config.py) were changed or added
but not committed when the script ran, the commit id ends with '-dirty'.
"""
import datetime, os, subprocess

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


def _git(*args):
    return subprocess.run(['git', '-C', REPO] + list(args), capture_output=True, text=True, check=True).stdout.strip()


def git_commit():
    try:
        commit = _git('rev-parse', '--short=10', 'HEAD')
        dirty = _git('status', '--porcelain', '--', 'Scripts', 'config.py')   # changed or new code files
        return commit + ('-dirty' if dirty else '')
    except Exception:
        return 'unknown'


def run_utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def stamp():
    """Dictionary with the commit id and the run time, ready for CSV columns or GeoTIFF tags."""
    return {'git_commit': git_commit(), 'run_utc': run_utc()}
