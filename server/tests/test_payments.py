import json, time, datetime as dt
from server import payments
from server.tests.test_api import client, signup, club  # noqa: F401


def rc(client, event, auth="rc-secret"):
    return client.post("/hooks/revenuecat", json={"event": event}, headers={"Authorization": auth})


def test_revenuecat_sets_and_ends_racer_pro(client, monkeypatch):
    monkeypatch.setenv("REVENUECAT_WEBHOOK_AUTH", "rc-secret")
    h = signup(client, "a@x.com"); uid = client.get("/me", headers=h).json()["id"]
    later = int((time.time() + 30 * 86400) * 1000)
    assert rc(client, {"type": "INITIAL_PURCHASE", "app_user_id": str(uid), "product_id": "bluepuff_racer_pro_yearly", "expiration_at_ms": later}, "nope").status_code == 403
    assert rc(client, {"type": "INITIAL_PURCHASE", "app_user_id": str(uid), "product_id": "bluepuff_racer_pro_yearly", "expiration_at_ms": later}).json()["changed"]
    assert client.get("/me", headers=h).json()["plan"] == "racer_pro"
    rc(client, {"type": "CANCELLATION", "app_user_id": str(uid), "product_id": "bluepuff_racer_pro_yearly", "expiration_at_ms": later})
    assert client.get("/me", headers=h).json()["plan"] == "racer_pro"          # paid up to the end date
    past = int((time.time() - 60) * 1000)
    rc(client, {"type": "RENEWAL", "app_user_id": str(uid), "product_id": "bluepuff_racer_monthly", "expiration_at_ms": past})
    assert client.get("/me", headers=h).json()["plan"] == "free"               # lapsed
    rc(client, {"type": "EXPIRATION", "app_user_id": str(uid), "product_id": "bluepuff_racer_monthly"})
    assert client.get("/me", headers=h).json()["plan"] == "free"
    assert not rc(client, {"type": "INITIAL_PURCHASE", "app_user_id": "$RCAnonymousID:abc"}).json()["changed"]


def test_stripe_signature():
    body = b'{"type":"x"}'; sig = payments.stripe_sign(body, "whsec_1")
    assert payments.stripe_verify(body, sig, "whsec_1")["type"] == "x"
    for bad in (payments.stripe_sign(body, "other"), payments.stripe_sign(body, "whsec_1", t=time.time() - 3600)):
        try: payments.stripe_verify(body, bad, "whsec_1"); assert False
        except ValueError: pass


def test_club_checkout_and_licence_webhook(client, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_1"); monkeypatch.setenv("STRIPE_PRICE_PLUS", "price_plus")
    sent = {}
    monkeypatch.setitem(payments.STRIPE, "post", lambda path, form: sent.update(path=path, form=form) or {"url": "https://checkout.stripe.com/c/x"})
    club(client, tier="none"); ha = signup(client, "admin@x.com"); club(client, tier="none", admin_email="admin@x.com")
    hm = signup(client, "m@x.com"); client.post("/me/clubs", json={"slug": "hayling"}, headers=hm)
    assert client.post("/clubs/hayling/checkout", json={"tier": "plus"}, headers=hm).status_code == 403
    assert client.post("/clubs/hayling/checkout", json={"tier": "pro"}, headers=ha).status_code == 503      # no price set
    r = client.post("/clubs/hayling/checkout", json={"tier": "plus"}, headers=ha).json()
    assert r["url"].startswith("https://checkout.stripe.com") and sent["form"]["metadata[club]"] == "hayling"
    assert sent["form"]["subscription_data[metadata][term_years]"] == 2
    ev = {"type": "checkout.session.completed", "data": {"object": {"payment_status": "paid", "metadata": {"club": "hayling", "tier": "plus"}}}}
    body = json.dumps(ev).encode()
    assert client.post("/hooks/stripe", content=body, headers={"Stripe-Signature": "t=1,v1=00"}).status_code == 400
    assert client.post("/hooks/stripe", content=body, headers={"Stripe-Signature": payments.stripe_sign(body, "whsec_1")}).json()["changed"]
    assert client.get("/clubs/hayling").json()["tier"] == "plus" and client.get("/me", headers=hm).json()["plan"] == "free"  # follower, not home
    end = int(time.time() + 365 * 86400)
    inv = {"type": "invoice.paid", "data": {"object": {"subscription_details": {"metadata": {"club": "hayling", "tier": "plus"}},
                                                        "lines": {"data": [{"period": {"end": end}}]}}}}
    body = json.dumps(inv).encode()
    assert client.post("/hooks/stripe", content=body, headers={"Stripe-Signature": payments.stripe_sign(body, "whsec_1")}).json()["changed"]
    assert "Club Plus" in client.get("/clubs/hayling/licence?paid=1").text
