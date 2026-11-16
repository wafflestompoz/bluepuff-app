"""Round 4: accuracy improvements that a live forecast can actually use.

1. Recent error ("adaptive MOS"): how wrong the multi-model mean has been at this station over the last 3, 10 and 30 days,
   overall and at this hour, using only days before the forecast day. Weather models drift with the season and the regime;
   a fixed correction learned from other summers can't follow that.
2. Calibrated race-day odds: round 1 turned the forecast into a probability with a fixed error spread of 2.5 kn for every
   forecast. Here a small logistic model learns the spread from past summers (leave-one-summer-out), per forecast.
3. No-station clubs (round 3 data, ~1,000 stations): the same recent-error signal borrowed from stations 25-100 km away
   (inverse-distance weighted), plus a fallback guard: where the no-station model has done worse than the raw models at
   the nearest training stations, use the raw multi-model mean instead.

Every score is out of sample: station clubs leave one summer out, no-station clubs use round 3's 4 folds with 25 km
exclusion zones. Writes reports/round4.json, reports/round4_by_club.csv.
"""
import os, sys, json, numpy as np, pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss
import backtest as B, backtest3 as B3
HERE = B.HERE; OUT = B.OUT

# ---------------------------------------------------------------- recent-error features
def recent_error(D, key="club"):
    """Trailing error of raw_mean (obs - raw_mean) per station, from days strictly before the forecast day."""
    D = D.assign(date=D.time.dt.normalize(), err=D.obs - D.raw_mean, rat=np.log((D.obs + 1) / (D.raw_mean + 1)))
    day = D.groupby([key, "date"]).agg(err=("err", "mean"), rat=("rat", "mean")).reset_index().sort_values([key, "date"])
    out = []
    for k, g in day.groupby(key, sort=False):
        g = g.set_index("date")
        r = pd.DataFrame(index=g.index)
        for n in (3, 10, 30):
            r[f"re_err{n}"] = g.err.rolling(f"{n}D", min_periods=max(1, n // 3)).mean()
        r["re_rat10"] = g.rat.rolling("10D", min_periods=3).mean()
        r = r.shift(1, freq="D")            # known before the forecast day starts
        r[key] = k; out.append(r.reset_index())
    R = pd.concat(out)
    hr = D.groupby([key, "hour", "date"]).err.mean().reset_index().sort_values([key, "hour", "date"])
    hh = []
    for (k, h), g in hr.groupby([key, "hour"], sort=False):
        s = g.set_index("date").err.rolling("10D", min_periods=3).mean().shift(1, freq="D")
        hh.append(pd.DataFrame({key: k, "hour": h, "date": s.index, "re_err10_hr": s.values}))
    H = pd.concat(hh)
    D = D.merge(R, on=[key, "date"], how="left").merge(H, on=[key, "hour", "date"], how="left")
    return D.drop(columns=["err", "rat"])

RE = ["re_err3", "re_err10", "re_err30", "re_rat10", "re_err10_hr"]

# ---------------------------------------------------------------- calibrated race-day probability
def day_feats(G, c):
    return np.c_[G[f"{c}_mean"] - B.ENOUGH, B.TOO_MUCH - G[f"{c}_max"], np.minimum(G[f"{c}_mean"] - B.ENOUGH, 0)]

def score_day_cal(G, col, years):
    """Logistic calibration of the race-day call, leave-one-summer-out."""
    ok = G[f"{col}_mean"].notna().values
    G = G[ok]; yrs = years[ok]; p = np.full(len(G), np.nan); y = G.race.values
    X = day_feats(G, col)
    for yr in np.unique(yrs):
        te = yrs == yr
        p[te] = LogisticRegression(C=10).fit(X[~te], y[~te]).predict_proba(X[te])[:, 1]
    return {"days": int(len(G)), "brier": round(float(brier_score_loss(y, p)), 4), "auc": round(float(roc_auc_score(y, p)), 3),
            "call_right": round(float(((p >= 0.5) == y).mean()), 3)}

def race_scores(D, cand):
    G = B.day_table(D, cand); yrs = np.array([d.year for d in G.index.get_level_values("date")])
    return {"fixed_spread": {c: B.score_day(G, c) for c in cand}, "calibrated": {c: score_day_cal(G, c, yrs) for c in cand}}

# ---------------------------------------------------------------- 1+2: clubs with a station
def station_clubs():
    D = B.table(); D = D[D.obs.notna()].reset_index(drop=True)
    R = B.raw_cols(D); D["raw_mean"] = D[R].mean(axis=1); D = D[D.raw_mean.notna()].reset_index(drop=True)
    D = recent_error(D); print("station table", len(D), flush=True)
    D["re_only"] = D.raw_mean + D.re_err10.fillna(0)              # simplest possible: add last 10 days' error
    D["bias"] = B.bias_cv(D, D.raw_mean)
    F = [c for c in B.feats(D) if c not in RE + ["date", "raw_mean", "re_only", "bias"]] + ["raw_mean"]
    D["kasta"], _ = B.cv(D, "year", F); print("kasta done", flush=True)
    D["kasta_re"], imp = B.cv(D, "year", F + RE)
    cand = ["raw_mean", "re_only", "bias", "kasta", "kasta_re"]
    res = {"hourly": {c: B.score_speed(D, c) for c in cand}}
    res["race_day"] = race_scores(D, cand)
    th = (D.ws850 < 8) & (D.sw_st > 300) if "sw_st" in D else None
    if th is not None: res["light_wind_sunny_hourly"] = {c: B.score_speed(D[th], c) for c in cand}
    bc = D.groupby("club").apply(lambda x: pd.Series({c: (x[c] - x.obs).abs().mean() for c in cand})).round(2)
    bc["gain_vs_kasta_pct"] = (100 * (1 - bc.kasta_re / bc.kasta)).round(0)
    res["clubs_improved_vs_kasta"] = int((bc.kasta_re < bc.kasta).sum())
    res["top_features"] = (imp / imp.sum()).sort_values(ascending=False).head(12).round(3).to_dict()
    return res, bc

# ---------------------------------------------------------------- 3: clubs without a station
def neighbour_recent(D, A, lo=25, hi=100):
    """Inverse-distance mean of other stations' recent errors, from stations lo-hi km away (never the station itself)."""
    ids = D.club.unique(); A = A.loc[ids]
    lat, lon = A.lat.values, A.lon.values
    dist = B3.km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    W = np.where((dist >= lo) & (dist <= hi), 1 / np.maximum(dist, 1) ** 2, 0)
    cols = ["re_err3", "re_err10", "re_err30"]
    day = D.drop_duplicates(["club", "date"])[["club", "date"] + cols]
    out = {}
    for c in cols:
        P = day.pivot(index="date", columns="club", values=c).reindex(columns=ids)
        V = P.values; M = ~np.isnan(V); V0 = np.nan_to_num(V)
        num = V0 @ W.T; den = M.astype(float) @ W.T
        out[f"nb_{c}"] = pd.DataFrame(np.where(den > 0, num / np.where(den > 0, den, 1), np.nan), index=P.index, columns=ids).stack()
    N = pd.DataFrame(out); N.index.names = ["date", "club"]
    nn = pd.Series((W > 0).sum(axis=1), index=ids, name="nb_count")
    return D.merge(N.reset_index(), on=["date", "club"], how="left").merge(nn, left_on="club", right_index=True, how="left")

def no_station_clubs():
    D = B3.table(); print("rows", len(D), "stations", D.club.nunique(), flush=True)
    D = recent_error(D)
    A = pd.read_csv(f"{HERE}/all_stations.csv").set_index("id")
    D = neighbour_recent(D, A)
    clubs = [c for c in pd.read_csv(f"{HERE}/clubs.csv").id if c in set(D.club)]
    # club station ids in all_stations are the ISD ids; clubs.csv lists club ids -> map via stations.csv like round 3
    rng = np.random.RandomState(0); order = list(clubs); rng.shuffle(order); fold = {c: i % 4 for i, c in enumerate(order)}
    base = [c for c in D.columns if c not in {"club", "time", "obs", "year", "date"} and not c.startswith(("re_", "nb_", "ns_"))]
    NB = [c for c in D.columns if c.startswith("nb_")]
    isclub = D.club.isin(clubs)
    for v in ("ns", "ns_nb"): D[v] = np.nan
    for f in range(4):
        fc = [c for c in clubs if fold[c] == f]
        near = {s for s in A.index if any(B3.km(A.lat[s], A.lon[s], A.lat[c], A.lon[c]) < 25 for c in fc)}
        te = D.club.isin(fc); tr = ~D.club.isin(near) & ~te
        D.loc[te, "ns"], _ = B.fit_predict(D[tr], D[te], base)
        D.loc[te, "ns_nb"], m = B.fit_predict(D[tr], D[te], base + NB)
        imp = (imp if f else 0) + pd.Series(m.booster_.feature_importance("gain"), index=base + NB)
        print("fold", f, "done", flush=True)
    # out-of-fold no-station predictions at every non-club station (5 spatial blocks), for the fallback guard
    S = D[~isclub & ~D.club.isin(set().union(*[{s for s in A.index if any(B3.km(A.lat[s], A.lon[s], A.lat[c], A.lon[c]) < 25 for c in clubs)}]))]
    blk = (np.floor(A.loc[S.club.unique(), "lon"] / 4) + 10 * np.floor(A.loc[S.club.unique(), "lat"] / 4)).astype(int)
    blk = blk.map({b: i % 5 for i, b in enumerate(sorted(blk.unique()))})
    S = S.assign(blk=S.club.map(blk)); S["oof"] = np.nan
    for b in range(5):
        te = S.blk == b; S.loc[te, "oof"], _ = B.fit_predict(S[~te], S[te], base + NB)
    sk = S.groupby("club").apply(lambda x: (x.raw_mean - x.obs).abs().mean() - (x.oof - x.obs).abs().mean())   # >0: model helps here
    st = A.loc[sk.index]
    def guard_gain(c, k=8):
        d = B3.km(A.lat[c], A.lon[c], st.lat.values, st.lon.values); o = np.argsort(np.where(d >= 25, d, np.inf))[:k]
        return float(np.average(sk.values[o], weights=1 / np.maximum(d[o], 1)))
    gg = {c: guard_gain(c) for c in clubs}
    D["ns_guard"] = np.where(D.club.map(gg).fillna(1) > 0, D.ns_nb, D.raw_mean)
    C = D[isclub].copy(); cand = ["raw_mean", "ns", "ns_nb", "ns_guard"]
    res = {"hourly": {c: B.score_speed(C, c) for c in cand}}
    res["race_day"] = race_scores(C, cand)
    th = (C.ws850 < 8) & (C.sw > 300); res["light_wind_sunny_hourly"] = {c: B.score_speed(C[th], c) for c in cand}
    bc = C.groupby("club").apply(lambda x: pd.Series({c: (x[c] - x.obs).abs().mean() for c in cand})).round(2)
    bc["guard_skill"] = pd.Series(gg).round(2); bc["fell_back"] = bc.guard_skill <= 0
    res["by_club_median"] = bc[cand].median().round(2).to_dict()
    res["clubs_worse_than_raw"] = {c: int((bc[c] > bc.raw_mean).sum()) for c in cand[1:]}
    res["clubs_fell_back"] = sorted(bc.index[bc.fell_back].tolist())
    res["top_features"] = (imp / imp.sum()).sort_values(ascending=False).head(12).round(3).to_dict()
    return res, bc

def main():
    res = {}
    if os.path.exists(f"{OUT}/round4.json"): res = json.load(open(f"{OUT}/round4.json"))
    if "--no-station-only" not in sys.argv:
        r, bc = station_clubs(); res["with_station"] = r; print(json.dumps(r, indent=1), flush=True)
        bc.to_csv(f"{OUT}/round4_by_club.csv"); json.dump(res, open(f"{OUT}/round4.json", "w"), indent=1)
    if os.path.exists(f"{B3.DA}/geo.parquet"):
        r, bn = no_station_clubs(); res["no_station"] = r; print(json.dumps(r, indent=1), flush=True)
        bn.to_csv(f"{OUT}/round4_by_club_nostation.csv")
    json.dump(res, open(f"{OUT}/round4.json", "w"), indent=1)

if __name__ == "__main__":
    if "--station-only" in sys.argv: B3.DA = "/nonexistent"
    main()
