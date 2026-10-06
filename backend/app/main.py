"""FastAPI backend for the AI Climate & SDG Action Map.

Run from backend/:   .venv\\Scripts\\python -m uvicorn app.main:app --port 8000
Live API docs (proof for judges): /docs
AI explanations use Pollinations (free, no key). Optional: Google Gemini with GEMINI_API_KEY. Put GEMINI_API_KEY in backend/.env locally,
or in Render's env vars.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine as eng
from . import sources as src

ROOT = Path(__file__).resolve().parent.parent
for _line in (ROOT / ".env").read_text("utf-8").splitlines() if (ROOT / ".env").exists() else []:
    if "=" in _line and not _line.lstrip().startswith("#"):  # tiny .env loader (no extra dependency)
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"'))

AI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"  # Gemini, OpenAI-compatible
AI_MODELS = [m for m in (os.getenv("GEMINI_MODEL"), "gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite") if m]
BBOX = (6.0, 37.6, 68.0, 97.6)  # MVP coverage: India region (lat_min, lat_max, lon_min, lon_max)

_analyses: dict = {}
_ai_cache: dict = {}


app = FastAPI(title="AI Climate & SDG Action Map API", version="1.0",
              description="Environmental data → risk engine (hazard + exposure + vulnerability) → SDG rulebook → "
                          "interventions → what-if → AI explanation. Scores are relative indicators for "
                          "prioritisation, not forecasts.")


def _check(lat: float, lon: float):
    if not (BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lon <= BBOX[3]):
        raise HTTPException(404, "Outside MVP coverage (India region). Pick a place in India.")


async def _safe(coro):
    try:
        return await coro
    except Exception as e:  # one failing source must never kill the whole analysis
        return e


async def analyze(lat: float, lon: float, name: str | None = None) -> dict:
    """One shared task per place: parallel requests reuse it, and finished tasks act as the cache."""
    key = (round(lat, 3), round(lon, 3))
    if key not in _analyses:
        _analyses[key] = asyncio.ensure_future(_compute(lat, lon, name))
    try:
        a = await _analyses[key]
    except Exception:
        _analyses.pop(key, None)  # let the next click retry
        raise
    if name:
        a["location"]["name"] = name
    return a


async def _compute(lat: float, lon: float, name: str | None) -> dict:
    t0 = time.time()
    mon, day, elev, veg, dens, wx, place = await asyncio.gather(
        _safe(src.power_monthly(lat, lon)), _safe(src.power_daily(lat, lon)),
        _safe(src.elevations(src.neighbours(lat, lon))), _safe(src.ndvi(lat, lon)),
        _safe(src.population_density(lat, lon)), _safe(src.weather_now(lat, lon)),
        _safe(src.place_name(lat, lon)) if not name else asyncio.sleep(0, name))
    ok = {k: not isinstance(v, Exception) for k, v in
          dict(mon=mon, day=day, elev=elev, veg=veg, dens=dens, wx=wx).items()}
    if not ok["mon"] and not ok["day"]:
        raise HTTPException(503, f"NASA POWER unavailable and nothing cached for this place ({mon}). Try again.")
    elevs = elev if ok["elev"] else None
    m = eng.monthly_indicators(mon) if ok["mon"] else {"history": [], "baseline": {}}
    d = eng.daily_indicators(day, elevs[0] if elevs else None) if ok["day"] else {}
    ter = eng.terrain(elevs, lat) if elevs else {}
    v = veg if ok["veg"] else {}
    ind = eng.combine_indicators(m, d, ter, ndvi=v.get("ndvi"), ndvi_anom=v.get("ndvi_anom"),
                                 pop_density=dens if ok["dens"] else None)
    norms = eng.load_norms()
    risks = eng.assess(ind, norms)
    scores = {h: r["score"] for h, r in risks.items()}
    ov = eng.overall(scores)
    sdgs = eng.sdg_impact(scores)
    a = {
        "location": {"lat": lat, "lon": lon, "elevation_m": ter.get("elev"),
                     "name": (place if isinstance(place, str) and place else f"{lat:.3f}°N, {lon:.3f}°E")},
        "as_of": date.today().isoformat(),
        "weather": wx if ok["wx"] else None,
        "overall": ov,
        "risks": risks,
        "sdg_impact": sdgs,
        "sdg_names": {str(k): n for k, n in eng.SDG_NAMES.items()},
        "sdg_tags": {str(k): t for k, t in eng.SDG_TAGS.items()},
        "interventions": eng.recommend(risks),
        "history": {"series": m.get("history", []), "baseline": m.get("baseline", {}),
                    "trend_c_decade": None if m.get("trend_c_decade") is None else round(m["trend_c_decade"], 2)},
        "indicators": {k: (round(x, 3) if isinstance(x, float) else x) for k, x in ind.items()},
        "data_sources": [
            {"name": "NASA POWER (MERRA-2), monthly 1991-present", "used_for": "Temperature anomaly, rainfall normal, soil wetness, history", "ok": ok["mon"]},
            {"name": "NASA POWER (MERRA-2), daily last 5+ years", "used_for": "Hot days, extreme 1-day rain, last-12-month rainfall (SPI)", "ok": ok["day"]},
            {"name": "Copernicus DEM GLO-90 via Open-Meteo", "used_for": "Elevation, relative lowness, slope", "ok": ok["elev"]},
            {"name": f"NASA MODIS MOD13Q1 NDVI 250 m (ORNL DAAC){', ' + v['as_of'] if v.get('as_of') else ''}", "used_for": "Vegetation / built-up proxy, NDVI anomaly", "ok": ok["veg"] and v.get("ndvi") is not None},
            {"name": "WorldPop 2020, 100 m (modelled)", "used_for": "Population exposure", "ok": ok["dens"] and dens is not None},
            {"name": "Open-Meteo forecast", "used_for": "Live weather (display only, not in scores)", "ok": ok["wx"]},
        ],
        "weights": eng.WEIGHTS,
        "norms": "India grid p5-p95" if eng.NORMS_FILE.exists() else "default ranges",
        "confidence": min((r["confidence"] for r in risks.values()), key=["low", "medium", "high"].index),
        "is_demo": False,
        "elapsed_s": round(time.time() - t0, 1),
    }
    a["explanation"] = eng.explain_template(a)
    a["_ind"] = ind
    return a


def _public(a: dict) -> dict:
    return {k: v for k, v in a.items() if not k.startswith("_")}


@app.get("/api/health")
async def health():
    return {"ok": True, "ai": True, "model": AI_MODELS[0] if os.getenv("GEMINI_API_KEY") else "pollinations",
            "norms": "India grid" if eng.NORMS_FILE.exists() else "default"}


@app.get("/api/search")
async def search(q: str = Query(min_length=2, max_length=80)):
    try:
        res = await src.search(q)
    except src.UpstreamError as e:
        raise HTTPException(503, str(e))
    res = [r for r in res if BBOX[0] <= r["lat"] <= BBOX[1] and BBOX[2] <= r["lon"] <= BBOX[3]]
    return sorted(res, key=lambda r: (r["country_code"] != "IN", -(r["population"] or 0)))


@app.get("/api/location")
async def location(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
                   name: str | None = Query(None, max_length=120)):
    """Everything for the side panel in one call: risks + drivers, SDG relevance, actions, history."""
    _check(lat, lon)
    return _public(await analyze(lat, lon, name))


class SimReq(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    intervention: Literal["urban_greening", "drainage"]
    amount: float = Field(ge=0, le=100)


@app.post("/api/simulation")
async def simulation(req: SimReq):
    """Re-run the same risk + SDG models with an intervention (low / central / high assumption)."""
    _check(req.lat, req.lon)
    a = await analyze(req.lat, req.lon)
    return eng.simulate(a["_ind"], req.intervention, req.amount)


class ExplainReq(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    intervention: Literal["urban_greening", "drainage"] | None = None
    amount: float | None = Field(None, ge=0, le=100)


def _line(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode()


@app.post("/api/explain")
async def explain(req: ExplainReq):
    """Grounded AI explanation, streamed as NDJSON: {"t": token}... then {"done": true, "valid": bool}."""
    _check(req.lat, req.lon)
    a = await analyze(req.lat, req.lon)
    sim = eng.simulate(a["_ind"], req.intervention, req.amount or 15) if req.intervention else None
    facts = eng.fact_sheet(a, sim)
    key = (round(req.lat, 3), round(req.lon, 3), req.intervention, req.amount)
    fallback = eng.explain_template(a, sim)

    async def gen():
        if key in _ai_cache:
            yield _line({"t": _ai_cache[key]})
            yield _line({"done": True, "valid": True, "cached": True})
            return
        key_ = os.getenv("GEMINI_API_KEY")
        msgs = [{"role": "system", "content": eng.AI_RULES},
                {"role": "user", "content": "FACTS:\n" + json.dumps(facts, ensure_ascii=False) +
                 "\n\nExplain this place's climate risk, why, its SDG relevance and the suggested actions."}]
        text, model, err = "", None, None
        if not key_:  # no key: Pollinations free text API (no signup, ~1 request / 15 s)
            model = "pollinations"
            try:
                r = await src.client().post("https://text.pollinations.ai/", json={"messages": msgs, "model": "openai"},
                                            timeout=60.0)
                r.raise_for_status()
                text = r.text.strip()
                if text.startswith("{"):  # OpenAI-style JSON answer
                    text = (json.loads(text).get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
                yield _line({"t": text})
            except Exception as e:
                err = e.__class__.__name__
        for model in ([] if not key_ else AI_MODELS):  # fall back to the next model if one is retired or rate-limited
            try:
                async with src.client().stream("POST", AI_URL, headers={"Authorization": f"Bearer {key_}"},
                                               json={"model": model, "messages": msgs, "stream": True,
                                                     "temperature": 0.2, "max_tokens": 260},
                                               timeout=httpx.Timeout(60.0, connect=5.0)) as r:
                    if r.status_code != 200:
                        err = f"HTTP {r.status_code}"
                        continue
                    async for raw in r.aiter_lines():
                        if not raw.startswith("data:"):
                            continue
                        data = raw[5:].strip()
                        if data == "[DONE]":
                            break
                        tok = (json.loads(data).get("choices") or [{}])[0].get("delta", {}).get("content") or ""
                        if tok:
                            text += tok
                            yield _line({"t": tok})
                err = None
                break
            except Exception as e:
                err = e.__class__.__name__
                if text:
                    break
        if err and not text:
            yield _line({"error": f"Online AI unavailable ({err}), showing the rule-based explanation.",
                         "fallback": fallback})
            return
        bad = eng.validate_numbers(text, facts)
        if bad or not text.strip():
            yield _line({"done": True, "valid": False, "bad_numbers": bad, "fallback": fallback, "model": model})
        else:
            _ai_cache[key] = text
            yield _line({"done": True, "valid": True, "model": model})

    return StreamingResponse(gen(), media_type="application/x-ndjson")


# Serve the built React site (frontend/dist) from the same server, so one URL hosts everything.
_DIST = ROOT.parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="site")
