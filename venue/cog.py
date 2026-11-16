"""Minimal reader for tiled GeoTIFFs (COGs) over HTTP range requests: enough for ESA WorldCover and the Copernicus DEM
on AWS, without GDAL. Supports DEFLATE/LZW-free (deflate or none) compression, horizontal and floating-point predictors,
and the overview levels."""
import struct, zlib, functools, numpy as np, requests

S = requests.Session()
TYPES = {1: ("B", 1), 2: ("c", 1), 3: ("H", 2), 4: ("I", 4), 5: ("II", 8), 11: ("f", 4), 12: ("d", 8), 16: ("Q", 8)}


def get(url, a, n):
    r = S.get(url, headers={"Range": f"bytes={a}-{a + n - 1}"}, timeout=30)
    if r.status_code == 404 or r.status_code == 403: raise FileNotFoundError(url)
    r.raise_for_status(); return r.content


class COG:
    def __init__(self, url):
        self.url = url; h = get(url, 0, 65536); self.h = h
        bo = h[:2]; self.e = "<" if bo == b"II" else ">"
        magic = struct.unpack(self.e + "H", h[2:4])[0]
        self.big = magic == 43
        off = struct.unpack(self.e + ("Q" if self.big else "I"), h[8:16] if self.big else h[4:8])[0]
        self.ifds = []
        while off:
            ifd, off = self._ifd(off); self.ifds.append(ifd)
        t = self.ifds[0]
        self.scale = t[33550][:2]; tp = t[33922]; self.origin = (tp[3], tp[4])     # pixel size (x, y), top-left (x, y)

    def _bytes(self, a, n):
        if a + n <= len(self.h): return self.h[a:a + n]
        return get(self.url, a, n)

    def _ifd(self, off):
        e = self.e; big = self.big
        n = struct.unpack(e + ("Q" if big else "H"), self._bytes(off, 8 if big else 2))[0]
        esz = 20 if big else 12; raw = self._bytes(off + (8 if big else 2), n * esz + 8)
        tags = {}
        for i in range(n):
            b = raw[i * esz:(i + 1) * esz]
            tag, typ = struct.unpack(e + "HH", b[:4])
            cnt = struct.unpack(e + ("Q" if big else "I"), b[4:12] if big else b[4:8])[0]
            fmt, sz = TYPES.get(typ, ("B", 1)); total = sz * cnt
            val = b[12:20] if big else b[8:12]
            if total > (8 if big else 4):
                p = struct.unpack(e + ("Q" if big else "I"), val)[0]; data = self._bytes(p, total)
            else: data = val[:total]
            if typ == 2: tags[tag] = data
            else:
                f = fmt[0] if fmt != "II" else "I"; k = cnt * (2 if typ == 5 else 1)
                tags[tag] = list(struct.unpack(e + f * k, data[:struct.calcsize(f) * k]))
        nxt_raw = raw[n * esz:n * esz + (8 if big else 4)]
        nxt = struct.unpack(e + ("Q" if big else "I"), nxt_raw)[0]
        return tags, nxt

    def level(self, k):
        t = self.ifds[k]
        return dict(w=t[256][0], h=t[257][0], tw=t[322][0], th=t[323][0], offs=t[324], cnts=t[325], comp=t.get(259, [1])[0],
                    pred=t.get(317, [1])[0], bits=t[258][0], fmt=t.get(339, [1])[0], nodata=t.get(42113))

    @functools.lru_cache(maxsize=512)
    def tile(self, k, ti):
        L = self.level(k); n = L["cnts"][ti]
        dt = {(8, 1): "u1", (16, 1): "u2", (16, 2): "i2", (32, 3): "f4", (32, 2): "i4"}[(L["bits"], L["fmt"])]
        if n == 0: return np.zeros((L["th"], L["tw"]), dt)
        b = get(self.url, L["offs"][ti], n)
        if L["comp"] in (8, 32946): b = zlib.decompress(b)
        elif L["comp"] != 1: raise NotImplementedError(f"compression {L['comp']}")
        if L["pred"] == 3:          # floating point predictor: byte-shuffled rows with horizontal differencing
            sz = L["bits"] // 8; a = np.frombuffer(b, "u1").reshape(L["th"], L["tw"] * sz)
            a = np.cumsum(a, axis=1, dtype="u1")
            a = a.reshape(L["th"], sz, L["tw"]).transpose(0, 2, 1)      # bytes are stored most significant first
            return np.ascontiguousarray(a).view(">" + dt).reshape(L["th"], L["tw"]).astype(dt)
        a = np.frombuffer(b, self.e + dt).reshape(L["th"], L["tw"])
        if L["pred"] == 2: a = np.cumsum(a, axis=1, dtype=a.dtype)
        return a

    def window(self, x0, y0, x1, y1, k=0):
        """Pixels covering geographic box (lon x0..x1, lat y0..y1) at overview k; returns array and its bounds."""
        L = self.level(k); f = self.level(0)["w"] / L["w"]
        sx, sy = self.scale[0] * f, self.scale[1] * f; ox, oy = self.origin
        c0 = max(0, int((x0 - ox) / sx)); c1 = min(L["w"], int(np.ceil((x1 - ox) / sx)))
        r0 = max(0, int((oy - y1) / sy)); r1 = min(L["h"], int(np.ceil((oy - y0) / sy)))
        out = np.zeros((max(0, r1 - r0), max(0, c1 - c0)), self.tile(k, 0).dtype)
        tx = (L["w"] + L["tw"] - 1) // L["tw"]
        for tr in range(r0 // L["th"], (r1 - 1) // L["th"] + 1 if r1 > r0 else 0):
            for tc in range(c0 // L["tw"], (c1 - 1) // L["tw"] + 1 if c1 > c0 else 0):
                T = self.tile(k, tr * tx + tc)
                ar0, ac0 = tr * L["th"], tc * L["tw"]
                rs, re_ = max(r0, ar0), min(r1, ar0 + L["th"]); cs, ce = max(c0, ac0), min(c1, ac0 + L["tw"])
                out[rs - r0:re_ - r0, cs - c0:ce - c0] = T[rs - ar0:re_ - ar0, cs - ac0:ce - ac0]
        return out, (ox + c0 * sx, oy - r1 * sy, ox + c1 * sx, oy - r0 * sy)
