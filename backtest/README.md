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

## Round 3: the no-station model trained on every open station (`backtest3.py`, `all_stations.csv`)

Training data: all 1,031 lowland (under 800 m) NOAA ISD stations in 43–58°N, 11°W–22°E with summer 2023–25 data, plus the
same models, weather-type signals and geography at each (`ALL=1` mode of `obs.py`, `extract_wind.py`, `geo.py`). Scored at the
44 club stations in 4 folds of 11. Each fold's training drops those clubs and every station within 25 km of them.
Same features in both rows, no club identity.

| Club has no station | Hourly error (kn) | Wind band right | Race-day call right | Race-day Brier | Light-wind sunny hours |
|---|---|---|---|---|---|
| Raw multi-model mean | 1.79 | 71.9% | 85.8% | 0.104 | 1.55 |
| Trained on the other 33 clubs | 1.79 | 72.8% | 87.4% | 0.101 | 1.39 |
| **Trained on ~1,000 stations** | **1.69 (−6%)** | **74.4%** | **88.7%** | **0.095** | **1.28 (−17%)** |

- Training on every station finally gives a real gain at clubs with no station of their own. 32 of the 44 clubs improve, the
  median club by 7%, and Thun, La Rochelle, Aarhus, Bourget and Locarno by 17–32%. Light-wind sunny hours, the thermal and
  sea-breeze days, improve most.
- A dozen clubs get worse, most clearly Weymouth (−54%), whose Portland station sits on an exposed headland unlike any
  training station, plus Lausanne and Grafham. A shipped version needs a guard, for example falling back to the raw
  mean where the model is less sure, or a per-region model.
- It is still far behind having a station (1.40 kn), so club anemometers remain the biggest lever. The gap between the two is
  where more stations (national networks, club stations) would help.
- After the models' own wind, the most useful inputs are location, terrain roughness, distance to the shore and water nearby,
  so geography now carries weight it couldn't with 44 examples.

## Water conditions: chop, waves, tides, currents, sea temperature (`chop.py`, `marine.py`, `depths.csv`)

**Chop at every club, lakes included.** Wind-wave height and period from the forecast wind at the race area, the open
water upwind of it in that wind direction (fetch, from WorldCover, `geo.py`) and the water depth, using the Shore Protection
Manual (USACE 1984) fetch- and depth-limited formulas. Depths in `depths.csv` are approximate mean depths entered by hand
(the IJsselmeer is about 4.5 m, Steinhuder Meer 1.35 m, the Alpine lakes 40–180 m); a global lake-depth dataset can replace them.
States: flat < 0.1 m, small chop 0.1–0.3, moderate 0.3–0.6, rough 0.6–1.0, big waves > 1 m. "Short chop" = 0.3 m or more with
crests under 12 m apart, the kind that stops a dinghy.

Summer race hours, 2023–25 (`reports/water.json`):
- Choppiest: Workum/IJsselmeer (moderate or worse 49% of hours), Nieuwpoort 48%, Hayling 37%, Dinard 31%, La Rochelle 30%.
- Shallow lakes are choppier than their size suggests: Lelystad/Markermeer 18%, Medemblik 14%. Deep Alpine lakes and
  reservoirs rarely pass small chop (Lausanne 8%, Neuchatel 6%, Geneva 3%, the rest under 1%).

**Check against the DWD EWAM wave model** (5 km) at the 22 sea clubs: hourly correlation 0.47 overall, 0.41–0.85 by club
(Hayling 0.85, Nieuwpoort 0.84, La Rochelle 0.83 on open water). Where they disagree, EWAM's nearest sea cell is usually outside
the harbour or estuary the club sails in (Burnham: River Crouch vs the Thames Estuary; Brest: inside the Rade), which is exactly
where the fetch method is the better guide. No buoy data was reachable to settle it.

**Sea clubs also get** (Open-Meteo open data, CC BY 4.0):
- Waves and swell: DWD EWAM, hourly (median summer wave height 0.02 m in the Rade de Brest to 0.78 m off Crosshaven).
- Tides and surge: Météo-France SMOC sea level, hourly. Spring ranges (95th percentile daily range) match known values:
  Dinard 11.2 m, Brest 6.0, Cherbourg 5.9, Granton 5.2, La Rochelle 5.1, Nieuwpoort 5.1, Plymouth 5.0, Burnham 4.7, Trieste 1.2,
  Mediterranean 0.3, Baltic and Kattegat under 0.7.
- Tidal and other currents: same source (95th percentile 2.6 kn at Cherbourg and Weymouth/Portland, 1.7 kn Nieuwpoort, under 0.5 kn in
  the Baltic). At 1/12 degree it misses harbour-scale streams.
- Sea temperature: Météo-France, 6-hourly, monthly medians in `reports/water.json`.
- Lakes get chop only. Lake water temperature isn't in the archive.

## Rounds 4 and 5: what a live forecast can add (`backtest4.py`, `backtest5.py`)

Baseline re-measured from a fresh rebuild of the data: 1.40 kn hourly error at clubs with a station, 1.70 kn without
(round 3 reported 1.69), raw multi-model mean 1.79 kn. Same out-of-sample schemes as before.

**What worked: learn the correction, not the wind** (`backtest5.py`, `*_res`). The model predicts how far the station will
be from the multi-model mean and adds that to the mean, instead of predicting the wind from scratch. It starts from the
raw forecast and moves only where it has learned to.

| Same day | Hourly error (kn) | Wind band right | Race-day call right | Race-day Brier | Light-wind sunny | Median club | Clubs worse than raw |
|---|---|---|---|---|---|---|---|
| Raw multi-model mean | 1.79 | 71.9% | 85.8% | 0.104 | 1.55 | 1.76 | n/a |
| **With a station**, round 1 model | 1.40 | 78.5% | 91.0% | 0.083 | 1.06 | 1.37 | 1 |
| **With a station, learns the correction** | **1.37** | **79.0%** | **91.4%** | **0.080** | **1.05** | **1.35** | **0** |
| **No station**, round 3 model | 1.70 | 74.2% | 88.7% | 0.095 | 1.28 | 1.64 | 10 |
| **No station, learns the correction** | **1.68** | **74.5%** | **88.7%** | **0.093** | **1.27** | **1.60** | 11 |
| No station, half model and half raw | 1.71 | 73.5% | 87.6% | 0.097 | 1.35 | 1.72 | 6 |

- With a station the gain is small but clean: 2% lower hourly error, 3% better Brier, and no club ends up worse than the raw
  models (one did before).
- Without a station: median club 1.64 → 1.60 kn, Aarhus 2.40 → 1.83, Draycote 2.36 → 2.19. Weymouth is still the worst case
  (1.89 raw → 2.73), and Lausanne, Burnham, Grafham and Rutland stay worse than raw.
- Halving the no-station correction is the only thing that limits the worst clubs (Weymouth +16% instead of +51%, 6 clubs worse
  instead of 10), at the cost of most of the average gain. It's a product call, not a free fix.

**What didn't** (`backtest4.py`, kept for the record):
- Recent error (how wrong the models were at the station in the last 3/10/30 days): on its own it takes the raw mean from
  1.79 to 1.62 kn with no machine learning at all, which is useful for a club whose anemometer is new and has no history yet.
  On top of the trained model it adds nothing (1.40 → 1.40): the model already knows the club.
- The same recent error borrowed from stations 25–100 km away, for clubs without a station: slightly worse (1.70 → 1.72).
- A fallback guard that drops to the raw mean where the no-station model did badly at the nearest training stations: it
  picked the wrong clubs (it never flagged Weymouth, whose neighbours the model handles well) and lost accuracy overall.
- Calibrating the race-day probability with a logistic fit instead of the fixed 2.5 kn spread: worse (Brier 0.083 → 0.084,
  call right 91.0% → 89.7%). The fixed spread is already well calibrated.

**What's left that would move the numbers most:** day-ahead and day-2/3 multi-model forecasts. Only GFS is scored that far out
(1.87 kn with a station), and the open archive only keeps past model runs from 2026, when there are no ISD observations yet.
Open-Meteo's paid API (previous-runs and historical-forecast) has 2024–25 runs at fixed leads and would let this be scored
against the stations here. Also, the scoring target is still the shore or airport station, not the race course.

## Australia (`backtest_au.py`, `clubs_au.csv`, `stations_au.csv`)

22 Australian clubs in `clubs_au.csv`. Race-area coordinates and depths are approximate and were entered by hand. 21 clubs
have an ISD station within 17 km; Ballarat (Lake Wendouree) has none within 45 km. Several clubs share a station (three in
Sydney Harbour, three in Melbourne, three on the Swan River and Fremantle), so 15 distinct stations. The on-water stations
(Fort Denison, St Kilda Harbour, Fawkner Beacon, Inner Dolphin Pylon) only appear in ISD from April 2024 and are sparse,
so the nearest full-record land or airport station is used instead (Sydney airport for the harbour, 11–16 km away).
Southern summers (Nov–Mar) 2022/23–2024/25, 09–18 local time. Europe's regional models don't reach Australia, so the raw
forecast is the mean of four global models: ECMWF IFS, DWD ICON (13 km), UKMO 10 km and ARPEGE world (25 km).

| Same day, out of sample | Hourly error (kn) | Bias (kn) | Wind band right | Race-day call right | Race-day Brier |
|---|---|---|---|---|---|
| Best single model (ARPEGE / IFS) | 3.21 / 3.20 | −1.6 / −1.3 | 56% / 54% | 71.8% / 73.7% | 0.199 / 0.176 |
| Raw mean of 4 global models | 3.02 | −1.68 | 55% | 73.1% | 0.177 |
| Per-club linear correction | 1.89 | 0.0 | 72% | 89.6% | 0.083 |
| **Learns the correction, club has a station** | **1.78 (−41%)** | −0.33 | **73%** | **90.0%** | 0.086 |
| Learns the wind, club has a station | 2.12 | −0.98 | 67% | 85.2% | 0.112 |
| No station (leave one station out) | 3.23 | −0.23 | 56% | 76.4% | 0.163 |
| No station, one pooled linear fit for all of Australia | 2.89 | 0.0 | 60% | 78.8% | 0.152 |

- The global models are much worse here than Europe's regional ones (3.0 vs 1.8 kn) and read about 1.7 kn light, most at
  the windy sea-breeze clubs: Sydney Harbour (4.7 kn raw → 2.1 corrected), Brighton SA and Adelaide (4.6–5.0 → 2.3–2.5),
  Hobart (4.3 → 2.2). With a station, every club improves, by 22–55%.
- Learning the correction is clearly better than learning the wind here (1.78 vs 2.12): with 21 clubs the direct model
  can't extrapolate, while the correction starts from the models.
- Without a station there's no usable gain yet. 15 stations are too few to learn geography, the same lesson as Europe
  round 3; the fix is to train on the ~640 Australian ISD stations. A single pooled linear fit removes the low bias
  (race-day calls 73% → 79%) but makes the median club worse (2.85 → 3.05 kn), so it isn't a safe default either.
- Scoring is against shore and airport stations, so the harbour numbers say more about the models' low bias than the race course.

### Scored on the water (`backtest_au_water.py`, `stations_au_water.csv`)

The table above is scored against land and airport stations. 12 of the clubs have an on-water or harbour station nearby:

- Fort Denison, Sydney Harbour (RSYS, Woollahra, Middle Harbour)
- Fawkner Beacon, Port Phillip (Brighton, Sandringham)
- St Kilda Harbour (RMYS)
- Banana Bank North Beacon, Moreton Bay (RQYS)
- Inner Dolphin Pylon, Swan River (Royal Perth, Freshwater Bay)
- Garden Island, Cockburn Sound (Fremantle)
- Gold Coast Seaway (Southport)
- Black Pole, Gulf St Vincent (Royal Adelaide)

Most of these only reach the NOAA archive from 2024, about every 3 hours, so this covers the 2024/25 southern summer: 8,660
club-hours, scored against the **on-water** reading. The two corrections trained on the water use the other months of that
summer (5 month folds). That's one summer only, and neighbouring months share weather, so those two rows are somewhat optimistic.

| 2024/25, scored on the water | Hourly error (kn) | Bias (kn) | Wind band right | Race-day call right | Race-day Brier |
|---|---|---|---|---|---|
| Raw mean of 4 global models | 3.79 | −3.27 | 45% | 72.3% | 0.179 |
| Correction learned at the airport | 3.94 | −1.75 | 48% | 79.0% | 0.142 |
| Per-club linear fit on the water | 2.31 | 0.0 | 68% | 91.3% | 0.077 |
| **Correction learned on the water** | **1.97** | 0.05 | **73%** | **92.6%** | **0.065** |

For the same hours scored the usual way, against the airport: raw 2.98 kn, airport correction 1.62 kn.

- The water is windier than the airports: 12.2 kn mean against 10.7. The raw models read 3.3 kn light on the water, against
  2.0 at the airports.
- **A correction learned at the airport doesn't carry over to the water.** It's worse than raw hour by hour (3.94 vs 3.79 kn),
  and much worse where the land station is sheltered. Brighton, RMYS and RQYS are scored at Melbourne Olympic Park and
  Brisbane airport, which average 5–7 kn while the water averages 11–13 kn. Their error goes up from about 2.4–5.3 kn raw
  to 6.0–6.9 kn.
- Learned on the water, even from one summer of 3-hourly readings, it halves the raw error (3.79 → 1.97 kn) and gets 93% of
  race-day calls right. Every club improves, Fremantle most (4.85 → 1.62 kn on Garden Island).
- So on-water readings are what the correction should learn from. For these 12 clubs the live forecast lists the on-water
  station (`forecast/clubs_static.csv`).
- Europe: the clubs already use the few coastal or lake stations in the NOAA archive (Stavoren, Oosterschelde, Houtribdijk,
  Roches Point, Portland). There's nothing more on the water in that archive. The national networks (KNMI and Rijkswaterstaat
  platforms, DWD, MeteoSwiss lake stations, UK Met Office) have more, but their hosts are blocked in this environment.

### More clubs next to on-water stations (`clubs_euw.csv`, `stations_euw.csv`; Goolwa and Hamilton Island in `clubs_au.csv`)

Found by checking every station in the NOAA archive for open water around it (WorldCover, `geo.py`), keeping those with full
2023–25 records, and adding a club that races beside each one:

- **Europe (9):** Royal Belgian SC (Zeebrugge mole), WSV IJmuiden (IJmuiden pier), Assens Sejlklub (Assens/Torø), Dragør
  Sejlklub (Drogden lighthouse), Skagen Sejlklub (Skagen), Pembrokeshire YC (Milford Haven waterway), Blundellsands SC
  (Crosby), JK Jugo Mali Lošinj (Mali Lošinj harbour) and Circolo Velico Ravennate (Marina di Ravenna).
- **Australia (2):** Goolwa Regatta YC (Hindmarsh Island, in the Murray mouth) and Hamilton Island YC (the island's shoreline
  airstrip). Both have hourly records from 2021.

All are scored over 3 summers, leaving one summer out (`REGION=euw python backtest_au.py` for Europe).

| Hourly error (kn), same day | Raw models | Learns the correction | Race-day calls, raw → corrected |
|---|---|---|---|
| 9 new European clubs (6 European models) | 2.24 | **1.66 (−26%)** | 81.2% → 87.5% |
| Goolwa / Hamilton Island (4 global models) | 4.26 / 4.23 | **1.94 / 2.05** | in the Australian set |

- Every one of the 9 European clubs improves, IJmuiden most (3.17 → 1.52) and Dragør (2.97 → 1.93). Skagen and Assens
  gain least, because the models are already close on open water (1.84 → 1.72, 1.75 → 1.54).
- With Goolwa and Hamilton Island, the Australian on-water set is 14 clubs and 11,559 hours. Scored on the water, the raw
  models are off by 3.92 kn, and the correction learned on the water brings that to 1.94 kn, with 92.5% of race-day calls right.
- No station isn't solved here either: leaving a station out is worse than raw at these clubs, as before.

## Data licences (matters before charging for bluepuff)

Every station observation in this folder comes from NOAA ISD. NOAA's own (US) data is public domain, but ISD carries
non-US stations under WMO Resolution 40, which restricts commercial use, and the Australian stations are BoM data, which is
free for non-commercial use only. So **every trained correction here (Europe, Australia and the on-water sets) is learned
from non-commercial data**. That's fine for research; a paid product needs the same corrections retrained on commercially
usable observations (KNMI, DWD, MeteoSwiss, DMI, Météo-France and Met Office are open for commercial use) or a BoM licence.
The model inputs (Open-Meteo open data, CC BY 4.0), WorldCover (CC BY 4.0) and Copernicus DEM are fine with attribution.
The live forecast (`forecast/`) uses no station data.

## Rerun

```bash
pip install -r requirements.txt rasterio
curl -o /tmp/claude-0/sail/isd-history.csv https://noaa-isd-pds.s3.amazonaws.com/isd-history.csv
python obs.py && for m in ecmwf_ifs dwd_icon_eu dwd_icon_d2 meteofrance_arome_france0025 meteofrance_arpege_europe; do python extract_wind.py $m; done
python extract_wind.py ukmo_global_deterministic_10km wind_speed_10m wind_direction_10m wind_gusts_10m
python extract_wind.py dwd_icon_eu temperature_2m direct_radiation cloud_cover pressure_msl wind_u_component_850hPa wind_v_component_850hPa
python extract_wind.py ecmwf_ifs boundary_layer_height && python gfs_day1.py && python backtest.py
python geo.py && python backtest2.py   # round 2, about 30 minutes
python marine.py && python chop.py       # water conditions, about 5 minutes
ALL=1 python obs.py && ALL=1 python geo.py && ALL=1 python extract_wind.py <model> ...   # round 3 data, about 1 hour
python backtest3.py                       # round 3
python backtest4.py && python backtest5.py  # rounds 4-5, about 2 hours on 4 cores
export REGION=au; python obs.py && for m in ecmwf_ifs dwd_icon meteofrance_arpege_world025; do python extract_wind.py $m; done
python extract_wind.py ukmo_global_deterministic_10km wind_speed_10m wind_direction_10m wind_gusts_10m
python extract_wind.py dwd_icon temperature_2m direct_radiation && python geo.py && unset REGION && python backtest_au.py   # Australia, ~10 min
REGION=au STATIONS=water python obs.py  # then extract_wind.py as above with the same env, then: python backtest_au_water.py
export REGION=euw; python obs.py && for m in ecmwf_ifs dwd_icon_eu dwd_icon_d2 meteofrance_arome_france0025 meteofrance_arpege_europe; do python extract_wind.py $m; done
python extract_wind.py ukmo_global_deterministic_10km wind_speed_10m wind_direction_10m wind_gusts_10m && python extract_wind.py dwd_icon_eu temperature_2m direct_radiation
python geo.py && python backtest_au.py && unset REGION   # 9 European on-water clubs
```
About 15 minutes of downloads and 15 minutes of training on 4 cores.
