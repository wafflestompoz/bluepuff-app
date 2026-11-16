import json, os
import numpy as np
from engine import briefing as B
from engine.tests.test_briefing import fc, FLEETS, GUN
from venue import venue as Vn


def sectors(**over):
    base = {"from": 0, "mean": 1.0, "left": 1.0, "right": 1.0, "top": 1.0, "bottom": 1.0, "shore_upwind_m": None,
            "shadow_m": None, "low_frac": 0.0, "water_frac": 1.0, "fetch_m": 5000, "relief_m": 0, "cross_fetch_m": 5000}
    S = [dict(base, **{"from": k * 22.5}) for k in range(16)]
    for k, v in over.items(): S[int(k)].update(v)
    return {"sectors": S}


def test_open_water():
    t = B.venue_tip(sectors(), 200)
    assert t["compass"] == "SSW" and "Open water" in t["notes"][0]


def test_side_with_more_wind_and_land_side():
    t = B.venue_tip(sectors(**{"0": {"left": 0.76, "right": 0.98}}), 5)      # wind from N, land to the W (left)
    assert "right side" in t["notes"][0] and "land to the W" in t["notes"][0]
    t = B.venue_tip(sectors(**{"12": {"left": 0.94, "right": 0.76}}), 270)   # wind from W, land to the N (right)
    assert "left side" in t["notes"][0] and "land to the N" in t["notes"][0]


def test_shadow_offshore_hills_and_channel():
    t = B.venue_tip(sectors(**{"4": {"top": 0.79, "bottom": 0.98, "shadow_m": 800, "fetch_m": 600, "relief_m": 1100}}), 90)
    text = " ".join(t["notes"])
    assert "windward mark" in text and "800 m" in text and "Offshore" in text and "High ground" in text
    t = B.venue_tip(sectors(**{"0": {"fetch_m": 4000, "cross_fetch_m": 900}}), 0)
    assert "runs along the water" in " ".join(t["notes"])


def test_briefing_carries_venue_tip_for_the_wind_at_the_gun():
    V = sectors(**{"14": {"left": 0.8, "right": 0.95}})      # NW
    b = B.briefing(fc([12] * 12, dirs=[315] * 12), GUN, FLEETS["ILCA6"], venue=V)
    assert b["venue"]["compass"] == "NW" and "right side" in b["venue"]["notes"][0]
    assert B.briefing(fc([12] * 12), GUN, FLEETS["ILCA6"])["venue"] is None


def test_shelter_profile_and_encoding():
    assert abs(Vn.shelter_factor(0) - 0.55) < 1e-6 and Vn.shelter_factor(10) < 0.2 and Vn.shelter_factor(30) < 0.02
    P = np.array([[np.nan, 1.0], [0.5, 0.82]])
    assert Vn.decode(Vn.encode(P), 2) == [[None, 100], [50, 82]]


def test_pressure_behind_a_wall_of_trees():
    """Synthetic venue: open water with a 12 m tree line along the north; a north wind is light near it and full far off."""
    G = Vn.Grid(50.0, 0.0, Vn.HALF + Vn.LOOK, Vn.CELL)
    water = G.N < 600; H = np.where(water, 0.0, 12.0).astype("float32")
    S, P = Vn.pressure(G, water, H, 0.0)
    near = P[(S.N > 450) & (S.N < 600)]; far = P[S.N < -900]
    assert np.nanmean(near) < 0.7 and np.nanmean(far) > 0.85
    S2, P2 = Vn.pressure(G, water, H, 180.0)                  # onshore: open water upwind
    assert np.nanmin(P2) > 0.95
    sm = Vn.summarise(S, P, 0.0)
    assert sm["top"] < sm["bottom"] and sm["shadow_m"] and sm["shadow_m"] >= 200
