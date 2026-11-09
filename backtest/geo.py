"""Water and terrain around each club's station and water point, from open rasters on AWS:
ESA WorldCover 2021 10 m land cover (s3://esa-worldcover, CC BY 4.0; class 80 = permanent water, missing tiles = sea) and
Copernicus DEM GLO-30 (s3://copernicus-dem-30m, free licence; missing tiles = sea). Read at ~100 m through the COG overviews.
Writes data/geo.parquet: one row per club with, for 'st' (station) and 'water' (race area):
  wf{a}_{b}_{s}: water fraction along the ray toward sector s (16 x 22.5 deg, the direction the wind comes FROM) between a and b km
  relief_{s}   : highest ground in sector s within 15 km minus the point's height (m)
  shore_km, water_r1/r5/r20 (water fraction in a radius), elev, rough10 (std of height within 10 km)"""
import os, math, numpy as np, pandas as pd, rasterio
from rasterio.merge import merge
from concurrent.futures import ThreadPoolExecutor
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR"); os.environ.setdefault("CURL_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
HERE = os.path.dirname(os.path.abspath(__file__))
RES = 0.001; HALF_KM = 32; SECT = 16; BANDS = [(0, 2), (2, 10), (10, 30)]
def wc_url(la, lo): return f"/vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{'N' if la>=0 else 'S'}{abs(la):02d}{'E' if lo>=0 else 'W'}{abs(lo):03d}_Map.tif"
def dem_url(la, lo):
    n = f"Copernicus_DSM_COG_10_{'N' if la>=0 else 'S'}{abs(la):02d}_00_{'E' if lo>=0 else 'W'}{abs(lo):03d}_00_DEM"
    return f"/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/{n}/{n}.tif"

def mosaic(lat, lon, kind):
    dlat = HALF_KM / 111.0; dlon = HALF_KM / (111.0 * math.cos(math.radians(lat)))
    b = (lon - dlon, lat - dlat, lon + dlon, lat + dlat)
    step = 3 if kind == "wc" else 1
    tiles = {(math.floor(y / step) * step, math.floor(x / step) * step) for y in (b[1], b[3]) for x in (b[0], b[2])}
    srcs = []
    for la, lo in tiles:
        try: srcs.append(rasterio.open(wc_url(la, lo) if kind == "wc" else dem_url(la, lo)))
        except Exception: pass                       # no tile = open sea
    ny, nx = int(round((b[3] - b[1]) / RES)), int(round((b[2] - b[0]) / RES))
    fill = 80 if kind == "wc" else 0
    if not srcs: return np.full((ny, nx), fill, "float32"), b
    a, _ = merge(srcs, bounds=b, res=RES, nodata=0 if kind == "wc" else -9999, resampling=rasterio.enums.Resampling.nearest)
    for s in srcs: s.close()
    a = a[0].astype("float32")[:ny, :nx]
    a[a == (0 if kind == "wc" else -9999)] = fill
    return a, b

def feats(lat, lon):
    W, b = mosaic(lat, lon, "wc"); H, _ = mosaic(lat, lon, "dem"); W = (W == 80).astype("float32")
    ny, nx = W.shape; kx = 111.0 * math.cos(math.radians(lat)) * RES; ky = 111.0 * RES     # km per pixel
    cy, cx = int((b[3] - lat) / RES), int((lon - b[0]) / RES)                               # rows run north -> south
    def at(A, dist_km, brg):
        y = cy - dist_km * math.cos(math.radians(brg)) / ky; x = cx + dist_km * math.sin(math.radians(brg)) / kx
        yi, xi = int(round(y)), int(round(x))
        return A[yi, xi] if 0 <= yi < ny and 0 <= xi < nx else np.nan
    f = {}
    for s in range(SECT):
        brgs = [s * 22.5 + o for o in (-7.5, 0, 7.5)]
        for a0, a1 in BANDS:
            d = np.arange(a0 + 0.1, a1, 0.2)
            f[f"wf{a0}_{a1}_{s}"] = float(np.nanmean([at(W, x, g) for x in d for g in brgs]))
        f[f"relief_{s}"] = float(np.nanmax([at(H, x, g) for x in np.arange(0.2, 15, 0.2) for g in brgs]) - H[cy, cx])
    for s in range(SECT):   # fetch: open water upwind before the first land (km, median of 3 rays, capped at the window ~30 km)
        fs = []
        for g in (s * 22.5 - 7.5, s * 22.5, s * 22.5 + 7.5):
            d = 0.1
            while d < HALF_KM - 1 and at(W, d, g) == 1: d += 0.1
            fs.append(d)
        f[f"fetch_{s}"] = float(np.median(fs))
    yy, xx = np.mgrid[0:ny, 0:nx]; dk = np.hypot((yy - cy) * ky, (xx - cx) * kx)
    for r in (1, 5, 20): f[f"water_r{r}"] = float(W[dk <= r].mean())
    shore = dk[W != W[cy, cx]]; f["shore_km"] = float(shore.min()) if shore.size else 30.0
    f["on_water"] = float(W[cy, cx]); f["elev"] = float(H[cy, cx]); f["rough10"] = float(H[dk <= 10].std())
    return f

def snap(lat, lon, max_km=6):
    """Move a race-area point that landed on land to the nearest open water (>= 80% water within ~1 km)."""
    from scipy.ndimage import uniform_filter
    W, b = mosaic(lat, lon, "wc"); W = (W == 80).astype("float32"); open_ = uniform_filter(W, 15) >= 0.8
    cy, cx = int((b[3] - lat) / RES), int((lon - b[0]) / RES)
    if open_[cy, cx]: return lat, lon, 0.0
    kx = 111.0 * math.cos(math.radians(lat)) * RES; ky = 111.0 * RES
    yy, xx = np.nonzero(open_); d = np.hypot((yy - cy) * ky, (xx - cx) * kx)
    if not d.size or d.min() > max_km: return lat, lon, float("nan")
    i = d.argmin(); return b[3] - yy[i] * RES, b[0] + xx[i] * RES, float(d[i])

def main_all():
    """ALL=1: station point only, for every station in all_stations.csv -> data/all/geo.parquet"""
    A = pd.read_csv(f"{HERE}/all_stations.csv")
    def one(r):
        try: return {"club": r.id} | {f"st_{k}": v for k, v in feats(r.lat, r.lon).items()}
        except Exception as e: print("fail", r.id, e); return {"club": r.id}
    with ThreadPoolExecutor(12) as ex: rows = list(ex.map(one, A.itertuples()))
    os.makedirs(f"{HERE}/data/all", exist_ok=True); pd.DataFrame(rows).to_parquet(f"{HERE}/data/all/geo.parquet", index=False); print("geo", len(rows))

def main():
    if os.environ.get("ALL") == "1": return main_all()
    C = pd.read_csv(f"{HERE}/clubs.csv"); S = pd.read_csv(f"{HERE}/stations.csv")
    H = pd.read_csv(os.environ.get("ISD_HISTORY", "/tmp/claude-0/sail/isd-history.csv"), dtype=str); H["station"] = H.USAF + "-" + H.WBAN
    S = S.merge(H[["station", "LAT", "LON"]], on="station").merge(C, left_on="club", right_on="id")
    def one(r):
        row = {"club": r.club}
        wl, wo, moved = snap(r.lat, r.lon); row |= {"water_lat": wl, "water_lon": wo, "water_moved_km": moved}
        for name, la, lo in (("st", float(r.LAT), float(r.LON)), ("water", wl, wo)):
            row |= {f"{name}_{k}": v for k, v in feats(la, lo).items()}
        return row
    with ThreadPoolExecutor(8) as ex: rows = list(ex.map(one, S.itertuples()))
    G = pd.DataFrame(rows); G.to_parquet(f"{HERE}/data/geo.parquet", index=False)
    print(G[["club", "water_moved_km", "st_on_water", "st_shore_km", "st_water_r5", "water_on_water", "water_shore_km", "water_water_r5", "st_rough10"]].round(2).to_string())

if __name__ == "__main__":
    main()
