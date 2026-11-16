# bluepuff server

FastAPI + SQLAlchemy (SQLite locally, Postgres in production). Reads the engine's forecasts from `FORECAST_DIR`
(`forecast/out/<club>.csv`, written by `forecast/live.py`) and builds briefings with `engine/briefing.py`.

```bash
pip install -r server/requirements.txt
ADMIN_TOKEN=... uvicorn server.app:app --reload        # http://localhost:8000/docs
python -m pytest server engine
```

| Area | Endpoints |
|---|---|
| Accounts | `POST /auth/signup`, `/auth/login`, `/auth/logout`, `GET /me`, `POST /me/push-token` |
| Clubs | `POST /me/clubs` (join by code = home club, or follow by id), `PATCH`/`DELETE /me/clubs/{slug}`, `GET /clubs`, `GET /clubs/{slug}` |
| Race officers | `PUT /clubs/{slug}/fleets/{cls}` (limits), `POST`/`DELETE /clubs/{slug}/starts`, `PUT /clubs/{slug}/roles` (admins) |
| Briefings | `GET /clubs/{slug}/briefings` (free: 2 days, headline only; Racer: 7 days with shifts, rig, water, sensor) |
| Notices | `POST /clubs/{slug}/notices` (`send_call` writes the race call; pushed via Expo), `GET /clubs/{slug}/notices` |
| Sensors | `POST /hooks/ttn` (The Things Network uplinks), `GET /clubs/{slug}/live`, `GET /clubs/{slug}/clubhouse` (screen) |
| Regattas | `POST /clubs/{slug}/events` (Club Pro, 4 a year), `GET /clubs/{slug}/events`, `GET /events/{slug}`, `GET /r/{slug}` (public page) |
| Payments | `POST /hooks/revenuecat` (Racer, Racer Pro in the apps), `POST /clubs/{slug}/checkout` + `POST /hooks/stripe` (club licences) |
| Staff | `POST /admin/clubs`, `POST /admin/sensors` (header `X-Admin-Token`) |

Licence tiers (`server/models.py`): Club 50 sailors; Plus 150 and 1 sensor; Pro 250, 2 sensors, 4 regatta pages, 5 coach seats.
bluepuff ships sensors; clubs mount them, then staff register the device EUI with `/admin/sensors`.

Env: `DATABASE_URL`, `FORECAST_DIR`, `CLUBS_STATIC`, `ADMIN_TOKEN`, `PUBLIC_URL`, `TTN_WEBHOOK_SECRET`,
`REVENUECAT_WEBHOOK_AUTH`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_CLUB|PLUS|PRO`.

Not done yet: Barani payload field names are matched loosely and need checking against a real unit's TTN output;
hosting; store listings and RevenueCat/Stripe product setup; password reset email.
