# Live club forecast (no Open-Meteo API calls)

`live.py` reads each weather model's latest run straight from Open-Meteo's free open-data copy on AWS
(`s3://openmeteo`, CC BY 4.0) with byte-range requests, using the 4Kasta readers in `backtest/lib`. It makes **no
Open-Meteo API calls**, so it doesn't touch the account quota Bluepow uses. The paid API stays a backup.

```bash
pip install -r backtest/requirements.txt
python forecast/live.py                 # all 67 clubs in clubs_static.csv, about 1 minute
python forecast/live.py hayling thun    # just these clubs
```

Writes `forecast/out/<club>.csv` (hourly, from 6 hours ago to the end of the longest run) and `forecast/out/latest.json`
(the next 48 hours for every club, plus which model run each value came from).

Per club and hour:
- Wind: ECMWF IFS, ICON-EU, ICON-D2, UKMO 10 km, AROME France and ARPEGE at the race area, in knots, plus their mean,
  spread, mean direction and mean gust. Where a regional model doesn't cover the club or its run is shorter, the mean uses
  the rest (`n_models`).
- Chop at every club with a known fetch and depth (`backtest/chop.py`): height, period, state and a short-chop flag.
- Sea clubs: DWD EWAM waves and swell, and Météo-France sea level (tide plus surge) and current, from the nearest sea cell
  with data, stepping out from the race area toward open water.

How far ahead (runs on 15 Nov 2026): ICON-EU about 1 day, AROME and ICON-D2 about 2, UKMO 2, ARPEGE 4, IFS 5–6, waves 2–3,
currents and tides about 9. The models update every 1–6 hours. Re-running every 3 hours picks up each new run. Each run
reads about 50 small byte ranges per model variable, with no API quota used.

`clubs_static.csv` is built from the backtest's geography (`backtest/geo.py`): the race-area point, open-water fetch in 16
directions, the most open sea direction and the approximate depth. The 23 clubs with no backtest geography get wind,
and sea clubs among them get waves and tides, but no chop until `geo.py` is run for them.

Not in here yet: the trained correction from the backtest (`backtest5.py`). It needs the trained model saved and, for
clubs with a station, live station readings.
