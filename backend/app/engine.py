"""Risk, SDG, recommendation and scenario engines for the AI Climate & SDG Action Map.

Pure Python (standard library only) so every number is traceable and testable.
Model spec = Project Bible ch. 9-12:

    Risk (0-100) = 100 x (wH*H + wE*E + wV*V)      H, E, V each scaled 0-1

Run `python -m app.engine` from backend/ for the self-check.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import mean, pstdev

WEIGHTS = {"heat": (0.40, 0.25, 0.35), "flood": (0.45, 0.25, 0.30), "drought": (0.45, 0.20, 0.35)}
HAZARDS = ("heat", "flood", "drought")
BASELINE = (1991, 2020)
FILL = -900  # NASA POWER marks missing values with -999
DISCLAIMER = "Model-based estimate under stated assumptions, not a guaranteed outcome."

# (p5, p95) normalisation ranges. These defaults are India-wide starting values;
# scripts/build_grid.py replaces them with real percentiles from the national grid.
DEFAULT_NORMS = {
    "txx_anom": (0.0, 2.0),        # deg C, recent hottest-month max temp vs 1991-2020
    "hw_days": (0.0, 40.0),        # days/yr at or above the IMD-style threshold
    "rx1day": (30.0, 150.0),       # mm, average annual max 1-day rainfall
    "elev": (0.0, 300.0),          # m, inverted (lower = more flood-prone)
    "rel_low": (0.0, 10.0),        # m below the surrounding terrain
    "slope": (0.2, 5.0),           # %, inverted (flatter = more flood-prone)
    "spi_deficit": (0.0, 1.5),     # -z of the last 12 months' rainfall
    "aridity": (300.0, 1500.0),    # mm/yr normal rainfall, inverted
    "t_anom": (0.0, 1.5),          # deg C, recent annual mean temp vs 1991-2020
}
NORMS_FILE = Path(__file__).resolve().parent.parent / "data" / "norms.json"


def load_norms() -> dict:
    norms = dict(DEFAULT_NORMS)
    try:
        saved = json.loads(NORMS_FILE.read_text("utf-8"))
        norms.update({k: tuple(v) for k, v in saved.items() if k in norms})
    except (OSError, ValueError):
        pass
    return norms


def scale(x, lo, hi, invert=False):
    """Min-max to [0, 1] with clipping (Bible 9.2)."""
    if x is None:
        return None
    t = 0.0 if hi == lo else min(1.0, max(0.0, (x - lo) / (hi - lo)))
    return 1.0 - t if invert else t


def wavg(parts):
    """Weighted mean of (weight, value) pairs, skipping missing values."""
    got = [(w, v) for w, v in parts if v is not None]
    if not got:
        return None
    return sum(w * v for w, v in got) / sum(w for w, _ in got)


def risk_class(score):
    if score is None:
        return "Insufficient data"
    for lo, name in ((80, "Very High"), (60, "High"), (40, "Moderate"), (20, "Low")):
        if score >= lo:
            return name
    return "Very Low"


def risk_score(hazard: str, H: float, E: float, V: float) -> int:
    wH, wE, wV = WEIGHTS[hazard]
    return round(100 * (wH * H + wE * E + wV * V))


# ---------------------------------------------------------------- indicators
DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _ok(v):
    return v is not None and v > FILL


def monthly_indicators(par: dict) -> dict:
    """From NASA POWER monthly 'parameter' block: {'T2M': {'199101': v, ..., '199113': v}}."""
    t2m, txx, rain, gwet = {}, {}, {}, {}
    months = {}
    for name in ("T2M", "T2M_MAX", "PRECTOTCORR", "GWETROOT"):
        for k, v in par.get(name, {}).items():
            m = int(k[4:])
            if 1 <= m <= 12 and _ok(v):
                months.setdefault(name, {}).setdefault(int(k[:4]), {})[m] = v
    pr_vals = [v for y in months.get("PRECTOTCORR", {}).values() for v in y.values()]
    pr_is_total = bool(pr_vals) and sorted(pr_vals)[len(pr_vals) // 2] > 60  # guard: mm/month vs mm/day
    for y, ms in months.get("T2M", {}).items():
        if len(ms) == 12:
            t2m[y] = mean(ms.values())
    for y, ms in months.get("T2M_MAX", {}).items():
        if len(ms) == 12:
            txx[y] = max(ms.values())
    for y, ms in months.get("PRECTOTCORR", {}).items():
        if len(ms) == 12:
            rain[y] = sum(v if pr_is_total else v * DAYS[m - 1] for m, v in ms.items())
    for y, ms in months.get("GWETROOT", {}).items():
        if len(ms) == 12:
            gwet[y] = mean(ms.values())

    def base(d):
        vals = [d[y] for y in range(BASELINE[0], BASELINE[1] + 1) if y in d]
        return vals if len(vals) >= 20 else None

    def recent(d):
        return [d[y] for y in sorted(d)[-5:]] if len(d) >= 25 else None

    out = {"t_anom": None, "txx_anom": None, "txx_recent": None, "rain_normal": None,
           "rain_sd": None, "aridity": None, "gwet": None, "trend_c_decade": None}
    if base(t2m) and recent(t2m):
        out["t_anom"] = mean(recent(t2m)) - mean(base(t2m))
    if base(txx) and recent(txx):
        out["txx_anom"] = mean(recent(txx)) - mean(base(txx))
        out["txx_recent"] = mean(recent(txx))
    if base(rain):
        out["rain_normal"] = out["aridity"] = mean(base(rain))
        out["rain_sd"] = pstdev(base(rain))
    if gwet:
        out["gwet"] = mean([gwet[y] for y in sorted(gwet)[-5:]])
    if len(t2m) >= 10:  # least-squares warming trend
        ys = sorted(t2m)
        my, mt = mean(ys), mean(t2m[y] for y in ys)
        den = sum((y - my) ** 2 for y in ys)
        out["trend_c_decade"] = 10 * sum((y - my) * (t2m[y] - mt) for y in ys) / den

    years = sorted(set(t2m) | set(rain) | set(txx))
    out["history"] = [{"year": y, "t2m": _r(t2m.get(y), 2), "txx": _r(txx.get(y), 2),
                       "rain": _r(rain.get(y), 0)} for y in years]
    out["baseline"] = {"t2m": _r(mean(base(t2m)), 2) if base(t2m) else None,
                       "txx": _r(mean(base(txx)), 2) if base(txx) else None,
                       "rain": _r(mean(base(rain)), 0) if base(rain) else None}
    return out


def daily_indicators(par: dict, elev_m) -> dict:
    """From NASA POWER daily 'parameter' block: {'T2M_MAX': {'20210101': v, ...}, 'PRECTOTCORR': {...}}."""
    thr = 30.0 if (elev_m or 0) >= 1000 else 40.0  # IMD heatwave thresholds: hills 30 C, plains 40 C
    tmax, rain = {}, {}
    for k, v in par.get("T2M_MAX", {}).items():
        if _ok(v):
            tmax.setdefault(int(k[:4]), []).append(v)
    for k, v in par.get("PRECTOTCORR", {}).items():
        if _ok(v):
            rain.setdefault(int(k[:4]), []).append(v)
    full = sorted(y for y, vs in tmax.items() if len(vs) >= 330)
    out = {"hw_days": None, "severe_days": None, "hw_threshold": thr, "rx1day": None,
           "rain_12m": None, "years": f"{full[0]}-{full[-1]}" if full else None}
    if full:
        out["hw_days"] = mean(sum(1 for v in tmax[y] if v >= thr) for y in full)
        out["severe_days"] = mean(sum(1 for v in tmax[y] if v >= 45) for y in full)
    rfull = [y for y in full if len(rain.get(y, [])) >= 330]
    if rfull:
        out["rx1day"] = mean(max(rain[y]) for y in rfull)
    keys = sorted(k for k, v in par.get("PRECTOTCORR", {}).items() if _ok(v))
    if len(keys) >= 365:
        out["rain_12m"] = sum(par["PRECTOTCORR"][k] for k in keys[-365:])
        out["rain_12m_window"] = f"{_d(keys[-365])} to {_d(keys[-1])}"
    return out


def terrain(elevs, lat) -> dict:
    """elevs = [centre, north, south, east, west] sampled 0.01 deg (~1.1 km) apart."""
    if not elevs or any(e is None for e in elevs):
        return {"elev": elevs[0] if elevs else None, "slope": None, "rel_low": None}
    c, n, s, e, w = elevs
    dy = 0.01 * 111_320
    dx = dy * max(0.2, math.cos(math.radians(lat)))
    slope = math.hypot((e - w) / (2 * dx), (n - s) / (2 * dy)) * 100
    return {"elev": c, "slope": slope, "rel_low": max(0.0, mean([n, s, e, w]) - c)}


def combine_indicators(mon: dict, day: dict, ter: dict, ndvi=None, ndvi_anom=None, pop_density=None) -> dict:
    ind = {**{k: v for k, v in mon.items() if k not in ("history", "baseline")}, **day, **ter,
           "ndvi": ndvi, "ndvi_anom": ndvi_anom, "pop_density": pop_density, "spi12": None, "spi_deficit": None}
    if day.get("rain_12m") is not None and mon.get("rain_sd"):
        ind["spi12"] = (day["rain_12m"] - mon["rain_normal"]) / mon["rain_sd"]
        ind["spi_deficit"] = max(0.0, -ind["spi12"])
    return ind


# ---------------------------------------------------------------- risk engine
def sub_indices(ind: dict, N: dict) -> dict:
    green = ind.get("green_override")
    if green is None:
        green = scale(ind.get("ndvi"), 0.05, 0.75)
    E = None
    if ind.get("pop_density") is not None:
        E = scale(math.log10(max(ind["pop_density"], 1.0)), 1.0, math.log10(30_000))
    low_green = None if green is None else 1.0 - green
    rain_term = scale(ind.get("rx1day"), *N["rx1day"])
    if rain_term is not None:
        rain_term *= ind.get("rain_factor", 1.0)
    lowland = wavg([(0.5, scale(ind.get("elev"), *N["elev"], invert=True)),
                    (0.5, scale(ind.get("rel_low"), *N["rel_low"]))])
    flood_v = None if low_green is None else max(0.0, low_green - ind.get("flood_v_cut", 0.0))
    ndvi_stress = None if ind.get("ndvi_anom") is None else scale(-ind["ndvi_anom"], 0.0, 0.15)
    return {
        "heat": {"H": wavg([(0.6, scale(ind.get("txx_anom"), *N["txx_anom"])),
                            (0.4, scale(ind.get("hw_days"), *N["hw_days"]))]),
                 "E": E, "V": low_green},
        "flood": {"H": wavg([(0.5, rain_term), (0.3, lowland),
                             (0.2, scale(ind.get("slope"), *N["slope"], invert=True))]),
                  "E": E, "V": flood_v},
        "drought": {"H": wavg([(0.5, scale(ind.get("spi_deficit"), *N["spi_deficit"])),
                               (0.25, scale(ind.get("aridity"), *N["aridity"], invert=True)),
                               (0.25, scale(ind.get("t_anom"), *N["t_anom"]))]),
                    "E": E,
                    "V": wavg([(0.6, ndvi_stress), (0.4, scale(ind.get("gwet"), 0.25, 0.75, invert=True))])},
    }


def scores_only(ind: dict, N: dict) -> dict:
    out = {}
    for hz, s in sub_indices(ind, N).items():
        if s["H"] is None:
            out[hz] = None
            continue
        out[hz] = risk_score(hz, s["H"], 0.5 if s["E"] is None else s["E"], 0.5 if s["V"] is None else s["V"])
    return out


def overall(scores: dict):
    got = {k: v for k, v in scores.items() if v is not None}
    if not got:
        return {"score": None, "class": risk_class(None), "dominant": None}
    sc = round(0.6 * max(got.values()) + 0.4 * mean(got.values()))
    return {"score": sc, "class": risk_class(sc), "dominant": max(got, key=got.get)}


def _fmt(v, nd=1, unit=""):
    return "n/a" if v is None else f"{v:,.{nd}f}{unit}"


def _signed(v, unit=""):
    return "n/a" if v is None else f"{v:+.1f}{unit}"


def hazard_text(hz: str, ind: dict) -> str:
    if hz == "heat":
        return (f"Hottest-month max temp {_signed(ind.get('txx_anom'), ' °C')} vs 1991-2020; "
                f"{_fmt(ind.get('hw_days'), 0)} days/yr ≥ {ind.get('hw_threshold', 40):.0f} °C")
    if hz == "flood":
        return (f"Max 1-day rain {_fmt(ind.get('rx1day'), 0, ' mm')}; elevation {_fmt(ind.get('elev'), 0, ' m')} "
                f"({_fmt(ind.get('rel_low'), 1, ' m')} below surroundings); slope {_fmt(ind.get('slope'), 1, '%')}")
    pct = None
    if ind.get("rain_12m") is not None and ind.get("rain_normal"):
        pct = 100 * ind["rain_12m"] / ind["rain_normal"]
    return (f"Last 12 months rain {_fmt(pct, 0, '%')} of normal (SPI-12 {_fmt(ind.get('spi12'), 1)}); "
            f"normal {_fmt(ind.get('rain_normal'), 0, ' mm/yr')}; mean temp {_signed(ind.get('t_anom'), ' °C')} vs 1991-2020")


def assess(ind: dict, norms: dict | None = None) -> dict:
    """Full risk result with drivers for every hazard (Bible 9.8: never a bare number)."""
    N = norms or load_norms()
    subs = sub_indices(ind, N)
    exp_txt = ("n/a" if ind.get("pop_density") is None
               else f"~{ind['pop_density']:,.0f} people/km² (WorldPop 2020)")
    veg_txt = "n/a" if ind.get("ndvi") is None else f"NDVI {ind['ndvi']:.2f} (MODIS)"
    if ind.get("green_override") is not None:
        veg_txt = f"green cover index {ind['green_override']:.2f} (scenario)"
    v_txt = {"heat": f"Low vegetation / built-up proxy: {veg_txt}",
             "flood": f"Impervious-surface proxy: {veg_txt}",
             "drought": ("Vegetation stress: NDVI anomaly "
                         f"{_fmt(ind.get('ndvi_anom'), 2)} vs same season; root-zone soil wetness {_fmt(ind.get('gwet'), 2)}")}
    risks = {}
    for hz in HAZARDS:
        s = subs[hz]
        wH, wE, wV = WEIGHTS[hz]
        if s["H"] is None:
            risks[hz] = {"score": None, "class": risk_class(None), "H": None, "E": s["E"], "V": s["V"],
                         "drivers": [], "confidence": "low", "reason": "insufficient data"}
            continue
        est = [k for k in ("E", "V") if s[k] is None]
        E = 0.5 if s["E"] is None else s["E"]
        V = 0.5 if s["V"] is None else s["V"]
        sc = risk_score(hz, s["H"], E, V)
        drivers = [
            {"name": "Hazard", "detail": hazard_text(hz, ind), "value": round(s["H"], 2), "contribution": round(wH * s["H"], 3)},
            {"name": "Exposure", "detail": exp_txt if "E" not in est else "No population data: neutral 0.5 used",
             "value": round(E, 2), "contribution": round(wE * E, 3), "estimated": "E" in est},
            {"name": "Vulnerability", "detail": v_txt[hz] if "V" not in est else "No vegetation data: neutral 0.5 used",
             "value": round(V, 2), "contribution": round(wV * V, 3), "estimated": "V" in est},
        ]
        drivers.sort(key=lambda d: -d["contribution"])
        risks[hz] = {"score": sc, "class": risk_class(sc), "H": round(s["H"], 3), "E": round(E, 3),
                     "V": round(V, 3), "drivers": drivers,
                     "confidence": ("high", "medium", "low")[len(est)]}
    return risks


# ---------------------------------------------------------------- SDG engine (Bible 10.2, v1)
SDG_NAMES = {1: "No Poverty", 2: "Zero Hunger", 3: "Good Health and Well-being", 4: "Quality Education",
             5: "Gender Equality", 6: "Clean Water and Sanitation", 7: "Affordable and Clean Energy",
             8: "Decent Work and Economic Growth", 9: "Industry, Innovation and Infrastructure",
             10: "Reduced Inequalities", 11: "Sustainable Cities and Communities",
             12: "Responsible Consumption and Production", 13: "Climate Action", 14: "Life Below Water",
             15: "Life on Land", 16: "Peace, Justice and Strong Institutions", 17: "Partnerships for the Goals"}
SDG_TAGS = {1: "supporting", 2: "core", 3: "core", 4: "indirect", 5: "indirect", 6: "core", 7: "supporting",
            8: "supporting", 9: "supporting", 10: "supporting", 11: "core", 12: "indirect", 13: "core",
            14: "supporting", 15: "core", 16: "indirect", 17: "indirect"}
RULEBOOK = {
    "flood": [(6, 1.0, "Floodwater contaminates water and sanitation", "6.1.1"),
              (11, 1.0, "Urban flooding damages homes and services", "11.5.1, 11.5.2"),
              (13, 1.0, "Climate-related disaster; adaptation need", "13.1.1"),
              (3, 0.6, "Injury, water-borne disease, blocked access to care", "1.5.1 / 11.5.1"),
              (9, 0.6, "Roads, power and drains damaged", "11.5.2")],
    "heat": [(3, 1.0, "Heat illness and mortality", "3.d (health risk)"),
             (11, 1.0, "Urban heat island; city liveability", "11.7.1"),
             (13, 1.0, "Climate extreme; adaptation need", "13.1.2"),
             (7, 0.6, "Cooling demand stresses energy systems", "7.1.1"),
             (8, 0.6, "Lost outdoor working hours", "8.5.2")],
    "drought": [(2, 1.0, "Crop and food-security stress", "2.1.1, 2.4.1"),
                (6, 1.0, "Water scarcity and stress", "6.4.2"),
                (13, 1.0, "Climate-related hazard", "13.1.1"),
                (15, 0.6, "Vegetation and land degradation", "15.3.1"),
                (1, 0.6, "Income loss for farming households", "1.5.1")],
}


def sdg_level(rel):
    return "High" if rel >= 60 else "Medium" if rel >= 35 else "Low"


def sdg_impact(scores: dict) -> list:
    best = {}
    for hz, links in RULEBOOK.items():
        sc = scores.get(hz)
        if sc is None:
            continue
        for sdg, strength, reason, indicator in links:
            rel = sc * strength
            if sdg not in best or rel > best[sdg]["relevance"]:
                best[sdg] = {"sdg": sdg, "name": SDG_NAMES[sdg], "relevance": round(rel), "level": sdg_level(rel),
                             "via": hz, "strength": "primary" if strength == 1.0 else "secondary",
                             "reason": reason, "indicator": indicator}
    return sorted(best.values(), key=lambda x: (-x["relevance"], x["sdg"]))


# ---------------------------------------------------------------- recommendation engine
INTERVENTIONS = [
    {"id": "urban_greening", "hazard": "heat", "name": "Urban greening & tree canopy", "driver": "V",
     "why": "Low vegetation raises heat vulnerability", "sdgs": [3, 11, 13, 15], "tradeoff": "Needs irrigation water (SDG 6)", "simulate": "urban_greening"},
    {"id": "heat_action_plan", "hazard": "heat", "name": "Heat-health early warning (Heat Action Plan)", "driver": "H",
     "why": "Hot days are frequent; warnings protect outdoor workers and the elderly", "sdgs": [3, 8, 11, 13], "tradeoff": "Needs reliable forecasts and outreach"},
    {"id": "cool_roofs", "hazard": "heat", "name": "Cool roofs on public buildings", "driver": "V",
     "why": "Dark roofs store heat in dense areas", "sdgs": [3, 7, 11], "tradeoff": "Upfront cost per building"},
    {"id": "drainage", "hazard": "flood", "name": "Drain desilting & extra drain capacity", "driver": "H",
     "why": "Extreme rainfall overwhelms drains", "sdgs": [6, 9, 11, 13], "tradeoff": "Cost; may shift water downstream", "simulate": "drainage"},
    {"id": "lake_buffer", "hazard": "flood", "name": "Lake-buffer & wetland restoration", "driver": "H",
     "why": "Low-lying land needs space for water", "sdgs": [6, 11, 13, 15], "tradeoff": "Competes for urban land"},
    {"id": "permeable", "hazard": "flood", "name": "Permeable paving & rain gardens", "driver": "V",
     "why": "Sealed surfaces turn rain into runoff", "sdgs": [6, 11, 13], "tradeoff": "Maintenance to stay permeable"},
    {"id": "rainwater", "hazard": "drought", "name": "Rainwater harvesting & groundwater recharge", "driver": "H",
     "why": "Rainfall deficit stresses water supply", "sdgs": [2, 6, 13], "tradeoff": "Storage space and upkeep"},
    {"id": "drip", "hazard": "drought", "name": "Efficient (drip) irrigation", "driver": "E",
     "why": "Farms are exposed to water shortage", "sdgs": [2, 6, 12], "tradeoff": "Upfront cost for small farmers (SDG 1)"},
    {"id": "watershed", "hazard": "drought", "name": "Watershed & soil-moisture conservation", "driver": "V",
     "why": "Vegetation and soil are drying", "sdgs": [2, 6, 15], "tradeoff": "Benefits take years"},
]


def recommend(risks: dict, limit=5) -> list:
    picks = []
    for hz in sorted(HAZARDS, key=lambda h: -(risks[h]["score"] or 0)):
        r = risks[hz]
        if (r["score"] or 0) < 40:
            continue
        opts = [i for i in INTERVENTIONS if i["hazard"] == hz]
        opts.sort(key=lambda i: -(r.get(i["driver"]) or 0.5))  # match the strongest driver first
        picks += [{**i, "for_score": r["score"]} for i in opts]
    return picks[:limit]


# ---------------------------------------------------------------- what-if engine (Bible ch. 11)
SCENARIOS = {
    "urban_greening": {
        "label": "+{a:.0f}% green cover", "min": 5, "max": 30, "default": 15, "sdgs": [3, 11, 13, 15, 6],
        "tradeoffs": ["Irrigation water demand for new green space (SDG 6), especially in water-stressed cities",
                      "Competes for scarce urban land (SDG 11)"],
        "assumptions": ["≈0.06 °C local cooling per point of green cover (≈0.9 °C for +15), the same order as the "
                        "~0.94 °C mean park-cooling effect in a systematic review; ±30% gives the range",
                        "Green cover replaces built-up surface, lowering heat and flood vulnerability",
                        "Hot-day counts held constant (conservative)"],
    },
    "drainage": {
        "label": "+{a:.0f}% drain capacity & permeable area", "min": 10, "max": 50, "default": 30, "sdgs": [6, 9, 11, 13, 3],
        "tradeoffs": ["Capital cost and construction disruption", "Water may be moved downstream rather than absorbed"],
        "assumptions": ["Each +10% capacity cuts the effective extreme-rainfall term by 8% (scenario parameter: "
                        "no real drain-network data); ±30% gives the range",
                        "Permeable area lowers flood vulnerability by 0.3 × the change"],
    },
}


def _apply(ind: dict, intervention: str, a: float, k: float) -> dict:
    out = dict(ind)
    if intervention == "urban_greening":
        if out.get("txx_anom") is not None:
            out["txx_anom"] = out["txx_anom"] - 0.06 * a * k
        green = scale(ind.get("ndvi"), 0.05, 0.75)
        out["green_override"] = min(1.0, (0.5 if green is None else green) + a / 100)
    elif intervention == "drainage":
        out["rain_factor"] = max(0.0, 1 - 0.008 * a * k)
        out["flood_v_cut"] = 0.3 * a / 100 * k
    return out


def simulate(ind: dict, intervention: str, amount: float, norms: dict | None = None) -> dict:
    if intervention not in SCENARIOS:
        raise ValueError(f"unknown intervention {intervention!r}")
    sc = SCENARIOS[intervention]
    a = float(min(sc["max"], max(sc["min"], amount)))
    N = norms or load_norms()
    before = scores_only(ind, N)
    runs = {k: scores_only(_apply(ind, intervention, a, k), N) for k in (0.7, 1.0, 1.3)}
    changes = {}
    for hz in HAZARDS:
        if before[hz] is None:
            continue
        vals = [runs[k][hz] for k in runs]
        if runs[1.0][hz] != before[hz] or min(vals) != max(vals):
            changes[hz] = {"before": before[hz], "after": runs[1.0][hz], "range": [min(vals), max(vals)]}
    sdg_b = {s["sdg"]: s["level"] for s in sdg_impact(before)}
    sdg_a = {s["sdg"]: s["level"] for s in sdg_impact(runs[1.0])}
    central = _apply(ind, intervention, a, 1.0)
    inputs = {}
    if intervention == "urban_greening":
        inputs["green_cover_index"] = [_r(scale(ind.get("ndvi"), 0.05, 0.75), 2), _r(central["green_override"], 2)]
        if ind.get("txx_anom") is not None:
            inputs["max_temp_anomaly_c"] = [_r(ind["txx_anom"], 1), _r(central["txx_anom"], 1)]
    else:
        inputs["extreme_rain_term_factor"] = [1.0, _r(central["rain_factor"], 2)]
        inputs["flood_vulnerability_cut"] = [0.0, _r(central["flood_v_cut"], 2)]
    return {"intervention": intervention, "amount": a, "label": sc["label"].format(a=a), "changes": changes,
            "overall": {"before": overall(before)["score"], "after": overall(runs[1.0])["score"]},
            "inputs_changed": inputs, "assumptions": sc["assumptions"], "sdg_relevance": sc["sdgs"],
            "sdg_changes": [{"sdg": s, "name": SDG_NAMES[s], "before": sdg_b[s], "after": sdg_a.get(s, "Low")}
                            for s in sdg_b if sdg_a.get(s, "Low") != sdg_b[s]],
            "tradeoffs": sc["tradeoffs"], "disclaimer": DISCLAIMER}


# ---------------------------------------------------------------- explanation + AI guardrails (Bible ch. 12)
AI_RULES = """You explain climate-risk results for a decision-support map.
Use ONLY facts and numbers from FACTS. Never invent data, sources, studies or statistics.
Describe scores as "modelled risk indicators", not measurements or predictions.
Say "relevant to SDG X", never "improves SDG X by N%".
Mention the main drivers, the most relevant SDGs and the suggested actions.
If FACTS has a scenario, explain it as a model-based estimate with its range.
End with one short caveat. Max 110 words. Plain language for a city official. No headings or lists."""


def explain_template(a: dict, sim: dict | None = None) -> str:
    """Rule-based explanation: instant, offline, and the fallback when the AI fails validation."""
    name = a["location"]["name"]
    ov = a["overall"]
    if ov["score"] is None:
        return f"There is not enough data to score {name} yet."
    risks = a["risks"]
    ranked = sorted((h for h in HAZARDS if risks[h]["score"] is not None), key=lambda h: -risks[h]["score"])
    top = ranked[0]
    drv = risks[top]["drivers"][0]
    parts = [f"{name} has a {ov['class'].lower()} combined climate-risk indicator ({ov['score']}/100). "
             f"The strongest signal is {top} risk at {risks[top]['score']} ({risks[top]['class']}), "
             f"driven mainly by {drv['name'].lower()}: {drv['detail']}."]
    others = [f"{h} {risks[h]['score']} ({risks[h]['class']})" for h in ranked[1:]]
    if others:
        parts.append("Other risks: " + ", ".join(others) + ".")
    high = [s for s in a["sdg_impact"] if s["level"] == "High"][:3] or a["sdg_impact"][:2]
    if high:
        parts.append("This is most relevant to " + ", ".join(f"SDG {s['sdg']} ({s['name']})" for s in high) + ".")
    if a["interventions"]:
        parts.append("Suggested actions: " + ", ".join(i["name"].lower() for i in a["interventions"][:3]) + ".")
    if sim and sim.get("changes"):
        ch = "; ".join(f"{h} {c['before']} → {c['after']} (range {c['range'][0]}-{c['range'][1]})"
                       for h, c in sim["changes"].items())
        parts.append(f"Scenario {sim['label']}: {ch}.")
    parts.append("These are modelled indicators for prioritisation, not forecasts.")
    return " ".join(parts)


def fact_sheet(a: dict, sim: dict | None = None) -> dict:
    facts = {
        "place": a["location"]["name"],
        "overall": {"score": a["overall"]["score"], "class": a["overall"]["class"]},
        "risks": {h: {"score": r["score"], "class": r["class"],
                      "drivers": [f"{d['name']}: {d['detail']}" for d in r["drivers"]]}
                  for h, r in a["risks"].items()},
        "sdg": [{"sdg": s["sdg"], "name": s["name"], "level": s["level"], "via": s["via"]} for s in a["sdg_impact"][:5]],
        "interventions": [i["name"] for i in a["interventions"][:4]],
        "is_demo": a.get("is_demo", False),
        "sources": [s["name"] for s in a["data_sources"] if s["ok"]],
    }
    if sim:
        facts["scenario"] = {"label": sim["label"], "changes": sim["changes"], "tradeoffs": sim["tradeoffs"]}
    return facts


_NUM = re.compile(r"(?<![\w.])[-+−]?\d[\d,]*(?:\.\d+)?")


def validate_numbers(text: str, facts: dict) -> list:
    """Every number in the AI answer must exist in the fact sheet (SDG numbers 1-17 always allowed)."""
    allowed = {float(n.replace(",", "").replace("−", "-")) for n in _NUM.findall(json.dumps(facts, ensure_ascii=False))}
    allowed |= {float(i) for i in range(0, 18)} | {100.0}
    bad = []
    for raw in _NUM.findall(text):
        v = float(raw.replace(",", "").replace("−", "-"))
        if not any(abs(abs(v) - abs(x)) <= 0.051 for x in allowed):
            bad.append(raw)
    return bad


# ---------------------------------------------------------------- helpers
def _r(v, nd):
    return None if v is None else round(v, nd)


def _d(k: str) -> str:
    return f"{k[:4]}-{k[4:6]}-{k[6:]}"


def percentile(vals, p):
    s = sorted(vals)
    if not s:
        return None
    i = (len(s) - 1) * p / 100
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


# ---------------------------------------------------------------- self-check
def _fixture():
    """Synthetic data in the exact NASA POWER JSON layout (not real measurements)."""
    import random
    rnd = random.Random(7)
    mon = {"T2M": {}, "T2M_MAX": {}, "PRECTOTCORR": {}, "GWETROOT": {}}
    for y in range(1991, 2026):
        warm = 0.03 * (y - 1991)
        for m in range(1, 13):
            k = f"{y}{m:02d}"
            mon["T2M"][k] = 24 + 4 * math.sin((m - 1) / 12 * 2 * math.pi) + warm + rnd.uniform(-0.3, 0.3)
            mon["T2M_MAX"][k] = 33 + 5 * math.sin((m - 1) / 12 * 2 * math.pi) + warm + rnd.uniform(-0.5, 0.5)
            mon["PRECTOTCORR"][k] = max(0.0, 3 + 5 * math.sin((m - 4) / 12 * 2 * math.pi) + rnd.uniform(-1, 1))
            mon["GWETROOT"][k] = 0.5
        for name in mon:
            mon[name][f"{y}13"] = -999.0
    day = {"T2M_MAX": {}, "PRECTOTCORR": {}}
    from datetime import date, timedelta
    d = date(2021, 1, 1)
    while d <= date(2026, 8, 31):
        k = d.strftime("%Y%m%d")
        day["T2M_MAX"][k] = 41.0 if d.month == 5 and d.day <= 10 else 32.0
        day["PRECTOTCORR"][k] = 120.0 if (d.month, d.day) == (9, 5) else (2.0 if 6 <= d.month <= 10 else 0.2)
        d += timedelta(days=1)
    return mon, day


if __name__ == "__main__":
    # Bible 9.3 worked example: H=0.70, E=0.60, V=0.72 -> 68 (High)
    assert risk_score("heat", 0.70, 0.60, 0.72) == 68 and risk_class(68) == "High"
    assert risk_class(60) == "High" and risk_class(59.9) == "Moderate" and risk_class(None) == "Insufficient data"
    # Bible 10.2 example: flood 82 -> SDG 11 High (82), SDG 9 Medium (49)
    sdg = {s["sdg"]: s for s in sdg_impact({"flood": 82, "heat": None, "drought": None})}
    assert sdg[11]["level"] == "High" and sdg[11]["relevance"] == 82 and sdg[9]["relevance"] == 49 and sdg[9]["level"] == "Medium"

    mon_raw, day_raw = _fixture()
    mon, day = monthly_indicators(mon_raw), daily_indicators(day_raw, 920)
    assert 0.5 < mon["t_anom"] < 1.3, mon["t_anom"]          # 0.03 C/yr warming -> ~0.9 C
    assert 0.2 < mon["trend_c_decade"] < 0.4, mon["trend_c_decade"]  # 0.03 C/yr = 0.3 C/decade
    assert day["hw_days"] == 10 and day["rx1day"] == 120.0
    ter = terrain([900, 905, 903, 904, 902], 12.97)
    assert ter["rel_low"] == 3.5 and ter["slope"] > 0
    ind = combine_indicators(mon, day, ter, ndvi=0.21, ndvi_anom=-0.05, pop_density=8500)
    risks = assess(ind, DEFAULT_NORMS)
    for hz in HAZARDS:
        r = risks[hz]
        assert 0 <= r["score"] <= 100 and r["confidence"] == "high" and len(r["drivers"]) == 3, (hz, r)
    # missing exposure/vegetation -> neutral 0.5, flagged, lower confidence
    r2 = assess(combine_indicators(mon, day, ter), DEFAULT_NORMS)
    assert r2["heat"]["confidence"] == "low" and any(d.get("estimated") for d in r2["heat"]["drivers"])
    # what-if: greening lowers heat and flood, never raises them; range brackets the central value
    sim = simulate(ind, "urban_greening", 15, DEFAULT_NORMS)
    h = sim["changes"]["heat"]
    assert h["after"] < h["before"] and h["range"][0] <= h["after"] <= h["range"][1], sim
    assert sim["changes"]["flood"]["after"] <= sim["changes"]["flood"]["before"]
    simd = simulate(ind, "drainage", 30, DEFAULT_NORMS)
    assert simd["changes"]["flood"]["after"] < simd["changes"]["flood"]["before"] and "heat" not in simd["changes"]
    # AI guardrail: invented numbers are caught, real ones pass
    facts = {"place": "X", "overall": {"score": 61}, "risks": {"heat": {"score": 55}}}
    assert validate_numbers("Heat risk is 55 and overall 61/100, relevant to SDG 3.", facts) == []
    assert validate_numbers("This will affect 340,000 people by 2030.", facts) == ["340,000", "2030"]
    print("engine self-check OK:", {h: risks[h]["score"] for h in HAZARDS}, "| greening heat", h)
