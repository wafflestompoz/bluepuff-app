import datetime as dt, importlib
import pandas as pd, pytest
from fastapi.testclient import TestClient
from engine.tests.test_briefing import fc


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("FORECAST_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_TOKEN", "staff")
    start = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)
    D = fc([12] * 24 * 10, start=str(start.tz_localize(None)))
    D.index.name = "time"; D.to_csv(tmp_path / "hayling.csv")
    from server import app as A
    importlib.reload(A)
    return TestClient(A.app)


def signup(c, email, pw="sailfast1"):
    r = c.post("/auth/signup", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def club(c, slug="hayling", tier="club", **kw):
    r = c.post("/admin/clubs", json={"slug": slug, "tier": tier, **kw}, headers={"X-Admin-Token": "staff"})
    assert r.status_code == 200, r.text
    return r.json()


def test_signup_login_logout(client):
    h = signup(client, "a@x.com")
    assert client.get("/me", headers=h).json()["plan"] == "free"
    assert client.post("/auth/signup", json={"email": "A@x.com", "password": "sailfast1"}).status_code == 409
    assert client.post("/auth/login", json={"email": "a@x.com", "password": "wrongpass"}).status_code == 401
    t = client.post("/auth/login", json={"email": "a@x.com", "password": "sailfast1"}).json()["token"]
    client.post("/auth/logout", headers={"Authorization": f"Bearer {t}"})
    assert client.get("/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401


def test_admin_needs_token(client):
    assert client.post("/admin/clubs", json={"slug": "hayling"}).status_code == 403
    c = club(client)
    assert c["name"] == "Hayling Island SC" and c["tz"] == "Europe/London" and len(c["code"]) == 6


def test_join_by_code_gives_racer_via_licence(client):
    code = club(client)["code"]; h = signup(client, "a@x.com")
    me = client.post("/me/clubs", json={"code": code.lower(), "fleet": "ILCA6"}, headers=h).json()
    assert me["plan"] == "racer" and me["clubs"][0]["home"] and "Hayling" in me["plan_via"]


def test_unlicensed_club_leaves_free_and_one_club_limit(client):
    club(client, tier="none"); club(client, slug="cowes", tier="none")
    h = signup(client, "a@x.com")
    assert client.post("/me/clubs", json={"slug": "hayling"}, headers=h).json()["plan"] == "free"
    assert client.post("/me/clubs", json={"slug": "cowes"}, headers=h).status_code == 402


def test_expired_licence_is_not_licensed(client):
    code = club(client, licence_until=str(dt.date.today() - dt.timedelta(days=1)))["code"]
    h = signup(client, "a@x.com")
    assert client.post("/me/clubs", json={"code": code}, headers=h).json()["plan"] == "free"


def test_member_cap(client, monkeypatch):
    from server import app as A
    monkeypatch.setitem(A.TIERS["club"], "cap", 2)
    code = club(client)["code"]
    for i in range(2): assert client.post("/me/clubs", json={"code": code}, headers=signup(client, f"s{i}@x.com")).status_code == 200
    r = client.post("/me/clubs", json={"code": code}, headers=signup(client, "late@x.com"))
    assert r.status_code == 409 and "full" in r.json()["detail"]


def test_racer_three_clubs(client):
    code = club(client)["code"]
    for s in ("cowes", "c3", "c4"): club(client, slug=s, name=s.upper())
    h = signup(client, "a@x.com")
    client.post("/me/clubs", json={"code": code}, headers=h)
    assert client.post("/me/clubs", json={"slug": "cowes"}, headers=h).status_code == 200
    assert client.post("/me/clubs", json={"slug": "c3"}, headers=h).status_code == 200
    assert client.post("/me/clubs", json={"slug": "c4"}, headers=h).status_code == 402


def test_officer_limits_starts_and_briefings(client):
    code = club(client, admin_email=None)["code"]
    ho = signup(client, "ro@x.com"); club(client, admin_email="ro@x.com")
    hs = signup(client, "s@x.com"); client.post("/me/clubs", json={"code": code, "fleet": "OPTI"}, headers=hs)
    # members can't set the programme
    assert client.post("/clubs/hayling/starts", json={"date": "2027-01-01", "time": "11:00", "fleets": ["OPTI"]}, headers=hs).status_code == 403
    r = client.put("/clubs/hayling/fleets/OPTI", json={"label": "Juniors", "max_gust_kn": 14}, headers=ho)
    assert r.status_code == 200 and r.json()[0]["max_gust_kn"] == 14
    today = pd.Timestamp.now(tz="Europe/London").date()
    for d in range(4):
        r = client.post("/clubs/hayling/starts", json={"date": str(today + dt.timedelta(days=d)), "time": "11:00", "fleets": ["OPTI", "ILCA6"]}, headers=ho)
        assert r.status_code == 200
    paid = client.get("/clubs/hayling/briefings", headers=hs).json()
    assert paid["plan"] == "racer" and len(paid["briefings"]) == 8
    juniors = [b for b in paid["briefings"] if b["fleet"] == "OPTI"][0]
    assert juniors["fleet_name"] == "Juniors" and "rig" in juniors
    assert juniors["call"]["p_race"] < [b for b in paid["briefings"] if b["fleet"] == "ILCA6"][0]["call"]["p_race"]
    # a free follower gets two days of headlines only
    club(client, tier="none"); hf = signup(client, "f@x.com")
    client.post("/me/clubs", json={"slug": "hayling"}, headers=hf)
    free = client.get("/clubs/hayling/briefings", headers=hf).json()
    assert free["plan"] == "free" and len(free["briefings"]) == 4 and "rig" not in free["briefings"][0]


def test_coach_seats_only_on_pro(client):
    code = club(client)["code"]; ha = signup(client, "admin@x.com"); club(client, admin_email="admin@x.com")
    signup(client, "coach@x.com")
    assert client.put("/clubs/hayling/roles", json={"email": "coach@x.com", "role": "coach"}, headers=ha).status_code == 402
    club(client, tier="pro")
    assert client.put("/clubs/hayling/roles", json={"email": "coach@x.com", "role": "coach"}, headers=ha).status_code == 200
    hc = {"Authorization": "Bearer " + client.post("/auth/login", json={"email": "coach@x.com", "password": "sailfast1"}).json()["token"]}
    assert client.get("/me", headers=hc).json()["plan"] == "racer_pro"


def test_venue_map_and_tip_in_briefings(client):
    code = club(client)["code"]
    v = client.get("/clubs/hayling/venue").json()
    assert len(v["sectors"]) == 16 and len(v["grids"]) == 16 and len(v["grids"][0]) == v["n"] ** 2
    ho = signup(client, "ro@x.com"); club(client, admin_email="ro@x.com")
    today = pd.Timestamp.now(tz="Europe/London").date()
    client.post("/clubs/hayling/starts", json={"date": str(today + dt.timedelta(days=1)), "time": "11:00", "fleets": ["ILCA6"]}, headers=ho)
    b = client.get("/clubs/hayling/briefings", headers=ho).json()["briefings"][0]
    assert b["venue"]["compass"] == "SW" and b["venue"]["notes"]
