"""Australia: the same backtest at 21 Australian clubs with a wind station, southern summers (Nov-Mar) 2022/23-2024/25.
Sailing hours 09-18 local time, race-day window 10-16 local. Europe's regional models don't cover Australia, so the raw
forecast is the mean of four global models in Open-Meteo's open-data archive: ECMWF IFS (9 km), DWD ICON (13 km),
UKMO 10 km and Meteo-France ARPEGE world (25 km).

Data: REGION=au python obs.py / extract_wind.py / geo.py  ->  data/au/
Scores (all out of sample), as in rounds 1 and 5:
  raw_mean, bias (per-club linear fit), kasta (club has a station, leave one summer out),
  kasta_res (learns the correction to the mean instead of the wind), kasta_ns (no station: leave one station out)
Writes reports/au.json and reports/au_by_club.csv.
"""
import os, json, numpy as np, pandas as pd
import backtest as B
HERE = B.HERE; OUT = B.OUT; KN = B.KN; DA = f"{HERE}/data/au"
MODELS = {"ecmwf_ifs": "ifs", "dwd_icon": "icon", "ukmo_global_deterministic_10km": "ukmo", "meteofrance_arpege_world025": "arpege"}
CTX = {("dwd_icon", "temperature_2m"): "t2", ("dwd_icon", "direct_radiation"): "sw"}
HOURS = range(9, 19)                  # 09-18 local

def load(model, var, name):
    f = f"{DA}/model/{model}__{var}.parquet"
    if not os.path.exists(f): return None
    d = pd.read_parquet(f); d[["club", "pt"]] = d.site.str.split("|", expand=True)
    return d.pivot_table(index=["club", "time"], columns="pt", values="v").add_prefix(name + "_")

def table():
    C = pd.read_csv(f"{HERE}/clubs_au.csv").set_index("id"); S = pd.read_csv(f"{HERE}/stations_au.csv")
    O = pd.read_parquet(f"{DA}/obs.parquet").merge(S, on="club")      # obs.py names rows by club
    O["obs"] = O.obs_ws * KN; O = O.set_index(["club", "time"])[["obs", "station"]]
    parts = [O]
    for m, s in MODELS.items():
        u, v, g = load(m, "wind_u_component_10m", s + "u"), load(m, "wind_v_component_10m", s + "v"), load(m, "wind_gusts_10m", s + "g")
        if u is None:
            sp, dr = load(m, "wind_speed_10m", s + "u"), load(m, "wind_direction_10m", s + "v")
            if sp is None: continue
            rad = np.radians(dr.values); u = -sp * np.sin(rad); v = pd.DataFrame(-sp.values * np.cos(rad), index=sp.index, columns=dr.columns)
        ws = pd.DataFrame({c.replace(s + "u_", s + "ws_"): np.hypot(u[c], v[c.replace(s + "u_", s + "v_")]) * KN for c in u.columns}, index=u.index)
        parts += [ws, u[[f"{s}u_st"]], v[[f"{s}v_st"]]] + ([g * KN] if g is not None else [])
    for (m, var), s in CTX.items():
        x = load(m, var, s)
        if x is not None: parts.append(x)
    D = pd.concat(parts, axis=1, join="outer").reindex(O.index).reset_index()
    tz = C.tz.to_dict()
    D["local"] = [t.tz_localize("UTC").tz_convert(tz[c]).tz_localize(None) for c, t in zip(D.club, D.time)]
    D = D[D.local.dt.month.isin([11, 12, 1, 2, 3]) & D.local.dt.hour.isin(HOURS) & D.obs.notna()].copy()
    D["year"] = D.local.dt.year - (D.local.dt.month <= 3)          # season label: Nov 2022 - Mar 2023 -> 2022
    D["hour"] = D.local.dt.hour; D["doy"] = D.local.dt.dayofyear; D["clubc"] = D.club.astype("category")
    for s in MODELS.values():
        if f"{s}u_st" in D: D[f"{s}dir_st"] = np.degrees(np.arctan2(-D[f"{s}u_st"], -D[f"{s}v_st"])) % 360
    if "t2_water" in D: D["t2_land_water"] = D[[f"t2_{p}" for p in "nsew" if f"t2_{p}" in D]].max(axis=1) - D.t2_water
    R = [f"{s}ws_st" for s in MODELS.values() if f"{s}ws_st" in D]
    D["raw_mean"] = D[R].mean(axis=1); D = D[D.raw_mean.notna()].reset_index(drop=True)
    return D, R

def day_table(D, cols):
    D = D.assign(date=D.local.dt.date); L = D[D.hour.between(10, 16)]
    G = L.groupby(["club", "date"]).agg({"obs": ["mean", "max"]} | {c: ["mean", "max"] for c in cols}); G.columns = [f"{a}_{b}" for a, b in G.columns]
    G = G[L.groupby(["club", "date"]).obs.count() >= 6]
    G["race"] = ((G.obs_mean >= B.ENOUGH) & (G.obs_max <= B.TOO_MUCH)).astype(int); return G

def main():
    D, R = table(); print("rows", len(D), "clubs", D.club.nunique(), "seasons", sorted(D.year.unique()), flush=True)
    drop = {"club", "time", "local", "obs", "station", "year", "raw_mean"}
    F = [c for c in D.columns if c not in drop] + ["raw_mean"]; Fn = [c for c in F if c != "clubc"]
    D["bias"] = B.bias_cv(D, D.raw_mean)
    D["kasta"], imp = B.cv(D, "year", F); print("kasta", flush=True)
    D["res"] = D.obs - D.raw_mean; D["kasta_res"] = np.nan; D["kasta_ns"] = np.nan
    for y in D.year.unique():
        te = D.year == y; p, _ = B.fit_predict(D[~te], D[te], F, target="res"); D.loc[te, "kasta_res"] = D.raw_mean[te] + p
    for st in D.station.unique():                                 # no station: hold out the station and every club using it
        te = D.station == st; p, _ = B.fit_predict(D[~te], D[te], Fn, target="res"); D.loc[te, "kasta_ns"] = D.raw_mean[te] + p
    cand = R + ["raw_mean", "bias", "kasta", "kasta_res", "kasta_ns"]
    res = {"hourly": {c: B.score_speed(D, c) for c in cand}}
    G = day_table(D, cand); res["race_day"] = {c: B.score_day(G, c) for c in cand}; res["race_day_base_rate"] = round(float(G.race.mean()), 3)
    C = pd.read_csv(f"{HERE}/clubs_au.csv").set_index("id")
    bc = D.groupby("club").apply(lambda x: pd.Series({"obs_kn": x.obs.mean(), "hours": len(x)} | {c: (x[c] - x.obs).abs().mean() for c in ["raw_mean", "bias", "kasta", "kasta_res", "kasta_ns"]})).round(2)
    bc = bc.join(C[["name", "water"]]); bc["gain_pct"] = (100 * (1 - bc.kasta_res / bc.raw_mean)).round(0)
    bc.sort_values("gain_pct").to_csv(f"{OUT}/au_by_club.csv")
    res["clubs_worse_than_raw"] = {c: int((bc[c] > bc.raw_mean + 0.005).sum()) for c in ["bias", "kasta", "kasta_res", "kasta_ns"]}
    res["by_club_median"] = bc[["raw_mean", "bias", "kasta", "kasta_res", "kasta_ns"]].median().round(2).to_dict()
    res["top_features"] = (imp / imp.sum()).sort_values(ascending=False).head(12).round(3).to_dict()
    json.dump(res, open(f"{OUT}/au.json", "w"), indent=1); print(json.dumps(res, indent=1)); print(bc.sort_values("gain_pct").to_string())

if __name__ == "__main__":
    main()
