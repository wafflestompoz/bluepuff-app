"""Payments.

Sailors (Racer, Racer Pro) buy inside the iOS and Android apps, which the stores require for digital subscriptions.
RevenueCat runs those purchases and tells us about them by webhook. Clubs buy licences on the web with Stripe Checkout
(an annual subscription on a 1 or 2-year term) and Stripe tells us by webhook.

Env: REVENUECAT_WEBHOOK_AUTH (the Authorization header value set in RevenueCat), STRIPE_SECRET_KEY,
STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_CLUB / STRIPE_PRICE_PLUS / STRIPE_PRICE_PRO (Stripe price ids), PUBLIC_URL.
"""
import hashlib, hmac, json, os, time, urllib.parse, urllib.request
import datetime as dt

# --- RevenueCat (sailor plans) ---------------------------------------------------------------------------------------

ACTIVE = {"INITIAL_PURCHASE", "RENEWAL", "PRODUCT_CHANGE", "UNCANCELLATION", "NON_RENEWING_PURCHASE", "SUBSCRIPTION_EXTENDED",
          "TEMPORARY_ENTITLEMENT_GRANT"}
ENDED = {"EXPIRATION"}
# CANCELLATION and BILLING_ISSUE leave access in place until the expiry date RevenueCat sends.


def plan_for_product(product_id: str) -> str:
    return "racer_pro" if "pro" in (product_id or "").lower() else "racer"


def revenuecat_change(event: dict):
    """(user_id, plan, plan_until) for a RevenueCat event, or None if it changes nothing."""
    kind = event.get("type")
    try: uid = int(event.get("app_user_id", ""))
    except ValueError: return None                      # anonymous ids: the app logs in with our user id first
    exp = event.get("expiration_at_ms")
    until = dt.datetime.fromtimestamp(exp / 1000, dt.timezone.utc) if exp else None
    if kind in ACTIVE: return uid, plan_for_product(event.get("new_product_id") or event.get("product_id")), until
    if kind in ENDED: return uid, "free", None
    if kind in ("CANCELLATION", "BILLING_ISSUE") and until: return uid, None, until     # keep plan, confirm end date
    return None


# --- Stripe (club licences) ------------------------------------------------------------------------------------------

def stripe_verify(payload: bytes, header: str, secret: str, tolerance=300, now=None) -> dict:
    """Check the Stripe-Signature header (HMAC-SHA256 over "t.payload") and return the event."""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    sigs = [v for k, v in (p.split("=", 1) for p in header.split(",") if "=" in p) if k == "v1"]
    t = int(parts.get("t", "0"))
    if abs((now or time.time()) - t) > tolerance: raise ValueError("Stale signature")
    want = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(want, s) for s in sigs): raise ValueError("Bad signature")
    return json.loads(payload)


def stripe_sign(payload: bytes, secret: str, t=None) -> str:      # for tests and local replays
    t = int(t or time.time())
    return f"t={t},v1={hmac.new(secret.encode(), f'{t}.'.encode() + payload, hashlib.sha256).hexdigest()}"


TERM_YEARS = {"club": 1, "plus": 2, "pro": 2}


def stripe_post(path, form):
    req = urllib.request.Request("https://api.stripe.com/v1/" + path, data=urllib.parse.urlencode(form).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['STRIPE_SECRET_KEY']}"})
    with urllib.request.urlopen(req, timeout=20) as r: return json.load(r)


STRIPE = {"post": stripe_post}      # tests swap this out


def checkout_session(club_slug, tier, admin_email, base_url):
    """A Stripe Checkout link for a club licence: billed yearly; Plus and Pro on a 2-year term."""
    price = os.environ.get(f"STRIPE_PRICE_{tier.upper()}")
    if not price: raise KeyError(f"No Stripe price set for {tier}")
    meta = {"club": club_slug, "tier": tier, "term_years": TERM_YEARS[tier]}
    form = {"mode": "subscription", "line_items[0][price]": price, "line_items[0][quantity]": 1,
            "customer_email": admin_email, "allow_promotion_codes": "true", "billing_address_collection": "required",
            "tax_id_collection[enabled]": "true",
            "success_url": f"{base_url}/clubs/{club_slug}/licence?paid=1", "cancel_url": f"{base_url}/clubs/{club_slug}/licence",
            **{f"metadata[{k}]": v for k, v in meta.items()}, **{f"subscription_data[metadata][{k}]": v for k, v in meta.items()}}
    return STRIPE["post"]("checkout/sessions", form)


def licence_change(event: dict):
    """(club_slug, tier, licence_until) from a Stripe event, or None."""
    kind = event.get("type"); obj = (event.get("data") or {}).get("object") or {}
    if kind == "checkout.session.completed":
        m = obj.get("metadata") or {}
        if obj.get("payment_status") not in ("paid", "no_payment_required") or not m.get("club"): return None
        return m["club"], m["tier"], dt.date.today() + dt.timedelta(days=365 + 14)     # until the first renewal, with grace
    if kind == "invoice.paid":
        m = ((obj.get("subscription_details") or {}).get("metadata")) or (obj.get("parent", {}).get("subscription_details", {}) or {}).get("metadata") or {}
        line = ((obj.get("lines") or {}).get("data") or [{}])[0]
        end = (line.get("period") or {}).get("end")
        if not m.get("club") or not end: return None
        return m["club"], m["tier"], dt.datetime.fromtimestamp(end, dt.timezone.utc).date() + dt.timedelta(days=14)
    return None
