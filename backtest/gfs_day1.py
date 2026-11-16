"""Day-ahead GFS 0.5 deg (NOAA, public domain, s3://noaa-gfs-bdp-pds) 10 m wind, gust and 2 m temperature at every
club site, from the 00Z run for 06-18 UTC the next day (lead 30-42 h). Same .idx byte-range approach as 4Kasta's
gfs_harvest.py. Output: data/model/gfs_day1.parquet (site, time, gfs1_u, gfs1_v, gfs1_gust, gfs1_t2)."""
import os, sys, tempfile, numpy as np, pandas as pd, requests, pygrib, threading
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from extract_wind import sites
B = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
WANT = {"UGRD:10 m above ground": "u", "VGRD:10 m above ground": "v", "GUST:surface": "gust", "TMP:2 m above ground": "t2"}
FH = [30, 33, 36, 39, 42]
S = sites(); IY = np.rint((90 - S.lat.values) / 0.5).astype(int); IX = np.rint((S.lon.values % 360) / 0.5).astype(int) % 720
_tl = threading.local()
def sess():
    if not hasattr(_tl, "s"): _tl.s = requests.Session()
    return _tl.s
def get(url, rng=None):
    for _ in range(5):
        try:
            r = sess().get(url, headers={"Range": f"bytes={rng[0]}-{rng[1]}"} if rng else {}, timeout=120)
            if r.status_code in (200, 206): return r
            if r.status_code == 404: return None
        except Exception: pass
    return None
def one(day, fh):
    base = f"{B}/gfs.{day:%Y%m%d}/00/atmos/gfs.t00z.pgrb2.0p50.f{fh:03d}"
    idx = get(base + ".idx")
    if idx is None: return None
    recs = [l.split(":") for l in idx.text.strip().splitlines()]; offs = [int(r[1]) for r in recs] + [None]
    out = {"site": S.id.values, "time": day + pd.Timedelta(hours=fh)}
    for i, r in enumerate(recs):
        k = f"{r[3]}:{r[4]}"
        if k in WANT and WANT[k] not in out:
            m = get(base, (offs[i], (offs[i + 1] or 0) - 1))
            if m is None: continue
            with tempfile.NamedTemporaryFile(suffix=".grb2") as f:
                f.write(m.content); f.flush(); g = pygrib.open(f.name); a = g.message(1).values; g.close()
            out["gfs1_" + WANT[k]] = a[IY, IX]
    return pd.DataFrame(out)
if __name__ == "__main__":
    days = [d for y in (2023, 2024, 2025) for d in pd.date_range(f"{y}-04-30", f"{y}-09-29")]
    jobs = [(d, fh) for d in days for fh in FH]
    with ThreadPoolExecutor(24) as ex: parts = [p for p in ex.map(lambda j: one(*j), jobs) if p is not None]
    df = pd.concat(parts, ignore_index=True); os.makedirs(f"{HERE}/data/model", exist_ok=True)
    df.to_parquet(f"{HERE}/data/model/gfs_day1.parquet", index=False); print("DONE gfs", len(parts), "of", len(jobs), len(df))
