"""Upstream data clients with an on-disk cache.

Every response is saved under backend/cache/, so a place that was analysed once loads
instantly and still works if the venue Wi-Fi drops (Bible 8.3: heavy work offline).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

import httpx

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)
UA = "AI-Climate-SDG-Action-Map/1.0 (Hack4SDG student project, BMS College of Engineering)"

POWER = "https://power.larc.nasa.gov/api/temporal"
MODIS = "https://modis.ornl.gov/rst/api/v1/MOD13Q1"

_client: httpx.AsyncClient | None = None
_limits = {"power.larc.nasa.gov": asyncio.Semaphore(4), "modis.ornl.gov": asyncio.Semaphore(4)}
_nominatim_lock = asyncio.Lock()
_nominatim_last = 0.0


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0),
                                    headers={"User-Agent": UA}, follow_redirects=True)
    return _client


class UpstreamError(RuntimeError):
    pass


async def get_json(url: str, params: dict, ttl: float | None = None, retries: int = 2, cache_if=None):
    """GET JSON with a disk cache. ttl=None caches forever (historical data never changes)."""
    global _nominatim_last
    key = hashlib.sha1((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if path.exists() and (ttl is None or time.time() - path.stat().st_mtime < ttl):
        return json.loads(path.read_text("utf-8"))
    host = httpx.URL(url).host
    err = None
    for attempt in range(retries + 1):
        try:
            if host == "nominatim.openstreetmap.org":  # public policy: max 1 request/second
                async with _nominatim_lock:
                    await asyncio.sleep(max(0.0, 1.1 - (time.time() - _nominatim_last)))
                    r = await client().get(url, params=params)
                    _nominatim_last = time.time()
            elif host in _limits:
                async with _limits[host]:
                    r = await client().get(url, params=params)
            else:
                r = await client().get(url, params=params)
            if r.status_code == 429 or r.status_code >= 500:
                err = f"HTTP {r.status_code}"
                await asyncio.sleep((20 if r.status_code == 429 else 2) * (attempt + 1))  # 429 = rate limit: back off
                continue
            if r.status_code >= 400:  # bad request: retrying will not help
                raise UpstreamError(f"{host} HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            if cache_if is None or cache_if(data):
                path.write_text(json.dumps(data), "utf-8")
            return data
        except UpstreamError:
            raise
        except (httpx.HTTPError, ValueError) as e:
            err = f"{e.__class__.__name__}: {e}"
            await asyncio.sleep(1 + attempt)
    if path.exists():  # stale cache beats no data
        return json.loads(path.read_text("utf-8"))
    raise UpstreamError(f"{host} failed: {err}")


def _ll(lat, lon, nd=2):
    return round(lat, nd), round(lon, nd)


# ---------------------------------------------------------------- NASA POWER
async def power_monthly(lat: float, lon: float) -> dict:
    """Monthly T2M, T2M_MAX, PRECTOTCORR, GWETROOT from 1991 to the last full year."""
    lat, lon = _ll(lat, lon)
    end = date.today().year - 1
    base = {"community": "AG", "latitude": lat, "longitude": lon, "start": 1991, "format": "JSON"}
    for params, last in ((dict(base, parameters="T2M,T2M_MAX,PRECTOTCORR,GWETROOT", end=end), False),
                         (dict(base, parameters="T2M,T2M_MAX,PRECTOTCORR", end=end - 1), True)):
        try:
            return (await get_json(f"{POWER}/monthly/point", params))["properties"]["parameter"]
        except UpstreamError:
            if last:
                raise
    raise UpstreamError("unreachable")


async def power_daily(lat: float, lon: float) -> dict:
    """Daily T2M_MAX + PRECTOTCORR: last 5 full years plus this year up to last month."""
    lat, lon = _ll(lat, lon)
    end = date.today().replace(day=1) - timedelta(days=1)  # last day of previous month (stable cache key)
    params = {"parameters": "T2M_MAX,PRECTOTCORR", "community": "AG", "latitude": lat, "longitude": lon,
              "start": f"{end.year - 5}0101", "end": end.strftime("%Y%m%d"), "format": "JSON"}
    return (await get_json(f"{POWER}/daily/point", params))["properties"]["parameter"]


# ---------------------------------------------------------------- Open-Meteo
async def elevations(points: list[tuple[float, float]]) -> list[float]:
    """Copernicus DEM (GLO-90) via the Open-Meteo Elevation API, 100 points per call."""
    out: list[float] = []
    for i in range(0, len(points), 100):
        if i:
            await asyncio.sleep(12)  # each coordinate counts as one Open-Meteo call (limit ~600/min)
        chunk = points[i:i + 100]
        d = await get_json("https://api.open-meteo.com/v1/elevation",
                           {"latitude": ",".join(f"{p[0]:.4f}" for p in chunk),
                            "longitude": ",".join(f"{p[1]:.4f}" for p in chunk)})
        out += d["elevation"]
    return out


def neighbours(lat: float, lon: float, d: float = 0.01):
    return [(lat, lon), (lat + d, lon), (lat - d, lon), (lat, lon + d), (lat, lon - d)]


async def weather_now(lat: float, lon: float) -> dict:
    lat, lon = _ll(lat, lon)
    d = await get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 7,
        "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
        "daily": "precipitation_sum,temperature_2m_max"}, ttl=1800)
    c, dl = d.get("current", {}), d.get("daily", {})
    rain7 = [v for v in dl.get("precipitation_sum", []) if v is not None]
    tmax7 = [v for v in dl.get("temperature_2m_max", []) if v is not None]
    return {"temperature_c": c.get("temperature_2m"), "humidity": c.get("relative_humidity_2m"),
            "wind_kmh": c.get("wind_speed_10m"), "precip_mm": c.get("precipitation"),
            "next7d_rain_mm": round(sum(rain7), 1) if rain7 else None,
            "next7d_tmax_c": max(tmax7) if tmax7 else None, "time": c.get("time")}


async def search(q: str) -> list[dict]:
    d = await get_json("https://geocoding-api.open-meteo.com/v1/search",
                       {"name": q, "count": 8, "language": "en", "format": "json"}, ttl=30 * 86400)
    return [{"name": r["name"], "admin1": r.get("admin1"), "country": r.get("country"),
             "country_code": r.get("country_code"), "lat": r["latitude"], "lon": r["longitude"],
             "population": r.get("population")} for r in d.get("results", [])]


# ---------------------------------------------------------------- OpenStreetMap (Nominatim)
async def place_name(lat: float, lon: float) -> str | None:
    lat, lon = _ll(lat, lon, 3)
    d = await get_json("https://nominatim.openstreetmap.org/reverse",
                       {"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 14, "accept-language": "en"})
    a = d.get("address", {})
    local = next((a[k] for k in ("suburb", "neighbourhood", "village", "town", "city_district", "city", "county") if a.get(k)), None)
    region = next((a[k] for k in ("city", "state_district", "state") if a.get(k) and a.get(k) != local), None)
    return ", ".join(x for x in (local, region) if x) or d.get("display_name")


# ---------------------------------------------------------------- MODIS NDVI (ORNL DAAC)
_STEP = 16  # MOD13Q1 16-day composites start on day-of-year 1, 17, 33, ...


async def _modis_dates(lat: float, lon: float) -> list[str]:
    try:
        d = await get_json(f"{MODIS}/dates", {"latitude": lat, "longitude": lon}, ttl=7 * 86400)
        dates = [x["modis_date"] for x in d.get("dates", [])]
        if dates:
            return sorted(dates)
    except UpstreamError:
        pass
    t = date.today() - timedelta(days=30)  # fallback: assume ~1 month processing lag
    doy = (t.timetuple().tm_yday - 1) // _STEP * _STEP + 1
    out, y = [], t.year
    for _ in range(6):
        out.append(f"A{y}{doy:03d}")
        doy -= _STEP
        if doy < 1:
            y -= 1
            doy = 353
    return sorted(out)


async def _ndvi_window(lat, lon, start: str, end: str):
    d = await get_json(f"{MODIS}/subset", {"latitude": lat, "longitude": lon, "band": "250m_16_days_NDVI",
                                          "startDate": start, "endDate": end, "kmAboveBelow": 1, "kmLeftRight": 1})
    vals = []
    for s in d.get("subset", []):
        good = [v for v in s.get("data", []) if v is not None and v > -2000]  # -3000 = fill
        if good:
            vals.append(mean(good) * float(d.get("scale") or 0.0001))
    return (mean(vals), d["subset"][-1]["calendar_date"]) if vals else (None, None)


async def ndvi(lat: float, lon: float) -> dict:
    """Mean NDVI of the latest ~2 months (3x3 km window) and its anomaly vs the same season in the 3 previous years."""
    lat, lon = _ll(lat, lon, 3)
    dates = (await _modis_dates(lat, lon))[-4:]
    first, last = dates[0], dates[-1]
    cur, as_of = await _ndvi_window(lat, lon, first, last)
    shifted = [(f"A{int(first[1:5]) - k}{first[5:]}", f"A{int(last[1:5]) - k}{last[5:]}") for k in (1, 2, 3)]
    past = await asyncio.gather(*[_ndvi_window(lat, lon, s, e) for s, e in shifted], return_exceptions=True)
    base = [p[0] for p in past if not isinstance(p, BaseException) and p[0] is not None]
    return {"ndvi": cur, "ndvi_anom": (cur - mean(base)) if (cur is not None and base) else None, "as_of": as_of}


# ---------------------------------------------------------------- WorldPop
async def population_density(lat: float, lon: float, half: float = 0.01) -> float | None:
    """People per km² in a ~2.2 km square (WorldPop 100 m, 2020)."""
    lat, lon = _ll(lat, lon, 3)
    ring = [[lon - half, lat - half], [lon + half, lat - half], [lon + half, lat + half],
            [lon - half, lat + half], [lon - half, lat - half]]
    geo = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                                                      "geometry": {"type": "Polygon", "coordinates": [ring]}}]}
    d = await get_json("https://api.worldpop.org/v1/services/stats",
                       {"dataset": "wpgppop", "year": 2020, "geojson": json.dumps(geo, separators=(",", ":")),
                        "runasync": "false"},
                       cache_if=lambda r: (r.get("data") or {}).get("total_population") is not None)
    total = (d.get("data") or {}).get("total_population")
    if total is None and d.get("taskid"):  # service answered asynchronously: poll briefly
        for _ in range(8):
            await asyncio.sleep(1.5)
            t = (await client().get(f"https://api.worldpop.org/v1/tasks/{d['taskid']}")).json()
            total = (t.get("data") or {}).get("total_population")
            if total is not None or t.get("error"):
                break
    if total is None:
        return None
    side = 2 * half * 111.32
    return float(total) / (side * side * math.cos(math.radians(lat)))
