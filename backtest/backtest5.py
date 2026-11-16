"""Round 5: cheaper, safer ways to combine the corrected and raw forecasts.

Round 4 found that recent-error and neighbour signals add nothing on top of the trained models. This round tests:
  *_res   : the model learns the correction (obs - raw multi-model mean) instead of the wind itself, so it starts from
            the raw forecast and only moves it where it has learned to. Usually safer at unusual sites and in strong wind.
  *_blend : the average of the trained model and the per-club linear fit (station clubs) or the raw mean (no station).
Same out-of-sample schemes as rounds 1 and 3. Saves predictions to data/round5_*.parquet, scores to reports/round5.json.
"""
import os, sys, json, numpy as np, pandas as pd
import backtest as B, backtest3 as B3, backtest4 as B4
HERE = B.HERE; OUT = B.OUT

def cv_res(D, how, cols):
    D = D.assign(res=D.obs - D.raw_mean); pred = pd.Series(np.nan, index=D.index)
    groups = D.year if how == "year" else D.club
    for g in groups.unique():
        te = groups == g; p, _ = B.fit_predict(D[~te], D[te], cols, target="res"); pred[te] = p
    return D.raw_mean + pred

def summarise(C, cand, extra=None):
    res = {"hourly": {c: B.score_speed(C, c) for c in cand}}
    G = B.day_table(C, cand); res["race_day"] = {c: B.score_day(G, c) for c in cand}
    th = (C.ws850 < 8) & (C[extra] > 300); res["light_wind_sunny_hourly"] = {c: B.score_speed(C[th], c) for c in cand}
    bc = C.groupby("club").apply(lambda x: pd.Series({c: (x[c] - x.obs).abs().mean() for c in cand})).round(2)
    res["by_club_median"] = bc.median().round(2).to_dict()
    res["clubs_worse_than_raw"] = {c: int((bc[c] > bc.raw_mean + 0.005).sum()) for c in cand if c != "raw_mean"}
    res["worst_club_pct_vs_raw"] = {c: round(float((100 * (bc[c] / bc.raw_mean - 1)).max()), 0) for c in cand if c != "raw_mean"}
    return res, bc

def station_clubs():
    D = B.table(); D = D[D.obs.notna()].reset_index(drop=True)
    D["raw_mean"] = D[B.raw_cols(D)].mean(axis=1); D = D[D.raw_mean.notna()].reset_index(drop=True)
    D["bias"] = B.bias_cv(D, D.raw_mean)
    F = [c for c in B.feats(D) if c not in {"raw_mean", "bias"}] + ["raw_mean"]
    D["kasta"], _ = B.cv(D, "year", F); print("kasta", flush=True)
    D["kasta_res"] = cv_res(D, "year", F); print("kasta_res", flush=True)
    D["kasta_blend"] = (D.kasta + D.bias.fillna(D.kasta)) / 2
    D["kasta_res_blend"] = (D.kasta_res + D.kasta) / 2
    cand = ["raw_mean", "bias", "kasta", "kasta_res", "kasta_blend", "kasta_res_blend"]
    D[["club", "time", "obs"] + cand].to_parquet(f"{HERE}/data/round5_station.parquet")
    return summarise(D, cand, "sw_st")

def no_station_clubs():
    D = B3.table(); print("rows", len(D), flush=True)
    A = pd.read_csv(f"{HERE}/all_stations.csv").set_index("id")
    clubs = [c for c in pd.read_csv(f"{HERE}/clubs.csv").id if c in set(D.club)]
    rng = np.random.RandomState(0); order = list(clubs); rng.shuffle(order); fold = {c: i % 4 for i, c in enumerate(order)}
    F = [c for c in D.columns if c not in {"club", "time", "obs", "year"}]
    D["res"] = D.obs - D.raw_mean
    for v in ("ns", "ns_res"): D[v] = np.nan
    for f in range(4):
        fc = [c for c in clubs if fold[c] == f]
        near = {s for s in A.index if any(B3.km(A.lat[s], A.lon[s], A.lat[c], A.lon[c]) < 25 for c in fc)}
        te = D.club.isin(fc); tr = ~D.club.isin(near) & ~te
        D.loc[te, "ns"], _ = B.fit_predict(D[tr], D[te], F)
        p, _ = B.fit_predict(D[tr], D[te], F, target="res"); D.loc[te, "ns_res"] = D.raw_mean[te] + p
        print("fold", f, flush=True)
    C = D[D.club.isin(clubs)].copy()
    C["ns_blend"] = (C.ns + C.raw_mean) / 2; C["ns_res_blend"] = (C.ns_res + C.ns) / 2
    cand = ["raw_mean", "ns", "ns_res", "ns_blend", "ns_res_blend"]
    C[["club", "time", "obs"] + cand].to_parquet(f"{HERE}/data/round5_nostation.parquet")
    return summarise(C, cand, "sw")

def main():
    f = f"{OUT}/round5.json"; res = json.load(open(f)) if os.path.exists(f) else {}
    if "--no-station-only" not in sys.argv:
        r, bc = station_clubs(); res["with_station"] = r; bc.to_csv(f"{OUT}/round5_by_club.csv")
        json.dump(res, open(f, "w"), indent=1); print(json.dumps(r, indent=1), flush=True)
    if "--station-only" not in sys.argv:
        r, bc = no_station_clubs(); res["no_station"] = r; bc.to_csv(f"{OUT}/round5_by_club_nostation.csv")
        json.dump(res, open(f, "w"), indent=1); print(json.dumps(r, indent=1), flush=True)

if __name__ == "__main__":
    main()
