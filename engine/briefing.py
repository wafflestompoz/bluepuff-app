"""Race-day briefings from the live club forecast (forecast/live.py).

For each start on a club's programme this works out, for each fleet racing in it:
- the race call: race on, marginal, too light or blown out, with the odds, against the fleet's wind range;
- shifts: whether the wind direction moves 10 degrees or more during the race, when, how likely, and which side pays;
- rig: the light, medium or heavy band for the fleet, with a short setup tip;
- water: chop, waves and swell, the tide (high and low water, the stream at the gun, wind against tide);
- a live sensor blend: when the club's own sensor has a recent reading, the forecast is nudged toward it, with the
  nudge fading over the following hours.

Odds come from the spread between the weather models plus a base error (the backtest's typical hourly wind error),
treated as one shared error for the whole race: a day that comes in windier than forecast is windier at the gun and
in the gusts. That gives closed-form odds: racing needs the wind at the gun above the fleet minimum AND the strongest
gust in the race window below the fleet's gust limit.

Usage: python -m engine.briefing programme.json [--forecast forecast/out] [--out briefings.json]
"""
import os, sys, json, math, argparse, datetime as dt
from dataclasses import dataclass, asdict
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
BASE_SD_KN = 1.8          # typical hourly wind error of the model blend (backtest, raw); gusts use 1.3x this
SHIFT_DEG = 10            # a shift worth telling a racer about
SENSOR_MAX_AGE_MIN = 45   # older readings are ignored
SENSOR_EFOLD_H = 3.0      # how fast the sensor nudge fades into the forecast
CALL_ON, CALL_OFF = 0.65, 0.6


@dataclass
class Fleet:
    cls: str
    name: str
    min_kn: float            # below this at the gun, no racing
    max_gust_kn: float       # the club's gust limit for this fleet
    light_below_kn: float    # rig bands
    heavy_above_kn: float
    trapeze: bool = False


def load_classes(path=None):
    C = pd.read_csv(path or f"{HERE}/classes.csv", dtype={"class": str})
    return {r["class"]: Fleet(r["class"], r["name"], float(r.min_kn), float(r.max_gust_kn), float(r.light_below_kn),
                              float(r.heavy_above_kn), bool(r.trapeze)) for _, r in C.iterrows()}


def club_tz(country, lat, lon):
    """IANA time zone for a club, from its country (and longitude and latitude in Australia)."""
    if country == "AU":
        if lon < 129: return "Australia/Perth"
        if lon < 141: return "Australia/Adelaide"
        if lat < -40: return "Australia/Hobart"
        if lat > -28.2 and lon > 141: return "Australia/Brisbane"
        return "Australia/Sydney"
    return {"UK": "Europe/London", "IE": "Europe/Dublin", "FR": "Europe/Paris", "DE": "Europe/Berlin", "NL": "Europe/Amsterdam",
            "BE": "Europe/Brussels", "CH": "Europe/Zurich", "AT": "Europe/Vienna", "IT": "Europe/Rome", "DK": "Europe/Copenhagen",
            "SE": "Europe/Stockholm", "PL": "Europe/Warsaw", "HU": "Europe/Budapest", "HR": "Europe/Zagreb",
            "ES": "Europe/Madrid", "PT": "Europe/Lisbon", "NO": "Europe/Oslo", "FI": "Europe/Helsinki",
            "NZ": "Pacific/Auckland"}.get(country, "UTC")


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def circ_diff(a, b):
    """Signed difference a - b in degrees, in (-180, 180]. Positive = clockwise (a veer)."""
    return (np.asarray(a, float) - np.asarray(b, float) + 180) % 360 - 180


def model_names(D):
    return [c[:-3] for c in D.columns if c.endswith("_kn") and c not in ("wind_kn", "gust_kn", "current_kn")
            and not c.endswith(("_gust_kn", "_spread_kn"))]


def load_forecast(path):
    D = pd.read_csv(path, parse_dates=["time"]).set_index("time")
    if D.index.tz is None: D.index = D.index.tz_localize("UTC")
    return D.sort_index()


def at(D, t, cols):
    """Values of columns at time t, interpolated in time (directions through their vectors)."""
    t = pd.Timestamp(t).as_unit("ns").value; x = D.index.as_unit("ns").asi8   # pandas 3 indexes may be in us
    out = {}
    for c in cols:
        if c not in D: continue
        s = D[c].astype(float)
        if c.endswith("_dir"):
            u, v = np.sin(np.radians(s)), np.cos(np.radians(s))
            ui = np.interp(t, x, u.values); vi = np.interp(t, x, v.values)
            out[c] = float(np.degrees(np.arctan2(ui, vi)) % 360)
        else:
            ok = s.notna()
            if ok.sum() == 0: continue
            out[c] = float(np.interp(t, x[ok.values], s.values[ok.values]))
    return out


def window(D, gun, hours):
    gun = pd.Timestamp(gun)
    return D[(D.index >= gun.floor("h")) & (D.index <= gun + pd.Timedelta(hours=hours))]


# --- live sensor -------------------------------------------------------------------------------------------------

def sensor_blend(D, reading, now=None):
    """Nudge the forecast toward the club sensor's latest reading, fading over the next hours.

    reading: {"time": ISO, "wind_kn": float, "gust_kn": float | None, "dir": float}. Returns (D', weight at each hour).
    """
    D = D.copy(); D["sensor_weight"] = 0.0
    if not reading: return D
    t_obs = pd.Timestamp(reading["time"]); t_obs = t_obs.tz_localize("UTC") if t_obs.tz is None else t_obs.tz_convert("UTC")
    now = pd.Timestamp(now or pd.Timestamp.now(tz="UTC"))
    if (now - t_obs) > pd.Timedelta(minutes=SENSOR_MAX_AGE_MIN): return D
    f = at(D, t_obs, ["wind_kn", "wind_dir"])
    if "wind_kn" not in f: return D
    dw = reading["wind_kn"] - f["wind_kn"]
    dd = float(circ_diff(reading["dir"], f["wind_dir"])) if reading.get("dir") is not None and "wind_dir" in f else 0.0
    hrs = (D.index - t_obs).total_seconds() / 3600
    w = np.where(hrs >= -1, np.exp(-np.clip(hrs, 0, None) / SENSOR_EFOLD_H), 0.0)
    D["sensor_weight"] = w
    D["wind_kn"] = np.clip(D.wind_kn + dw * w, 0, None)
    if "gust_kn" in D: D["gust_kn"] = np.clip(D.gust_kn + dw * w, 0, None)
    for m in model_names(D):
        D[f"{m}_kn"] = np.clip(D[f"{m}_kn"] + dw * w, 0, None)
        if f"{m}_gust_kn" in D: D[f"{m}_gust_kn"] = np.clip(D[f"{m}_gust_kn"] + dw * w, 0, None)
        if f"{m}_dir" in D: D[f"{m}_dir"] = (D[f"{m}_dir"] + dd * w) % 360
    if "wind_dir" in D: D["wind_dir"] = (D.wind_dir + dd * w) % 360
    return D


# --- the race call -----------------------------------------------------------------------------------------------

def race_call(D, gun, hours, fleet, base_sd=BASE_SD_KN):
    """Odds that the fleet races: wind at the gun >= min_kn and every gust in the window <= max_gust_kn."""
    g = at(D, gun, ["wind_kn", "wind_spread_kn", "gust_kn", "wind_dir", "sensor_weight"])
    W = window(D, gun, hours)
    if "wind_kn" not in g or W.empty: return None
    shrink = 1 - 0.5 * g.get("sensor_weight", 0.0)               # a fresh sensor reading halves the near-term error
    sd_w = math.hypot(g.get("wind_spread_kn", 0.0) or 0.0, base_sd * shrink)
    gusts = W.gust_kn if "gust_kn" in W else W.wind_kn * 1.4
    gcols = [c for c in W if c.endswith("_gust_kn")]
    i = int(np.nanargmax(gusts.values)); gmax = float(gusts.iloc[i]); t_gmax = gusts.index[i]
    g_spread = float(np.nanstd(W[gcols].iloc[i].values)) if gcols else 0.0
    sd_g = math.hypot(g_spread, 1.3 * base_sd * shrink)
    a = (fleet.min_kn - g["wind_kn"]) / sd_w                       # need the shared error z >= a
    b = (fleet.max_gust_kn - gmax) / sd_g                          # and z <= b
    p_on = max(0.0, ncdf(b) - ncdf(a)); p_light = ncdf(min(a, b)); p_strong = 1 - ncdf(max(a, b))
    if p_on >= CALL_ON: call = "race_on"
    elif p_strong >= CALL_OFF: call = "blown_out"
    elif p_light >= CALL_OFF: call = "too_light"
    else: call = "marginal"
    # when the gust risk starts: first hour where the chance of a gust over the limit reaches 25%
    risk_from = None
    for t, gv in gusts.items():
        if 1 - ncdf((fleet.max_gust_kn - gv) / sd_g) >= 0.25: risk_from = t; break
    if call == "race_on": why = f"Inside the {fleet.name} range."
    elif p_strong >= p_light:
        why = (f"{round(100 * p_strong)}% chance gusts pass the {fleet.max_gust_kn:g} kn limit"
               + (f" from {fmt_local(risk_from, D.attrs.get('tz'))}" if risk_from is not None else "") + ".")
    else:
        why = f"{round(100 * p_light)}% chance of less than {fleet.min_kn:g} kn at the gun."
    return {"call": call, "p_race": round(p_on, 2), "p_too_light": round(p_light, 2), "p_blown_out": round(p_strong, 2),
            "wind_kn": round(g["wind_kn"], 1), "gust_max_kn": round(gmax, 1), "gust_max_at": iso(t_gmax),
            "dir": round(g.get("wind_dir", float("nan")), 0), "why": why,
            "gust_limit_risk_from": iso(risk_from) if risk_from is not None else None}


# --- shifts ------------------------------------------------------------------------------------------------------

def shifts(D, gun, hours, min_wind_kn=4.0):
    """The first persistent shift of SHIFT_DEG or more in the race window, its timing, odds and which side pays."""
    W = window(D, gun, hours)
    W = W[W.index >= pd.Timestamp(gun).floor("h")]
    ms = [m for m in model_names(D) if f"{m}_dir" in D]
    g = at(D, gun, ["wind_dir", "wind_kn"] + [f"{m}_dir" for m in ms])
    if "wind_dir" not in g or W.empty: return None
    if g.get("wind_kn", 0) < min_wind_kn:
        return {"kind": "unreliable", "advice": "Too light for a reliable direction: expect shifty, patchy wind."}
    d_mean = circ_diff(W.wind_dir.values, g["wind_dir"])
    hit = np.where((np.abs(d_mean) >= SHIFT_DEG) & (W.wind_kn.values >= min_wind_kn))[0]
    if len(hit) == 0:
        agree = [abs(float(circ_diff(W[f"{m}_dir"].values, g[f"{m}_dir"]).max(initial=0))) < SHIFT_DEG
                 and abs(float(circ_diff(W[f"{m}_dir"].values, g[f"{m}_dir"]).min(initial=0))) < SHIFT_DEG
                 for m in ms if f"{m}_dir" in g and W[f"{m}_dir"].notna().all()]
        p = round(sum(agree) / len(agree), 2) if agree else None
        return {"kind": "steady", "p": p, "advice": f"Steady direction, within {SHIFT_DEG}° through the race."
                + (f" {round(100 * p)}% of models agree." if p is not None else "")}
    k = hit[0]; t = W.index[k]; size = float(d_mean[k]); side = "right" if size > 0 else "left"
    votes = []
    for m in ms:
        if f"{m}_dir" not in g or pd.isna(W[f"{m}_dir"].iloc[k]): continue
        dm = float(circ_diff(W[f"{m}_dir"].iloc[k], g[f"{m}_dir"]))
        votes.append(np.sign(dm) == np.sign(size) and abs(dm) >= 0.7 * SHIFT_DEG)
    p = round(sum(votes) / len(votes), 2) if votes else None
    tz = D.attrs.get("tz"); when = fmt_local(t, tz)
    if side == "right":
        advice = (f"Wind shifts right about {abs(size):.0f}° by {when}. Before it arrives the right side pays: "
                  f"favour port tack early. After it, starboard is lifted.")
    else:
        advice = (f"Wind shifts left about {abs(size):.0f}° by {when}. Before it arrives the left side pays: "
                  f"favour starboard tack early. After it, port is lifted.")
    return {"kind": "shift", "side": side, "size_deg": round(abs(size)), "at": iso(t), "p": p,
            "from_dir": round(g["wind_dir"]), "to_dir": round(float(W.wind_dir.iloc[k])), "advice": advice}


# --- rig ---------------------------------------------------------------------------------------------------------

RIG_TIPS = {
    "light": "Ease the outhaul and vang for a deeper sail, sit forward and steer smoothly.",
    "medium": "Full hike, vang on, flatten the outhaul as the puffs come.",
    "heavy": "Cunningham and vang hard, outhaul tight, ease early in the puffs.",
}


def rig(wind_kn, gust_kn, fleet):
    band = "light" if wind_kn < fleet.light_below_kn else "heavy" if (wind_kn >= fleet.heavy_above_kn or gust_kn >= fleet.heavy_above_kn + 6) else "medium"
    tip = RIG_TIPS[band]
    if fleet.trapeze and band != "light": tip += " Crew on the wire."
    return {"band": band, "tip": tip}


# --- water -------------------------------------------------------------------------------------------------------

def tide_turns(D, t0, t1):
    """High and low water times between t0 and t1 from the sea level series (local extrema)."""
    if "sea_level_height_msl" not in D: return []
    s = D.sea_level_height_msl.dropna()
    s = s[(s.index >= pd.Timestamp(t0) - pd.Timedelta(hours=1)) & (s.index <= pd.Timestamp(t1) + pd.Timedelta(hours=1))]
    out = []
    for i in range(1, len(s) - 1):
        a, b, c = s.iloc[i - 1], s.iloc[i], s.iloc[i + 1]
        if b > a and b >= c: kind = "high"
        elif b < a and b <= c: kind = "low"
        else: continue
        # refine the turning time with a parabola through the three hourly points
        den = a - 2 * b + c; off = 0.5 * (a - c) / den if den else 0.0
        t = s.index[i] + pd.Timedelta(hours=float(np.clip(off, -0.5, 0.5)))
        if pd.Timestamp(t0) <= t <= pd.Timestamp(t1):
            out.append({"kind": kind, "time": iso(t), "height_m": round(float(b - 0.25 * (a - c) * off), 2)})
    return out


def water(D, gun, hours):
    g = at(D, gun, ["chop_m", "chop_period_s", "wave_height", "wave_period", "swell_wave_height", "current_kn", "current_dir", "wind_dir"])
    W = window(D, gun, hours); out = {}
    if "chop_m" in g:
        cmax = float(W.chop_m.max()) if "chop_m" in W else g["chop_m"]
        out["chop"] = {"m": round(g["chop_m"], 2), "period_s": round(g.get("chop_period_s", float("nan")), 1),
                       "max_m": round(cmax, 2), "label": chop_label(cmax)}
    if "wave_height" in g:
        out["waves"] = {"m": round(g["wave_height"], 2), "period_s": round(g.get("wave_period", float("nan")), 1),
                        "swell_m": round(g.get("swell_wave_height", float("nan")), 2)}
    if "current_kn" in g:
        against = "wind_dir" in g and abs(float(circ_diff(g["current_dir"], g["wind_dir"]))) < 60
        out["stream"] = {"kn": round(g["current_kn"], 1), "to_dir": round(g["current_dir"]), "wind_against_tide": bool(against)}
    day0 = pd.Timestamp(gun).floor("D"); turns = tide_turns(D, day0, day0 + pd.Timedelta(days=1))
    if turns: out["tide"] = turns
    return out


def chop_label(m):
    return "flat" if m < 0.1 else "small chop" if m < 0.3 else "moderate chop" if m < 0.6 else "rough" if m < 1.0 else "big waves"


# --- the briefing ------------------------------------------------------------------------------------------------

def iso(t):
    return None if t is None else pd.Timestamp(t).tz_convert("UTC").strftime("%Y-%m-%dT%H:%MZ")


def fmt_local(t, tz):
    t = pd.Timestamp(t)
    return (t.tz_convert(tz) if tz else t).strftime("%H:%M")


def briefing(D, gun, fleet, hours=2.5, sensor=None, now=None, base_sd=BASE_SD_KN):
    """One fleet's briefing for one start. D: the club's hourly forecast (forecast/out/<club>.csv), gun: UTC time."""
    gun = pd.Timestamp(gun); gun = gun.tz_localize("UTC") if gun.tz is None else gun.tz_convert("UTC")
    Ds = sensor_blend(D, sensor, now=now); Ds.attrs = D.attrs
    rc = race_call(Ds, gun, hours, fleet, base_sd)
    if rc is None: return None
    return {"fleet": fleet.cls, "fleet_name": fleet.name, "gun": iso(gun), "window_h": hours,
            "call": rc, "shift": shifts(Ds, gun, hours), "rig": rig(rc["wind_kn"], rc["gust_max_kn"], fleet),
            "water": water(Ds, gun, hours), "sensor_used": bool(sensor) and float(Ds.sensor_weight.max()) > 0,
            "hourly": hourly(Ds, gun, hours)}


def hourly(D, gun, hours):
    W = window(D, gun, hours)
    cols = [c for c in ["wind_kn", "gust_kn", "wind_dir", "chop_m", "current_kn", "current_dir", "sea_level_height_msl"] if c in W]
    return [{"time": iso(t), **{c: (None if pd.isna(r[c]) else round(float(r[c]), 1)) for c in cols}} for t, r in W[cols].iterrows()]


def club_briefings(D, programme, classes, tz, sensor=None, now=None):
    """All briefings for a club. programme: [{"date": "YYYY-MM-DD", "starts": [{"time": "HH:MM", "fleets": [...],
    "window_h": 2.5, "limits": {"CLASS": {"max_gust_kn": 16}}}]}], times local to the club."""
    D = D.copy(); D.attrs["tz"] = tz; out = []
    for day in programme:
        for st in day["starts"]:
            gun = pd.Timestamp(f"{day['date']} {st['time']}").tz_localize(tz).tz_convert("UTC")
            if gun > D.index.max() or gun < D.index.min(): continue
            for f in st["fleets"]:
                fl = classes.get(f) or classes["GENERIC"]
                if st.get("limits", {}).get(f): fl = Fleet(**{**asdict(fl), **st["limits"][f]})
                b = briefing(D, gun, fl, st.get("window_h", 2.5), sensor, now)
                if b: out.append({"date": day["date"], "start": st["time"], **b})
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("programme")
    ap.add_argument("--forecast", default=f"{ROOT}/forecast/out"); ap.add_argument("--out", default=None)
    a = ap.parse_args()
    P = json.load(open(a.programme)); classes = load_classes()
    S = pd.read_csv(f"{ROOT}/forecast/clubs_static.csv").set_index("club")
    res = {"generated": iso(pd.Timestamp.now(tz="UTC")), "clubs": {}}
    for club, prog in P.items():
        f = f"{a.forecast}/{club}.csv"
        if not os.path.exists(f): print("no forecast for", club); continue
        c = S.loc[club]; tz = club_tz(c.country, c.water_lat, c.water_lon)
        res["clubs"][club] = {"tz": tz, "briefings": club_briefings(load_forecast(f), prog["days"], classes, tz, prog.get("sensor"))}
    out = a.out or f"{a.forecast}/briefings.json"
    json.dump(res, open(out, "w"), indent=1); print(f"{sum(len(v['briefings']) for v in res['clubs'].values())} briefings -> {out}")


if __name__ == "__main__":
    main()
