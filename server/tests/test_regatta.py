import datetime as dt
import pandas as pd
from server.tests.test_api import client, signup, club  # noqa: F401


def setup(client, tier="pro"):
    club(client, tier=tier); ho = signup(client, "ro@x.com"); club(client, tier=tier, admin_email="ro@x.com"); return ho


def ev(today, name="Spring Open", days=(0, 2)):
    return {"name": name, "first_day": str(today + dt.timedelta(days=days[0])), "last_day": str(today + dt.timedelta(days=days[1])),
            "classes": ["ILCA6", "OPTI"], "entries": 64}


def test_regatta_pages_only_on_pro(client):
    ho = setup(client, "plus"); today = pd.Timestamp.now(tz="Europe/London").date()
    assert client.post("/clubs/hayling/events", json=ev(today), headers=ho).status_code == 402


def test_four_events_a_year(client):
    ho = setup(client); d = dt.date(2031, 3, 1)
    for i in range(4): assert client.post("/clubs/hayling/events", json=ev(d + dt.timedelta(days=30 * i), f"Open {i}"), headers=ho).status_code == 200
    assert client.post("/clubs/hayling/events", json=ev(dt.date(2031, 9, 1), "Late"), headers=ho).status_code == 402
    assert client.post("/clubs/hayling/events", json=ev(dt.date(2032, 3, 1), "Next year"), headers=ho).status_code == 200


def test_event_page_shows_calls_tide_and_notices(client, monkeypatch):
    ho = setup(client); today = pd.Timestamp.now(tz="Europe/London").date()
    r = client.post("/clubs/hayling/events", json=ev(today), headers=ho).json()
    eid = client.get(f"/events/{r['slug']}").json()
    assert len(eid["days"]) == 3 and len(eid["days"][0]["races"]) == 2 and eid["days"][0]["starts"][0]["time"] == "11:00"
    from server import push
    monkeypatch.setitem(push.SENDER, "fn", lambda *a: 0)
    n = client.post("/clubs/hayling/notices", json={"text": "Course 2 today, first gun 11:00.", "event_id": 1}, headers=ho)
    assert n.status_code == 200
    page = client.get(r["url"]).text
    assert "Spring Open" in page and "Course 2 today" in page and "64 entries" in page and "ON</span>" in page and 'id="qr"' in page
    assert client.get("/r/nope").status_code == 404
    assert client.get("/clubs/hayling/events").json()[0]["slug"] == r["slug"]
