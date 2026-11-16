# Venue maps

How the land around each club's race area changes the wind on the course, for 16 wind directions.
`python -m venue.venue [club ...]` writes `venue/out/<club>.json` (about a minute for all 100 clubs).

**Inputs**, read directly from AWS with no keys (`venue/cog.py` is a small Cloud Optimized GeoTIFF reader):
- ESA WorldCover 2021, 10 m land cover (CC BY 4.0), for water, trees and buildings.
- Copernicus DEM GLO-30, a surface model that includes large buildings and woods.

**Model**, on a 20 m grid around the race-area point (snapped to open water when it sits on the shore):
- *Shelter.* Upwind obstacles are taken as their height above the water, capped at 40 m. They reduce the wind by
  55% · exp(−x / 9H), which is about 30% at 5 H and 18% at 10 H, and nothing past about 30 H (the usual shelterbelt
  profile). The worst obstacle within 3 km sets the reduction.
- *Recovery.* Wind that has just come off land recovers over open water: 1 − 0.2 · exp(−fetch / 700 m).
- *Averaging.* Results are averaged over the wind direction ±10°.
- *Big terrain.* Hills and mountains higher than the cap steer and channel the wind rather than simply blocking it.
  They are reported as `relief_m`, and as channelling where there is long water along the wind and short water
  across it. The forecast models already resolve terrain at 1–2 km.

**Output per direction:**
- the mean wind as a fraction of the open-water wind, for the left and right sides and the top and bottom of a
  1.2 × 1.8 km beat
- how far the shadow reaches off the windward shore
- open water upwind, cross-wind water and the highest ground upwind
- a 48 × 48 map at 50 m, one character per cell: `!` is land, otherwise `chr(35 + wind% // 2)`

`engine/briefing.py` (`venue_tip`) turns these numbers into race tips. The server serves the map at
`/clubs/{slug}/venue`.

**Limits.** This is an estimate from terrain data. It does not include:
- sea breezes
- wind bending along a shore
- thermal or katabatic winds
- tide

It needs checking against club sensors and GPS tracks.
