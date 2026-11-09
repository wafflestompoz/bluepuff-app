# Sailing backtest (Bluepuff spike, Nov 2026)

Moved from bluepow-app (closed PR #30). `lib/` holds copies of 4Kasta's open-data readers (`extract.py`, `grids.py`, `httpfs.py`) from bluepow-app `model/kasta/src`.

Can a 4Kasta-style correction forecast the wind at dinghy sailing clubs better than the raw weather models?
44 European clubs (UK, IE, NL, BE, DE, DK, SE, PL, FR, CH, IT, AT) with a wind station within about 15 km,
summers (May–Sep) 2023–2025, sailing hours 09–18 CEST (07–16 UTC). Wind in knots.

## Data (all open, read from AWS)

- **Station wind**: NOAA ISD hourly reports (`s3://noaa-isd-pds`, public domain), 10-min mean at the hour. The archive ends
  August 2025. Most stations are airports or coastal/lake-shore synop stations, not on the race course. `obs.py`.
- **Same-day models** (`extract_wind.py`, reuses 4Kasta's `lib/extract.py`): Open-Meteo open-data archive (CC BY 4.0),
  which holds each model's latest short-range run (lead about 0–12 h): ECMWF IFS, ICON-EU, ICON-D2, UKMO 10 km, AROME France,
  ARPEGE. 10 m u/v and gusts at the station, the club's water point and 4 neighbours about 15 km away, plus ICON-EU
  temperature, radiation, cloud, pressure and 850 hPa wind, and IFS boundary-layer height.
- **Day-ahead** (`gfs_day1.py`, same byte-range approach as 4Kasta's `gfs_harvest.py`): NOAA GFS 0.5° 00Z run for 09/12/15 UTC
  the next day (lead 33–39 h).

## Method (`backtest.py`)

- `raw_*`: each model at the station; `raw_mean` = average of the models (what multi-model apps show).
- `bias`: per-club linear correction of `raw_mean` against the station (simple MOS).
- `kasta`: LightGBM on every model, point and context variable plus club, hour and day of year (the 4Kasta recipe),
  trained leave-one-summer-out, so every score is out of sample. **Needs a station at the club.**
- `kasta_ns`: same model trained leave-one-club-out: the forecast for a club **without** its own station.
- Race day: 10:00–16:00 CEST mean ≥ 6 kn and no hour above 22 kn (62% of days). The probability comes from the forecast
  mean/max with a fixed error spread; "call right" = the 50% call matched what happened.

## Results (`reports/metrics.json`, `reports/by_club.csv`)

| Same day (lead ~0–12 h) | Hourly error (kn) | Wind band right* | Race-day call right | Race-day Brier |
|---|---|---|---|---|
| Best single model (AROME / ICON-D2, where they cover) | 1.87 / 1.91 | 72% / 71% | 88% / 86% | 0.097 / 0.106 |
| Raw multi-model mean | 1.79 | 72% | 85.8% | 0.104 |
| Per-club bias correction | 1.53 | 77% | 89.7% | 0.088 |
| **4Kasta-style, club has a station** | **1.40** | **79%** | **91.1%** | **0.083** |
| 4Kasta-style, no station at the club | 1.77 | 73% | 88.0% | 0.101 |

| Day ahead (GFS 0.5°) | Hourly error (kn) | Wind band right* |
|---|---|---|
| Raw GFS | 2.59 | 62% |
| Per-club bias correction | 2.05 | 70% |
| **4Kasta-style, with station** | **1.87** | **72%** |
| 4Kasta-style, no station | 2.41 | 63% |

\* bands: under 5, 5–12, 12–18, over 18 kn.

- With a station, the correction cuts the hourly error by 22% on the multi-model mean (median club 16%, range 1–57%) and
  by 28% for the day-ahead global model. Race-day calls go from about 86% to 91% right.
- Biggest gains where the models are worst: sheltered lakes and reservoirs (Lausanne, Thun, Draycote, Queen Mary, Konstanz) and
  some coasts (Aarhus, Flensburg, Trieste, La Rochelle). Smallest on open exposed water (Workum, Cherbourg, Granton), where the raw
  models are already good.
- Without a station the gain mostly disappears (hourly about 1% better than the raw mean, day-ahead 7%). The edge is site-specific.
- A per-club linear correction gets about two thirds of the gain; LightGBM adds the rest (about 8% more on hourly error).

## Caveats

- Scored against the nearby station, not the race course. A station 10 km inland is not the water.
- Mean wind only: ISD gust reports are too sparse to score gusts.
- Same-day uses short leads; day-ahead uses only coarse GFS. The real day-1–3 multi-model test needs archived runs
  (Open-Meteo `data_run/` keeps 2025–26 runs) plus 2026 station data, which this container can't reach (MeteoSwiss, DWD, KNMI hosts blocked).
- Thermal and sea-breeze days aren't scored separately yet.

## Round 2: geography, weather type and morning readings (`geo.py`, `backtest2.py`)

- `geo.py`: water and terrain around each station and race area from ESA WorldCover 10 m (CC BY 4.0) and Copernicus DEM
  GLO-30 on AWS. Open water upwind at 0–2, 2–10 and 10–30 km in 16 directions, distance to shore, water within 1/5/20 km,
  highest ground upwind within 15 km, roughness. Race-area points that landed on the shore are moved to the nearest open
  water (13 clubs, median 0.6 km). In the model these are turned upwind with the models' wind direction.
- Weather type: land-minus-water temperature (and times sunshine), 850 hPa wind vs surface wind (ratio, veer), boundary-layer
  height, model spread.
- Morning: the 08:00 CEST station reading, the models' error then and the 06–08 mean, as if the forecast were issued at 08:00.
- The no-station model is now scored in 11 groups of 4 held-out clubs.

| Hourly error (kn), same day | Club has a station | No station | Light-wind sunny days, station / none |
|---|---|---|---|
| Raw multi-model mean | 1.79 | 1.79 | 1.55 / 1.55 |
| Round 1 | 1.40 | 1.77 | 1.06 / 1.34 |
| + geography | 1.38 | 1.78 | 1.05 / 1.33 |
| + weather type | 1.40 | 1.78 | 1.05 / 1.33 |
| + morning readings | 1.38 | n/a | 1.05 / n/a |

Race-day calls: 91.0% → 91.4% (station), 88.0% → 87.6–87.8% (none). Median club without a station: 1.70 → 1.64 kn with geography and weather type.

**What this says:** none of the three moves the needle much on this data.
- With a station, the club identity plus multi-model features already capture the local bias; geography is redundant there.
- Without a station, 44 clubs are 44 examples of geography, far too few to learn how fetch and hills change the wind.
  The fix is to train the geography on every open station (about 700 in Europe in ISD alone, thousands in the national
  networks), not just the ones near clubs.
- Morning readings add little because the same-day archive is already a 0–12 h forecast that has seen the morning.
  They should matter more for a forecast issued the evening before.
- Light-wind sunny days are where the corrected model shines (−32% error with a station), but the extra
  sea-breeze signals didn't add to that.
- The scoring target is still the shore or airport station, so the race-area features can't be rewarded yet.

## Rerun

```bash
pip install -r requirements.txt rasterio
curl -o /tmp/claude-0/sail/isd-history.csv https://noaa-isd-pds.s3.amazonaws.com/isd-history.csv
python obs.py && for m in ecmwf_ifs dwd_icon_eu dwd_icon_d2 meteofrance_arome_france0025 meteofrance_arpege_europe; do python extract_wind.py $m; done
python extract_wind.py ukmo_global_deterministic_10km wind_speed_10m wind_direction_10m wind_gusts_10m
python extract_wind.py dwd_icon_eu temperature_2m direct_radiation cloud_cover pressure_msl wind_u_component_850hPa wind_v_component_850hPa
python extract_wind.py ecmwf_ifs boundary_layer_height && python gfs_day1.py && python backtest.py
python geo.py && python backtest2.py   # round 2, about 30 minutes
```
About 15 minutes of downloads and 15 minutes of training on 4 cores.
