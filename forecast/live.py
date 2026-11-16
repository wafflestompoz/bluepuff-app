"""Live club forecast from Open-Meteo's free open-data copy on AWS (s3://openmeteo, CC BY 4.0). No API calls.

Open-Meteo keeps each model's latest run in the newest time chunks of its .om files (data/<model>/<var>/chunk_N.om),
running ahead to `data_end_time` in data/<model>/static/meta.json. This reads just those chunks at each club's race area
with byte-range requests (the 4Kasta readers in backtest/lib), so it costs no Open-Meteo API quota.

Per club and hour: each model's 10 m wind and gusts (kn) and direction, the multi-model mean, chop from fetch and depth
(backtest/chop.py), and for sea clubs DWD EWAM waves and Meteo-France sea level (tide + surge) and currents.

Usage: python forecast/live.py [club ...]   ->  forecast/out/latest.json and forecast/out/<club>.csv
Env:   HOURS_BACK (default 6), OUT_DIR (default forecast/out)
"""
import os, sys, re, json, time, math, datetime as dt
import numpy as np, pandas as pd, requests, omfiles
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, f"{ROOT}/backtest/lib"); sys.path.insert(0, f"{ROOT}/backtest")
from httpfs import HttpFS
from grids import GRIDS, Regular
from chop import chop, label

KN = 1.943844
BASE = "https://openmeteo.s3.amazonaws.com"
WIND_EU = {"ecmwf_ifs": "ifs", "dwd_icon_eu": "iconeu", "dwd_icon_d2": "icond2", "ukmo_global_deterministic_10km": "ukmo",
           "meteofrance_arome_france0025": "arome", "meteofrance_arpege_europe": "arpege"}
WIND_GLOBAL = {"ecmwf_ifs": "ifs", "dwd_icon": "icon", "ukmo_global_deterministic_10km": "ukmo", "meteofrance_arpege_world025": "arpege"}
WIND = {"europe": WIND_EU, "au": WIND_GLOBAL}          # region -> models; anywhere else uses the global set
GRIDS["dwd_ewam"] = Regular(721, 526, 30.0, -10.5, 0.05, 0.1)
GRIDS["meteofrance_currents"] = Regular(2041, 4320, -79.958336, -179.95833, 1 / 12, 1 / 12)
GRIDS["meteofrance_wave"] = Regular(2041, 4320, -79.958336, -179.95833, 1 / 12, 1 / 12)
WAVES = ["wave_height", "wave_period", "wave_direction", "swell_wave_height"]
TIDES = ("meteofrance_currents", ["sea_level_height_msl", "ocean_u_current", "ocean_v_current"])
MARINE = {"europe": {"dwd_ewam": WAVES, TIDES[0]: TIDES[1]}, "au": {"meteofrance_wave": WAVES, TIDES[0]: TIDES[1]}}
MARINE_STEPS_KM = [0, 3, 6, 10, 15]          # race area, then out toward open water, until a sea cell has data
hfs = HttpFS()

def meta(model):
    return requests.get(f"{BASE}/data/{model}/static/meta.json", timeout=30).json()

def chunk_files(model, var, m, t0, t1):
    """The chunk files covering [t0, t1): file name and its start time."""
    L = m["chunk_time_length"] * m["temporal_resolution_seconds"]
    want = range(int(t0 // L), int(t1 // L) + 1)
    return [(f"chunk_{c}.om", c * L) for c in want
            if requests.head(f"{BASE}/data/{model}/{var}/chunk_{c}.om", timeout=30).status_code == 200]

def read_points(model, var, fname, tstart, res, pts, t0):
    """Values at grid points [(name, y, x)] from one chunk, from time t0 on. Returns {name: (times, values)}."""
    r = omfiles.OmFileReader.from_fsspec(hfs, f"openmeteo/data/{model}/{var}/{fname}")
    shp = r.shape; nt = shp[-1]; times = tstart + np.arange(nt) * res
    i0 = int(np.searchsorted(times, t0)); out = {}
    g = GRIDS[model]
    for name, yx in pts:
        if yx is None or i0 >= nt: continue
        if len(shp) == 3 and shp[0] > 1:
            a = r.read_array((slice(yx[0], yx[0] + 1), slice(yx[1], yx[1] + 1), slice(i0, nt)))[0, 0]
        else:
            f = g.flat(yx)
            a = r.read_array((slice(f, f + 1), slice(i0, nt)))[0] if len(shp) == 2 else r.read_array((slice(0, 1), slice(f, f + 1), slice(i0, nt)))[0, 0]
        out[name] = (times[i0:], a.astype("float32"))
    r.close(); return out

def series(model, var, pts, t0, m):
    """Hourly series per point for one model variable over the latest run, NaN where the model has no data."""
    files = chunk_files(model, var, m, t0, m["data_end_time"])
    g = GRIDS[model]; P = [(n, g.index(la, lo)) for n, la, lo in pts]
    acc = {}
    for fn, ts in files:
        for k in range(4):
            try:
                for n, (tt, vv) in read_points(model, var, fn, ts, m["temporal_resolution_seconds"], P, t0).items():
                    acc.setdefault(n, []).append(pd.Series(vv, index=pd.to_datetime(tt, unit="s", utc=True)))
                break
            except Exception as e:
                if k == 3: print("read fail", model, var, fn, str(e)[:100], flush=True)
                time.sleep(2 * (k + 1))
    out = {}
    for n, parts in acc.items():
        s = pd.concat(parts).sort_index(); s = s[~s.index.duplicated(keep="last")]
        out[n] = s[s.index <= pd.Timestamp(m["data_end_time"], unit="s", tz="UTC")]
    return out

def marine_points(c):
    """Candidate sea points: the race area, then 3-15 km toward the most open water."""
    brg = math.radians(c.sea_dir_deg if pd.notna(c.sea_dir_deg) else 0)
    return [(f"{c.Index}|k{i}", c.water_lat + d * math.cos(brg) / 111.0, c.water_lon + d * math.sin(brg) / (111.0 * math.cos(math.radians(c.water_lat))))
            for i, d in enumerate(MARINE_STEPS_KM)]

def upwind(row, wdir, prefix="water_fetch_"):
    v = np.array([row[f"{prefix}{k}"] for k in range(16)], float); x = (np.asarray(wdir) % 360) / 22.5
    i0 = np.floor(x).astype(int) % 16; w = x - np.floor(x); return v[i0] * (1 - w) + v[(i0 + 1) % 16] * w

def run(clubs=None):
    C = pd.read_csv(f"{HERE}/clubs_static.csv")
    if clubs: C = C[C.club.isin(clubs)]
    C = C.set_index("club")
    t0 = time.time() - 3600 * float(os.environ.get("HOURS_BACK", 6))
    C["region"] = C.region.fillna("europe") if "region" in C else "europe"
    wind_of = lambda c: WIND.get(C.region[c], WIND_GLOBAL); marine_of = lambda c: MARINE.get(C.region[c], MARINE["au"])
    jobs = []
    for m in dict.fromkeys(k for w in WIND.values() for k in w):
        pts = [(c, r.water_lat, r.water_lon) for c, r in C.iterrows() if m in wind_of(c)]
        if pts: jobs += [(m, v, pts) for v in (["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"] if m.startswith("ukmo")
                                                else ["wind_u_component_10m", "wind_v_component_10m", "wind_gusts_10m"])]
    for m, vs in {k: v for mm in MARINE.values() for k, v in mm.items()}.items():
        sea = [p for r in C[C.water == "sea"].itertuples() if m in marine_of(r.Index) for p in marine_points(r)]
        if sea: jobs += [(m, v, sea) for v in vs]
    metas = {m: meta(m) for m in {j[0] for j in jobs}}
    with ThreadPoolExecutor(16) as ex:
        res = dict(zip([(m, v) for m, v, _ in jobs], ex.map(lambda j: series(j[0], j[1], j[2], t0, metas[j[0]]), jobs)))
    runs = {m: dt.datetime.fromtimestamp(metas[m]["last_run_initialisation_time"], dt.timezone.utc).strftime("%Y-%m-%d %H:%MZ") for m in metas}
    os.makedirs(OUT := os.environ.get("OUT_DIR", f"{HERE}/out"), exist_ok=True)
    summary = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%MZ"), "source": "Open-Meteo open data on AWS (CC BY 4.0)",
               "model_runs": runs, "clubs": {}}
    for club, c in C.iterrows():
        cols = {}
        for m, s in wind_of(club).items():
            if m.startswith("ukmo"):
                sp, dr = res[(m, "wind_speed_10m")].get(club), res[(m, "wind_direction_10m")].get(club)
                if sp is None or dr is None: continue
                rad = np.radians(dr); cols[f"{s}_u"], cols[f"{s}_v"] = -sp * np.sin(rad), -sp * np.cos(rad)
            else:
                u, v = res[(m, "wind_u_component_10m")].get(club), res[(m, "wind_v_component_10m")].get(club)
                if u is None or v is None: continue
                cols[f"{s}_u"], cols[f"{s}_v"] = u, v
            g = res[(m, "wind_gusts_10m")].get(club)
            if g is not None: cols[f"{s}_gust_kn"] = g * KN
        D = pd.DataFrame(cols)
        if D.empty: continue
        for s in wind_of(club).values():
            if f"{s}_u" in D: D[f"{s}_kn"] = np.hypot(D[f"{s}_u"], D[f"{s}_v"]) * KN
        ks = [c_ for c_ in D if c_.endswith("_kn") and "gust" not in c_]
        U = D[[c_ for c_ in D if c_.endswith("_u")]].mean(axis=1); V = D[[c_ for c_ in D if c_.endswith("_v")]].mean(axis=1)
        D["wind_kn"] = D[ks].mean(axis=1); D["wind_spread_kn"] = D[ks].std(axis=1); D["wind_dir"] = np.degrees(np.arctan2(-U, -V)) % 360
        D["gust_kn"] = D[[c_ for c_ in D if c_.endswith("_gust_kn")]].mean(axis=1); D["n_models"] = D[ks].notna().sum(axis=1)
        for s in wind_of(club).values():            # each model's direction, for shift odds (engine/briefing.py)
            if f"{s}_u" in D: D[f"{s}_dir"] = np.degrees(np.arctan2(-D[f"{s}_u"], -D[f"{s}_v"])) % 360
        D = D.drop(columns=[c_ for c_ in D if c_.endswith(("_u", "_v"))])
        if pd.notna(c.water_fetch_0) and pd.notna(c.depth_m):
            D["fetch_km"] = upwind(c, D.wind_dir.values)
            hs, tp, _ = chop(D.wind_kn / KN, D.fetch_km, c.depth_m); D["chop_m"], D["chop_period_s"] = hs, tp
            D["chop"] = label(D.chop_m).astype(str); D["short_chop"] = (hs >= 0.3) & (9.81 * tp ** 2 / (2 * np.pi) < 12)
        if c.water == "sea":
            for (m, v), d in res.items():
                if m not in marine_of(club): continue
                ok = [k for k in range(len(MARINE_STEPS_KM)) if f"{club}|k{k}" in d and d[f"{club}|k{k}"].notna().any()]
                if ok: D[v] = d[f"{club}|k{ok[0]}"]
            if "ocean_u_current" in D:
                D["current_kn"] = np.hypot(D.ocean_u_current, D.ocean_v_current) * KN
                D["current_dir"] = np.degrees(np.arctan2(D.ocean_u_current, D.ocean_v_current)) % 360   # direction it flows to
                D = D.drop(columns=["ocean_u_current", "ocean_v_current"])
        D = D[D.n_models > 0].round(2); D.index.name = "time"
        D.to_csv(f"{OUT}/{club}.csv")
        nxt = D[D.index >= pd.Timestamp.now(tz="UTC").floor("h")].head(48)
        summary["clubs"][club] = {"name": c["name"], "region": c.region, "models": list(wind_of(club).values()), "hours": len(D), "until": D.index.max().strftime("%Y-%m-%d %H:%MZ"),
                                  "next_48h": json.loads(nxt.reset_index().assign(time=lambda x: x.time.dt.strftime("%Y-%m-%dT%H:%MZ"))
                                                         .to_json(orient="records"))}
    json.dump(summary, open(f"{OUT}/latest.json", "w"), indent=1)
    return summary

if __name__ == "__main__":
    t = time.time(); s = run(sys.argv[1:] or None)
    print(f"{len(s['clubs'])} clubs in {time.time() - t:.0f}s; runs: {s['model_runs']}")
