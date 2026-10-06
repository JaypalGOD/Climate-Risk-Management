"""Map page: interactive risk map + analysis panel (engines live in backend/app)."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pandas as pd
import pydeck as pdk
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app import engine as eng  # noqa: E402
from app import sources as src  # noqa: E402
from app import main as api  # noqa: E402  (reuses the analysis pipeline)


from views.mapkit import CLASS_COLOR, LAYERS, background_map, legend_html  # noqa: E402

DEMO = {"Bengaluru": (12.9716, 77.5946), "Mumbai": (19.076, 72.8777), "Delhi": (28.6139, 77.209),
        "Chennai": (13.0827, 80.2707), "Kolkata": (22.5726, 88.3639), "Jaipur": (26.9124, 75.7873),
        "Guwahati": (26.1445, 91.7362), "Latur": (18.4088, 76.5604)}
SDG_COLOR = {1: "#E5243B", 2: "#DDA63A", 3: "#4C9F38", 4: "#C5192D", 5: "#FF3A21", 6: "#26BDE2", 7: "#FCC30B",
             8: "#A21942", 9: "#FD6925", 10: "#DD1367", 11: "#FD9D24", 12: "#BF8B2E", 13: "#3F7E44", 14: "#0A97D9",
             15: "#56C02B", 16: "#00689D", 17: "#19486A"}
st.markdown("""<style>
.st-key-panel { position: fixed !important; top: 64px; right: 16px; bottom: 16px; width: min(440px, 94vw); z-index: 5;
  overflow-y: auto; padding: 16px 18px; background: rgba(255,255,255,.66); backdrop-filter: blur(16px) saturate(1.3);
  -webkit-backdrop-filter: blur(16px); border: 1px solid rgba(22,163,74,.2); border-radius: 20px;
  box-shadow: 0 18px 50px rgba(15,81,50,.18); animation: slideIn .6s cubic-bezier(.2,.7,.2,1); }
.st-key-legend { position: fixed !important; left: 16px; bottom: 16px; z-index: 5; max-width: 520px; padding: 10px 14px;
  background: rgba(255,255,255,.7); backdrop-filter: blur(12px); border-radius: 14px; border: 1px solid rgba(22,163,74,.2); }
@keyframes slideIn { from { opacity: 0; transform: translateX(30px); } to { opacity: 1; transform: none; } }
@media (max-width: 760px) { .st-key-panel { top: auto; left: 8px; right: 8px; width: auto; max-height: 55vh; } }
</style>""", unsafe_allow_html=True)


def run(coro):
    """Run one async pipeline call; httpx clients and locks belong to one event loop, so make fresh ones."""
    src._client = None
    src._limits = {h: asyncio.Semaphore(4) for h in src._limits}
    src._nominatim_lock = asyncio.Lock()

    async def go():
        try:
            return await coro
        finally:
            if src._client:
                await src._client.aclose()
    return asyncio.run(go())


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def analyse(lat: float, lon: float, name: str | None):
    a = run(api._compute(lat, lon, name))
    a["_ind"] = {k: v for k, v in a["_ind"].items()}
    return a


@st.cache_data(show_spinner=False, ttl=86400)
def search(q: str):
    try:
        return [r for r in run(src.search(q)) if r["country_code"] == "IN"]
    except Exception:
        return []


@st.cache_data(show_spinner=False, ttl=86400)
def ai_text(lat, lon, facts_json: str):
    """Free Pollinations text API (no key). Returns (text, ok, note); the number validator guards it."""
    facts = json.loads(facts_json)
    msgs = [{"role": "system", "content": eng.AI_RULES},
            {"role": "user", "content": "FACTS:\n" + facts_json +
             "\n\nExplain this place's climate risk, why, its SDG relevance and the suggested actions."}]
    try:
        r = httpx.post("https://text.pollinations.ai/", json={"messages": msgs, "model": "openai"},
                       timeout=60, headers={"User-Agent": src.UA})
        r.raise_for_status()
        text = r.text.strip()
        if text.startswith("{"):
            text = (json.loads(text).get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    except Exception as e:
        return None, False, f"Online AI unavailable ({e.__class__.__name__}), showing the rule-based explanation."
    bad = eng.validate_numbers(text, facts)
    if bad or not text:
        return None, False, f"AI used numbers not in our data ({', '.join(bad)}), so the rule-based explanation is shown."
    return text, True, "Number check passed · Pollinations"


def pill(text, col):
    return f'<span class="pill" style="background:{col}26;color:{col};border:1px solid {col}66">{text}</span>'


# ------------------------------------------------------------------ sidebar
if "place" not in st.session_state:
    st.session_state.place = ("Bengaluru", *DEMO["Bengaluru"])

with st.sidebar:
    pick = st.radio("Demo cities", list(DEMO), horizontal=True, index=None, key="demo")
    if pick and st.session_state.get("last_demo") != pick:
        st.session_state.last_demo = pick
        st.session_state.place = (pick, *DEMO[pick])
    q = st.text_input("Search any place in India", placeholder="e.g. Bellandur, Patna, Shimla…")
    if len(q.strip()) >= 2:
        res = search(q.strip())
        if res:
            labels = [f"{r['name']}, {r.get('admin1') or ''}" for r in res]
            i = st.selectbox("Results", range(len(res)), format_func=lambda k: labels[k])
            if st.button("Analyse this place", type="primary"):
                st.session_state.place = (labels[i].strip(", "), res[i]["lat"], res[i]["lon"])
        else:
            st.caption("No match in India.")
    st.divider()
    layer = st.selectbox("Map layer", list(LAYERS))
    opacity = st.slider("Layer opacity", 0.2, 0.9, 0.6, 0.05)
    st.caption("National layers show **hazard (H)** on a 1° grid from NASA POWER + Copernicus DEM. "
               "Click a grid cell or pick a place for full **risk = hazard + exposure + vulnerability**.")

# ------------------------------------------------------------------ full-screen map
clicked = background_map(layer, opacity, st.session_state.place)
if clicked:
    cell = (f"Area near {clicked[0]}°N, {clicked[1]}°E", *clicked)
    if st.session_state.place != cell:
        st.session_state.place = cell
        st.rerun()
with st.container(key="legend"):
    st.markdown(f"<b>{layer}</b> &nbsp; {legend_html(layer)}<br><span class='small'>Drag to pan · scroll to zoom · "
                "click a coloured cell to analyse it</span>", unsafe_allow_html=True)

# ------------------------------------------------------------------ analysis panel (glass, over the map)
with st.container(key="panel"):
    name, lat, lon = st.session_state.place
    if not (api.BBOX[0] <= lat <= api.BBOX[1] and api.BBOX[2] <= lon <= api.BBOX[3]):
        st.error("Outside MVP coverage (India region).")
        st.stop()
    with st.spinner("Fetching NASA POWER, Copernicus DEM, MODIS NDVI and WorldPop, then running the engines…"):
        try:
            a = analyse(round(lat, 4), round(lon, 4), name)
        except Exception as e:
            st.error(f"Could not analyse this place: {getattr(e, 'detail', e)}")
            st.stop()

    loc, ov, risks = a["location"], a["overall"], a["risks"]
    st.subheader(loc["name"])
    st.caption(f"{lat:.3f}°N, {lon:.3f}°E" + (f" · {loc['elevation_m']:.0f} m elevation" if loc["elevation_m"] is not None else ""))
    w = a["weather"]
    if w:
        c = st.columns(4)
        c[0].metric("Now", f"{w['temperature_c']} °C")
        c[1].metric("Humidity", f"{w['humidity']}%")
        c[2].metric("Wind", f"{w['wind_kmh']} km/h")
        c[3].metric("Rain next 7 d", f"{w['next7d_rain_mm']} mm")

    col = CLASS_COLOR[ov["class"]]
    st.markdown(f'<div class="card"><span class="small">CLIMATE RISK</span><br>'
                f'<span style="font-size:42px;font-weight:800;color:{col}">{ov["score"]}</span>'
                f'<span class="small"> / 100</span> &nbsp; {pill(ov["class"], col)} &nbsp; '
                f'{pill(a["confidence"] + " confidence", "#38bdf8")}<br>'
                f'<span class="small">Main threat: <b>{(ov["dominant"] or "–").title()}</b> · real data, not demo values</span></div>',
                unsafe_allow_html=True)

    tabs = st.tabs(["Risks", "SDG impact", "Actions & What-If", "AI insight", "History", "Method"])

    with tabs[0]:
        st.caption("Risk = 100 × (wH·H + wE·E + wV·V), following the IPCC hazard–exposure–vulnerability idea")
        for hz in ("flood", "heat", "drought"):
            r = risks[hz]
            wts = a["weights"][hz]
            c = CLASS_COLOR[r["class"]]
            st.markdown(f'<div class="card"><b>{hz.title()}</b> &nbsp; <span style="font-size:22px;font-weight:800;color:{c}">'
                        f'{r["score"]}</span> {pill(r["class"], c)}</div>', unsafe_allow_html=True)
            cc = st.columns(3)
            for i, k in enumerate(("H", "E", "V")):
                cc[i].progress(float(r[k] or 0), text=f"{['Hazard', 'Exposure', 'Vulnerability'][i]} ×{wts[i]}: {r[k] or 0:.2f}")
            with st.expander("Drivers"):
                for d in r["drivers"]:
                    st.markdown(f"**{d['name']}** (+{round(d['contribution'] * 100)} pts){' · *estimated*' if d.get('estimated') else ''}  \n{d['detail']}")

    with tabs[1]:
        by = {s["sdg"]: s for s in a["sdg_impact"]}
        tiles = "".join(f'<span class="sdg" title="SDG {n}" style="background:{SDG_COLOR[n]};'
                        f'opacity:{1 if n in by and by[n]["level"] == "High" else .75 if n in by and by[n]["level"] == "Medium" else .5 if n in by else .12}">{n}</span>'
                        for n in range(1, 18))
        st.markdown(tiles, unsafe_allow_html=True)
        st.caption("Explicit rulebook: relevance = risk score × link strength (primary 1.0, secondary 0.6) → High ≥ 60 · Medium 35–59 · Low < 35")
        lvl = {"High": "#fc8d59", "Medium": "#fee08b", "Low": "#91cf60"}
        for s in a["sdg_impact"][:7]:
            st.markdown(f'<div class="card"><span class="sdg" style="background:{SDG_COLOR[s["sdg"]]}">{s["sdg"]}</span> '
                        f'<b>{s["name"]}</b> {pill(s["level"], lvl[s["level"]])}<br><span class="small">via {s["via"]} '
                        f'({s["strength"]}) · {s["reason"]} · indicator {s["indicator"]}</span></div>', unsafe_allow_html=True)
        st.caption('We say "relevant to SDG X". We never claim to improve an SDG by a percentage.')

    with tabs[2]:
        if not a["interventions"]:
            st.info("No risk is Moderate or above. Keep monitoring.")
        for i in a["interventions"]:
            chips = "".join(f'<span class="sdg" style="background:{SDG_COLOR[n]}">{n}</span>' for n in i["sdgs"])
            st.markdown(f'<div class="card"><b>{i["name"]}</b><br><span class="small">{i["why"]} · trade-off: {i["tradeoff"]}</span><br>{chips}</div>',
                        unsafe_allow_html=True)
        st.markdown("#### “What if?” simulator")
        iv = st.radio("Intervention", ["urban_greening", "drainage"], horizontal=True,
                      format_func={"urban_greening": "🌳 Urban greening", "drainage": "🚰 Better drainage"}.get)
        sc = eng.SCENARIOS[iv]
        amt = st.slider("Intervention size (%)", sc["min"], sc["max"], sc["default"])
        sim = eng.simulate(a["_ind"], iv, amt)
        for hz, ch in sim["changes"].items():
            rng = f" (range {ch['range'][0]}–{ch['range'][1]})" if ch["range"][0] != ch["range"][1] else ""
            st.metric(f"{hz.title()} risk", ch["after"], delta=ch["after"] - ch["before"], delta_color="inverse", help=f"before {ch['before']}{rng}")
        if sim["sdg_changes"]:
            st.write("SDG relevance: " + " · ".join(f"SDG {s['sdg']} {s['before']} → {s['after']}" for s in sim["sdg_changes"]))
        st.write("Relevant SDGs: " + ", ".join(str(n) for n in sim["sdg_relevance"]) + " · Trade-offs: " + "; ".join(sim["tradeoffs"]))
        with st.expander("ⓘ How was this estimated?"):
            for x in sim["assumptions"]:
                st.write("• " + x)
        st.caption(sim["disclaimer"])
        st.session_state.sim = sim

    with tabs[3]:
        st.markdown(f'<div class="card">{a["explanation"]}</div>', unsafe_allow_html=True)
        use_sim = st.checkbox("Include the current What-If scenario")
        if st.button("✨ Deep AI analysis", type="primary"):
            facts = eng.fact_sheet(a, st.session_state.get("sim") if use_sim else None)
            with st.spinner("Asking the online AI (free tier, can take ~10 s)…"):
                text, ok, note = ai_text(lat, lon, json.dumps(facts, ensure_ascii=False))
            st.markdown(f'<div class="card" style="border-color:#38bdf866">{text or eng.explain_template(a, st.session_state.get("sim") if use_sim else None)}</div>',
                        unsafe_allow_html=True)
            (st.success if ok else st.warning)(note)
        st.caption("Pipeline: real data → risk engine → fact sheet JSON → AI → number validator → template fallback. AI narrates, never invents.")

    with tabs[4]:
        h = a["history"]
        s = [p for p in h["series"] if p["t2m"] is not None]
        base = h["baseline"]
        if len(s) >= 5 and base.get("t2m") is not None:
            df = pd.DataFrame(s).set_index("year")
            df["temp anomaly °C"] = (df["t2m"] - base["t2m"]).round(2)
            st.markdown("**Warming stripes:** each bar is one year's mean temperature vs 1991–2020"
                        + (f" · trend **{h['trend_c_decade']:+} °C / decade**" if h["trend_c_decade"] is not None else ""))
            st.bar_chart(df["temp anomaly °C"], color="#f87171", height=170)
            yr = st.slider("Year", int(df.index.min()), int(df.index.max()), int(df.index.max()))
            row = df.loc[yr]
            c = st.columns(3)
            c[0].metric(f"{yr} mean temp", f"{row['t2m']:.1f} °C", f"{row['temp anomaly °C']:+.2f} °C", delta_color="inverse")
            c[1].metric("Hottest month max", f"{row['txx']:.1f} °C" if pd.notna(row["txx"]) else "–")
            pct = round(100 * row["rain"] / base["rain"]) if pd.notna(row["rain"]) and base.get("rain") else None
            c[2].metric("Annual rain", f"{row['rain']:.0f} mm" if pd.notna(row["rain"]) else "–", f"{pct}% of normal" if pct else None)
            st.bar_chart(df["rain"], color="#38bdf8", height=140)
        else:
            st.info("Not enough history for this place.")

    with tabs[5]:
        st.write("Weights: heat 0.40/0.25/0.35 · flood 0.45/0.25/0.30 · drought 0.45/0.20/0.35 · normalisation: " + a["norms"])
        for s_ in a["data_sources"]:
            st.write(("✅ " if s_["ok"] else "⚠️ ") + f"**{s_['name']}**: {s_['used_for']}")
        st.caption("Limits: ~50 km reanalysis inputs smooth local extremes · weights are published assumptions, not validated · "
                   "flood score is a susceptibility indicator, not a forecast · drainage is a scenario parameter (no drain-network data) · "
                   "population is modelled (WorldPop 2020); built-up share approximated from low NDVI.")
        st.caption(f"Computed in {a['elapsed_s']} s · {a['as_of']}")
