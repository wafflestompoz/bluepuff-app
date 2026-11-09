"""Round 3: the no-station model trained on every open lowland station in Europe (1,031 NOAA ISD stations, all_stations.csv),
not just the 44 next to clubs. Scored at the 44 club stations in 4 folds of 11 clubs; each fold's training drops the
fold's clubs and every station within 25 km of them, so no nearby data leaks in.
Variants, same features (models at the station, weather type, geography turned upwind, lat/lon/height; no club id):
  clubs_only   : trained on the other 33 club stations (what round 2 could do)
  all_stations : trained on all stations outside the fold's 25 km zones
Writes reports/round3.json and reports/round3_by_club.csv."""
import os, json, numpy as np, pandas as pd
import backtest as B, backtest2 as B2
HERE = B.HERE; OUT = B.OUT; KN = B.KN; DA = f"{HERE}/data/all"

def load(model, var, name):
    f = f"{DA}/model/{model}__{var}.parquet"
    if not os.path.exists(f): return None
    d = pd.read_parquet(f); d["club"] = d.site.str.split("|").str[0]
    return d.pivot_table(index=["club", "time"], values="v").rename(columns={"v": name})

def table():
    O = pd.read_parquet(f"{DA}/obs.parquet"); O["obs"] = O.obs_ws * KN
    O = O[O.time.dt.month.between(5, 9) & O.time.dt.hour.isin(B.WIN) & (O.time.dt.year >= 2023)].set_index(["club", "time"])[["obs"]]
    parts = [O]; us, vs = [], []
    for m, s in B.MODELS.items():
        u, v = load(m, "wind_u_component_10m", f"{s}u"), load(m, "wind_v_component_10m", f"{s}v")
        if u is None:
            sp, dr = load(m, "wind_speed_10m", "sp"), load(m, "wind_direction_10m", "dr")
            if sp is None: continue
            x = sp.join(dr); rad = np.radians(x.dr); u = (-x.sp * np.sin(rad)).rename(f"{s}u").to_frame(); v = (-x.sp * np.cos(rad)).rename(f"{s}v").to_frame()
        ws = np.hypot(u[f"{s}u"], v[f"{s}v"]).rename(f"{s}ws") * KN
        parts += [ws.to_frame(), u, v]
    for (m, var), s in {("dwd_icon_eu", "temperature_2m"): "t2", ("dwd_icon_eu", "direct_radiation"): "sw",
                        ("dwd_icon_eu", "wind_u_component_850hPa"): "u850", ("dwd_icon_eu", "wind_v_component_850hPa"): "v850"}.items():
        x = load(m, var, s)
        if x is not None: parts.append(x)
    D = pd.concat(parts, axis=1).loc[O.index].reset_index()
    D = D[D.obs.notna()]
    R = [f"{s}ws" for s in B.MODELS.values() if f"{s}ws" in D]; D["raw_mean"] = D[R].mean(axis=1); D = D[D.raw_mean.notna()]
    U = D[[f"{s}u" for s in B.MODELS.values() if f"{s}u" in D]].mean(axis=1); V = D[[f"{s}v" for s in B.MODELS.values() if f"{s}v" in D]].mean(axis=1)
    D["wdir"] = (np.degrees(np.arctan2(-U, -V)) % 360).values; D["w_spread"] = D[R].std(axis=1)
    D["ws850"] = np.hypot(D.u850, D.v850) * KN; D["w_gust_ratio"] = D.ws850 / (D.raw_mean + 1)
    D["w_veer"] = ((np.degrees(np.arctan2(-D.u850, -D.v850)) % 360 - D.wdir + 180) % 360) - 180
    D["hour"] = D.time.dt.hour; D["doy"] = D.time.dt.dayofyear; D["year"] = D.time.dt.year
    A = pd.read_csv(f"{HERE}/all_stations.csv").set_index("id")
    D["lat"], D["lon"], D["elev"] = A.loc[D.club, "lat"].values, A.loc[D.club, "lon"].values, A.loc[D.club, "elev"].values
    G = pd.read_parquet(f"{DA}/geo.parquet").dropna(subset=["st_elev"]); D = D[D.club.isin(G.club)].reset_index(drop=True)
    for b0, b1 in [(0, 2), (2, 10), (10, 30)]: D[f"g_up_wf{b0}_{b1}"] = B2.upwind(G, D, f"st_wf{b0}_{b1}", D.wdir.values)
    D["g_up_relief"] = B2.upwind(G, D, "st_relief", D.wdir.values); D["g_up_fetch"] = B2.upwind(G, D, "st_fetch", D.wdir.values) if "st_fetch_0" in G else np.nan
    for k in ("shore_km", "water_r1", "water_r5", "water_r20", "on_water", "elev", "rough10"):
        D[f"g_{k}"] = G.set_index("club").loc[D.club, f"st_{k}"].values
    return D

def km(a, b, c, d):
    r = np.pi / 180; return 6371 * 2 * np.arcsin(np.sqrt(np.sin((c - a) * r / 2) ** 2 + np.cos(a * r) * np.cos(c * r) * np.sin((d - b) * r / 2) ** 2))

def main():
    D = table(); print("rows", len(D), "stations", D.club.nunique(), flush=True)
    clubs = pd.read_csv(f"{HERE}/clubs.csv").id; clubs = [c for c in clubs if c in set(D.club)]
    A = pd.read_csv(f"{HERE}/all_stations.csv").set_index("id")
    rng = np.random.RandomState(0); order = list(clubs); rng.shuffle(order); fold = {c: i % 4 for i, c in enumerate(order)}
    F = [c for c in D.columns if c not in {"club", "time", "obs", "year"}]
    isclub = D.club.isin(clubs)
    for v in ("clubs_only", "all_stations"): D[f"ns_{v}"] = np.nan
    for f in range(4):
        fc = [c for c in clubs if fold[c] == f]
        near = {s for s in A.index if any(km(A.lat[s], A.lon[s], A.lat[c], A.lon[c]) < 25 for c in fc)}
        te = D.club.isin(fc)
        for v, tr in (("clubs_only", isclub & ~te), ("all_stations", ~D.club.isin(near) & ~te)):
            p, m = B.fit_predict(D[tr], D[te], F); D.loc[te, f"ns_{v}"] = p
            print("fold", f, v, "train stations", D[tr].club.nunique(), flush=True)
            if v == "all_stations": imp = (imp if f else 0) + pd.Series(m.booster_.feature_importance("gain"), index=F)
    C = D[isclub].copy(); cand = ["raw_mean", "ns_clubs_only", "ns_all_stations"]
    res = {"hourly": {c: B.score_speed(C, c) for c in cand}}
    Gd = B.day_table(C, cand); res["race_day"] = {c: B.score_day(Gd, c) for c in cand}
    th = (C.ws850 < 8) & (C.sw > 300); res["light_wind_sunny_hourly"] = {c: B.score_speed(C[th], c) for c in cand}
    bc = C.groupby("club").apply(lambda x: pd.Series({c: (x[c] - x.obs).abs().mean() for c in cand})).round(2)
    bc["gain_pct"] = (100 * (1 - bc.ns_all_stations / bc.raw_mean)).round(0); bc.sort_values("gain_pct").to_csv(f"{OUT}/round3_by_club.csv")
    res["by_club_median"] = bc.median().round(2).to_dict(); res["clubs_improved"] = int((bc.ns_all_stations < bc.raw_mean).sum())
    res["top_features"] = (imp / imp.sum()).sort_values(ascending=False).head(15).round(3).to_dict()
    json.dump(res, open(f"{OUT}/round3.json", "w"), indent=1); print(json.dumps(res, indent=1)); print(bc.sort_values("gain_pct").to_string())

if __name__ == "__main__":
    main()
