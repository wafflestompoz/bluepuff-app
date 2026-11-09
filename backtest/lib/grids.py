"""Grid definitions for Open-Meteo open-data (.om) models on AWS (s3://openmeteo, CC BY 4.0)."""
import numpy as np, math

class Regular:
    def __init__(s, ny, nx, lat0, lon0, dlat, dlon):
        s.ny, s.nx, s.lat0, s.lon0, s.dlat, s.dlon = ny, nx, lat0, lon0, dlat, dlon
    def index(s, lat, lon):
        y = int(round((lat - s.lat0) / s.dlat)); x = int(round((lon - s.lon0) / s.dlon))
        if not (0 <= y < s.ny and 0 <= x < s.nx): return None
        return y, x
    def latlon(s, y, x): return s.lat0 + y * s.dlat, s.lon0 + x * s.dlon
    def flat(s, yx): return yx[0] * s.nx + yx[1]

class GaussianO:
    """Octahedral reduced Gaussian grid (ECMWF O1280). Rows north->south, row k has 4k+16 pts (k=1..N), mirrored."""
    def __init__(s, N):
        s.N = N
        nlon = [4 * k + 16 for k in range(1, N + 1)]
        s.nlon = np.array(nlon + nlon[::-1])
        s.offset = np.concatenate([[0], np.cumsum(s.nlon)[:-1]])
        # gaussian latitudes approx (accurate to << grid spacing)
        n = 2 * N
        s.lats = np.array([90 - (i + 0.5) * 180 / n for i in range(n)])
        s.ny = n
    def index(s, lat, lon):
        y = int(np.argmin(np.abs(s.lats - lat)))
        nl = s.nlon[y]; x = int(round(((lon % 360) / 360) * nl)) % nl
        return y, x
    def latlon(s, y, x):
        lon = x * 360 / s.nlon[y]; return s.lats[y], (lon + 180) % 360 - 180
    def flat(s, yx): return int(s.offset[yx[0]] + yx[1])

GRIDS = {
    "copernicus_era5": Regular(721, 1440, -90, -180, 0.25, 0.25),
    "ecmwf_ifs025": Regular(721, 1440, -90, -180, 0.25, 0.25),
    "ecmwf_ifs": GaussianO(1280),
    "dwd_icon_eu": Regular(657, 1377, 29.5, -23.5, 0.0625, 0.0625),
    "dwd_icon_d2": Regular(746, 1215, 43.18, -3.94, 0.02, 0.02),
    "ukmo_global_deterministic_10km": Regular(1920, 2560, -90, -180, 180 / 1920, 360 / 2560),
    "meteofrance_arome_france0025": Regular(717, 1121, 37.5, -12.0, 0.025, 0.025),
    "meteofrance_arpege_europe": Regular(521, 741, 20.0, -32.0, 0.1, 0.1),
    "italia_meteo_arpae_icon_2i": Regular(761, 761, 33.7, 3.0, 0.02, 0.025),
    "geosphere_arome_austria": Regular(492, 594, 42.981, 5.498, 0.018, 0.028),
}
