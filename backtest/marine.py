"""Waves, sea level (tide + surge), currents and sea temperature at each sea club, summers 2023-25, from Open-Meteo's
open-data archive (CC BY 4.0): DWD EWAM (Europe, ~5 km, hourly), Meteo-France SMOC currents and sea level (1/12 deg, hourly,
tides included), Meteo-France sea-surface temperature (1/12 deg, 6-hourly).
Coastal grid cells are often missing, so each club gets candidate points from its race area out toward its most open
water direction (0, 3, 6, 10, 15 km); the analysis uses the nearest one with data.
Usage: python marine.py  ->  data/model/<model>__<var>.parquet (site = club|k0..k4)"""
import os, math, numpy as np, pandas as pd
import extract_wind as X
from grids import GRIDS, Regular
HERE = X.HERE
GRIDS["dwd_ewam"] = Regular(721, 526, 30.0, -10.5, 0.05, 0.1)
for m in ("meteofrance_currents", "meteofrance_sea_surface_temperature", "meteofrance_wave"):
    GRIDS[m] = Regular(2041, 4320, -79.958336, -179.95833, 1 / 12, 1 / 12)
STEPS = [0, 3, 6, 10, 15]
JOBS = {"dwd_ewam": ["wave_height", "wave_period", "wave_direction", "wind_wave_height", "wind_wave_period", "swell_wave_height"],
        "meteofrance_currents": ["sea_level_height_msl", "ocean_u_current", "ocean_v_current"],
        "meteofrance_sea_surface_temperature": ["sea_surface_temperature"]}

def sites():
    C = pd.read_csv(f"{HERE}/clubs.csv"); G = pd.read_parquet(f"{HERE}/data/geo.parquet").set_index("club")
    rows = []
    for r in C[C.water == "sea"].itertuples():
        if r.id not in G.index: continue
        g = G.loc[r.id]; la, lo = g.water_lat, g.water_lon
        s = int(np.argmax([g[f"water_wf10_30_{k}"] for k in range(16)])); brg = math.radians(s * 22.5)
        for i, d in enumerate(STEPS):
            rows.append((f"{r.id}|k{i}", la + d * math.cos(brg) / 111.0, lo + d * math.sin(brg) / (111.0 * math.cos(math.radians(la)))))
    return pd.DataFrame(rows, columns=["id", "lat", "lon"])

if __name__ == "__main__":
    X.sites = sites
    for m, vs in JOBS.items(): X.main(m, vs)
