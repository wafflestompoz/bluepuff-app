# Briefing engine

Turns the live club forecast (`forecast/live.py`) into race-day briefings, one per fleet per start:

- **Race call** – race on, marginal, too light or blown out, with the odds. Racing needs the wind at the gun above the
  fleet's minimum and every gust in the race window under the fleet's gust limit. The odds come from the spread
  between the models plus a base error (1.8 kn, the backtest's raw hourly error; gusts 1.3x), treated as one shared
  error for the race.
- **Shift** – the first shift of 10° or more in the window, when it arrives, the share of models that agree, and which
  side of the beat pays. Below 4 kn the direction is flagged as unreliable.
- **Rig** – light, medium or heavy band for the class, with a short setup tip.
- **Water** – chop, waves and swell, high and low water, the stream at the gun and wind against tide.
- **Live sensor** – a club sensor reading under 45 minutes old shifts the forecast toward it, fading with a 3-hour
  e-folding time, and halves the near-term error.

Class wind ranges and rig bands are starting values in `classes.csv`; clubs override the gust limit per start
(`limits` in the programme), for example a 16 kn junior limit.

```bash
python forecast/live.py hayling rsys                  # live forecast -> forecast/out/<club>.csv
python -m engine.briefing engine/programme_example.json   # -> forecast/out/briefings.json
python -m pytest engine
```

Known gaps: gust odds use the models' raw gusts, which run high at some harbour clubs; calibrate them against club
sensors once those report. The trained correction from the backtest is not applied yet.
