"""bluepuff API: accounts, clubs and licences, programmes and limits, briefings, notices, sensors and regatta pages.

Run: uvicorn server.app:app --reload
Env: DATABASE_URL (default sqlite:///server/bluepuff.db), FORECAST_DIR (default forecast/out), ADMIN_TOKEN (staff
     calls), CLUBS_STATIC (default forecast/clubs_static.csv).
"""
import os, re, json, html, secrets, hashlib, datetime as dt
from functools import lru_cache
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from engine import briefing as E
from server import payments, push
from server.models import (TIERS, ClubFleet, Club, Event, Membership, Notice, PushToken, Reading, Sensor, Session, Start,
                           User, make_session_factory)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = FastAPI(title="bluepuff API", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
CLASSES = E.load_classes()
MAX_CLUBS = {"free": 1, "racer": 3, "racer_pro": 3}
FREE_DAYS, PAID_DAYS = 2, 7


def settings():
    return {"db": os.environ.get("DATABASE_URL", f"sqlite:///{ROOT}/server/bluepuff.db"),
            "forecast": os.environ.get("FORECAST_DIR", f"{ROOT}/forecast/out"),
            "admin": os.environ.get("ADMIN_TOKEN", ""),
            "static": os.environ.get("CLUBS_STATIC", f"{ROOT}/forecast/clubs_static.csv")}


@lru_cache(maxsize=4)
def _factory(url):
    return make_session_factory(url)


def db():
    s = _factory(settings()["db"])()
    try: yield s
    finally: s.close()


def today_utc():
    return dt.datetime.now(dt.timezone.utc).date()


def club_today(club):
    return pd.Timestamp.now(tz=club.tz).date()


# --- accounts ----------------------------------------------------------------------------------------------------

def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    return f"scrypt${salt}${hashlib.scrypt(pw.encode(), salt=salt.encode(), n=2**14, r=8, p=1).hex()}"


def check_pw(pw, stored):
    _, salt, _h = stored.split("$"); return secrets.compare_digest(hash_pw(pw, salt), stored)


def tok_hash(t): return hashlib.sha256(t.encode()).hexdigest()


def current_user(authorization: str = Header(default=""), s=Depends(db)):
    t = authorization.removeprefix("Bearer ").strip()
    row = s.get(Session, tok_hash(t)) if t else None
    if not row: raise HTTPException(401, "Sign in first")
    return row.user


def admin(x_admin_token: str = Header(default="")):
    a = settings()["admin"]
    if not a or not secrets.compare_digest(x_admin_token, a): raise HTTPException(403, "Staff only")


class SignUp(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8)
    name: str = ""


class Login(BaseModel):
    email: str
    password: str


def new_session(s, user):
    t = secrets.token_urlsafe(32); s.add(Session(token_hash=tok_hash(t), user_id=user.id)); s.commit(); return t


@app.post("/auth/signup")
def signup(b: SignUp, s=Depends(db)):
    email = b.email.lower().strip()
    if s.scalar(select(User).where(User.email == email)): raise HTTPException(409, "That email already has an account")
    u = User(email=email, name=b.name, password_hash=hash_pw(b.password)); s.add(u); s.commit()
    return {"token": new_session(s, u), "user": me_view(s, u)}


@app.post("/auth/login")
def login(b: Login, s=Depends(db)):
    u = s.scalar(select(User).where(User.email == b.email.lower().strip()))
    if not u or not check_pw(b.password, u.password_hash): raise HTTPException(401, "Wrong email or password")
    return {"token": new_session(s, u), "user": me_view(s, u)}


@app.post("/auth/logout")
def logout(authorization: str = Header(default=""), s=Depends(db)):
    row = s.get(Session, tok_hash(authorization.removeprefix("Bearer ").strip()))
    if row: s.delete(row); s.commit()
    return {"ok": True}


# --- licences and entitlements -----------------------------------------------------------------------------------

def licensed(club):
    return club.tier in TIERS and club.tier != "none" and (club.licence_until is None or club.licence_until >= today_utc())


def entitlement(s, u):
    """free | racer | racer_pro, and where it comes from."""
    if u.plan in ("racer", "racer_pro") and (u.plan_until is None or _utc(u.plan_until) >= dt.datetime.now(dt.timezone.utc)):
        own = u.plan
    else: own = "free"
    via = None
    for m in u.memberships:
        if m.role == "coach" and m.club.tier == "pro" and licensed(m.club): return "racer_pro", f"coach at {m.club.name}"
        if m.home and licensed(m.club): via = f"club licence: {m.club.name}"
    if own != "free": return own, "own subscription"
    return ("racer", via) if via else ("free", None)


def members_count(s, club):
    return s.scalar(select(func.count()).select_from(Membership).where(Membership.club_id == club.id, Membership.home.is_(True),
                                                                      Membership.role != "coach"))


def me_view(s, u):
    plan, via = entitlement(s, u)
    return {"id": u.id, "email": u.email, "name": u.name, "plan": plan, "plan_via": via,
            "clubs": [{"slug": m.club.slug, "name": m.club.name, "role": m.role, "home": m.home, "fleet": m.fleet} for m in u.memberships]}


@app.get("/me")
def me(u=Depends(current_user), s=Depends(db)):
    return me_view(s, u)


class Join(BaseModel):
    code: str | None = None          # a club code (home club, covered by its licence)
    slug: str | None = None          # or a travel venue by its id
    fleet: str | None = None


@app.post("/me/clubs")
def join_club(b: Join, u=Depends(current_user), s=Depends(db)):
    if b.code:
        club = s.scalar(select(Club).where(Club.code == b.code.strip().upper()))
        if not club: raise HTTPException(404, "No club has that code")
    elif b.slug:
        club = s.scalar(select(Club).where(Club.slug == b.slug))
        if not club: raise HTTPException(404, "No such club")
    else: raise HTTPException(422, "Give a club code or a club id")
    if any(m.club_id == club.id for m in u.memberships): raise HTTPException(409, "Already following this club")
    plan, _ = entitlement(s, u)
    home = bool(b.code) and not any(m.home for m in u.memberships)
    limit = MAX_CLUBS["racer"] if (home and licensed(club)) else MAX_CLUBS[plan]
    if len(u.memberships) >= limit:
        raise HTTPException(402, "Free accounts follow one club; Racer covers three" if plan == "free" else "Racer covers three clubs")
    if home and licensed(club) and members_count(s, club) >= TIERS[club.tier]["cap"]:
        raise HTTPException(409, f"{club.name}'s licence is full ({TIERS[club.tier]['cap']} sailors). Ask the club to upgrade.")
    if b.fleet and b.fleet not in CLASSES: raise HTTPException(422, "Unknown class")
    s.add(Membership(user_id=u.id, club_id=club.id, home=home, fleet=b.fleet)); s.commit(); s.refresh(u)
    return me_view(s, u)


@app.patch("/me/clubs/{slug}")
def set_fleet(slug: str, b: Join, u=Depends(current_user), s=Depends(db)):
    m = membership(u, slug)
    if b.fleet and b.fleet not in CLASSES: raise HTTPException(422, "Unknown class")
    m.fleet = b.fleet; s.commit(); return me_view(s, u)


@app.delete("/me/clubs/{slug}")
def leave_club(slug: str, u=Depends(current_user), s=Depends(db)):
    m = membership(u, slug); s.delete(m); s.commit(); s.refresh(u); return me_view(s, u)


def membership(u, slug, roles=None):
    m = next((m for m in u.memberships if m.club.slug == slug), None)
    if not m: raise HTTPException(404, "You don't follow this club")
    if roles and m.role not in roles: raise HTTPException(403, "Race officers only")
    return m


# --- clubs (public) ----------------------------------------------------------------------------------------------

def club_or_404(s, slug):
    c = s.scalar(select(Club).where(Club.slug == slug))
    if not c: raise HTTPException(404, "No such club")
    return c


@app.get("/clubs")
def list_clubs(q: str = "", s=Depends(db)):
    rows = s.scalars(select(Club).where(Club.name.ilike(f"%{q}%")).order_by(Club.name).limit(50)).all()
    return [{"slug": c.slug, "name": c.name, "country": c.country} for c in rows]


@app.get("/clubs/{slug}")
def club_view(slug: str, s=Depends(db)):
    c = club_or_404(s, slug)
    return {"slug": c.slug, "name": c.name, "country": c.country, "tz": c.tz, "licensed": licensed(c), "tier": c.tier,
            "fleets": fleets_view(c), "starts": starts_view(s, c, today_utc(), 14)}


def fleets_view(c):
    own = {f.cls: f for f in c.fleets}
    return [{"cls": k, "name": (own[k].label if k in own and own[k].label else v.name),
             "min_kn": own[k].min_kn if k in own and own[k].min_kn is not None else v.min_kn,
             "max_gust_kn": own[k].max_gust_kn if k in own and own[k].max_gust_kn is not None else v.max_gust_kn,
             "club_limit": k in own and (own[k].min_kn is not None or own[k].max_gust_kn is not None)} for k, v in CLASSES.items() if k in own or not own]


def starts_view(s, c, d0, days):
    rows = s.scalars(select(Start).where(Start.club_id == c.id, Start.date >= d0, Start.date < d0 + dt.timedelta(days=days))
                     .order_by(Start.date, Start.time)).all()
    return [{"id": r.id, "date": r.date.isoformat(), "time": r.time, "fleets": r.fleets.split(","), "window_h": r.window_h,
             "event_id": r.event_id} for r in rows]


# --- officers: fleets, limits, programme, notices ----------------------------------------------------------------

OFFICERS = ("officer", "admin")


class FleetLimit(BaseModel):
    label: str | None = None
    min_kn: float | None = Field(default=None, ge=0, le=40)
    max_gust_kn: float | None = Field(default=None, ge=0, le=60)


@app.put("/clubs/{slug}/fleets/{cls}")
def put_fleet(slug: str, cls: str, b: FleetLimit, u=Depends(current_user), s=Depends(db)):
    m = membership(u, slug, OFFICERS)
    if cls not in CLASSES: raise HTTPException(422, "Unknown class")
    f = next((f for f in m.club.fleets if f.cls == cls), None) or ClubFleet(club_id=m.club_id, cls=cls)
    f.label, f.min_kn, f.max_gust_kn = b.label, b.min_kn, b.max_gust_kn; s.add(f); s.commit(); s.refresh(m.club)
    return fleets_view(m.club)


class StartIn(BaseModel):
    date: dt.date
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    fleets: list[str]
    window_h: float = Field(default=2.5, gt=0, le=8)
    event_id: int | None = None


@app.post("/clubs/{slug}/starts")
def add_start(slug: str, b: StartIn, u=Depends(current_user), s=Depends(db)):
    m = membership(u, slug, OFFICERS)
    bad = [f for f in b.fleets if f not in CLASSES]
    if bad or not b.fleets: raise HTTPException(422, f"Unknown class: {', '.join(bad)}" if bad else "Name at least one fleet")
    r = Start(club_id=m.club_id, date=b.date, time=b.time, fleets=",".join(b.fleets), window_h=b.window_h, event_id=b.event_id)
    s.add(r); s.commit(); return {"id": r.id}


@app.delete("/clubs/{slug}/starts/{sid}")
def del_start(slug: str, sid: int, u=Depends(current_user), s=Depends(db)):
    m = membership(u, slug, OFFICERS); r = s.get(Start, sid)
    if not r or r.club_id != m.club_id: raise HTTPException(404, "No such start")
    s.delete(r); s.commit(); return {"ok": True}


class Role(BaseModel):
    email: str
    role: str


@app.put("/clubs/{slug}/roles")
def set_role(slug: str, b: Role, u=Depends(current_user), s=Depends(db)):
    """Club admins name officers and coaches. Coach seats (Racer Pro) come with Club Pro, up to 5."""
    m = membership(u, slug, ("admin",))
    if b.role not in ("member", "officer", "admin", "coach"): raise HTTPException(422, "Unknown role")
    target = s.scalar(select(User).where(User.email == b.email.lower()))
    if not target: raise HTTPException(404, "They need a bluepuff account first")
    tm = next((x for x in target.memberships if x.club_id == m.club_id), None)
    if b.role == "coach":
        seats = TIERS[m.club.tier]["coaches"]
        used = s.scalar(select(func.count()).select_from(Membership).where(Membership.club_id == m.club_id, Membership.role == "coach"))
        if not (tm and tm.role == "coach") and used >= seats:
            raise HTTPException(402, "Coach seats come with Club Pro (5 seats)" if seats == 0 else f"All {seats} coach seats are taken")
    if not tm:
        tm = Membership(user_id=target.id, club_id=m.club_id, home=False); s.add(tm)
    tm.role = b.role; s.commit(); return {"email": target.email, "role": tm.role}


# --- briefings ---------------------------------------------------------------------------------------------------

def forecast_for(slug):
    f = os.path.join(settings()["forecast"], f"{slug}.csv")
    if not os.path.exists(f): return None
    return _load_forecast(f, os.path.getmtime(f))


@lru_cache(maxsize=256)
def _load_forecast(path, mtime):
    return E.load_forecast(path)


def latest_reading(s, club):
    r = s.execute(select(Reading).join(Sensor, Reading.sensor_id == Sensor.id).where(Sensor.club_id == club.id)
                  .order_by(Reading.time.desc()).limit(1)).scalar()
    if not r: return None
    t = r.time if r.time.tzinfo else r.time.replace(tzinfo=dt.timezone.utc)
    return {"time": t.isoformat(), "wind_kn": r.wind_kn, "gust_kn": r.gust_kn, "dir": r.dir}


def programme_for(s, club, d0, days, start_ids=None):
    limits = {f.cls: {k: v for k, v in (("min_kn", f.min_kn), ("max_gust_kn", f.max_gust_kn)) if v is not None} for f in club.fleets}
    prog = {}
    for st in starts_view(s, club, d0, days):
        if start_ids is not None and st["id"] not in start_ids: continue
        prog.setdefault(st["date"], []).append({"time": st["time"], "fleets": st["fleets"], "window_h": st["window_h"],
                                                "limits": {f: limits[f] for f in st["fleets"] if limits.get(f)}, "id": st["id"]})
    return [{"date": d, "starts": v} for d, v in sorted(prog.items())]


def club_briefings(s, club, d0, days, start_ids=None):
    D = forecast_for(club.slug)
    if D is None: return None, None
    sensor = latest_reading(s, club)
    out = E.club_briefings(D, programme_for(s, club, d0, days, start_ids), CLASSES, club.tz, sensor)
    names = {f["cls"]: f["name"] for f in fleets_view(club)}
    for b in out: b["fleet_name"] = names.get(b["fleet"], b["fleet_name"])
    return out, sensor


HEADLINE = ("date", "start", "fleet", "fleet_name", "gun")


@app.get("/clubs/{slug}/briefings")
def briefings(slug: str, days: int = Query(PAID_DAYS, ge=1, le=PAID_DAYS), u=Depends(current_user), s=Depends(db)):
    """Briefings for the club's programme. Free accounts: home club only, today and tomorrow, the call and wind only."""
    club = club_or_404(s, slug); plan, _ = entitlement(s, u)
    follows = any(m.club_id == club.id for m in u.memberships)
    if plan != "racer_pro" and not follows: raise HTTPException(402, "Follow this club first (Racer covers three clubs)")
    if plan == "free": days = min(days, FREE_DAYS)
    out, sensor = club_briefings(s, club, club_today(club), days)
    if out is None: raise HTTPException(503, "No forecast for this club yet")
    if plan == "free":
        out = [{**{k: b[k] for k in HEADLINE}, "call": {k: b["call"][k] for k in ("call", "p_race", "wind_kn", "dir")}} for b in out]
    return {"club": club.slug, "plan": plan, "sensor": sensor if plan != "free" else None, "briefings": out}


# --- admin (bluepuff staff) --------------------------------------------------------------------------------------

class ClubIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9_-]+$")
    name: str | None = None
    tier: str = "none"
    licence_until: dt.date | None = None
    admin_email: str | None = None


def new_code(s):
    while True:
        c = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        if not s.scalar(select(Club).where(Club.code == c)): return c


@app.post("/admin/clubs", dependencies=[Depends(admin)])
def admin_club(b: ClubIn, s=Depends(db)):
    if b.tier not in TIERS: raise HTTPException(422, "Unknown tier")
    st = pd.read_csv(settings()["static"]).set_index("club")
    c = s.scalar(select(Club).where(Club.slug == b.slug))
    if not c:
        if b.slug not in st.index and not b.name: raise HTTPException(404, "Not a forecast club; give a name to add it anyway")
        r = st.loc[b.slug] if b.slug in st.index else None
        c = Club(slug=b.slug, name=b.name or r["name"], country=(r.country if r is not None else ""), code=new_code(s),
                 tz=E.club_tz(r.country, r.water_lat, r.water_lon) if r is not None else "UTC")
        s.add(c)
    c.tier, c.licence_until = b.tier, b.licence_until
    if b.name: c.name = b.name
    s.commit()
    if b.admin_email:
        u = s.scalar(select(User).where(User.email == b.admin_email.lower()))
        if u:
            m = next((m for m in u.memberships if m.club_id == c.id), None) or Membership(user_id=u.id, club_id=c.id, home=True)
            m.role = "admin"; s.add(m); s.commit()
    return {"slug": c.slug, "name": c.name, "code": c.code, "tier": c.tier, "tz": c.tz,
            "licence_until": c.licence_until.isoformat() if c.licence_until else None, "members": members_count(s, c)}


# --- club sensors: The Things Network webhook, live wind, clubhouse screen ----------------------------------------
#
# bluepuff ships each club a Barani MeteoWind IoT Pro (LoRaWAN); the club mounts it. The Things Network decodes the
# uplink with the vendor's codec from the LoRaWAN device repository and posts it here. Field names differ between
# codec versions, so we accept the common spellings. Speeds are m/s unless the key ends in _kn.

MS_TO_KN = 1.943844
WIND_KEYS = ("wind_kn", "Wind_ave10", "wind_ave10", "wind_avg", "wind_speed", "speed_avg", "wind_ms")
GUST_KEYS = ("gust_kn", "Wind_max10", "wind_max10", "wind_max", "gust", "gust_ms")
DIR_KEYS = ("dir", "Dir_ave10", "dir_ave10", "wind_dir", "direction")
BATT_KEYS = ("battery_v", "Battery", "battery")
STALE_MIN = 45                      # matches engine/briefing.py: older readings are ignored


def pick(d, keys, speed=False):
    for k in keys:
        if d.get(k) is not None:
            v = float(d[k]); return v if (not speed or k.endswith("_kn")) else round(v * MS_TO_KN, 1)
    return None


def ttn_secret(x_webhook_secret: str = Header(default="")):
    want = os.environ.get("TTN_WEBHOOK_SECRET", "")
    if not want or not secrets.compare_digest(x_webhook_secret, want): raise HTTPException(403, "Bad webhook secret")


@app.post("/hooks/ttn", dependencies=[Depends(ttn_secret)])
def ttn_uplink(body: dict, s=Depends(db)):
    eui = (body.get("end_device_ids") or {}).get("dev_eui", "").upper()
    sensor = s.scalar(select(Sensor).where(Sensor.dev_eui == eui))
    if not sensor: raise HTTPException(404, "Unknown sensor")
    up = body.get("uplink_message") or {}
    d = up.get("decoded_payload") or {}
    t = pd.Timestamp(body.get("received_at") or up.get("received_at") or dt.datetime.now(dt.timezone.utc)).tz_convert("UTC")
    r = Reading(sensor_id=sensor.id, time=t.to_pydatetime(), wind_kn=pick(d, WIND_KEYS, True), gust_kn=pick(d, GUST_KEYS, True),
                dir=pick(d, DIR_KEYS), battery_v=pick(d, BATT_KEYS))
    if r.wind_kn is None: raise HTTPException(422, "No wind speed in the decoded payload")
    s.add(r); s.commit(); return {"ok": True}


def _utc(t): return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


@app.get("/clubs/{slug}/live")
def live(slug: str, hours: float = Query(2, gt=0, le=24), s=Depends(db)):
    """Each club sensor's latest reading and the recent trace. Public, so the clubhouse screen needs no sign-in."""
    club = club_or_404(s, slug); now = dt.datetime.now(dt.timezone.utc); out = []
    for sn in s.scalars(select(Sensor).where(Sensor.club_id == club.id)).all():
        rows = s.scalars(select(Reading).where(Reading.sensor_id == sn.id, Reading.time >= now - dt.timedelta(hours=hours))
                         .order_by(Reading.time)).all()
        last = rows[-1] if rows else None
        out.append({"label": sn.label, "model": sn.model,
                    "latest": None if not last else {"time": _utc(last.time).isoformat(), "wind_kn": last.wind_kn, "gust_kn": last.gust_kn,
                                                     "dir": last.dir, "battery_v": last.battery_v,
                                                     "age_min": round((now - _utc(last.time)).total_seconds() / 60, 1),
                                                     "fresh": (now - _utc(last.time)) <= dt.timedelta(minutes=STALE_MIN)},
                    "trace": [{"time": _utc(r.time).isoformat(), "wind_kn": r.wind_kn, "gust_kn": r.gust_kn, "dir": r.dir} for r in rows]})
    return {"club": club.slug, "name": club.name, "sensors": out}


@app.post("/admin/sensors", dependencies=[Depends(admin)])
def admin_sensor(club: str, dev_eui: str, label: str = "Club sensor", model: str = "barani-meteowind-iot-pro",
                 shipped: dt.date | None = None, s=Depends(db)):
    c = club_or_404(s, club); have = s.scalar(select(func.count()).select_from(Sensor).where(Sensor.club_id == c.id))
    if have >= TIERS[c.tier]["sensors"]:
        raise HTTPException(402, f"{TIERS[c.tier]['sensors']} sensor(s) on this licence" if TIERS[c.tier]["sensors"] else "Sensors come with Club Plus and Club Pro")
    sn = Sensor(club_id=c.id, dev_eui=dev_eui.upper(), label=label, model=model, shipped=shipped); s.add(sn); s.commit()
    return {"id": sn.id, "dev_eui": sn.dev_eui, "club": c.slug}


CLUBHOUSE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} live wind</title><style>
:root{{--bg:#06204a;--fg:#fff;--muted:#9fb6d9;--accent:#4fb3ff}}body{{margin:0;background:var(--bg);color:var(--fg);font:16px system-ui,sans-serif}}
main{{max-width:1100px;margin:auto;padding:24px}}h1{{font-weight:600;margin:0 0 4px}}.muted{{color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-top:20px}}
.card{{background:#0b2d63;border-radius:14px;padding:20px}}.big{{font-size:72px;font-weight:700;line-height:1}}.unit{{font-size:24px;color:var(--muted)}}
.arrow{{display:inline-block;font-size:48px;transition:transform .5s}}svg{{width:100%;height:120px}}</style></head><body><main>
<h1>{name}</h1><div class="muted">Live wind from the club sensor. Updates every minute. <span id="age"></span></div>
<div class="grid" id="cards"></div></main><script>
const slug={slug!r};
function spark(tr){{if(tr.length<2)return"";const w=600,h=120,max=Math.max(...tr.map(r=>r.gust_kn||r.wind_kn))*1.1||1,
x=i=>i/(tr.length-1)*w,y=v=>h-v/max*h,line=k=>tr.map((r,i)=>(i?"L":"M")+x(i).toFixed(1)+","+y(r[k]||0).toFixed(1)).join("");
return `<svg viewBox="0 0 ${{w}} ${{h}}" preserveAspectRatio="none"><path d="${{line("gust_kn")}}" stroke="#9fb6d9" fill="none" stroke-dasharray="4 4"/><path d="${{line("wind_kn")}}" stroke="#4fb3ff" stroke-width="3" fill="none"/></svg>`}}
async function load(){{const r=await fetch(`../../clubs/${{slug}}/live?hours=2`).then(r=>r.json());
document.getElementById("cards").innerHTML=r.sensors.map(s=>{{const l=s.latest;if(!l)return`<div class="card"><b>${{s.label}}</b><p class="muted">No readings yet</p></div>`;
return`<div class="card"><b>${{s.label}}</b>${{l.fresh?"":' <span class="muted">(last reading '+Math.round(l.age_min)+' min ago)</span>'}}
<div><span class="big">${{Math.round(l.wind_kn)}}</span><span class="unit"> kn</span> <span class="unit">gust ${{Math.round(l.gust_kn??l.wind_kn)}}</span></div>
<div><span class="arrow" style="transform:rotate(${{(l.dir??0)+180}}deg)">&uarr;</span> <span class="unit">${{l.dir==null?"":Math.round(l.dir)+"&deg;"}}</span></div>${{spark(s.trace)}}</div>`}}).join("");
document.getElementById("age").textContent="Checked "+new Date().toLocaleTimeString()}}
load();setInterval(load,60000);</script></body></html>"""


@app.get("/clubs/{slug}/clubhouse", response_class=HTMLResponse)
def clubhouse(slug: str, s=Depends(db)):
    c = club_or_404(s, slug)
    return CLUBHOUSE.format(name=html.escape(c.name), slug=c.slug)


# --- notices and "send the call" -----------------------------------------------------------------------------------

class PushIn(BaseModel):
    token: str = Field(min_length=10)


@app.post("/me/push-token")
def add_push_token(b: PushIn, u=Depends(current_user), s=Depends(db)):
    row = s.get(PushToken, b.token) or PushToken(token=b.token)
    row.user_id = u.id; s.add(row); s.commit(); return {"ok": True}


class NoticeIn(BaseModel):
    text: str | None = Field(default=None, max_length=1000)
    send_call: bool = False           # write the text from today's race call
    start_id: int | None = None       # which start the call is for (default: today's starts)
    event_id: int | None = None
    push: bool = True


CALL_WORDS = {"race_on": "Racing is ON", "marginal": "Racing is MARGINAL, decision on the water", "too_light": "Too light: likely postponement",
              "blown_out": "Too windy: racing likely abandoned"}


def call_text(club, briefs):
    lines = []
    for b in briefs:
        c = b["call"]
        lines.append(f"{b['start']} {b['fleet_name']}: {CALL_WORDS.get(c['call'], c['call'])} "
                     f"({round(c['wind_kn'])} kn, gusts {round(c['gust_max_kn'])}, {round(100 * c['p_race'])}% chance of racing)")
    return f"{club.name} race call\n" + "\n".join(lines)


@app.post("/clubs/{slug}/notices")
def post_notice(slug: str, b: NoticeIn, u=Depends(current_user), s=Depends(db)):
    m = membership(u, slug, OFFICERS); club = m.club
    if b.event_id is not None:
        ev = s.get(Event, b.event_id)
        if not ev or ev.club_id != club.id: raise HTTPException(404, "No such regatta")
    text = (b.text or "").strip()
    if b.send_call:
        out, _ = club_briefings(s, club, club_today(club), 1, {b.start_id} if b.start_id else None)
        if not out: raise HTTPException(409, "No starts with a forecast today")
        text = (text + "\n\n" if text else "") + call_text(club, out)
    if not text: raise HTTPException(422, "Write a notice or send the call")
    n = Notice(club_id=club.id, event_id=b.event_id, author_id=u.id, text=text); s.add(n); s.commit()
    if b.push:
        tokens = s.scalars(select(PushToken.token).join(Membership, Membership.user_id == PushToken.user_id)
                           .where(Membership.club_id == club.id)).all()
        n.pushed = push.send(sorted(set(tokens)), club.name, text[:240], {"club": club.slug, "notice": n.id}); s.commit()
    return notice_view(n)


def notice_view(n):
    return {"id": n.id, "text": n.text, "created": _utc(n.created).isoformat(), "event_id": n.event_id, "pushed": n.pushed}


@app.get("/clubs/{slug}/notices")
def list_notices(slug: str, limit: int = Query(20, le=100), s=Depends(db)):
    c = club_or_404(s, slug)
    return [notice_view(n) for n in s.scalars(select(Notice).where(Notice.club_id == c.id).order_by(Notice.id.desc()).limit(limit))]


# --- regatta pages (Club Pro: 4 events a year) ---------------------------------------------------------------------

class EventIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    first_day: dt.date
    last_day: dt.date
    classes: list[str]
    entries: int | None = Field(default=None, ge=0)
    first_gun: str = Field(default="11:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")   # used on days with no starts set


def slugify(t): return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


@app.post("/clubs/{slug}/events")
def add_event(slug: str, b: EventIn, u=Depends(current_user), s=Depends(db)):
    m = membership(u, slug, OFFICERS); club = m.club
    if not licensed(club) or TIERS[club.tier]["events"] == 0: raise HTTPException(402, "Regatta pages come with Club Pro")
    if b.last_day < b.first_day or (b.last_day - b.first_day).days > 13: raise HTTPException(422, "Check the dates (up to 14 days)")
    bad = [c for c in b.classes if c not in CLASSES]
    if bad or not b.classes: raise HTTPException(422, f"Unknown class: {', '.join(bad)}" if bad else "Name at least one class")
    year = b.first_day.year
    used = s.scalar(select(func.count()).select_from(Event).where(Event.club_id == club.id, Event.first_day >= dt.date(year, 1, 1),
                                                                  Event.first_day <= dt.date(year, 12, 31)))
    if used >= TIERS[club.tier]["events"]: raise HTTPException(402, f"Club Pro includes {TIERS[club.tier]['events']} regatta pages a year")
    base = f"{slugify(b.name)}-{year}"; es = base; k = 2
    while s.scalar(select(Event).where(Event.slug == es)): es = f"{base}-{k}"; k += 1
    ev = Event(club_id=club.id, slug=es, name=b.name, first_day=b.first_day, last_day=b.last_day, classes=",".join(b.classes),
               entries=b.entries)
    s.add(ev); s.commit()
    for d in range((b.last_day - b.first_day).days + 1):
        s.add(Start(club_id=club.id, date=b.first_day + dt.timedelta(days=d), time=b.first_gun, fleets=",".join(b.classes), event_id=ev.id))
    s.commit()
    return {"slug": ev.slug, "url": f"/r/{ev.slug}"}


def event_or_404(s, es):
    ev = s.scalar(select(Event).where(Event.slug == es))
    if not ev: raise HTTPException(404, "No such regatta")
    return ev


def event_view(s, ev):
    club = s.get(Club, ev.club_id); D = forecast_for(club.slug); tz = club.tz
    days = []
    starts = s.scalars(select(Start).where(Start.event_id == ev.id).order_by(Start.date, Start.time)).all()
    ids = {st.id for st in starts}
    briefs = (club_briefings(s, club, ev.first_day, (ev.last_day - ev.first_day).days + 1, ids)[0] or []) if D is not None else []
    for k in range((ev.last_day - ev.first_day).days + 1):
        d = ev.first_day + dt.timedelta(days=k); ds = d.isoformat()
        day0 = pd.Timestamp(ds, tz=tz)
        tide = [{**t, "local": pd.Timestamp(t["time"]).tz_convert(tz).strftime("%H:%M")}
                for t in (E.tide_turns(D, day0.tz_convert("UTC"), (day0 + pd.Timedelta(days=1)).tz_convert("UTC")) if D is not None else [])]
        days.append({"date": ds, "label": day0.strftime("%a %d %b"), "tide": tide,
                     "races": [{**b, "gun_local": pd.Timestamp(b["gun"]).tz_convert(tz).strftime("%H:%M")} for b in briefs if b["date"] == ds],
                     "starts": [{"time": st.time, "fleets": st.fleets.split(",")} for st in starts if st.date == d]})
    notices = s.scalars(select(Notice).where(Notice.event_id == ev.id).order_by(Notice.id.desc()).limit(30)).all()
    return {"slug": ev.slug, "name": ev.name, "club": {"slug": club.slug, "name": club.name}, "tz": tz,
            "first_day": ev.first_day.isoformat(), "last_day": ev.last_day.isoformat(), "entries": ev.entries,
            "classes": [{"cls": c, "name": CLASSES[c].name} for c in ev.classes.split(",") if c in CLASSES],
            "days": days, "notices": [{**notice_view(n), "local": pd.Timestamp(_utc(n.created)).tz_convert(tz).strftime("%a %H:%M")} for n in notices]}


@app.get("/events/{es}")
def event_json(es: str, s=Depends(db)):
    return event_view(s, event_or_404(s, es))


CALL_STYLE = {"race_on": ("ON", "on"), "marginal": ("MARGINAL", "marg"), "too_light": ("TOO LIGHT", "off"), "blown_out": ("TOO WINDY", "off")}


def event_html(v, page_url):
    e = html.escape; days_html = []
    for d in v["days"]:
        rows = "".join(
            f"<tr><td>{e(r['gun_local'])}</td><td>{e(r['fleet_name'])}</td><td><span class='pill {CALL_STYLE[r['call']['call']][1]}'>"
            f"{CALL_STYLE[r['call']['call']][0]}</span></td><td>{round(r['call']['wind_kn'])} kn</td><td>{round(r['call']['gust_max_kn'])} kn</td>"
            f"<td>{round(r['call']['dir'])}&deg;</td><td>{round(100 * r['call']['p_race'])}%</td></tr>" for r in d["races"])
        shifts = {r["shift"]["advice"] for r in d["races"] if r["shift"].get("kind") == "shift"}
        water = next((r["water"] for r in d["races"] if r["water"]), {})
        wbits = []
        if water.get("chop"): wbits.append(f"Chop: {e(water['chop']['label'])}")
        if water.get("stream"): wbits.append(f"Stream {water['stream']['kn']} kn" + (" against the wind" if water["stream"]["wind_against_tide"] else ""))
        tide = " &middot; ".join(f"{'HW' if t['kind'] == 'high' else 'LW'} {e(t['local'])}" for t in d["tide"])
        body = (f"<table><thead><tr><th>Gun</th><th>Class</th><th>Call</th><th>Wind</th><th>Gusts</th><th>From</th><th>Racing</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>" if rows else "<p class='muted'>The forecast for this day isn't out yet. It appears about a week ahead.</p>")
        extra = "".join(f"<p class='tip'>{e(a)}</p>" for a in sorted(shifts))
        meta = " &middot; ".join(x for x in [tide, *wbits] if x)
        days_html.append(f"<section class='day'><h2>{e(d['label'])}</h2>{f'<p class=muted>{meta}</p>' if meta else ''}{body}{extra}</section>")
    notices = "".join(f"<li><span class='muted'>{e(n['local'])}</span> {e(n['text'])}</li>" for n in v["notices"]) or "<li class='muted'>No notices yet.</li>"
    classes = ", ".join(e(c["name"]) for c in v["classes"])
    entries = f" &middot; {v['entries']} entries" if v.get("entries") else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(v['name'])}</title><meta name="description" content="Race-day wind and water for {e(v['name'])} at {e(v['club']['name'])}">
<style>:root{{--bg:#f6f8fc;--card:#fff;--fg:#0b1b33;--muted:#5b6b85;--blue:#0A4DA8;--on:#1f8a4c;--marg:#c98a00;--off:#b3261e;--line:#e3e8f1}}
@media (prefers-color-scheme:dark){{:root{{--bg:#07142a;--card:#0d2142;--fg:#eef3fb;--muted:#9fb0cc;--line:#1d3561}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,-apple-system,sans-serif}}main{{max-width:960px;margin:auto;padding:16px}}
header{{background:var(--blue);color:#fff;padding:28px 16px}}header .in{{max-width:960px;margin:auto;display:flex;gap:16px;justify-content:space-between;flex-wrap:wrap}}
h1{{margin:0 0 4px;font-size:28px}}h2{{margin:0 0 6px;font-size:20px}}.muted{{color:var(--muted)}}header .muted{{color:#cfe0ff}}
.day,.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:16px 0;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;min-width:520px}}th,td{{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line)}}th{{font-size:13px;color:var(--muted);font-weight:600}}
.pill{{font-weight:700;font-size:12px;padding:3px 8px;border-radius:999px;color:#fff}}.on{{background:var(--on)}}.marg{{background:var(--marg)}}.off{{background:var(--off)}}
.tip{{margin:10px 0 0;padding:10px 12px;border-left:4px solid var(--blue);background:color-mix(in srgb,var(--blue) 8%,transparent)}}
#qr{{background:#fff;padding:8px;border-radius:8px;width:112px;height:112px}}ul{{padding-left:18px}}footer{{font-size:13px;margin:24px 0}}
@media print{{header{{background:none;color:#000}}header .muted{{color:#333}}.day{{break-inside:avoid}}}}</style></head><body>
<header><div class="in"><div><h1>{e(v['name'])}</h1><div class="muted">{e(v['club']['name'])} &middot; {e(v['days'][0]['label'])} to {e(v['days'][-1]['label'])}{entries}</div>
<div class="muted">{classes}</div></div><div id="qr" aria-label="QR code for this page"></div></div></header><main>
<div class="card"><h2>Notices from the race office</h2><ul>{notices}</ul></div>
{''.join(days_html)}
<footer class="muted">Race calls are the chance that wind stays inside each class's limits through the racing window. Times are local ({e(v['tz'])}).
Forecast by bluepuff from ECMWF, DWD, Météo-France and other open models via Open-Meteo (CC BY 4.0). The race officer's decision on the water is final.</footer>
</main><script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
<script>try{{new QRCode(document.getElementById("qr"),{{text:{json.dumps(page_url)}||location.href,width:96,height:96}})}}catch(e){{}}
setTimeout(()=>location.reload(),15*60*1000)</script></body></html>"""


@app.get("/r/{es}", response_class=HTMLResponse)
def event_page(es: str, s=Depends(db)):
    v = event_view(s, event_or_404(s, es))
    base = os.environ.get("PUBLIC_URL", "").rstrip("/")
    return event_html(v, f"{base}/r/{es}" if base else "")


@app.get("/clubs/{slug}/events")
def club_events(slug: str, s=Depends(db)):
    c = club_or_404(s, slug)
    rows = s.scalars(select(Event).where(Event.club_id == c.id, Event.last_day >= club_today(c) - dt.timedelta(days=7))
                     .order_by(Event.first_day)).all()
    return [{"slug": e.slug, "name": e.name, "first_day": e.first_day.isoformat(), "last_day": e.last_day.isoformat(),
             "classes": e.classes.split(","), "entries": e.entries, "url": f"/r/{e.slug}"} for e in rows]


# --- payments: RevenueCat (sailors, in the apps) and Stripe (club licences, on the web) -----------------------------

@app.post("/hooks/revenuecat")
def revenuecat_hook(body: dict, authorization: str = Header(default=""), s=Depends(db)):
    want = os.environ.get("REVENUECAT_WEBHOOK_AUTH", "")
    if not want or not secrets.compare_digest(authorization, want): raise HTTPException(403, "Bad webhook auth")
    ch = payments.revenuecat_change(body.get("event") or {})
    if not ch: return {"ok": True, "changed": False}
    uid, plan, until = ch; u = s.get(User, uid)
    if not u: return {"ok": True, "changed": False}
    if plan is not None: u.plan = plan
    u.plan_until = until; s.commit()
    return {"ok": True, "changed": True}


class CheckoutIn(BaseModel):
    tier: str


@app.post("/clubs/{slug}/checkout")
def club_checkout(slug: str, b: CheckoutIn, u=Depends(current_user), s=Depends(db)):
    """Club admins buy or upgrade the club's licence. Returns a Stripe Checkout URL to open in the browser."""
    m = membership(u, slug, ("admin",))
    if b.tier not in ("club", "plus", "pro"): raise HTTPException(422, "Pick club, plus or pro")
    if licensed(m.club) and m.club.tier == "pro" and b.tier != "pro": raise HTTPException(409, "Talk to us to move down a tier")
    base = os.environ.get("PUBLIC_URL", "").rstrip("/") or "http://localhost:8000"
    try: cs = payments.checkout_session(slug, b.tier, u.email, base)
    except KeyError as e: raise HTTPException(503, str(e.args[0]))
    return {"url": cs["url"]}


@app.post("/hooks/stripe")
async def stripe_hook(request: Request, s=Depends(db)):
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    try: ev = payments.stripe_verify(await request.body(), request.headers.get("stripe-signature", ""), secret) if secret else None
    except ValueError: ev = None
    if not ev: raise HTTPException(400, "Bad signature")
    ch = payments.licence_change(ev)
    if not ch: return {"ok": True, "changed": False}
    slug, tier, until = ch; club = s.scalar(select(Club).where(Club.slug == slug))
    if not club or tier not in TIERS: return {"ok": True, "changed": False}
    club.tier = tier; club.licence_until = max(until, club.licence_until or until); s.commit()
    return {"ok": True, "changed": True}


@app.get("/clubs/{slug}/licence", response_class=HTMLResponse)
def licence_page(slug: str, paid: int = 0, s=Depends(db)):
    c = club_or_404(s, slug); e = html.escape
    state = (f"{e(c.name)} is on <b>{e({'club': 'Club', 'plus': 'Club Plus', 'pro': 'Club Pro'}.get(c.tier, 'no licence'))}</b>"
             + (f" until {c.licence_until:%d %b %Y}" if c.licence_until and licensed(c) else "") + ".")
    note = "<p>Thank you. Your payment went through; the licence updates within a minute.</p>" if paid else ""
    return (f"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>{e(c.name)} licence</title>"
            f"<body style='font:16px system-ui;max-width:560px;margin:40px auto;padding:0 16px'><h1>bluepuff club licence</h1>{note}<p>{state}</p>"
            f"<p>Members join in the app with your club code. Questions: reply to your receipt email.</p></body>")
