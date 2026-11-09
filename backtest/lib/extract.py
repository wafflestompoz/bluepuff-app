"""Extract hourly model data at resort (and context lattice) points from s3://openmeteo and aggregate to daily ski-day features.
Usage: python extract.py MODEL OUTDIR [vars...]
"""
import sys, os, re, time, json, datetime as dt, threading
import numpy as np, pandas as pd, s3fs, omfiles, requests
from httpfs import HttpFS
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(__file__))
from grids import GRIDS

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
WINTERS = [(dt.datetime(y, 11, 1), dt.datetime(y + 1, 5, 1)) for y in range(2021, 2027)]  # 2021/22 .. 2026/27 (live)
DEFAULT_VARS = ["cloud_cover", "cloud_cover_low", "direct_radiation", "shortwave_radiation", "snowfall_water_equivalent",
                "precipitation", "temperature_2m", "wind_gusts_10m", "pressure_msl", "freezing_level_height", "snow_depth", "sunshine_duration"]
fs = s3fs.S3FileSystem(anon=True)  # used for listings only
hfs = HttpFS()

def sites():
    r = pd.read_csv(f"{ROOT}/data/processed/resorts.csv")
    s = r[["id", "lat", "lon"]].copy(); s["kind"] = "resort"
    # context lattice (1 degree) for continental / regional scale features
    la, lo = np.meshgrid(np.arange(42, 54.1, 1.0), np.arange(-4, 20.1, 1.0), indexing="ij")
    lat = pd.DataFrame({"id": [f"L{a:.0f}_{b:.0f}" for a, b in zip(la.ravel(), lo.ravel())], "lat": la.ravel(), "lon": lo.ravel(), "kind": "lattice"})
    return pd.concat([s, lat], ignore_index=True)

def files_for(model, var, meta):
    L = meta["chunk_time_length"] * meta["temporal_resolution_seconds"]
    names = [p.split("/")[-1] for p in fs.ls(f"openmeteo/data/{model}/{var}/")]
    out = []
    chunks = {int(m.group(1)): n for n in names for m in [re.match(r"chunk_(\d+)\.om$", n)] if m}
    years = {int(m.group(1)): n for n in names for m in [re.match(r"year_(\d+)\.om$", n)] if m}
    first_chunk_t = min(chunks) * L if chunks else 1e18
    for w0, w1 in WINTERS:
        t0, t1 = w0.replace(tzinfo=dt.timezone.utc).timestamp(), w1.replace(tzinfo=dt.timezone.utc).timestamp()
        for c, n in chunks.items():
            cs, ce = c * L, (c + 1) * L
            if ce > t0 and cs < t1: out.append((n, cs, meta["temporal_resolution_seconds"]))
        for y, n in years.items():
            ys, ye = dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc).timestamp(), dt.datetime(y + 1, 1, 1, tzinfo=dt.timezone.utc).timestamp()
            if ye > t0 and ys < t1 and ys < first_chunk_t: out.append((n, ys, meta["temporal_resolution_seconds"]))
    return sorted(set(out), key=lambda x: x[1])

def read_file(model, var, fname, t_start, res, groups, win_hours):
    """returns dict site_idx -> (times array, values array)"""
    path = f"openmeteo/data/{model}/{var}/{fname}"
    for attempt in range(4):
        try:
            r = omfiles.OmFileReader.from_fsspec(hfs, path); break
        except Exception as e:
            if attempt == 3: print("open fail", path, e, flush=True); return {}
            time.sleep(2 * (attempt + 1))
    shp = r.shape; nt = shp[-1]
    times = t_start + np.arange(nt) * res
    # restrict to winter hours to save reads
    keep = np.zeros(nt, bool)
    for a, b in win_hours: keep |= (times >= a) & (times < b)
    if not keep.any(): return {}
    i0, i1 = int(np.argmax(keep)), int(nt - np.argmax(keep[::-1]))
    out = {}
    for key, members in groups.items():
        try:
            if len(shp) == 3 and shp[0] > 1:
                y, (x0, x1) = key
                a = r.read_array((slice(y, y + 1), slice(x0, x1), slice(i0, i1)))[0]
                for si, x in members: out[si] = a[x - x0]
            else:
                f0, f1 = key
                a = r.read_array((slice(f0, f1), slice(i0, i1))) if len(shp) == 2 else r.read_array((slice(0, 1), slice(f0, f1), slice(i0, i1)))[0]
                for si, f in members: out[si] = a[f - f0]
        except Exception as e:
            print("read fail", path, key, str(e)[:120], flush=True)
    r.close()
    return {k: (times[i0:i1], v) for k, v in out.items()}

def build_groups(g, S, shape, chunks):
    groups = {}
    for si, (la, lo) in enumerate(zip(S.lat, S.lon)):
        yx = g.index(la, lo)
        if yx is None: continue
        if len(shape) == 3 and shape[0] > 1:
            cx = chunks[1]; x0 = (yx[1] // cx) * cx
            groups.setdefault((yx[0], (x0, min(x0 + cx, shape[1]))), set()).add((si, yx[1]))
        else:
            f = g.flat(yx); cf = chunks[-2]; f0 = (f // cf) * cf
            groups.setdefault((f0, f0 + cf), set()).add((si, f))
    return groups

def daily(times, vals, var):
    """aggregate hourly series to ski-day features. day d: daytime = 07-15 UTC (08-16 CET); snow window = d-1 08 UTC -> d 08 UTC."""
    s = pd.Series(vals, index=pd.to_datetime(times, unit="s")).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s = s.resample("1h").asfreq() if len(s) > 1 and (s.index[1] - s.index[0]) <= pd.Timedelta("1h") else s
    day = s[(s.index.hour >= 7) & (s.index.hour <= 15)]
    D = {}
    if var in ("cloud_cover", "cloud_cover_low", "direct_radiation", "shortwave_radiation", "temperature_2m", "freezing_level_height", "pressure_msl"):
        D[var + "_day"] = day.groupby(day.index.date).mean()
    if var == "sunshine_duration":
        D[var + "_day"] = day.groupby(day.index.date).sum() / 3600
    if var == "temperature_2m":
        D["t2m_min24"] = s.shift(16, freq="h").pipe(lambda x: x.groupby(x.index.date).min())  # 08 UTC d-1 .. 08 UTC d
    if var == "wind_gusts_10m":
        D[var + "_daymax"] = day.groupby(day.index.date).max()
    if var in ("snowfall_water_equivalent", "precipitation"):
        x = s.shift(16, freq="h")  # sum of 08 UTC (d-1) .. 07 UTC (d) assigned to day d
        cnt = x.groupby(x.index.date).count()
        sm = x.groupby(x.index.date).sum()
        D[var + "_24h"] = sm.where(cnt >= 20)
    if var == "snow_depth":
        D[var + "_08"] = s[s.index.hour == 8].pipe(lambda x: x.groupby(x.index.date).mean())
    return pd.DataFrame(D).dropna(how="all")

def main(model, outdir, vars_):
    os.makedirs(outdir, exist_ok=True)
    meta = requests.get(f"https://openmeteo.s3.amazonaws.com/data/{model}/static/meta.json", timeout=30).json()
    g = GRIDS[model]; S = sites()
    win_hours = [(a.replace(tzinfo=dt.timezone.utc).timestamp() - 86400, b.replace(tzinfo=dt.timezone.utc).timestamp()) for a, b in WINTERS]
    avail = {p.split("/")[-1] for p in fs.ls(f"openmeteo/data/{model}/")}
    for var in vars_:
        if var not in avail: continue
        outp = f"{outdir}/{model}__{var}.parquet"
        if os.path.exists(outp): print("skip", outp); continue
        files = files_for(model, var, meta)
        if not files: continue
        t = time.time(); acc = {}
        # discover shapes (one header read per distinct layout) and build groups
        layouts = {}
        def shape_of(fn):
            r = omfiles.OmFileReader.from_fsspec(hfs, f"openmeteo/data/{model}/{var}/{fn}")
            shp, chk = tuple(r.shape), tuple(r.chunks); r.close(); return fn, shp, chk
        with ThreadPoolExecutor(32) as ex:
            shapes = list(ex.map(lambda f: shape_of(f[0]), files))
        jobs = []
        for (fn, ts, res), (_, shp, chk) in zip(files, shapes):
            key = (shp[:-1], chk[:-1])
            if key not in layouts: layouts[key] = build_groups(g, S, shp, chk)
            items = list(layouts[key].items())
            B = int(os.environ.get("GROUPS_PER_JOB", 12))
            for b in range(0, len(items), B):
                jobs.append((fn, ts, res, dict(items[b:b + B])))
        print(f"{model} {var}: {len(files)} files, {len(jobs)} jobs", flush=True)
        with ThreadPoolExecutor(int(os.environ.get("NTHREADS", 96))) as ex:
            futs = [ex.submit(read_file, model, var, fn, ts, res, grp, win_hours) for fn, ts, res, grp in jobs]
            for k, fu in enumerate(as_completed(futs)):
                for si, (tt, vv) in fu.result().items():
                    acc.setdefault(si, []).append((tt, vv))
                if k % 500 == 0: print(f"{model} {var} {k+1}/{len(jobs)} jobs {time.time()-t:.0f}s", flush=True)
        frames = []
        for si, parts in acc.items():
            tt = np.concatenate([p[0] for p in parts]); vv = np.concatenate([p[1] for p in parts]).astype("float32")
            d = daily(tt, vv, var); d["site"] = S.id.iloc[si]; frames.append(d)
        if not frames: continue
        df = pd.concat(frames); df.index.name = "date"; df = df.reset_index()
        df.to_parquet(outp, index=False)
        print(f"DONE {model} {var} rows={len(df)} {time.time()-t:.0f}s", flush=True)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:] or DEFAULT_VARS)
