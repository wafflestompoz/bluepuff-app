import datetime as dt
import pandas as pd
from server.tests.test_api import client, signup, club  # noqa: F401 (fixture)


def uplink(eui, payload, when=None):
    when = when or dt.datetime.now(dt.timezone.utc)
    return {"end_device_ids": {"dev_eui": eui}, "received_at": when.isoformat().replace("+00:00", "Z"),
            "uplink_message": {"decoded_payload": payload}}


def test_sensors_only_on_plus_and_pro(client):
    club(client)
    r = client.post("/admin/sensors", params={"club": "hayling", "dev_eui": "a1"}, headers={"X-Admin-Token": "staff"})
    assert r.status_code == 402
    club(client, tier="plus")
    assert client.post("/admin/sensors", params={"club": "hayling", "dev_eui": "a1"}, headers={"X-Admin-Token": "staff"}).status_code == 200
    assert client.post("/admin/sensors", params={"club": "hayling", "dev_eui": "a2"}, headers={"X-Admin-Token": "staff"}).status_code == 402


def test_ttn_webhook_live_and_briefing_blend(client, monkeypatch):
    monkeypatch.setenv("TTN_WEBHOOK_SECRET", "hook")
    code = club(client, tier="plus")["code"]
    client.post("/admin/sensors", params={"club": "hayling", "dev_eui": "a1b2"}, headers={"X-Admin-Token": "staff"})
    assert client.post("/hooks/ttn", json=uplink("A1B2", {"Wind_ave10": 5}), headers={"X-Webhook-Secret": "no"}).status_code == 403
    assert client.post("/hooks/ttn", json=uplink("FFFF", {"Wind_ave10": 5}), headers={"X-Webhook-Secret": "hook"}).status_code == 404
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)
    client.post("/hooks/ttn", json=uplink("A1B2", {"Wind_ave10": 3}, old), headers={"X-Webhook-Secret": "hook"})
    r = client.post("/hooks/ttn", json=uplink("A1B2", {"Wind_ave10": 9.0, "Wind_max10": 12.0, "Dir_ave10": 240, "Battery": 3.6}),
                    headers={"X-Webhook-Secret": "hook"})
    assert r.status_code == 200
    live = client.get("/clubs/hayling/live").json()["sensors"][0]
    assert live["latest"]["wind_kn"] == 17.5 and live["latest"]["gust_kn"] == 23.3 and live["latest"]["fresh"]
    assert len(live["trace"]) == 1                                  # the 3 h old reading is outside the 2 h trace
    assert "Hayling Island SC" in client.get("/clubs/hayling/clubhouse").text
    h = signup(client, "s@x.com"); client.post("/me/clubs", json={"code": code}, headers=h)
    assert client.get("/clubs/hayling/briefings", headers=h).json()["sensor"]["wind_kn"] == 17.5


def test_send_the_call_pushes_to_members(client, monkeypatch):
    from server import push
    sent = []
    monkeypatch.setitem(push.SENDER, "fn", lambda toks, title, body, data: sent.append((toks, title, body)) or len(toks))
    code = club(client)["code"]
    ho = signup(client, "ro@x.com"); club(client, admin_email="ro@x.com")
    hs = signup(client, "s@x.com"); client.post("/me/clubs", json={"code": code}, headers=hs)
    client.post("/me/push-token", json={"token": "ExponentPushToken[abc123]"}, headers=hs)
    hx = signup(client, "outsider@x.com"); client.post("/me/push-token", json={"token": "ExponentPushToken[zzz999]"}, headers=hx)
    assert client.post("/clubs/hayling/notices", json={"text": "hi"}, headers=hs).status_code == 403
    r = client.post("/clubs/hayling/notices", json={"send_call": True}, headers=ho)
    assert r.status_code == 409                                     # no starts today yet
    today = pd.Timestamp.now(tz="Europe/London").date()
    client.post("/clubs/hayling/starts", json={"date": str(today), "time": "23:00", "fleets": ["ILCA6"]}, headers=ho)
    r = client.post("/clubs/hayling/notices", json={"text": "Briefing 10:00 in the bar.", "send_call": True}, headers=ho).json()
    assert "Racing is ON" in r["text"] and r["text"].startswith("Briefing") and r["pushed"] == 1
    assert sent[0][0] == ["ExponentPushToken[abc123]"]      # members only, not the outsider
    assert client.get("/clubs/hayling/notices").json()[0]["id"] == r["id"]
