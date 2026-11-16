import numpy as np, pandas as pd, pytest
from engine import briefing as B

FLEETS = B.load_classes()


def fc(wind, gust=None, dirs=None, models=("ifs", "icon", "arpege"), spread=0.5, start="2027-03-13 06:00", **extra):
    """Synthetic hourly forecast: wind/gust lists in kn, dirs a list of per-hour directions (same for every model)
    or a dict model -> list."""
    n = len(wind); idx = pd.date_range(start, periods=n, freq="h", tz="UTC")
    gust = gust if gust is not None else [w * 1.35 for w in wind]
    dirs = dirs if dirs is not None else [220] * n
    D = pd.DataFrame(index=idx)
    for k, m in enumerate(models):
        d = dirs[m] if isinstance(dirs, dict) else dirs
        D[f"{m}_kn"] = np.array(wind) + (k - 1) * spread
        D[f"{m}_gust_kn"] = np.array(gust) + (k - 1) * spread
        D[f"{m}_dir"] = d
    ks = [f"{m}_kn" for m in models]
    D["wind_kn"] = D[ks].mean(axis=1); D["wind_spread_kn"] = D[ks].std(axis=1)
    D["gust_kn"] = D[[f"{m}_gust_kn" for m in models]].mean(axis=1)
    u = np.mean([np.sin(np.radians(D[f"{m}_dir"])) for m in models], axis=0); v = np.mean([np.cos(np.radians(D[f"{m}_dir"])) for m in models], axis=0)
    D["wind_dir"] = np.degrees(np.arctan2(u, v)) % 360
    for k, vals in extra.items(): D[k] = vals
    D.attrs["tz"] = "Europe/London"
    return D


GUN = "2027-03-13 11:00"


def test_race_on_in_a_good_breeze():
    b = B.briefing(fc([12] * 12), GUN, FLEETS["ILCA6"])
    assert b["call"]["call"] == "race_on" and b["call"]["p_race"] > 0.9
    assert b["rig"]["band"] == "medium"


def test_blown_out_when_gusts_far_past_limit():
    b = B.briefing(fc([26] * 12, [36] * 12), GUN, FLEETS["OPTI"])
    assert b["call"]["call"] == "blown_out" and b["call"]["p_blown_out"] > 0.9
    assert b["rig"]["band"] == "heavy"


def test_too_light():
    b = B.briefing(fc([1.5] * 12, [2.5] * 12), GUN, FLEETS["ILCA7"])
    assert b["call"]["call"] == "too_light"
    assert b["shift"]["kind"] == "unreliable"


def test_marginal_junior_limit_names_the_time():
    wind = [10, 10, 10, 10, 10, 11, 12, 13, 13, 12, 11, 10]
    gust = [13, 13, 13, 13, 13, 14, 15, 17, 18, 16, 14, 13]      # gusts climb past 16 kn from 13:00
    b = B.briefing(fc(wind, gust), GUN, FLEETS["OPTI_JUNIOR"], hours=3)
    c = b["call"]
    assert c["call"] in ("marginal", "blown_out") and 0.2 < c["p_blown_out"] < 0.95
    assert "16 kn limit from" in c["why"]
    assert c["gust_max_at"] == "2027-03-13T14:00Z"


def test_club_limit_override():
    D = fc([12] * 12, [17] * 12)
    prog = [{"date": "2027-03-13", "starts": [{"time": "11:00", "fleets": ["OPTI"], "limits": {"OPTI": {"max_gust_kn": 14}}}]}]
    out = B.club_briefings(D, prog, FLEETS, "UTC")
    assert out[0]["call"]["call"] == "blown_out"


def test_right_shift_with_odds_and_side():
    dirs = [215] * 7 + [222, 228, 232, 232, 232]                   # 7 deg at 13:00, 13 deg by 14:00
    b = B.briefing(fc([12] * 12, dirs=dirs), GUN, FLEETS["ILCA6"], hours=3)
    s = b["shift"]
    assert s["kind"] == "shift" and s["side"] == "right" and s["p"] == 1.0
    assert s["at"] == "2027-03-13T14:00Z" and "port tack early" in s["advice"]


def test_left_shift_split_models():
    base = [220] * 12
    back = [220] * 7 + [205, 200, 200, 200, 200]
    b = B.briefing(fc([12] * 12, dirs={"ifs": back, "icon": back, "arpege": base}), GUN, FLEETS["ILCA6"], hours=3)
    s = b["shift"]
    assert s["kind"] == "shift" and s["side"] == "left" and s["p"] == pytest.approx(0.67, abs=0.01)
    assert "starboard tack early" in s["advice"]


def test_steady_direction():
    b = B.briefing(fc([12] * 12, dirs=[220, 222, 218, 221, 223, 219, 220, 222, 221, 219, 220, 221]), GUN, FLEETS["ILCA6"])
    assert b["shift"]["kind"] == "steady" and b["shift"]["p"] == 1.0


def test_sensor_nudges_near_term_and_fades():
    D = fc([10] * 12)
    now = pd.Timestamp("2027-03-13 10:50", tz="UTC")
    b = B.briefing(D, GUN, FLEETS["ILCA6"], sensor={"time": "2027-03-13T10:45Z", "wind_kn": 14, "dir": 230}, now=now)
    assert b["sensor_used"] and b["call"]["wind_kn"] > 13
    hr = {h["time"]: h for h in b["hourly"]}
    assert hr["2027-03-13T11:00Z"]["wind_kn"] > hr["2027-03-13T13:00Z"]["wind_kn"] > 10.5
    stale = B.briefing(D, GUN, FLEETS["ILCA6"], sensor={"time": "2027-03-13T08:00Z", "wind_kn": 14, "dir": 230}, now=now)
    assert not stale["sensor_used"] and stale["call"]["wind_kn"] == pytest.approx(10, abs=0.01)


def test_sensor_narrows_the_odds():
    D = fc([5] * 12, [7] * 12)
    now = pd.Timestamp("2027-03-13 10:55", tz="UTC")
    plain = B.briefing(D, GUN, FLEETS["ILCA6"])["call"]["p_race"]
    sensed = B.briefing(D, GUN, FLEETS["ILCA6"], sensor={"time": "2027-03-13T10:55Z", "wind_kn": 5, "dir": 220}, now=now)["call"]["p_race"]
    assert sensed > plain


def test_water_tide_turns_and_wind_against_tide():
    n = 30; t = np.arange(n)
    level = 2.0 * np.cos(2 * np.pi * (t - 2) / 12.42)                       # high water near 08:00
    D = fc([14] * n, chop_m=[0.35] * n, chop_period_s=[2.4] * n, current_kn=[0.8] * n, current_dir=[215] * n,
           sea_level_height_msl=level, start="2027-03-13 06:00")
    w = B.briefing(D, GUN, FLEETS["420"])["water"]
    assert w["stream"]["wind_against_tide"] is True
    kinds = [x["kind"] for x in w["tide"]]
    assert kinds[:2] == ["high", "low"] and w["tide"][0]["time"].startswith("2027-03-13T08")
    assert w["chop"]["label"] == "moderate chop"


def test_rig_trapeze_note():
    b = B.briefing(fc([16] * 12), GUN, FLEETS["420"])
    assert b["rig"]["band"] == "heavy" and "wire" in b["rig"]["tip"]


@pytest.mark.parametrize("country,lat,lon,tz", [("UK", 50.8, -1, "Europe/London"), ("AU", -33.85, 151.2, "Australia/Sydney"),
                                                  ("AU", -31.95, 115.8, "Australia/Perth"), ("AU", -27.4, 153.1, "Australia/Brisbane"),
                                                  ("AU", -34.9, 138.5, "Australia/Adelaide"), ("AU", -42.9, 147.3, "Australia/Hobart")])
def test_club_tz(country, lat, lon, tz):
    assert B.club_tz(country, lat, lon) == tz


def test_programme_local_time():
    D = fc([12] * 12)
    prog = [{"date": "2027-03-13", "starts": [{"time": "11:00", "fleets": ["ILCA6", "UNKNOWN"]}]}]
    out = B.club_briefings(D, prog, FLEETS, "Europe/London")
    assert [o["fleet"] for o in out] == ["ILCA6", "GENERIC"] and out[0]["gun"] == "2027-03-13T11:00Z"
