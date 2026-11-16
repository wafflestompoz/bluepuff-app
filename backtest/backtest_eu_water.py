"""Europe, scored on the water: does the forecast hold up on the water, and should the correction learn from on-water stations?

Stations (stations_eu_national.csv, built from the national open-data networks, see obs_national.py):
  water: 45 KNMI, DWD, MeteoSwiss and DMI stations on piers, lighthouses, dykes, platforms, islands and lakeshores (>= 50% water
         within 1 km in ESA WorldCover); 11 are within 15 km of a bluepuff club. Plus 11 on-water NOAA ISD stations at clubs
         (Portland, Zeebrugge, Trieste...), scored separately because ISD's non-US data is non-commercial.
  land : 146 national stations with < 5% water within 1 km and > 1 km from the shore (DWD, DMI, KNMI, MeteoSwiss lowland).
Hourly, May-Sep 2023-25, 09-18 local. Raw forecast: mean of Europe's 6 models (IFS, ICON-EU, ICON-D2, UKMO, AROME, ARPEGE)
from Open-Meteo's open-data archive on AWS (same-day lead, as in rounds 1-5).

Scored against the ON-WATER reading (all out of sample):
  raw_mean    : mean of the 6 models at the station
  water_bias  : per-station linear fit on the water, other summers (the station's own history)
  land_corr   : correction learned on the 146 land stations, other summers, applied on the water (no station of its own)
  water_ns    : correction learned on the OTHER on-water stations (8 spatial folds; no station of its own)
  water_ns_geo: water_ns plus geography (water within 1/5/20 km, shore distance, open water upwind in the model wind's sector)
  all_ns_geo  : learned on land and water stations together with geography, other stations
  water_st    : learned on all on-water stations incl. this one's other summers (a club with its own on-water station)
For reference the land stations are scored the same way (raw, land correction from other land stations).
Data: python obs_national.py stations_eu_national.csv data/eu_nat; POINTS=<club,lat,lon csv> POINTS_TAG=eu_nat python extract_wind.py ...
Geography: geo.feats() per station -> data/eu_nat/geo.parquet. Writes reports/eu_water.json, eu_water_by_station.csv.
"""
import json, os, numpy as np, pandas as pd
import backtest as B, backtest_au as A
HERE = B.HERE; OUT = B.OUT; KN = B.KN; DA = f"{HERE}/data/eu_nat"
A.DA = DA; MODELS = B.MODELS; CTX = {("dwd_icon_eu", "temperature_2m"): "t2", ("dwd_icon_eu", "direct_radiation"): "sw"}
HOURS = range(9, 19); MONTHS = [5, 6, 7, 8, 9]; FOLDS = 8

def table():
    S = pd.read_csv(f"{HERE}/stations_eu_national.csv")
    O = pd.read_parquet(f"{DA}/obs.parquet"); O = O[O.club.isin(S.club)]
    O["obs"] = O.obs_ws * KN; O["obs_gust_kn"] = O.obs_gust * KN; O = O.set_index(["club", "time"])[["obs", "obs_gust_kn"]]
    parts = [O]
    for m, s in MODELS.items():
        u, v, g = A.load(m, "wind_u_component_10m", s + "u"), A.load(m, "wind_v_component_10m", s + "v"), A.load(m, "wind_gusts_10m", s + "g")
        if u is None:
            sp, dr = A.load(m, "wind_speed_10m", s + "u"), A.load(m, "wind_direction_10m", s + "v")
            if sp is None: continue
            rad = np.radians(dr.values); u = -sp * np.sin(rad); v = pd.DataFrame(-sp.values * np.cos(rad), index=sp.index, columns=dr.columns)
        ws = pd.DataFrame({c.replace(s + "u_", s + "ws_"): np.hypot(u[c], v[c.replace(s + "u_", s + "v_")]) * KN for c in u.columns}, index=u.index)
        parts += [ws, u[[f"{s}u_st"]], v[[f"{s}v_st"]]] + ([g * KN] if g is not None else [])
    for (m, var), s in CTX.items():
        x = A.load(m, var, s)
        if x is not None: parts.append(x)
    D = pd.concat(parts, axis=1, join="outer").reindex(O.index).reset_index()
    tz = dict(zip(S.club, np.where(S.lon < 0, "Europe/London", "Europe/Berlin")))
    D["local"] = D.groupby("club").time.transform(lambda t: t.dt.tz_localize("UTC").dt.tz_convert(tz[t.name]).dt.tz_localize(None))
    D = D[D.local.dt.month.isin(MONTHS) & D.local.dt.hour.isin(HOURS) & D.obs.notna()].copy()
    D["year"] = D.local.dt.year; D["hour"] = D.local.dt.hour; D["doy"] = D.local.dt.dayofyear
    for s in MODELS.values():
        if f"{s}u_st" in D: D[f"{s}dir_st"] = np.degrees(np.arctan2(-D[f"{s}u_st"], -D[f"{s}v_st"])) % 360
    if "t2_st" in D: D["t2_land_st"] = D[[f"t2_{p}" for p in "nsew" if f"t2_{p}" in D]].max(axis=1) - D.t2_st
    R = [f"{s}ws_st" for s in MODELS.values() if f"{s}ws_st" in D]
    D["raw_mean"] = D[R].mean(axis=1); D = D[D.raw_mean.notna()].reset_index(drop=True)
    D = D.merge(S[["club", "kind", "licence", "near_club", "name", "lat", "lon"]].rename(columns={"name": "stname"}), on="club")
    return D, R

def add_geo(D):
    G = pd.read_parquet(f"{DA}/geo.parquet").set_index("club")
    for c in ("st_water_r1", "st_water_r5", "st_water_r20", "st_shore_km", "st_rough10", "st_elev"): D[c] = D.club.map(G[c])
    sec = ((D.ifsdir_st + 11.25) // 22.5).astype(int) % 16          # the sector the model wind comes from
    up = lambda pre: G[[f"{pre}{s}" for s in range(16)]].reindex(D.club).to_numpy()[np.arange(len(D)), sec.to_numpy()]
    for a, b in B_ANDS: D[f"up_wf{a}_{b}"] = up(f"st_wf{a}_{b}_")
    D["up_fetch"] = up("st_fetch_"); D["up_relief"] = up("st_relief_")
    return D
B_ANDS = [(0, 2), (2, 10), (10, 30)]
GEO = ["st_water_r1", "st_water_r5", "st_water_r20", "st_shore_km", "st_rough10", "st_elev", "up_wf0_2", "up_wf2_10", "up_wf10_30", "up_fetch", "up_relief"]

def spatial_folds(S, k=FOLDS, km=25):
    """Stations within ~25 km share a fold (IJmond/IJmuiden, Assens/Bago...), folds balanced by count."""
    from scipy.cluster.hierarchy import fcluster, linkage
    xy = np.c_[S.lat.values * 111, S.lon.values * 111 * np.cos(np.radians(S.lat.values))]
    cl = fcluster(linkage(xy, "single"), km, "distance")
    order = pd.Series(cl).value_counts().index; fold = {c: i % k for i, c in enumerate(order)}
    return dict(zip(S.club, [fold[c] for c in cl]))

def main():
    if os.environ.get("REPORT") == "1": return report(pd.read_parquet(f"{DA}/predictions.parquet"))   # rescore without retraining
    D, R = table(); D = add_geo(D)
    print("rows", len(D), D.groupby("kind").club.nunique().to_dict(), flush=True)
    meta = {"club", "time", "local", "obs", "obs_gust_kn", "year", "raw_mean", "res", "kind", "licence", "near_club", "stname", "lat", "lon", "clubc", "fold"}
    F = [c for c in D.columns if c not in meta and c not in GEO] + ["raw_mean"]
    D["res"] = D.obs - D.raw_mean; D["clubc"] = D.club.astype("category")
    S = D.drop_duplicates("club")[["club", "lat", "lon", "kind"]]
    D["fold"] = D.club.map(spatial_folds(S))
    W = D.kind == "water"; Wn = W & (D.licence == "national-open"); L = D.kind == "land"
    cand = ["raw_mean", "water_bias", "land_corr", "water_ns", "water_ns_geo", "all_ns_geo", "water_st"]
    for c in cand[1:]: D[c] = np.nan
    for y in D.year.unique():                             # other summers
        te, tr = D.year == y, D.year != y
        for cl in D[W].club.unique():
            a, b = tr & (D.club == cl), te & (D.club == cl)
            if a.sum() >= 200: D.loc[b, "water_bias"] = np.polyval(np.polyfit(D.raw_mean[a], D.obs[a], 1), D.raw_mean[b])
        p, _ = B.fit_predict(D[tr & L], D[te & W], F, target="res"); D.loc[te & W, "land_corr"] = D.raw_mean[te & W] + p
        p, _ = B.fit_predict(D[tr & W], D[te & W], F + ["clubc"], target="res"); D.loc[te & W, "water_st"] = D.raw_mean[te & W] + p
        print("year", y, flush=True)
    D["land_ref"] = np.nan
    for f in range(FOLDS):                                # other stations (spatial folds); ISD stations never train
        te, tr = D.fold == f, D.fold != f
        p, _ = B.fit_predict(D[tr & Wn], D[te & W], F, target="res"); D.loc[te & W, "water_ns"] = D.raw_mean[te & W] + p
        p, _ = B.fit_predict(D[tr & Wn], D[te & W], F + GEO, target="res"); D.loc[te & W, "water_ns_geo"] = D.raw_mean[te & W] + p
        p, _ = B.fit_predict(D[tr & (Wn | L)], D[te & W], F + GEO, target="res"); D.loc[te & W, "all_ns_geo"] = D.raw_mean[te & W] + p
        p, _ = B.fit_predict(D[tr & L], D[te & L], F, target="res"); D.loc[te & L, "land_ref"] = D.raw_mean[te & L] + p
        print("fold", f, flush=True)
    D = D[["club", "time", "local", "hour", "obs", "raw_mean", "kind", "licence", "near_club", "stname"] + cand[1:] + ["land_ref"]]
    D.to_parquet(f"{DA}/predictions.parquet", index=False); report(D)

CAND = ["raw_mean", "water_bias", "land_corr", "water_ns", "water_ns_geo", "all_ns_geo", "water_st"]
def report(D):
    cand = CAND; W = D.kind == "water"; Wn = W & (D.licence == "national-open"); L = D.kind == "land"
    res = {"stations": {f"{k}/{l}": int(n) for (k, l), n in D.groupby(["kind", "licence"]).club.nunique().items()},
           "obs_mean_kn": D.groupby("kind").obs.mean().round(1).to_dict(), "raw_bias_kn": (D.raw_mean - D.obs).groupby(D.kind).mean().round(2).to_dict()}
    for name, m in (("water_national", Wn), ("water_isd_clubs", W & (D.licence != "national-open")), ("water_near_clubs", Wn & (D.near_club.fillna("") != ""))):
        X = D[m]; res[name] = {"hours": len(X), "stations": int(X.club.nunique()), "hourly": {c: B.score_speed(X, c) for c in cand}}
        G = A.day_table(X, cand); res[name]["race_days"] = len(G); res[name]["race_day"] = {c: B.score_day(G, c) for c in cand}
    X = D[L]; res["land_reference"] = {"hourly": {c: B.score_speed(X, c) for c in ["raw_mean", "land_ref"]}}
    G = A.day_table(X, ["raw_mean", "land_ref"]); res["land_reference"]["race_day"] = {c: B.score_day(G, c) for c in ["raw_mean", "land_ref"]}
    bc = D[W].groupby("club").apply(lambda x: pd.Series({"name": x.stname.iloc[0], "near_club": x.near_club.iloc[0], "licence": x.licence.iloc[0],
                                                         "hours": len(x), "obs_kn": x.obs.mean()} | {c: (x[c] - x.obs).abs().mean() for c in cand}))
    bc = bc.round(2).sort_values("raw_mean"); bc.to_csv(f"{OUT}/eu_water_by_station.csv")
    json.dump(res, open(f"{OUT}/eu_water.json", "w"), indent=1); print(json.dumps(res, indent=1)); print(bc.to_string())

if __name__ == "__main__":
    main()
