"""Full-screen interactive background map (pan / zoom / click like Google Maps), shared by all pages."""
import base64
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

import pydeck as pdk
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
CLASS_COLOR = {"Very Low": "#1a9850", "Low": "#91cf60", "Moderate": "#fee08b", "High": "#fc8d59",
               "Very High": "#d73027", "Insufficient data": "#64748b"}
LAYERS = {  # label: (grid property, colour stops, unit)
    "Climate hazard": ("climate", None, "/100"), "Heat hazard": ("heat", None, "/100"),
    "Flood hazard": ("flood", None, "/100"), "Drought hazard": ("drought", None, "/100"),
    "Max temperature": ("tmax", [(26, "#fff5b8"), (32, "#fecc5c"), (37, "#fd8d3c"), (41, "#f03b20"), (45, "#bd0026")], "°C"),
    "Normal rainfall": ("rain", [(250, "#8c510a"), (600, "#d8b365"), (1000, "#c7eae5"), (1800, "#5ab4ac"), (3000, "#2c7fb8")], " mm"),
    "Rain last 12 months": ("rain12_pct", [(50, "#8c510a"), (80, "#d8b365"), (100, "#f5f5f5"), (120, "#5ab4ac"), (150, "#01665e")], "% of normal"),
}




@st.cache_data(show_spinner=False)
def grid():
    p = ROOT / "frontend" / "public" / "data" / "grid.geojson"
    return json.loads(p.read_text("utf-8")) if p.exists() else None


def hex_rgb(h, a=170):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [a]


def risk_class(v):
    return "Very High" if v >= 80 else "High" if v >= 60 else "Moderate" if v >= 40 else "Low" if v >= 20 else "Very Low"


def colour(v, stops):
    if v is None:
        return None
    if stops is None:
        return CLASS_COLOR[risk_class(v)]
    for (x0, c0), (x1, c1) in zip(stops, stops[1:]):
        if v <= x1:
            t = 0 if v <= x0 else (v - x0) / (x1 - x0)
            a, b = hex_rgb(c0), hex_rgb(c1)
            return "#" + "".join(f"{round(a[i] + (b[i] - a[i]) * t):02x}" for i in range(3))
    return stops[-1][1]


RISK_RAMP = [(0, "#1a9850"), (20, "#91cf60"), (40, "#fee08b"), (60, "#fc8d59"), (80, "#d73027"), (100, "#a50026")]
BOUNDS = (68.0, 8.0, 97.0, 36.0)  # lon_min, lat_min, lon_max, lat_max of the 1-degree grid


def _merc(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


PAD = 5.0  # degrees of soft fade around the grid, so the field melts into the sea like Windy


def _blur(a, sig):
    """Separable Gaussian blur (numpy only)."""
    k = np.exp(-0.5 * (np.arange(-3 * sig, 3 * sig + 1) / sig) ** 2)
    k /= k.sum()
    a = np.apply_along_axis(lambda r: np.convolve(r, k, "same"), 1, a)
    return np.apply_along_axis(lambda c: np.convolve(c, k, "same"), 0, a)


@st.cache_data(show_spinner=False)
def smooth_field(prop: str, stops_key: str, opacity: float) -> str:
    """Turns the 1-degree grid into a smooth, Windy-style colour field (PNG data URI).
    Two-scale normalised smoothing: fine detail over land, a wide blur that extends the colours into
    the sea and fades out. Rows are re-sampled to Web-Mercator so the image lines up with the basemap.
    Display only: the analysis still uses the real cell values."""
    g = grid()
    stops = LAYERS[next(k for k in LAYERS if LAYERS[k][0] == prop)][1] or RISK_RAMP
    lon0, lat0, lon1, lat1 = field_bounds()
    up = 6                                   # blur at 6 px per degree, then upscale smoothly
    nx, ny = int(lon1 - lon0) * up, int(lat1 - lat0) * up
    V, M = np.zeros((ny, nx)), np.zeros((ny, nx))
    for f in g["features"]:
        pr = f["properties"]
        v = pr.get(prop)
        if v is None:
            continue
        i0, j0 = int((lat1 - pr["lat"] - 0.5) * up), int((pr["lon"] - 0.5 - lon0) * up)  # cell centre -> 1x1 deg block
        if 0 <= i0 < ny and 0 <= j0 < nx:
            V[i0:i0 + up, j0:j0 + up], M[i0:i0 + up, j0:j0 + up] = v, 1.0
    ms, vs = _blur(M, up * 0.6), _blur(V * M, up * 0.6)      # fine scale
    ml, vl = _blur(M, up * 2.6), _blur(V * M, up * 2.6)      # wide scale fills gaps and the coast
    fine = vs / np.maximum(ms, 1e-6)
    wide = vl / np.maximum(ml, 1e-6)
    w = np.clip(ms / 0.6, 0, 1)
    val = w * fine + (1 - w) * wide
    alpha = np.clip(ml / 0.35, 0, 1) ** 1.5                  # soft fade away from land
    W, H = nx * 5, ny * 5                                    # final 30 px per degree
    big = lambda a: np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((W, H), Image.BICUBIC))
    val, alpha = big(val), np.clip(big(alpha), 0, 1)
    ym = np.linspace(_merc(lat1), _merc(lat0), H)            # equal-latitude rows -> equal-Mercator rows
    lat_rows = np.degrees(2 * np.arctan(np.exp(ym)) - np.pi / 2)
    src = np.clip((lat1 - lat_rows) / (lat1 - lat0) * (H - 1), 0, H - 1)
    r0 = np.floor(src).astype(int)
    r1 = np.minimum(r0 + 1, H - 1)
    t = (src - r0)[:, None]
    val = val[r0] * (1 - t) + val[r1] * t
    alpha = alpha[r0] * (1 - t) + alpha[r1] * t
    xs = np.array([x for x, _ in stops], float)
    cols = np.array([hex_rgb(c)[:3] for _, c in stops], float)
    rgb = np.stack([np.interp(val, xs, cols[:, k]) for k in range(3)], -1)
    rgba = np.dstack([rgb, alpha * 255 * opacity]).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def field_bounds():
    return BOUNDS[0] - PAD, BOUNDS[1] - PAD, BOUNDS[2] + PAD, BOUNDS[3] + PAD


def legend_html(layer):
    _, stops, unit = LAYERS[layer]
    if stops is None:
        return " ".join(f'<span class="pill" style="background:{c}33;color:#1f2937;border:1px solid {c}">{t}</span>'
                        for t, c in CLASS_COLOR.items() if t != "Insufficient data")
    return " → ".join(f"{v}{unit}" for v, _ in stops)


def background_map(layer="Climate hazard", opacity=0.55, place=None, key="map"):
    """Draws the full-screen map. Returns (lat, lon) of a clicked grid cell, or None."""
    st.markdown("""<style>
    .st-key-bgmap { position: fixed !important; inset: 0; z-index: 0; }
    .st-key-bgmap > div, .st-key-bgmap [data-testid="stDeckGlJsonChart"], .st-key-bgmap [data-testid="stDeckGlJsonChart"] > div {
      height: 100vh !important; width: 100vw !important; }
    /* deck.gl places the hover box relative to this layer; Streamlit leaves it below the canvas (box drawn off-screen) */
    .st-key-bgmap .deck-widgets-root { position: absolute !important; inset: 0 !important; pointer-events: none; }
    .st-key-bgmap .deck-tooltip { max-width: 320px; line-height: 1.45; }
    .stApp::before { display: none; }          /* the real map replaces the decorative background */
    </style>""", unsafe_allow_html=True)
    prop, stops, unit = LAYERS[layer]
    g = grid()
    layers = []
    if g:
        fmt = lambda v, u="": "–" if v is None else f"{v}{u}"
        for f in g["features"]:  # hover text: the selected layer first, then every layer for this cell
            pr = f["properties"]
            v = pr.get(prop)
            pr["_v"] = fmt(v, unit)
            pr["_k"] = risk_class(v) if (stops is None and v is not None) else ""
            pr["_ll"] = f"{pr['lat']:.1f}°N, {pr['lon']:.1f}°E"
            pr["_all"] = (f"Climate {fmt(pr.get('climate'))} · Heat {fmt(pr.get('heat'))} · Flood {fmt(pr.get('flood'))} · "
                          f"Drought {fmt(pr.get('drought'))}")
            pr["_wx"] = f"Max temp {fmt(pr.get('tmax'), ' °C')} · Rain {fmt(pr.get('rain'), ' mm/yr')} · Last 12 mo {fmt(pr.get('rain12_pct'), '%')}"
            pr["_c"] = [0, 0, 0, 1]  # invisible cells: keep hover and click-to-analyse
        # pydeck evaluates plain strings as JS expressions ("data:..." -> syntax error), so pass a quoted literal
        layers.append(pdk.Layer("BitmapLayer", id="field", image=f"'{smooth_field(prop, layer, round(opacity, 2))}'",
                                bounds=list(field_bounds()), opacity=1.0))
        layers.append(pdk.Layer("GeoJsonLayer", g, id="grid", pickable=True, stroked=False, filled=True,
                                get_fill_color="properties._c"))
    view = pdk.ViewState(latitude=22.5, longitude=80.5, zoom=4.3)
    if place:
        _, lat, lon = place
        layers.append(pdk.Layer("ScatterplotLayer", [{"lat": lat, "lon": lon}], get_position="[lon, lat]",
                                get_radius=6000, radius_min_pixels=8, get_fill_color=[22, 163, 74, 255],
                                stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=3))
    deck = pdk.Deck(layers=layers, map_provider="carto", map_style="light", initial_view_state=view,
                    tooltip={"html": f"<div style='font-size:11px;color:#4b5563'>{{_ll}}</div>"
                                     f"<div style='font-size:15px;margin:2px 0'><b>{layer}: {{_v}}</b> {{_k}}</div>"
                                     "<div>{_all}</div><div>{_wx}</div>"
                                     "<div style='margin-top:4px;color:#15803d'>Click to analyse this area</div>",
                             "style": {"background": "rgba(255,255,255,.88)", "color": "#14532d", "fontSize": "12px",
                                       "borderRadius": "12px", "padding": "8px 12px", "backdropFilter": "blur(8px)",
                                       "border": "1px solid rgba(22,163,74,.35)", "boxShadow": "0 6px 20px rgba(0,0,0,.12)"}})
    with st.container(key="bgmap"):
        # Streamlit paints the selected object opaque (black square on our invisible cells), so a new key per
        # place remounts the chart with no selection once the click has been handled
        ev = st.pydeck_chart(deck, on_select="rerun", selection_mode="single-object", key=f"{key}-{place}", height=900)
    try:
        objs = ev.selection.objects.get("grid") or []
    except AttributeError:
        objs = []
    if objs:
        p = objs[0].get("properties", objs[0])
        return float(p["lat"]), float(p["lon"])
    return None
