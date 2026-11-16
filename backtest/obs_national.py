"""Hourly wind from the national open-data networks, for stations that NOAA's ISD archive lacks or only has 3-hourly:
  knmi : KNMI hourly data (daggegevens.knmi.nl), incl. North Sea platforms, IJsselmeer/Markermeer dykes, Zeeland water stations
  dwd  : DWD Climate Data Center 10-minute wind (opendata.dwd.de), incl. lighthouses and harbour stations
  ch   : MeteoSwiss open data SwissMetNet 10-minute (data.geo.admin.ch), incl. lakeshore stations
  dmi  : DMI metObs API v2 (opendataapi.dmi.dk, no key), incl. lighthouses and islands
  isd  : NOAA ISD (s3://noaa-isd-pds), as obs.py
All are the 10-minute mean ending at the full hour (KNMI FF; DWD FF_10; MeteoSwiss fkl010z0; DMI wind_speed), plus direction and,
where available, the hour's max gust. May-Sep 2023-25.
Usage: python obs_national.py STATIONS_CSV OUT_DIR   (csv columns: club, station 'net:id'; club is the row key, often the station itself)
Writes OUT_DIR/obs.parquet in obs.py's format: club, time (UTC), obs_ws (m/s), obs_dir (deg), obs_gust (m/s, may be NaN).
UK Met Office MIDAS (CEDA) needs a CEDA login, and Meteo-France's open data host is blocked here, so neither is used yet.
"""
import io, os, sys, time, zipfile, requests, numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
import obs as ISD
YEARS = [2023, 2024, 2025]; MONTHS = range(5, 10)

def get(url, **kw):
    for k in range(5):
        try:
            r = requests.get(url, timeout=300, **kw) if "data" not in kw else requests.post(url, timeout=300, **kw)
            if r.status_code in (200, 404): return r
        except requests.RequestException: pass
        time.sleep(3 * (k + 1))
    raise RuntimeError(url)

def summer(df):
    df = df.dropna(subset=["obs_ws"]); df = df[(df.time.dt.minute == 0) & df.time.dt.year.isin(YEARS) & df.time.dt.month.isin(MONTHS)]
    return df.drop_duplicates("time").sort_values("time")

def knmi(sid):
    out = []
    for y in YEARS:
        r = get("https://www.daggegevens.knmi.nl/klimatologie/uurgegevens",
                data={"start": f"{y}050101", "end": f"{y}100124", "vars": "DD:FF:FX", "stns": sid})
        rows = [l.split(",") for l in r.text.splitlines() if l and not l.startswith("#")]
        for p in rows:
            p = [x.strip() for x in p]
            t = pd.Timestamp(p[1]) + pd.Timedelta(hours=int(p[2]))      # HH = hour ending, UT
            f = lambda x: float(x) if x not in ("",) else np.nan
            dd = f(p[3]); out.append((t, f(p[4]) / 10, np.nan if dd in (0, 990) else dd, f(p[5]) / 10))
    return pd.DataFrame(out, columns=["time", "obs_ws", "obs_dir", "obs_gust"])

DWD = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes"
_idx = {}
def dwd_files(kind, sub):
    if (kind, sub) not in _idx: _idx[kind, sub] = get(f"{DWD}/{kind}/{sub}/").text
    return _idx[kind, sub]

def dwd_read(kind, sid):
    import re
    frames = []
    for sub in ("historical", "recent"):
        for fn in re.findall(rf'href="(10minutenwerte_[a-z_]*_{sid}_[^"]*\.zip)"', dwd_files(kind, sub)):
            if sub == "historical":
                a, b = fn.split("_")[-3:-1]
                if b < f"{YEARS[0]}0501" or a > f"{YEARS[-1]}1001": continue
            z = zipfile.ZipFile(io.BytesIO(get(f"{DWD}/{kind}/{sub}/{fn}").content))
            d = pd.read_csv(z.open(z.namelist()[0]), sep=";", skipinitialspace=True); d.columns = [c.strip() for c in d.columns]
            d["time"] = pd.to_datetime(d.MESS_DATUM.astype(str), format="%Y%m%d%H%M"); frames.append(d)
    if not frames: return None
    d = pd.concat(frames).drop_duplicates("time").set_index("time").replace(-999, np.nan)
    return d

def dwd(sid):
    w = dwd_read("wind", sid)
    if w is None: return pd.DataFrame(columns=["time", "obs_ws", "obs_dir", "obs_gust"])
    out = pd.DataFrame({"obs_ws": w.FF_10, "obs_dir": w.DD_10})
    g = dwd_read("extreme_wind", sid)              # FX_10: max gust in the 10 minutes -> hourly max of the last 6
    if g is not None and "FX_10" in g: out["obs_gust"] = g.FX_10.reindex(out.index).rolling(6, min_periods=4).max()
    else: out["obs_gust"] = np.nan
    return out.reset_index()

def ch(sid):
    s = sid.lower(); frames = []
    for part in ("historical_2020-2029", "recent"):
        r = get(f"https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/{s}/ogd-smn_{s}_t_{part}.csv")
        if r.status_code != 200: continue
        d = pd.read_csv(io.StringIO(r.text), sep=";"); frames.append(d)
    d = pd.concat(frames)
    d["time"] = pd.to_datetime(d.reference_timestamp, format="%d.%m.%Y %H:%M")
    d = d.drop_duplicates("time").set_index("time").sort_index()
    gust = d.fkl010z1.rolling(6, min_periods=4).max() if "fkl010z1" in d else np.nan     # z1: max 1-s gust in the 10 minutes
    return pd.DataFrame({"obs_ws": d.fkl010z0, "obs_dir": d.dkl010z0, "obs_gust": gust}).reset_index()

def dmi(sid):
    out = {}
    for par, col in (("wind_speed", "obs_ws"), ("wind_dir", "obs_dir"), ("wind_max", "obs_gust")):
        for y in YEARS:
            r = get("https://opendataapi.dmi.dk/v2/metObs/collections/observation/items",
                    params={"stationId": sid, "parameterId": par, "datetime": f"{y}-05-01T00:00:00Z/{y}-10-01T00:00:00Z", "limit": 300000})
            for f in r.json().get("features", []):
                p = f["properties"]; out.setdefault(p["observed"], {})[col] = p["value"]
    d = pd.DataFrame.from_dict(out, orient="index")
    if d.empty: return pd.DataFrame(columns=["time", "obs_ws", "obs_dir", "obs_gust"])
    d.index = pd.to_datetime(d.index).tz_localize(None); d = d.sort_index()
    for c in ("obs_ws", "obs_dir", "obs_gust"):
        if c not in d: d[c] = np.nan
    d["obs_gust"] = d.obs_gust.rolling("60min").max()          # wind_max: max 3-s gust in the 10 minutes -> the hour's max
    return d.rename_axis("time").reset_index()[["time", "obs_ws", "obs_dir", "obs_gust"]]

def isd(sid):
    ISD.YEARS = YEARS; return ISD.station("x", sid).drop(columns="club")

def one(club, station):
    net, sid = station.split(":", 1)
    try: d = summer({"knmi": knmi, "dwd": dwd, "ch": ch, "dmi": dmi, "isd": isd}[net](sid))
    except Exception as e: print("fail", station, repr(e)[:200], flush=True); return None
    print(f"{station:14s} {club:22s} hours={len(d)}", flush=True); return d.assign(club=club)

if __name__ == "__main__":
    S = pd.read_csv(sys.argv[1], dtype=str); out = sys.argv[2]; os.makedirs(out, exist_ok=True)
    with ThreadPoolExecutor(8) as ex: parts = list(ex.map(lambda r: one(r.club, r.station), S.itertuples()))
    O = pd.concat([p for p in parts if p is not None], ignore_index=True)
    O.to_parquet(f"{out}/obs.parquet", index=False)
    print(O.groupby("club").agg(n=("obs_ws", "size"), ws=("obs_ws", "mean"), gust=("obs_gust", lambda x: x.notna().mean())).round(2).to_string())
