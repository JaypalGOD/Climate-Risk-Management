"""Builds the green, light globe document from the React component's source (single source of truth)."""
from pathlib import Path

TSX = Path(__file__).resolve().parent.parent / "frontend" / "src" / "components" / "ui" / "globe-study.tsx"
GREEN = "12,110,48"
FOCUS = """<style id="threeui-study-focus">
:root{color-scheme:light;--bg:transparent}
html,body,.frame{width:100%!important;height:100%!important;overflow:hidden!important;background:transparent!important}
body{margin:0!important}.frame{padding:0!important}header{display:none!important}
.grid{display:block!important;width:100%!important;height:100%!important;overflow:hidden!important}
.fig{display:flex!important;width:100%!important;height:100%!important;padding:0!important}
.fig::before,.fig::after,.fignum,.fig h3,.fig p{display:none!important}
.art{display:flex!important;width:100%!important;height:100%!important;max-height:none!important;margin:0!important;align-items:center!important;justify-content:center!important}
.plate{width:min(100cqw,100cqh)!important;height:min(100cqw,100cqh)!important;
  background:radial-gradient(ellipse 60% 58% at 50% 48%,rgba(22,163,74,.10),rgba(22,163,74,0) 70%)!important}
</style>"""


def globe_html(ink: str = GREEN) -> str:
    src = TSX.read_text("utf-8")
    doc = src.split("const GLOBE_STUDY_SOURCE = `", 1)[1].split("\n`;", 1)[0]
    authored = "var INK  = '226,228,233';"
    if authored not in doc:
        raise ValueError("globe-study.tsx changed: INK line not found")
    # India-first start and east/west mirror fix are baked into globe-study.tsx
    return doc.replace(authored, f"var INK  = '{ink}';").replace("</head>", FOCUS + "\n</head>")
