"""AI Climate & SDG Action Map: Streamlit app (router, theme, background map, cookie notice, info pages).

Local:   double-click streamlit.bat   (or: backend\\.venv\\Scripts\\python -m streamlit run streamlit_app.py)
Online:  share.streamlit.io -> Create app -> this repo -> main file: streamlit_app.py
"""
import base64
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import importlib
import views.globe
import views.mapkit
for _m in (views.mapkit, views.globe):  # pick up edits to helper modules without restarting the server
    importlib.reload(_m)
from views.globe import globe_html


ROOT = Path(__file__).resolve().parent
EFFECTIVE = "7 October 2026"
st.set_page_config(page_title="AI Climate & SDG Action Map", page_icon="🌿", layout="wide")


# ------------------------------------------------------------------ background map (built from our own India grid)
@st.cache_data(show_spinner=False)
def background_svg() -> str:
    """Draws the national hazard grid as a soft green SVG map, used as the animated page background."""
    p = ROOT / "frontend" / "public" / "data" / "grid.geojson"
    cells = json.loads(p.read_text("utf-8"))["features"] if p.exists() else []
    greens = ["#d9f2e1", "#b9e6c7", "#8fd4a7", "#5fbf85", "#2f9e62"]
    rects = []
    for f in cells:
        pr = f["properties"]
        v = pr.get("climate")
        c = greens[min(4, int((v or 0) // 20))]
        x, y = (pr["lon"] - 66) * 20, (38 - pr["lat"]) * 20
        rects.append(f'<rect x="{x - 9.4:.1f}" y="{y - 9.4:.1f}" width="18.8" height="18.8" rx="4" fill="{c}"/>')
    lines = "".join(f'<path d="M0 {y} H660" stroke="#16a34a" stroke-opacity=".06"/>' for y in range(0, 640, 40))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 660 640">{lines}'
           f'<g opacity=".9">{"".join(rects)}</g></svg>')
    return base64.b64encode(svg.encode()).decode()


st.markdown(f"""<style>
:root {{ --green:#16a34a; --deep:#0f5132; --ink:#0f2e1d; --muted:#4b6b58; }}
.stApp {{ background: linear-gradient(160deg,#f6fbf7 0%,#e9f7ee 55%,#dff3e6 100%); }}
.stApp::before {{ content:""; position:fixed; inset:-6%; z-index:0; pointer-events:none;
  background:url("data:image/svg+xml;base64,{background_svg()}") center/min(115vw,1250px) no-repeat;
  opacity:.75; animation: drift 38s ease-in-out infinite alternate; }}
.stApp::after {{ content:""; position:fixed; inset:0; z-index:0; pointer-events:none;
  background: radial-gradient(circle at 15% 20%, rgba(255,255,255,.75), transparent 45%),
              radial-gradient(circle at 85% 80%, rgba(255,255,255,.6), transparent 40%); }}
@keyframes drift {{ from {{ transform: scale(1) translate(0,0); }} to {{ transform: scale(1.08) translate(-2%,1.5%); }} }}
.stApp > header, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {{ position:relative; z-index:1; }}
[data-testid="stHeader"] {{ background: transparent; }}
/* every panel and box: light green, well rounded */
.glass, .card, .st-key-legallist, .st-key-topnav, .st-key-panel, .st-key-legend, [role="dialog"], [data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]), [data-testid="stExpander"] details, [data-testid="stAlert"] > div, .st-key-homewrap .glass, .st-key-homewrap .card {{
  background: rgba(220,252,231,.80) !important; border: 1px solid rgba(22,163,74,.30) !important; border-radius: 24px !important;
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); box-shadow: 0 8px 24px rgba(15,81,50,.10) !important; }}
[data-testid="stSidebar"], [data-testid="stSidebar"] > div {{ background: rgba(220,252,231,.70) !important; }}
.st-key-panel .card, .st-key-panel [data-testid="stVerticalBlockBorderWrapper"] {{ background: rgba(240,253,244,.92) !important; }}
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {{ background: #f0fdf4 !important; border-radius: 14px !important; }}
.stButton button, .stLinkButton a, [data-testid="stPageLink"] a {{ border-radius: 999px !important; }}
/* black text everywhere, in light and dark mode */
.stApp, .stApp *:not(svg):not(path), .deck-tooltip, .deck-tooltip * {{ color: #000 !important; -webkit-text-fill-color: #000 !important; }}
[data-testid="stSidebar"] {{ position:sticky !important; top:0; height:100vh !important; }}  /* keep it viewport-tall so it scrolls */
[data-testid="stSidebarContent"] {{ height:100% !important; overflow-y:auto !important; }}
[data-testid="stSidebar"], [data-testid="stSidebar"] > div {{ background: rgba(255,255,255,.25) !important; backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); }}
.block-container {{ padding-top: 1.4rem; }}
.glass, .card {{ background: rgba(255,255,255,.58); backdrop-filter: blur(14px) saturate(1.2); -webkit-backdrop-filter: blur(14px);
  border:1px solid rgba(22,163,74,.18); border-radius:18px; box-shadow:0 10px 30px rgba(15,81,50,.08); }}
.glass {{ padding: 26px 30px; margin-bottom: 18px; }}
.card {{ padding: 12px 16px; margin-bottom: 9px; transition: transform .25s ease, box-shadow .25s ease; }}
.card:hover {{ transform: translateY(-3px); box-shadow:0 16px 36px rgba(15,81,50,.14); }}
.fade {{ opacity:0; animation: fadeUp .8s cubic-bezier(.2,.7,.2,1) forwards; }}
.d1 {{ animation-delay:.1s }} .d2 {{ animation-delay:.25s }} .d3 {{ animation-delay:.4s }} .d4 {{ animation-delay:.55s }} .d5 {{ animation-delay:.7s }}
@keyframes fadeUp {{ from {{ opacity:0; transform: translateY(18px); }} to {{ opacity:1; transform:none; }} }}
.hero h1 {{ font-size: clamp(1.9rem, 3.4vw, 3rem); overflow-wrap: normal; word-break: normal; hyphens: none; line-height:1.08; color:var(--ink); margin:0 0 .4rem; letter-spacing:-.02em; }}
.hero h1 span {{ background: linear-gradient(90deg,#16a34a,#0ea5a4); -webkit-background-clip:text; color:transparent; }}
.hero p {{ font-size:1.12rem; color:var(--muted); max-width:760px; }}
.badge {{ display:inline-block; padding:4px 12px; border-radius:99px; background:rgba(22,163,74,.12); color:var(--deep);
  font-weight:600; font-size:.8rem; margin-bottom:.8rem; animation: pulse 3s ease-in-out infinite; }}
@keyframes pulse {{ 50% {{ box-shadow:0 0 0 8px rgba(22,163,74,0); }} 0%,100% {{ box-shadow:0 0 0 0 rgba(22,163,74,.25); }} }}
.step {{ padding:12px 16px; }}
.step b {{ font-size:1.4rem; color:var(--green); margin-right:10px; }}
.float {{ animation: float 6s ease-in-out infinite; display:inline-block; }}
@keyframes float {{ 50% {{ transform: translateY(-6px); }} }}
.sdg {{ display:inline-block; width:26px; height:26px; line-height:26px; text-align:center; border-radius:6px; color:#fff;
  font-weight:700; font-size:12px; margin:1px; }}
.pill {{ display:inline-block; padding:1px 9px; border-radius:99px; font-size:12px; font-weight:600; }}
.small {{ font-size:12.5px; color:var(--muted); }}
.legal h3 {{ color:var(--deep); margin-top:1.2rem; }} .legal p, .legal li {{ color:#284a37; }}
@media (prefers-reduced-motion: reduce) {{ *, .stApp::before {{ animation:none !important; transition:none !important; }} .fade {{ opacity:1; }} }}
</style>""", unsafe_allow_html=True)

# Silk background video on every page. st.video serves the file with the right type (Streamlit's
# /app/static route sends .mp4 as text/plain, which browsers refuse to play); CSS turns it into a backdrop.
st.markdown("""<style>
.stApp::before, .stApp::after { display:none !important; }
[data-testid="stMain"], [data-testid="stMainBlockContainer"], .main { background: transparent !important; }
.st-key-silkbg { position:fixed !important; inset:0; z-index:-1; pointer-events:none; }
.st-key-silkbg video { position:fixed; inset:0; width:100vw !important; height:100vh !important; object-fit:cover; }
.st-key-silkbg video::-webkit-media-controls, .st-key-silkbg video::-webkit-media-controls-enclosure { display:none !important; }
</style>""", unsafe_allow_html=True)
with st.container(key="silkbg"):
    st.video(str(ROOT / "static" / "hero_loop.mp4"), autoplay=True, loop=True, muted=True)


# ------------------------------------------------------------------ cookie notice
@st.dialog("🍪 Cookies on this site")
def cookie_notice():
    st.write("We do **not** use advertising, tracking or analytics cookies. The hosting platform (Streamlit) sets "
             "**strictly necessary** cookies so the app and your session work. These cannot be switched off.")
    st.page_link(PAGES["privacy"], label="Read our Privacy Policy", icon="🔒")
    c1, c2 = st.columns(2)
    if c1.button("Accept", type="primary", use_container_width=True):
        st.session_state.cookies = "accepted"
        st.rerun()
    if c2.button("Essential only", use_container_width=True):
        st.session_state.cookies = "essential"
        st.rerun()


def footer():
    st.markdown("<br>", unsafe_allow_html=True)
    c = st.columns([2, 1, 1, 1, 1])
    c[0].caption("© 2026 Team SapioCoders · BMS College of Engineering · Hack4SDG project")
    c[1].page_link(PAGES["privacy"], label="Privacy")
    c[2].page_link(PAGES["terms"], label="Terms")
    c[3].page_link(PAGES["security"], label="Security")
    c[4].page_link(PAGES["cookies"], label="Cookies")


def legal_list():
    with st.container(key="legallist"):
        st.markdown("#### 📚 Policies & information")
        for k, desc in (("privacy", "what data is processed and who receives it"),
                        ("terms", "how the site may be used; scores are not forecasts"),
                        ("security", "how we keep the app and its data safe"),
                        ("cookies", "only essential cookies, no tracking")):
            c1, c2 = st.columns([1, 2.2])
            c1.page_link(PAGES[k], label=PAGES[k].title, icon=PAGES[k].icon)
            c2.caption(desc)
        st.caption("© 2026 Team SapioCoders · BMS College of Engineering · Hack4SDG project")


# ------------------------------------------------------------------ pages
def home():
    st.markdown("""<style>
    .st-key-homewrap { max-width: 1200px; margin: 0 auto; }
    .st-key-globe iframe { background: transparent; }
    .st-key-globe { animation: fadeUp 1s ease both; }
    .st-key-homewrap .glass, .st-key-homewrap .card { background: rgba(255,255,255,.28); backdrop-filter: blur(6px) saturate(1.3);
      -webkit-backdrop-filter: blur(6px); border-color: rgba(255,255,255,.5); }
    .st-key-legallist { background: rgba(255,255,255,.35); backdrop-filter: blur(8px); border-radius: 18px; padding: 14px 20px;
      border: 1px solid rgba(255,255,255,.55); }
    /* home: no side menu, a top bar instead */
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] { display: none !important; }
    .st-key-topnav { position: sticky; top: 0; z-index: 10; background: rgba(255,255,255,.35); backdrop-filter: blur(10px);
      -webkit-backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,.55); border-radius: 16px; padding: 6px 16px; margin-bottom: 14px; }
    .st-key-topnav p { margin: 0; }
    </style>""", unsafe_allow_html=True)
    with st.container(key="topnav"):
        b, n1, n2, n3 = st.columns([3, 0.7, 0.8, 0.9], vertical_alignment="center")
        b.markdown("**🌿 AI Climate & SDG Action Map** <span class='small'>· Team SapioCoders · BMS College of Engineering</span>",
                   unsafe_allow_html=True)
        n1.page_link(PAGES["home"], label="Home", icon="🌿")
        n2.page_link(PAGES["map"], label="Live map", icon="🗺️")
        n3.page_link(PAGES["privacy"], label="Privacy", icon="🔒")
    with st.container(key="homewrap"):
        home_content(link_list=True)


def home_content(link_list=False):
    left, right = st.columns([1.15, 1], gap="large", vertical_alignment="center")
    with left:
        st.markdown("""<div class="glass hero fade">
          <div class="badge">🌿 Hack4SDG 2026 · Team SapioCoders</div>
          <h1>From environmental data to <span>real-world SDG action</span></h1>
          <p>Click any place in India and see its <b>heat, flood and drought risk</b>, why it is at risk, which
          <b>Sustainable Development Goals</b> it affects, what could be done, and how much a change could help.</p>
        </div>""", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        if c1.button("🗺️ Open the live map", type="primary", use_container_width=True):
            st.switch_page(PAGES["map"])
        c2.page_link(PAGES["security"], label="How we keep it safe", icon="🛡️")
    with right:  # interactive green globe (frontend/src/components/ui/globe-study.tsx)
        with st.container(key="globe"):
            components.html(globe_html(), height=540)
            st.caption("🌍 Drag to spin · scroll to zoom · click to drop a pin")

    st.markdown("""<div class="glass fade d1"><h3>🎯 Our goal</h3>
      <p>Climate data is everywhere, but it rarely tells a city <i>what to do</i>. Dashboards stop at
      "rainfall = 180 mm". We carry it all the way: <b>data → risk → SDG impact → action → what-if</b>, with every
      score showing its drivers and sources. We support SDG decisions; we don't claim to solve the SDGs.</p></div>""",
                unsafe_allow_html=True)

    steps = [("1", "Real data", "NASA POWER climate, Copernicus elevation, MODIS vegetation, WorldPop population"),
             ("2", "Risk engine", "Hazard + exposure + vulnerability → a 0–100 score for heat, flood and drought"),
             ("3", "SDG rulebook", "An explicit, published mapping from each risk to the SDGs it affects"),
             ("4", "Actions", "Interventions matched to the drivers, like greening, drainage or rainwater harvesting"),
             ("5", "What-if + AI", "Simulate a change with a range; AI explains it and is number-checked")]
    for i, (n, t, d) in enumerate(steps):
        st.markdown(f'<div class="card step fade d{i + 1}"><b class="float">{n}</b><strong>{t}</strong>'
                         f'<div class="small">{d}</div></div>', unsafe_allow_html=True)

    a = b = st
    sdg_col = {2: "#DDA63A", 3: "#4C9F38", 6: "#26BDE2", 7: "#FCC30B", 8: "#A21942", 9: "#FD6925",
               11: "#FD9D24", 13: "#3F7E44", 15: "#56C02B", 1: "#E5243B"}
    chips = "".join(f'<span class="sdg" style="background:{c}">{n}</span>' for n, c in sorted(sdg_col.items()))
    a.markdown(f"""<div class="glass fade d2"><h4>🌍 SDGs we inform</h4>{chips}
      <p class="small" style="margin-top:.6rem">Core: 2, 3, 6, 11, 13, 15 · Supporting: 1, 7, 8, 9 · Relevance is
      always "relevant to SDG X", never "improves SDG X by N%".</p></div>""", unsafe_allow_html=True)
    b.markdown("""<div class="glass fade d3"><h4>✅ Honest by design</h4>
      <ul class="small"><li>Scores are relative indicators for prioritisation, not forecasts</li>
      <li>Weights and limits are published on every result</li>
      <li>AI only narrates our numbers; invented numbers are rejected</li>
      <li>No accounts, no tracking, no personal data</li></ul></div>""", unsafe_allow_html=True)

    st.markdown("""<div class="glass fade d4"><h4>👥 Who it's for</h4><p class="small">City planners and disaster cells
      (where to act first), NGOs (where to target help), researchers and students (learning SDGs through real data),
      and citizens (understanding local climate risk).</p></div>""", unsafe_allow_html=True)
    if link_list:
        legal_list()
    else:
        footer()


def legal(title, body, slug):
    def page():
        st.markdown(f'<div class="glass legal fade"><h2>{title}</h2><p class="small">Effective {EFFECTIVE} · '
                    f'AI Climate &amp; SDG Action Map (student project by Team SapioCoders)</p>{body}</div>',
                    unsafe_allow_html=True)
        footer()
    page.__name__ = slug  # each page needs a unique function name
    return page


PRIVACY = """
<h3>1. Summary</h3><p>We don't ask for your name, email or any account. We don't sell or share personal data, and we use no analytics or ads.</p>
<h3>2. What is processed</h3><ul>
<li><b>Places you pick or search</b> (coordinates and search text) are used to fetch public environmental data for that place.</li>
<li><b>Technical data</b> such as your IP address and browser type may be logged by our hosting provider (Streamlit Community Cloud) for security and operation.</li></ul>
<h3>3. Third-party services</h3><p>To analyse a place, its coordinates (never your identity) are sent to: NASA POWER, Open-Meteo, OpenStreetMap Nominatim, NASA MODIS (ORNL DAAC), WorldPop, and the Pollinations AI text service (for the optional AI explanation, which receives only our computed results). Each has its own privacy policy.</p>
<h3>4. Cookies</h3><p>Only strictly necessary cookies set by the hosting platform. See the Cookie Policy.</p>
<h3>5. Retention</h3><p>Analysis results are cached temporarily on the server to make the app fast; they contain place data only, not personal data.</p>
<h3>6. Your rights</h3><p>Because we don't collect personal data, there is normally nothing to access or delete. If you have a concern, contact the team through our hackathon organisers or project repository.</p>
<h3>7. Children</h3><p>The site is educational and collects no personal data from anyone.</p>
<h3>8. Changes</h3><p>We'll update this page and its effective date if anything changes.</p>"""

TERMS = """
<h3>1. Purpose</h3><p>This is an educational prototype built for the Hack4SDG hackathon. By using it you accept these terms.</p>
<h3>2. Not advice, not a forecast</h3><p>Risk scores are <b>relative indicators for prioritisation</b>, not predictions, warnings or professional advice. <b>Do not use this site for emergency decisions</b>; follow official sources such as IMD and NDMA.</p>
<h3>3. AI content</h3><p>AI explanations are generated automatically from our computed results and checked for invented numbers, but they can still be wrong or incomplete.</p>
<h3>4. Scenarios</h3><p>What-if results are model-based estimates under stated assumptions, not guaranteed outcomes.</p>
<h3>5. Data sources &amp; licences</h3><p>NASA POWER and NASA MODIS (public), Open-Meteo (CC BY 4.0), WorldPop (CC BY 4.0), map data © OpenStreetMap contributors (ODbL), basemap © CARTO. All credit belongs to these providers.</p>
<h3>6. Acceptable use</h3><p>Don't overload, scrape or attack the service, and don't present its outputs as official government data.</p>
<h3>7. No warranty</h3><p>The service is provided "as is" without warranties. To the extent the law allows, the team is not liable for decisions made using it.</p>
<h3>8. Changes</h3><p>We may update these terms; the effective date above will change.</p>"""

SECURITY = """
<h3>How we keep the app safe</h3><ul>
<li><b>No accounts or passwords</b>: there is nothing to steal or leak.</li>
<li><b>No secrets in the browser</b>: all data and AI calls run on the server.</li>
<li><b>Encrypted traffic</b>: the hosted site is served over HTTPS.</li>
<li><b>Input validation</b>: coordinates are checked against the India coverage area; free text only goes to the place search.</li>
<li><b>Polite to data providers</b>: caching and rate limits protect upstream services (e.g. 1 request/second to OpenStreetMap).</li>
<li><b>AI guardrails</b>: the AI only sees a fact sheet of our results; every number it writes is checked, and failures fall back to a rule-based explanation.</li>
<li><b>Graceful failure</b>: if a source is down, the score is flagged "estimated" or "insufficient data", never faked.</li></ul>
<h3>Reporting a problem</h3><p>Found a bug or security issue? Please tell the team through the hackathon organisers or our project repository's issues page.</p>"""

COOKIES = """
<h3>What we use</h3><p>Only <b>strictly necessary</b> cookies set by the hosting platform (Streamlit) to run the app and keep your session working.</p>
<h3>What we don't use</h3><p>No advertising, tracking, analytics or social-media cookies.</p>
<h3>Your choice</h3><p>Because only essential cookies are used, the app works the same whichever button you press in the notice. You can also clear cookies in your browser settings at any time.</p>"""

PAGES = {
    "home": st.Page(home, title="Home", icon="🌿", default=True, url_path="home"),
    "map": st.Page("views/map_page.py", title="Live map", icon="🗺️", url_path="map"),
    "privacy": st.Page(legal("Privacy Policy", PRIVACY, "privacy"), title="Privacy Policy", icon="🔒", url_path="privacy"),
    "terms": st.Page(legal("Terms &amp; Conditions", TERMS, "terms"), title="Terms & Conditions", icon="📄", url_path="terms"),
    "security": st.Page(legal("Security", SECURITY, "security"), title="Security", icon="🛡️", url_path="security"),
    "cookies": st.Page(legal("Cookie Policy", COOKIES, "cookies"), title="Cookie Policy", icon="🍪", url_path="cookies"),
}

# Legal pages stay reachable from the footer links but are hidden from the side menu.
nav = st.navigation(list(PAGES.values()), position="hidden")
with st.sidebar:
    st.markdown("### 🌿 AI Climate & SDG Action Map")
    st.caption("Team SapioCoders · BMS College of Engineering")
    st.page_link(PAGES["home"], label="Home", icon="🌿")
    st.page_link(PAGES["map"], label="Live map", icon="🗺️")
if "cookies" not in st.session_state:
    cookie_notice()
nav.run()
