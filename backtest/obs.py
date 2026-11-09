"""Hourly station wind from NOAA ISD (s3://noaa-isd-pds, public domain) for the sailing backtest.
Writes data/obs.parquet: club, time (UTC, hourly), obs_ws (m/s, 10-min mean at the hour), obs_dir (deg), obs_gust (m/s, may be NaN)."""
import gzip, io, re, os, requests, pandas as pd, numpy as np
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
ALL = os.environ.get("ALL") == "1"          # ALL=1: every lowland European station (all_stations.csv) -> data/all/
DATA = f"{HERE}/data/all" if ALL else f"{HERE}/data"; os.makedirs(DATA, exist_ok=True)
YEARS = [2023, 2024, 2025]

def parse(text):
    rows = []
    for ln in text.splitlines():
        if len(ln) < 70: continue
        t = pd.Timestamp(f"{ln[15:23]}T{ln[23:25]}:{ln[25:27]}")
        d, dq, ws, wq = ln[60:63], ln[63], ln[65:69], ln[69]
        if ws == "9999" or wq not in "0145" : continue
        g = re.search(r"OC1(\d{4})(\d)", ln[105:])
        rows.append((t, int(ws) / 10, np.nan if d == "999" else int(d), int(g.group(1)) / 10 if g and g.group(1) != "9999" else np.nan))
    return rows

def station(club, st):
    out = []
    for y in YEARS:
        r = requests.get(f"https://noaa-isd-pds.s3.amazonaws.com/data/{y}/{st}-{y}.gz", timeout=120)
        if r.status_code != 200:
            if not ALL: print("missing", club, st, y)
            continue
        out += parse(gzip.decompress(r.content).decode("latin-1"))
    df = pd.DataFrame(out, columns=["time", "obs_ws", "obs_dir", "obs_gust"])
    if df.empty: return df.assign(club=club)
    # keep reports near the full hour (synop/metar at :00 or :50/:20 for METAR), round to the hour
    df["time"] = df.time.dt.round("1h"); df = df.groupby("time").last().reset_index(); df["club"] = club
    return df

if __name__ == "__main__":
    S = pd.read_csv(f"{HERE}/all_stations.csv").rename(columns={"id": "club"}) if ALL else pd.read_csv(f"{HERE}/stations.csv")
    with ThreadPoolExecutor(12) as ex:
        parts = list(ex.map(lambda r: station(r.club, r.station), S.itertuples()))
    O = pd.concat(parts, ignore_index=True)
    O.to_parquet(f"{DATA}/obs.parquet", index=False)
    if ALL: print(O.club.nunique(), len(O)); raise SystemExit
    print(O.groupby("club").agg(n=("obs_ws", "size"), ws=("obs_ws", "mean"), gust=("obs_gust", lambda x: x.notna().mean())).round(2).to_string())
