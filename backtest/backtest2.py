"""Round 2 of the sailing backtest: what each improvement adds on top of backtest.py's 4Kasta-style model.
  geo     : water and terrain around the station and race area (geo.py), turned upwind with the models' wind direction
  weather : weather-type signals: land-minus-water temperature, sunshine, cloud, large-scale (850 hPa) wind and its angle
            to the surface wind, boundary-layer height, and their ratios
  morning : the 08:00 CEST (06 UTC) station reading, the models' error then and the 06-08 CEST mean, as if issued at 08:00.
            Only possible at clubs with a station.
Scored like backtest.py: leave-one-summer-out (club has a station) and leave-clubs-out in 11 groups of 4 (club has none).
Writes reports/round2.json and reports/round2_by_club.csv.
"""
import os, json, numpy as np, pandas as pd
import backtest as B
HERE = B.HERE; OUT = B.OUT; KN = B.KN

def circ_mean_dir(D, models):
    u = D[[f"{s}u_st" for s in models if f"{s}u_st" in D]].mean(axis=1); v = D[[f"{s}v_st" for s in models if f"{s}v_st" in D]].mean(axis=1)
    return (np.degrees(np.arctan2(-u, -v)) % 360).values

def upwind(G, D, prefix, theta):
    """Value of sector feature `prefix_{s}` toward the direction the wind blows from, interpolated between sectors."""
    cols = [f"{prefix}_{s}" for s in range(16)]
    M = G.set_index("club").loc[D.club, cols].values
    x = theta / 22.5; i0 = np.floor(x).astype(int) % 16; i1 = (i0 + 1) % 16; w = x - np.floor(x)
    r = np.arange(len(D)); return M[r, i0] * (1 - w) + M[r, i1] * w

def add_geo(D):
    G = pd.read_parquet(f"{HERE}/data/geo.parquet"); th = circ_mean_dir(D, B.MODELS.values()); D["wdir"] = th
    for a in ("st", "water"):
        for b0, b1 in [(0, 2), (2, 10), (10, 30)]: D[f"g_{a}_up_wf{b0}_{b1}"] = upwind(G, D, f"{a}_wf{b0}_{b1}", th)
        D[f"g_{a}_up_relief"] = upwind(G, D, f"{a}_relief", th)
        D[f"g_{a}_down_wf2_10"] = upwind(G, D, f"{a}_wf2_10", (th + 180) % 360)
        for k in ("shore_km", "water_r1", "water_r5", "water_r20", "on_water", "elev", "rough10"):
            D[f"g_{a}_{k}"] = G.set_index("club").loc[D.club, f"{a}_{k}"].values
    D["g_fetch_gap"] = D.g_water_up_wf2_10 - D.g_st_up_wf2_10   # race area more exposed than the station in this wind?
    return D

def add_weather(D):
    if "ws850" in D:
        D["w_gust_ratio"] = D.ws850 / (D.raw_mean + 1)
        D["w_veer"] = ((D.dir850 - D.wdir + 180) % 360) - 180
    land = [f"t2_{p}" for p in ("n", "s", "e", "w") if f"t2_{p}" in D]
    if land and "t2_water" in D:
        D["w_land_sea_dt"] = D[land].mean(axis=1) - D.t2_water
        D["w_land_sea_dt_x_sun"] = D.w_land_sea_dt * D.get("sw_st", 0) / 500
    if "blh_st" in D: D["w_blh"] = D.blh_st
    D["w_spread"] = D[B.raw_cols(D)].std(axis=1)            # model disagreement
    return D

def add_morning(D):
    O = pd.read_parquet(f"{HERE}/data/obs.parquet"); O["obs"] = O.obs_ws * KN; O["date"] = O.time.dt.normalize()
    m = O[O.time.dt.hour.isin([4, 5, 6])].pivot_table(index=["club", "date"], columns=O.time.dt.hour, values="obs")
    m.columns = [f"m_obs{h:02d}" for h in m.columns]; m["m_obs_mean"] = m.mean(axis=1)
    d6 = O[O.time.dt.hour == 6].set_index(["club", "date"]).obs_dir.rename("m_dir06")
    D["date"] = D.time.dt.normalize(); D = D.join(m, on=["club", "date"]).join(d6, on=["club", "date"])
    # the models' error at 06 UTC needs the 06 UTC model values, which table() dropped (outside the window): rebuild them
    raw06 = []
    for mname, s in B.MODELS.items():
        u = B.load(mname, "wind_u_component_10m", s + "u")
        if u is None:
            sp = B.load(mname, "wind_speed_10m", s + "u")
            if sp is None: continue
            x = sp[f"{s}u_st"] * KN
        else:
            v = B.load(mname, "wind_v_component_10m", s + "v"); x = np.hypot(u[f"{s}u_st"], v[f"{s}v_st"]) * KN
        x = x.reset_index(); x = x[x.time.dt.hour == 6]; x["date"] = x.time.dt.normalize()
        raw06.append(x.set_index(["club", "date"]).iloc[:, -1].rename(s))
    R6 = pd.concat(raw06, axis=1).mean(axis=1).rename("m_raw06")
    D = D.join(R6, on=["club", "date"]); D["m_err06"] = D.m_obs06 - D.m_raw06; D["m_lead"] = D.hour - 6
    return D.drop(columns=["date"])

def group_folds(D, k=11):
    clubs = sorted(D.club.unique()); rng = np.random.RandomState(0); rng.shuffle(clubs)
    return D.club.map({c: i % k for i, c in enumerate(clubs)})

def cv_groups(D, groups, cols):
    pred = pd.Series(np.nan, index=D.index); imp = 0
    for g in groups.unique():
        te = groups == g; p, m = B.fit_predict(D[~te], D[te], cols); pred[te] = p
        imp = imp + pd.Series(m.booster_.feature_importance("gain"), index=cols)
    return pred, imp

def main():
    D = B.table(); D = D[D.obs.notna()].reset_index(drop=True)
    D["raw_mean"] = D[B.raw_cols(D)].mean(axis=1)
    base = B.feats(D); base_ns = [c for c in base if c != "clubc"]
    D = add_weather(add_geo(D)); D = add_morning(D)
    G = [c for c in D.columns if c.startswith("g_")] + ["wdir"]; W = [c for c in D.columns if c.startswith("w_")]
    Mo = [c for c in D.columns if c.startswith("m_")]
    yrs, clubs = D.year, group_folds(D)
    runs = {"v1": (base, base_ns), "geo": (base + G, base_ns + G), "geo_weather": (base + G + W, base_ns + G + W),
            "geo_weather_morning": (base + G + W + Mo, None)}
    res = {"hourly": {}, "race_day": {}}; imps = {}
    D["raw_mean_"] = D.raw_mean
    for name, (fs, fns) in runs.items():
        D[f"st_{name}"], imps[name] = cv_groups(D, yrs, fs)
        if fns: D[f"ns_{name}"], _ = cv_groups(D, clubs, fns)
        print("done", name, flush=True)
    cand = ["raw_mean_"] + [c for c in D.columns if c.startswith(("st_", "ns_"))]
    res["hourly"] = {c: B.score_speed(D, c) for c in cand}
    Gd = B.day_table(D, cand); res["race_day"] = {c: B.score_day(Gd, c) for c in cand}
    # light-wind thermal days (gradient under 8 kn at 850 hPa, sunny) where sea/lake breezes matter
    th = (D.ws850 < 8) & (D.get("sw_st", 0) > 300)
    res["thermal_days_hourly"] = {c: B.score_speed(D[th], c) for c in cand}
    imp = imps["geo_weather_morning"]; res["top_features_full"] = (imp / imp.sum()).sort_values(ascending=False).head(20).round(3).to_dict()
    bc = D.groupby("club").apply(lambda x: pd.Series({c: (x[c] - x.obs).abs().mean() for c in cand})).round(2)
    bc.to_csv(f"{OUT}/round2_by_club.csv"); res["by_club_median"] = bc.median().round(2).to_dict()
    json.dump(res, open(f"{OUT}/round2.json", "w"), indent=1); print(json.dumps(res, indent=1))

if __name__ == "__main__":
    main()
