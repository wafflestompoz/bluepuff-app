"""Australia, scored on the water: does the forecast hold up against on-water stations, not just airports?

12 clubs have an on-water or harbour station nearby (stations_au_water.csv: Fort Denison, Fawkner Beacon, St Kilda Harbour,
Banana Bank Beacon, Inner Dolphin Pylon, Garden Island, Gold Coast Seaway, Black Pole). Most of these only reach the NOAA
archive from 2024, about every 3 hours, so the comparison is the 2024/25 southern summer (Nov-Mar), 09-18 local, on the
hours that have an on-water reading.

Compared, all scored against the ON-WATER station:
  raw_mean       : mean of the 4 global models at the on-water station
  airport_corr   : the correction learned at the club's land/airport station (stations_au.csv) on 2022/23-2023/24, applied in 2024/25
  water_bias     : per-club linear fit on the on-water station, other months of 2024/25 (5 month folds)
  water_corr     : learns the correction at the on-water stations, other months of 2024/25 (5 month folds)
  water_corr_ap  : water_corr with the airport-trained correction as an extra input
Data: REGION=au STATIONS=water python obs.py / extract_wind.py -> data/au_water/. Writes reports/au_water.json, au_water_by_club.csv.
"""
import json, numpy as np, pandas as pd
import backtest as B, backtest_au as A
HERE = B.HERE; OUT = B.OUT

def main():
    Da, R = A.table(f"{HERE}/data/au", "stations_au.csv")
    Dw, Rw = A.table(f"{HERE}/data/au_water", "stations_au_water.csv")
    clubs = sorted(Dw.club.unique()); print("water clubs", clubs, "rows", len(Dw), flush=True)
    # airport-trained correction: all 21 clubs, seasons before 2024, predicted at the airport point for 2024/25
    drop = {"club", "time", "local", "obs", "station", "year", "raw_mean", "res"}
    F = [c for c in Da.columns if c not in drop] + ["raw_mean"]
    Da["res"] = Da.obs - Da.raw_mean; tr, te = Da.year < 2024, Da.year == 2024
    p, _ = B.fit_predict(Da[tr], Da[te], F, target="res")
    AP = Da[te].assign(airport_corr=Da.raw_mean[te] + p, airport_obs=Da.obs[te], airport_raw=Da.raw_mean[te])[["club", "time", "airport_corr", "airport_obs", "airport_raw"]]
    W = Dw[Dw.year == 2024].merge(AP, on=["club", "time"], how="inner").reset_index(drop=True)
    W["res"] = W.obs - W.raw_mean; W["month"] = W.local.dt.month
    Fw = [c for c in W.columns if c not in drop | {"airport_corr", "airport_obs", "airport_raw", "month"}] + ["raw_mean"]
    for c in ("water_bias", "water_corr", "water_corr_ap"): W[c] = np.nan
    for m in W.month.unique():
        te = W.month == m; tr = ~te
        for cl in clubs:
            a, b = tr & (W.club == cl), te & (W.club == cl)
            if a.sum() >= 50: W.loc[b, "water_bias"] = np.polyval(np.polyfit(W.raw_mean[a], W.obs[a], 1), W.raw_mean[b])
        W.loc[te, "water_corr"] = W.raw_mean[te] + B.fit_predict(W[tr], W[te], Fw, target="res")[0]
        W.loc[te, "water_corr_ap"] = W.raw_mean[te] + B.fit_predict(W[tr], W[te], Fw + ["airport_corr"], target="res")[0]
    cand = ["raw_mean", "airport_corr", "water_bias", "water_corr", "water_corr_ap"]
    res = {"hours": len(W), "clubs": clubs, "vs_on_water": {c: B.score_speed(W, c) for c in cand}}
    # the same hours scored the usual way, against the airport, for reference
    ref = W.assign(obs=W.airport_obs, raw_ap=W.airport_raw)
    res["vs_airport_same_hours"] = {c: B.score_speed(ref, c) for c in ["raw_ap", "airport_corr"]}
    res["obs_mean_kn"] = {"on_water": round(float(W.obs.mean()), 1), "airport": round(float(W.airport_obs.mean()), 1)}
    G = A.day_table(W, cand, min_obs=2)   # on-water readings are about 3-hourly: 2-3 per race window
    res["race_day_on_water"] = {c: B.score_day(G, c) for c in cand}; res["race_days"] = len(G)
    bc = W.groupby("club").apply(lambda x: pd.Series({"hours": len(x), "water_kn": x.obs.mean(), "airport_kn": x.airport_obs.mean()} |
                                                     {c: (x[c] - x.obs).abs().mean() for c in cand})).round(2)
    bc = bc.join(pd.read_csv(f"{HERE}/stations_au_water.csv").set_index("club")[["kind"]])
    bc.to_csv(f"{OUT}/au_water_by_club.csv")
    json.dump(res, open(f"{OUT}/au_water.json", "w"), indent=1); print(json.dumps(res, indent=1)); print(bc.to_string())

if __name__ == "__main__":
    main()
