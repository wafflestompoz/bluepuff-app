"""Venue map: where the land around a club's race area takes wind off the course, for 16 wind directions.

For each wind direction we march upwind from every point of water around the club's race area and look at what the
wind has just crossed:
  * shelter behind obstacles: shore, trees, buildings and hills, by height above the water H and distance x.
    Wind is reduced by about 55% close behind an obstacle, ~30% at 5 H, ~18% at 10 H and recovers by ~30 H
    (the standard shelterbelt profile: Heisler & DeWalle 1988; Cleugh 1998), taken as the worst obstacle upwind;
  * recovery over open water: wind that has just come off land is slower and recovers over the first km or so of
    water (internal boundary layer; up to ~20% slower right at the shore).
The result is the wind as a fraction of the open-water wind, on a 50 m grid, 2.4 x 2.4 km around the race area,
plus a summary per direction that engine/briefing.py turns into race tips. It is an estimate from terrain data and
needs checking on the water (club sensors, GPS tracks).

Data (read straight from AWS, no keys): ESA WorldCover 2021 10 m land cover (CC BY 4.0) and Copernicus DEM GLO-30
(a surface model, so it includes buildings and woods where they are big enough to show at 30 m).

Run: python -m venue.venue [club ...]  -> venue/out/<club>.json
"""
import json, math, os, sys
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
from venue.cog import COG

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out")
CELL = 20.0                 # metres, model grid
SHOW = 50.0                 # metres, published grid
HALF = 1200.0               # race area half-width (m)
LOOK = 3000.0               # how far upwind to look (m)
SECT = 16
HMAX = 40.0                 # shelter uses obstacles up to cliff height; big hills and mountains steer and channel the
                            # wind rather than simply blocking it, and the forecast models (1-2 km grids) already see them
CANOPY = {10: 12.0, 20: 2.0, 30: 0.3, 40: 0.5, 50: 8.0, 60: 0.2, 70: 0.0, 80: 0.0, 90: 0.5, 95: 6.0, 100: 0.1}   # min height (m) by WorldCover class
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def wc_url(la, lo):
    return (f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_"
            f"{'N' if la >= 0 else 'S'}{abs(la):02d}{'E' if lo >= 0 else 'W'}{abs(lo):03d}_Map.tif")


def dem_url(la, lo):
    n = f"Copernicus_DSM_COG_10_{'N' if la >= 0 else 'S'}{abs(la):02d}_00_{'E' if lo >= 0 else 'W'}{abs(lo):03d}_00_DEM"
    return f"https://copernicus-dem-30m.s3.amazonaws.com/{n}/{n}.tif"


def sample(kind, lats, lons):
    """Value of the raster at each (lat, lon); missing tiles are open sea."""
    step = 3 if kind == "wc" else 1
    out = np.full(lats.shape, 80 if kind == "wc" else 0.0, "float32")
    tl = np.floor(lats / step).astype(int) * step; tn = np.floor(lons / step).astype(int) * step
    for la, lo in set(zip(tl.ravel().tolist(), tn.ravel().tolist())):
        m = (tl == la) & (tn == lo)
        # WorldCover tiles are named by their lower-left corner; DEM tiles too
        try: c = COG(wc_url(la, lo) if kind == "wc" else dem_url(la, lo))
        except FileNotFoundError: continue
        y0, y1, x0, x1 = lats[m].min(), lats[m].max(), lons[m].min(), lons[m].max()
        a, b = c.window(x0 - 0.001, y0 - 0.001, x1 + 0.001, y1 + 0.001)
        if a.size == 0: continue
        ny, nx = a.shape
        r = np.clip(((b[3] - lats[m]) / (b[3] - b[1]) * ny).astype(int), 0, ny - 1)
        cc = np.clip(((lons[m] - b[0]) / (b[2] - b[0]) * nx).astype(int), 0, nx - 1)
        v = a[r, cc].astype("float32")
        if kind == "wc": v[v == 0] = 80
        out[m] = v
    return out


class Grid:
    """A local metric grid (east, north) around a point."""
    def __init__(self, lat, lon, half, cell):
        self.lat, self.lon, self.cell = lat, lon, cell
        n = int(round(2 * half / cell)); self.n = n
        c = (np.arange(n) + 0.5) * cell - half
        self.E, self.N = np.meshgrid(c, -c)                 # rows run north -> south
        self.kx = 111320.0 * math.cos(math.radians(lat)); self.ky = 110540.0

    def latlon(self, e, n): return self.lat + n / self.ky, self.lon + e / self.kx

    def index(self, e, n):
        half = self.n * self.cell / 2
        return ((half - n) / self.cell).astype(int), ((e + half) / self.cell).astype(int)


def surface(lat, lon):
    """Land cover, obstacle height above the race-area water and a water mask on a 20 m grid."""
    G = Grid(lat, lon, HALF + LOOK, CELL)
    la, lo = G.latlon(G.E, G.N)
    wc = sample("wc", la, lo); dem = sample("dem", la, lo)
    water = wc == 80
    inner = (np.abs(G.E) <= HALF) & (np.abs(G.N) <= HALF)
    wl = float(np.median(dem[water & inner])) if (water & inner).any() else 0.0
    canopy = np.vectorize(lambda k: CANOPY.get(int(k), 0.0))(wc).astype("float32")
    H = np.where(water, 0.0, np.maximum(dem - wl, canopy)).astype("float32")
    return G, water, H, wl


def snap(lat, lon, max_m=3000):
    """Move a race-area point that is on land, or hard against it, to the nearest open water."""
    from scipy.ndimage import uniform_filter
    G = Grid(lat, lon, max_m + 300, CELL); la, lo = G.latlon(G.E, G.N)
    water = sample("wc", la, lo) == 80
    open_ = uniform_filter(water.astype("float32"), int(300 / CELL)) >= 0.8
    c = G.n // 2
    if open_[c, c]: return lat, lon, 0.0
    ys, xs = np.nonzero(open_)
    if not ys.size: return lat, lon, float("nan")
    d = np.hypot(G.E[ys, xs], G.N[ys, xs]); i = d.argmin()
    if d[i] > max_m: return lat, lon, float("nan")
    a, b = G.latlon(G.E[ys[i], xs[i]], G.N[ys[i], xs[i]]); return float(a), float(b), float(d[i])


def shelter_factor(x_over_h):
    return 0.55 * np.exp(-x_over_h / 9.0)


def pressure(G, water, H, frm):
    """Wind as a fraction of open-water wind at every race-area cell, for wind FROM `frm` degrees."""
    S = Grid(G.lat, G.lon, HALF, SHOW)
    e0, n0 = S.E.ravel(), S.N.ravel()
    steps = np.arange(CELL, LOOK + CELL, CELL)
    out = np.zeros(e0.shape, "float32")
    for off in (-10.0, 0.0, 10.0):                     # a spread of directions, as the wind wanders
        th = math.radians(frm + off); ue, un = math.sin(th), math.cos(th)
        E = e0[:, None] + steps[None, :] * ue; N = n0[:, None] + steps[None, :] * un
        r, c = G.index(E, N); r = np.clip(r, 0, G.n - 1); c = np.clip(c, 0, G.n - 1)
        h = np.minimum(H[r, c], HMAX); w = water[r, c]
        s = np.where(h > 0.5, shelter_factor(steps[None, :] / np.maximum(h, 0.5)), 0.0).max(axis=1)
        land = ~w
        first = np.where(land.any(axis=1), land.argmax(axis=1), len(steps))
        fetch = np.where(first < len(steps), steps[np.minimum(first, len(steps) - 1)] - CELL / 2, 10000.0)
        rec = 1.0 - 0.2 * np.exp(-fetch / 700.0)
        out += (1.0 - s) * rec / 3.0
    r, c = G.index(e0, n0); here = water[r, c]
    P = np.where(here, out, np.nan).reshape(S.n, S.n)
    return S, P


def upwind_profile(G, water, H, frm):
    """From the race-area centre looking upwind: open water before the first land (m) and the highest ground (m)."""
    steps = np.arange(CELL, 15000, CELL); fetch, relief = [], []
    for off in (-10.0, 0.0, 10.0):
        th = math.radians(frm + off); E = steps * math.sin(th); N = steps * math.cos(th)
        inside = (np.abs(E) < G.n * CELL / 2) & (np.abs(N) < G.n * CELL / 2)
        r, c = G.index(E[inside], N[inside]); w = water[r, c]; h = H[r, c]
        fetch.append(float(steps[inside][~w][0]) if (~w).any() else float(steps[inside][-1]))
        relief.append(float(h.max()) if h.size else 0.0)
    return int(np.median(fetch)), int(max(relief))


def summarise(S, P, frm):
    """Side-of-course numbers for a beat into a wind from `frm`, inside a 1.2 km x 1.8 km course box."""
    th = math.radians(frm); ue, un = math.sin(th), math.cos(th); le, ln = -un, ue      # upwind and left (looking upwind)
    along = S.E * ue + S.N * un; across = S.E * le + S.N * ln
    box = (np.abs(across) <= 600) & (np.abs(along) <= 900) & ~np.isnan(P)
    def m(mask):
        v = P[mask & box]; return round(float(v.mean()), 3) if v.size >= 8 else None
    left, right = m(across > 0), m(across < 0)
    top, bottom = m(along > 300), m(along < -300)
    # how far the shadow reaches off the windward shore, along the course axis
    ax = []
    for d in np.arange(0, HALF, SHOW):
        r, c = S.index(np.array([d * ue]), np.array([d * un]))
        r, c = int(np.clip(r[0], 0, S.n - 1)), int(np.clip(c[0], 0, S.n - 1)); ax.append(P[r, c])
    ax = np.array(ax, "float32"); shore = int(np.argmax(np.isnan(ax))) if np.isnan(ax).any() else None
    shadow_m = None
    if shore:
        seg = ax[:shore][::-1]                          # from the shore back toward the centre
        k = int(np.argmax(seg >= 0.9)) if (seg >= 0.9).any() else len(seg)
        shadow_m = int(k * SHOW) if k else 0
    water_box = float(box.sum() / max(1, ((np.abs(across) <= 600) & (np.abs(along) <= 900)).sum()))
    return {"from": frm, "mean": m(np.ones_like(box)), "left": left, "right": right, "top": top, "bottom": bottom,
            "shore_upwind_m": int(shore * SHOW) if shore else None, "shadow_m": shadow_m, "low_frac":
            float(np.round(np.mean(P[box] < 0.85), 2)) if box.any() else None, "water_frac": round(water_box, 2)}


def encode(P):
    """One character per 50 m cell, row by row from the north-west: '!' land, else chr(35 + wind% // 2)."""
    return "".join("!" if np.isnan(v) else chr(35 + int(round(min(1.0, max(0.0, v)) * 50))) for v in P.ravel())


def decode(s, n):
    return [[None if ch == "!" else (ord(ch) - 35) * 2 for ch in s[r * n:(r + 1) * n]] for r in range(n)]


def build(club):
    lat, lon, moved = snap(float(club.water_lat), float(club.water_lon))
    G, water, H, wl = surface(lat, lon)
    sectors, grids = [], []
    # the wide grid only reaches HALF + LOOK; read further out for the upwind profile
    for s in range(SECT):
        S, P = pressure(G, water, H, s * 22.5)
        fetch_m, relief_m = upwind_profile(G, water, H, s * 22.5)
        sectors.append({**summarise(S, P, s * 22.5), "fetch_m": fetch_m, "relief_m": relief_m,
                        "cross_fetch_m": None})
        grids.append(encode(P))
    for k, sec in enumerate(sectors):        # long open water along the wind but short across it: a channel
        sec["cross_fetch_m"] = int(min(sectors[(k + 4) % SECT]["fetch_m"], sectors[(k + 12) % SECT]["fetch_m"]))
    return {"club": club.club, "name": club["name"], "lat": round(lat, 5), "lon": round(lon, 5), "moved_m": round(moved),
            "water_level_m": round(wl, 1), "cell_m": SHOW, "size_m": 2 * HALF, "n": int(round(2 * HALF / SHOW)), "sectors": sectors, "grids": grids,
            "source": "ESA WorldCover 2021 (CC BY 4.0), Copernicus DEM GLO-30; bluepuff shelter model"}


def main():
    clubs = pd.read_csv(os.path.join(ROOT, "forecast", "clubs_static.csv"))
    want = sys.argv[1:]
    if want: clubs = clubs[clubs.club.isin(want)]
    os.makedirs(OUT, exist_ok=True)
    def one(r):
        try:
            v = build(r)
            with open(os.path.join(OUT, f"{r.club}.json"), "w") as f: json.dump(v, f, separators=(",", ":"))
            return r.club, "ok"
        except Exception as e: return r.club, f"failed: {e}"
    with ThreadPoolExecutor(6) as ex:
        for club, st in ex.map(one, [r for _, r in clubs.iterrows()]): print(club, st, flush=True)


if __name__ == "__main__":
    main()
