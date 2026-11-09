"""Sailing backtest: raw models vs a 4Kasta-style corrected forecast of station wind at 44 European clubs, summers 2023-25.
Sailing window: 07-16 UTC (09-18 CEST), May-Sep. Wind in knots.
  same-day : Open-Meteo archive (lead ~0-12 h): ICON-D2/EU, IFS, UKMO, AROME, ARPEGE at station, water point and 4 neighbours
  day-ahead: GFS 0.5 deg 00Z run for the next day (lead 30-42 h), 09/12/15 UTC
Corrections, scored out of sample:
  bias    : per-club linear fit of obs on the raw multi-model mean (MOS-lite), leave-one-summer-out
  kasta   : LightGBM on all models, points and context (4Kasta recipe), leave-one-summer-out (club has a station)
  kasta-ns: same, leave-one-club-out (club has NO station: what we can offer elsewhere)
Writes reports/metrics.json, reports/by_club.csv and prints a summary.
"""
import os, json, numpy as np, pandas as pd, lightgbm as lgb
from sklearn.metrics import roc_auc_score, brier_score_loss
HERE = os.path.dirname(os.path.abspath(__file__)); M = f"{HERE}/data/model"; OUT = f"{HERE}/reports"; os.makedirs(OUT, exist_ok=True)
KN = 1.943844
WIN = range(7, 17)
MODELS = {"ecmwf_ifs": "ifs", "dwd_icon_eu": "iconeu", "dwd_icon_d2": "icond2", "ukmo_global_deterministic_10km": "ukmo",
          "meteofrance_arome_france0025": "arome", "meteofrance_arpege_europe": "arpege"}
CTX = {("dwd_icon_eu", "temperature_2m"): "t2", ("dwd_icon_eu", "direct_radiation"): "sw", ("dwd_icon_eu", "cloud_cover"): "cc",
       ("dwd_icon_eu", "pressure_msl"): "mslp", ("dwd_icon_eu", "wind_u_component_850hPa"): "u850", ("dwd_icon_eu", "wind_v_component_850hPa"): "v850",
       ("ecmwf_ifs", "boundary_layer_height"): "blh"}
PTS = ["st", "water", "n", "s", "e", "w"]
ENOUGH, TOO_MUCH = 6, 22      # a raceable day: 10-16 local mean >= 6 kn and no hour above 22 kn

def load(model, var, name):
    f = f"{M}/{model}__{var}.parquet"
    if not os.path.exists(f): return None
    d = pd.read_parquet(f); d[["club", "pt"]] = d.site.str.split("|", expand=True)
    return d.pivot_table(index=["club", "time"], columns="pt", values="v").add_prefix(name + "_")

def table():
    O = pd.read_parquet(f"{HERE}/data/obs.parquet"); O["obs"] = O.obs_ws * KN
    O = O[O.time.dt.month.between(5, 9) & O.time.dt.hour.isin(WIN)].set_index(["club", "time"])[["obs", "obs_dir"]]
    parts = [O]
    for m, s in MODELS.items():
        u, v, g = load(m, "wind_u_component_10m", s + "u"), load(m, "wind_v_component_10m", s + "v"), load(m, "wind_gusts_10m", s + "g")
        if u is None:   # UKMO is archived as speed + direction
            sp, dr = load(m, "wind_speed_10m", s + "u"), load(m, "wind_direction_10m", s + "v")
            if sp is None: continue
            rad = np.radians(dr.values); u = -sp * np.sin(rad); v = (-sp.values * np.cos(rad)); v = pd.DataFrame(v, index=sp.index, columns=dr.columns)
        ws = pd.DataFrame({c.replace(s + "u_", s + "ws_"): np.hypot(u[c], v[c.replace(s + "u_", s + "v_")]) * KN for c in u.columns}, index=u.index)
        parts += [ws, u[[f"{s}u_st"]], v[[f"{s}v_st"]]] + ([g * KN] if g is not None else [])
    for (m, var), s in CTX.items():
        x = load(m, var, s)
        if x is not None: parts.append(x[[c for c in x.columns if c.endswith(("_st", "_water", "_n", "_s", "_e", "_w"))]])
    D = pd.concat(parts, axis=1, join="outer").loc[O.index]
    D = D.reset_index(); D["year"] = D.time.dt.year; D["hour"] = D.time.dt.hour; D["doy"] = D.time.dt.dayofyear
    D["clubc"] = D.club.astype("category")
    if "t2_water" in D: D["t2_land_water"] = D[[f"t2_{p}" for p in ("n", "s", "e", "w") if f"t2_{p}" in D]].max(axis=1) - D.t2_water
    if "u850_st" in D: D["ws850"] = np.hypot(D.u850_st, D.v850_st) * KN; D["dir850"] = np.degrees(np.arctan2(-D.u850_st, -D.v850_st)) % 360
    for s in MODELS.values():
        if f"{s}u_st" in D: D[f"{s}dir_st"] = np.degrees(np.arctan2(-D[f"{s}u_st"], -D[f"{s}v_st"])) % 360
    return D

def raw_cols(D): return [f"{s}ws_st" for s in MODELS.values() if f"{s}ws_st" in D]

def feats(D, with_club=True):
    drop = {"club", "time", "obs", "obs_dir", "year", "pred", "bias", "kasta", "kasta_ns"} | ({"clubc"} if not with_club else set())
    return [c for c in D.columns if c not in drop and not c.startswith("p_")]

def fit_predict(tr, te, cols, target="obs"):
    m = lgb.LGBMRegressor(n_estimators=600, learning_rate=0.03, num_leaves=63, min_child_samples=50, subsample=0.8, subsample_freq=1,
                          colsample_bytree=0.7, objective="l1", verbose=-1)
    m.fit(tr[cols], tr[target]); return m.predict(te[cols]), m

def cv(D, how, cols):
    pred = pd.Series(np.nan, index=D.index); imp = None
    groups = D.year if how == "year" else D.club
    for g in groups.unique():
        te = groups == g; p, m = fit_predict(D[~te], D[te], cols); pred[te] = p
        imp = (imp if imp is not None else 0) + pd.Series(m.booster_.feature_importance("gain"), index=cols)
    return pred, imp

def bias_cv(D, x):
    pred = pd.Series(np.nan, index=D.index)
    for y in D.year.unique():
        tr, te = D.year != y, D.year == y
        for c in D.club.unique():
            a, b = tr & (D.club == c) & x.notna(), te & (D.club == c)
            if a.sum() < 200: continue
            k = np.polyfit(x[a], D.obs[a], 1); pred[b] = np.polyval(k, x[b])
    return pred

def day_table(D, cols):
    D = D.assign(date=D.time.dt.date)
    L = D[D.hour.between(8, 14)]
    agg = {"obs": ["mean", "max"]} | {c: ["mean", "max"] for c in cols}
    G = L.groupby(["club", "date"]).agg(agg); G.columns = [f"{a}_{b}" for a, b in G.columns]
    G = G[L.groupby(["club", "date"]).obs.count() >= 6]
    G["race"] = ((G.obs_mean >= ENOUGH) & (G.obs_max <= TOO_MUCH)).astype(int)
    return G

def score_speed(D, col):
    ok = D[col].notna() & D.obs.notna(); e = D.loc[ok, col] - D.loc[ok, "obs"]
    band = lambda x: pd.cut(x, [-1, 5, 12, 18, 99], labels=False)   # light / medium / fresh / strong (kn)
    return {"n": int(ok.sum()), "mae_kn": round(float(e.abs().mean()), 2), "bias_kn": round(float(e.mean()), 2),
            "band_hit": round(float((band(D.loc[ok, col]) == band(D.loc[ok, "obs"])).mean()), 3)}

def p_race(mean, mx, sd=None):
    """Probability that the day is raceable, from a forecast mean/max and the CV error spread."""
    from scipy.stats import norm
    sd = sd if sd is not None else 2.5
    return norm.cdf((mean - ENOUGH) / sd) * norm.cdf((TOO_MUCH - mx) / (sd * 1.4))

def score_day(G, col):
    ok = G[f"{col}_mean"].notna()
    if ok.sum() < 100: return None
    p = p_race(G.loc[ok, f"{col}_mean"], G.loc[ok, f"{col}_max"])
    y = G.loc[ok, "race"]
    return {"days": int(ok.sum()), "brier": round(float(brier_score_loss(y, p)), 4), "auc": round(float(roc_auc_score(y, p)), 3),
            "call_right": round(float(((p >= 0.5) == y).mean()), 3)}

def main():
    D = table(); print("rows", len(D), "clubs", D.club.nunique(), "obs mean kn", round(D.obs.mean(), 1))
    D = D[D.obs.notna()].reset_index(drop=True)
    R = raw_cols(D); D["raw_mean"] = D[R].mean(axis=1)
    D["raw_best"] = D["icond2ws_st"].fillna(D.get("aromews_st")).fillna(D["iconeuws_st"]) if "icond2ws_st" in D else D["iconeuws_st"]
    D["raw_water"] = D[[c.replace("_st", "_water") for c in R if c.replace("_st", "_water") in D]].mean(axis=1)
    D["bias"] = bias_cv(D, D.raw_mean)
    F = feats(D); D["kasta"], imp = cv(D, "year", F)
    Fn = feats(D, with_club=False); D["kasta_ns"], _ = cv(D, "club", Fn)
    cand = R + ["raw_mean", "raw_best", "raw_water", "bias", "kasta", "kasta_ns"]
    res = {"same_day": {"hourly": {c: score_speed(D, c) for c in cand}}}
    G = day_table(D, cand); res["same_day"]["race_day"] = {c: score_day(G, c) for c in cand}
    res["same_day"]["race_day_base_rate"] = round(float(G.race.mean()), 3)
    # by club: MAE raw_mean vs kasta, and in which kind of water
    C = pd.read_csv(f"{HERE}/clubs.csv").set_index("id")
    bc = D.groupby("club").apply(lambda x: pd.Series({"obs_kn": x.obs.mean(), "raw_mean": (x.raw_mean - x.obs).abs().mean(), "raw_best": (x.raw_best - x.obs).abs().mean(),
                                                         "bias": (x.bias - x.obs).abs().mean(), "kasta": (x.kasta - x.obs).abs().mean(), "kasta_ns": (x.kasta_ns - x.obs).abs().mean(),
                                                         "raw_bias": (x.raw_mean - x.obs).mean()})).round(2)
    bc = bc.join(C[["name", "country", "water"]]); bc["gain_pct"] = (100 * (1 - bc.kasta / bc.raw_mean)).round(0)
    bc.sort_values("gain_pct").to_csv(f"{OUT}/by_club.csv")
    res["same_day"]["by_water"] = bc.groupby("water")[["raw_mean", "bias", "kasta", "kasta_ns"]].mean().round(2).to_dict("index")
    res["same_day"]["top_features"] = (imp / imp.sum()).sort_values(ascending=False).head(15).round(3).to_dict()
    # day-ahead with GFS
    gf = f"{M}/gfs_day1.parquet"
    if os.path.exists(gf):
        Gd = pd.read_parquet(gf); Gd[["club", "pt"]] = Gd.site.str.split("|", expand=True)
        Gd["ws"] = np.hypot(Gd.gfs1_u, Gd.gfs1_v) * KN; Gd["gust"] = Gd.gfs1_gust * KN; Gd["dir"] = np.degrees(np.arctan2(-Gd.gfs1_u, -Gd.gfs1_v)) % 360
        Gd = Gd[Gd.pt == "st"][["club", "time", "ws", "gust", "dir", "gfs1_t2"]].rename(columns={"ws": "gfs1_ws", "gust": "gfs1_g", "dir": "gfs1_dir"})
        A = D[["club", "time", "obs", "year", "hour", "doy", "clubc"]].merge(Gd, on=["club", "time"])
        A = A[A.hour.isin([9, 12, 15])].reset_index(drop=True)
        fa = ["gfs1_ws", "gfs1_g", "gfs1_dir", "gfs1_t2", "hour", "doy", "clubc"]
        A["bias"] = bias_cv(A, A.gfs1_ws); A["kasta"], _ = cv(A, "year", fa); A["kasta_ns"], _ = cv(A, "club", [c for c in fa if c != "clubc"])
        res["day_ahead_gfs"] = {c: score_speed(A, c) for c in ["gfs1_ws", "bias", "kasta", "kasta_ns"]}
    json.dump(res, open(f"{OUT}/metrics.json", "w"), indent=1)
    print(json.dumps(res, indent=1)); print(bc.sort_values("gain_pct").to_string())

if __name__ == "__main__":
    main()
