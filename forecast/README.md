# Live club forecast (no Open-Meteo API calls)

`live.py` reads each weather model's latest run straight from Open-Meteo's free open-data copy on AWS
(`s3://openmeteo`, CC BY 4.0) with byte-range requests, using the 4Kasta readers in `backtest/lib`. It makes **no
Open-Meteo API calls**, so it doesn't touch the account quota Bluepow uses. The paid API stays a backup.

```bash
pip install -r backtest/requirements.txt
python forecast/live.py                 # all 89 clubs in clubs_static.csv, about 2 minutes
python forecast/live.py hayling thun    # just these clubs
```

Writes `forecast/out/<club>.csv` (hourly, from 6 hours ago to the end of the longest run) and `forecast/out/latest.json`
(the next 48 hours for every club, plus which model run each value came from).

Per club and hour:
- Wind at the race area, in knots, plus the models' mean, spread, mean direction and mean gust. European clubs
  (`region` europe): ECMWF IFS, ICON-EU, ICON-D2, UKMO 10 km, AROME France and ARPEGE Europe. Australian clubs (`region` au)
  and anywhere else: the global models ECMWF IFS, DWD ICON, UKMO 10 km and ARPEGE world. Where a regional model doesn't cover the club or its run is shorter, the mean uses
  the rest (`n_models`).
- Chop at every club with a known fetch and depth (`backtest/chop.py`): height, period, state and a short-chop flag.
- Sea clubs: waves and swell (DWD EWAM in Europe, Météo-France global waves elsewhere), and Météo-France sea level (tide plus surge) and current, from the nearest sea cell
  with data, stepping out from the race area toward open water.

How far ahead (runs on 15–16 Nov 2026): ICON-EU about 1 day, AROME and ICON-D2 about 2, UKMO 2, ARPEGE 4, ICON global 5,
IFS 6 (15 days from its 00Z run), waves 2–3 (Météo-France about 8), currents and tides about 9. The models update every 1–6 hours. Re-running every 3 hours picks up each new run. Each run
reads about 50 small byte ranges per model variable, with no API quota used.

`clubs_static.csv` is built from the backtest's geography (`backtest/geo.py`, `REGION=au` for Australia): the race-area point, open-water fetch in 16
directions, the most open sea direction and the approximate depth. The 23 European clubs with no backtest geography get wind,
and sea clubs among them get waves and tides, but no chop until `geo.py` is run for them.

Not in here yet: the trained correction from the backtest (`backtest5.py`). It needs the trained model saved and, for
clubs with a station, live station readings.

Australia (22 clubs) has no chop gap, but its harbour and river clubs often get no wave value: the nearest global wave
cell with data is outside the harbour, and the race-area chop is the better guide there. The global models read about
1.7 kn light in Australia (backtest/README), so these raw numbers need the trained correction more than in Europe.
