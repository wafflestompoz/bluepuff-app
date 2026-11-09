"""Water conditions for dinghy sailors.
Chop (wind waves) at every club, lakes included, from wind speed, fetch upwind of the race area (geo.py) and water depth
(depths.csv), with the Shore Protection Manual (USACE 1984) fetch- and depth-limited growth formulas:
  UA = 0.71 U^1.23 (U = 10 m wind, m/s);  d* = g d / UA^2;  F* = g F / UA^2
  Hs = 0.283 UA^2/g tanh(0.530 d*^0.75) tanh(0.00565 F*^0.5 / tanh(0.530 d*^0.75))
  T  = 7.54  UA/g   tanh(0.833 d*^0.375) tanh(0.0379 F*^0.333 / tanh(0.833 d*^0.375))
Wavelength L0 = g T^2 / 2pi. Short chop (Hs >= 0.3 m with crests under 12 m apart, a few dinghy lengths) is what slows a
dinghy most; the formulas keep steepness near 1/25, so wavelength is the more useful flag.
Checked against DWD EWAM wind-sea height at the sea clubs (marine.py), and tides against known spring ranges.
Writes reports/water.json."""
import os, json, numpy as np, pandas as pd
import backtest as B
HERE = B.HERE; OUT = B.OUT; g = 9.81

def chop(U, F_km, d_m):
    U = np.maximum(np.asarray(U, float), 0.1); F = np.maximum(np.asarray(F_km, float), 0.05) * 1000; d = np.asarray(d_m, float)
    UA = 0.71 * U ** 1.23; ds, fs = g * d / UA ** 2, g * F / UA ** 2
    a, b = np.tanh(0.530 * ds ** 0.75), np.tanh(0.833 * ds ** 0.375)
    hs = 0.283 * UA ** 2 / g * a * np.tanh(0.00565 * fs ** 0.5 / a)
    t = 7.54 * UA / g * b * np.tanh(0.0379 * fs ** (1 / 3) / b)
    return hs, t, hs / (g * t ** 2 / (2 * np.pi))

def label(hs):
    return pd.cut(hs, [-1, 0.1, 0.3, 0.6, 1.0, 99], labels=["flat", "small chop", "moderate chop", "rough", "big waves"])

def upwind_fetch(G, clubs, theta):
    M = G.set_index("club").loc[clubs, [f"water_fetch_{s}" for s in range(16)]].values
    x = theta / 22.5; i0 = np.floor(x).astype(int) % 16; i1 = (i0 + 1) % 16; w = x - np.floor(x); r = np.arange(len(clubs))
    return M[r, i0] * (1 - w) + M[r, i1] * w

def model_wind_water():
    """Mean of the models' 10 m wind at the race area (knots -> m/s) and their mean direction, May-Sep 07-16 UTC."""
    us, vs = [], []
    for m, s in B.MODELS.items():
        u, v = B.load(m, "wind_u_component_10m", "u"), B.load(m, "wind_v_component_10m", "v")
        if u is None:
            sp, dr = B.load(m, "wind_speed_10m", "u"), B.load(m, "wind_direction_10m", "v")
            if sp is None: continue
            rad = np.radians(dr["v_water"]); u = (-sp["u_water"] * np.sin(rad)).rename("u_water").to_frame(); v = (-sp["u_water"] * np.cos(rad)).rename("v_water").to_frame()
        us.append(u["u_water"].rename(s)); vs.append(v["v_water"].rename(s))
    U, V = pd.concat(us, axis=1).mean(axis=1), pd.concat(vs, axis=1).mean(axis=1)
    W = pd.DataFrame({"ws": np.hypot(U, V), "wdir": np.degrees(np.arctan2(-U, -V)) % 360}).reset_index()
    return W[W.time.dt.month.between(5, 9) & W.time.dt.hour.isin(B.WIN)]

def marine(model, var):
    f = f"{HERE}/data/model/{model}__{var}.parquet"
    if not os.path.exists(f): return None
    d = pd.read_parquet(f); d[["club", "k"]] = d.site.str.split("|", expand=True); return d

def nearest_valid(d):
    """For each club keep the candidate point nearest the race area that has data."""
    k = d.dropna(subset=["v"]).groupby(["club", "k"]).size().reset_index().sort_values("k").groupby("club").first().k
    return d[d.k == d.club.map(k)].drop(columns="k")

def main():
    G = pd.read_parquet(f"{HERE}/data/geo.parquet"); Dp = pd.read_csv(f"{HERE}/depths.csv").set_index("club")
    C = pd.read_csv(f"{HERE}/clubs.csv").set_index("id")
    W = model_wind_water(); W = W[W.club.isin(Dp.index)]
    W["fetch_km"] = upwind_fetch(G, W.club.values, W.wdir.values); W["depth"] = Dp.loc[W.club, "depth_m"].values
    W["hs"], W["tp"], W["steep"] = chop(W.ws, W.fetch_km, W.depth); W["state"] = label(W.hs)
    W["water"] = C.loc[W.club, "water"].values
    res = {"chop_by_club": W.groupby("club").apply(lambda x: {"water": x.water.iloc[0], "median_hs_m": round(float(x.hs.median()), 2),
           "p90_hs_m": round(float(x.hs.quantile(.9)), 2), "share_moderate_or_worse": round(float((x.hs >= 0.3).mean()), 3),
           "share_short_chop": round(float(((x.hs >= 0.3) & (g * x.tp ** 2 / (2 * np.pi) < 12)).mean()), 3)}).to_dict()}
    # check against DWD EWAM wind-sea height at the sea clubs
    ew = marine("dwd_ewam", "wind_wave_height")
    if ew is not None:
        ew = nearest_valid(ew).rename(columns={"v": "ewam_ws_h"})
        J = W.merge(ew[["club", "time", "ewam_ws_h"]], on=["club", "time"]).dropna(subset=["ewam_ws_h"])
        def cmp(x):
            return {"n": len(x), "corr": round(float(np.corrcoef(x.hs, x.ewam_ws_h)[0, 1]), 2), "ours_median_m": round(float(x.hs.median()), 2),
                    "ewam_median_m": round(float(x.ewam_ws_h.median()), 2), "same_state": round(float((label(x.hs) == label(x.ewam_ws_h)).mean()), 2)}
        res["chop_vs_ewam"] = {c: cmp(x) for c, x in J.groupby("club")}
        res["chop_vs_ewam_all"] = cmp(J)
    # tides: daily range of sea level (tide + surge), median and 95th percentile (springs), and currents
    sl = marine("meteofrance_currents", "sea_level_height_msl")
    if sl is not None:
        sl = nearest_valid(sl); sl["date"] = sl.time.dt.date
        rng = sl.groupby(["club", "date"]).v.agg(lambda x: x.max() - x.min() if x.count() >= 20 else np.nan)
        res["tide_daily_range_m"] = rng.groupby("club").agg(lambda x: {"median": round(float(x.median()), 2), "p95": round(float(x.quantile(.95)), 2)}).to_dict()
    cu, cv = marine("meteofrance_currents", "ocean_u_current"), marine("meteofrance_currents", "ocean_v_current")
    if cu is not None and cv is not None:
        cu, cv = nearest_valid(cu), nearest_valid(cv); J = cu.merge(cv, on=["club", "time"], suffixes=("_u", "_v"))
        J["kn"] = np.hypot(J.v_u, J.v_v) * B.KN
        res["current_kn"] = J.groupby("club").kn.agg(lambda x: {"median": round(float(x.median()), 2), "p95": round(float(x.quantile(.95)), 2)}).to_dict()
    sst = marine("meteofrance_sea_surface_temperature", "sea_surface_temperature")
    if sst is not None:
        sst = nearest_valid(sst); sst["month"] = sst.time.dt.month
        res["sea_temp_c_by_month"] = sst[sst.month.between(5, 9)].groupby(["club", "month"]).v.median().round(1).unstack().to_dict("index")
    hw = marine("dwd_ewam", "wave_height"); sw = marine("dwd_ewam", "swell_wave_height")
    if hw is not None:
        hw = nearest_valid(hw); hw = hw[hw.time.dt.month.between(5, 9)]
        res["wave_height_m"] = hw.groupby("club").v.agg(lambda x: {"median": round(float(x.median()), 2), "p90": round(float(x.quantile(.9)), 2)}).to_dict()
    json.dump(res, open(f"{OUT}/water.json", "w"), indent=1, default=str)
    return res

if __name__ == "__main__":
    r = main()
    for k in ("chop_vs_ewam_all", "chop_vs_ewam", "tide_daily_range_m", "current_kn", "wave_height_m"):
        print(k, json.dumps(r.get(k), default=str)[:3000])
    print(pd.DataFrame(r["chop_by_club"]).T.to_string())
