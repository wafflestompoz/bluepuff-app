"""Hourly model wind at each club's station, its water point and 4 neighbours (~15 km), summers 2023-2025,
from Open-Meteo's open-data archive (s3://openmeteo/data, CC BY 4.0). Reuses 4Kasta's readers (copied to lib/ from bluepow-app).
The archive holds each model's most recent short-range forecast per hour (lead ~0-12 h), so this measures same-day skill.
Usage: python extract_wind.py MODEL [vars...]  ->  data/model/<model>__<var>.parquet (site, time, value)
"""
import sys, os, time, datetime as dt, numpy as np, pandas as pd, requests, omfiles
from concurrent.futures import ThreadPoolExecutor, as_completed
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))   # 4Kasta open-data readers, copied from bluepow-app model/kasta/src
import extract
from grids import GRIDS
SUMMERS = [(dt.datetime(y, 5, 1), dt.datetime(y, 10, 1)) for y in (2023, 2024, 2025)]
extract.WINTERS = SUMMERS                      # files_for() picks chunks overlapping these windows
VARS = ["wind_u_component_10m", "wind_v_component_10m", "wind_gusts_10m"]
NB = 0.15

ALL = os.environ.get("ALL") == "1"   # ALL=1: station point only, for every station in all_stations.csv -> data/all/model

def sites():
    if ALL:
        A = pd.read_csv(f"{HERE}/all_stations.csv"); return pd.DataFrame({"id": A.id + "|st", "lat": A.lat, "lon": A.lon})
    C = pd.read_csv(f"{HERE}/clubs.csv"); S = pd.read_csv(f"{HERE}/stations.csv")
    H = pd.read_csv(os.environ.get("ISD_HISTORY", "/tmp/claude-0/sail/isd-history.csv"), dtype=str); H["station"] = H.USAF + "-" + H.WBAN
    S = S.merge(H[["station", "LAT", "LON"]], on="station"); S["slat"] = S.LAT.astype(float); S["slon"] = S.LON.astype(float)
    rows = []
    for r in S.merge(C, left_on="club", right_on="id").itertuples():
        rows += [(f"{r.club}|st", r.slat, r.slon), (f"{r.club}|water", r.lat, r.lon)]
        for k, (a, b) in {"n": (NB, 0), "s": (-NB, 0), "e": (0, NB * 1.5), "w": (0, -NB * 1.5)}.items():
            rows.append((f"{r.club}|{k}", r.slat + a, r.slon + b))
    return pd.DataFrame(rows, columns=["id", "lat", "lon"])

def main(model, vars_):
    out = f"{HERE}/data/all/model" if ALL else f"{HERE}/data/model"; os.makedirs(out, exist_ok=True)
    meta = requests.get(f"https://openmeteo.s3.amazonaws.com/data/{model}/static/meta.json", timeout=30).json()
    g = GRIDS[model]; S = sites()
    win = [(a.replace(tzinfo=dt.timezone.utc).timestamp(), b.replace(tzinfo=dt.timezone.utc).timestamp()) for a, b in SUMMERS]
    for var in vars_:
        outp = f"{out}/{model}__{var}.parquet"
        if os.path.exists(outp): continue
        files = extract.files_for(model, var, meta)
        if not files: print("no files", model, var); continue
        t = time.time(); layouts = {}; jobs = []
        def shape_of(fn):
            r = omfiles.OmFileReader.from_fsspec(extract.hfs, f"openmeteo/data/{model}/{var}/{fn}")
            s = (tuple(r.shape), tuple(r.chunks)); r.close(); return s
        with ThreadPoolExecutor(32) as ex: shapes = list(ex.map(lambda f: shape_of(f[0]), files))
        for (fn, ts, res), (shp, chk) in zip(files, shapes):
            key = (shp[:-1], chk[:-1])
            if key not in layouts: layouts[key] = extract.build_groups(g, S, shp, chk)
            items = list(layouts[key].items())
            for b in range(0, len(items), 12): jobs.append((fn, ts, res, dict(items[b:b + 12])))
        acc = {}
        with ThreadPoolExecutor(64) as ex:
            futs = [ex.submit(extract.read_file, model, var, fn, ts, res, grp, win) for fn, ts, res, grp in jobs]
            for fu in as_completed(futs):
                for si, (tt, vv) in fu.result().items(): acc.setdefault(si, []).append((tt, vv))
        frames = []
        for si, parts in acc.items():
            tt = np.concatenate([p[0] for p in parts]); vv = np.concatenate([p[1] for p in parts]).astype("float32")
            d = pd.DataFrame({"time": pd.to_datetime(tt, unit="s"), "v": vv}).dropna().drop_duplicates("time", keep="last")
            d["site"] = S.id.iloc[si]; frames.append(d)
        df = pd.concat(frames, ignore_index=True)
        df.to_parquet(outp, index=False)
        print(f"DONE {model} {var} sites={df.site.nunique()} rows={len(df)} files={len(files)} {time.time()-t:.0f}s", flush=True)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or VARS)
