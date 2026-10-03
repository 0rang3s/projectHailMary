"""
CUT OFF dashboard.

    streamlit run frontend/app.py

One page for the Albany River flood. Every number comes from data/real
(stats, ice, lifelines, alerts, and the water / ice GeoJSON). August 7 is the
summer baseline already used by those files.

Ask Cut Off uses api/llm.py from the shared assistant. With GROQ_API_KEY in
.env it looks up dates through that tool-using model. Without a key it still
answers from the files loaded on this page.
"""
import html
import json
import os
import glob
import sys
import textwrap
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st
import folium
from folium.template import Template
import streamlit.components.v1 as components
from streamlit_folium import st_folium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = os.path.join(ROOT, "data", "real")
HERE = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass
try:
    import importlib
    import api.llm as llm_mod
    importlib.reload(llm_mod)
    ask_model = llm_mod.ask
    ask_with_data = llm_mod.ask_with_data
    generate_alert = llm_mod.generate_alert
    situation_report = llm_mod.situation_report
except Exception:
    ask_model = ask_with_data = generate_alert = situation_report = None

# Same distance cutoffs as pipeline/analyze.py.
RED_M, YELLOW_M = 200, 1000

EXPOSURE = {
    "red": "HIGH EXPOSURE",
    "yellow": "ELEVATED",
    "green": "LOWER EXPOSURE",
    "no_data": "NOT COVERED",
}
STATUS_COLOR = {"red": "#d7301f", "yellow": "#fe9929", "green": "#31a354", "no_data": "#969696"}
AUDIENCES = (
    ("coordinator", "Coordinator"),
    ("community", "Community"),
    ("pilots", "Pilots"),
)

st.set_page_config(page_title="CUT OFF", layout="wide", initial_sidebar_state="collapsed")
# Styles live in style.css so the page layout stays in this file.
st.markdown(f"<style>{open(os.path.join(HERE, 'style.css'), encoding='utf-8').read()}</style>", unsafe_allow_html=True)


def show(fragment):
    # Injected into the page so style.css applies. Dedent keeps the HTML out of a code block.
    st.markdown(textwrap.dedent(fragment).strip(), unsafe_allow_html=True)


def button(label, key, primary=False, icon=None):
    kwargs = {"key": key, "type": "primary" if primary else "secondary", "width": "stretch"}
    if icon:
        kwargs["icon"] = icon
    try:
        return st.button(label, **kwargs)
    except TypeError:
        kwargs.pop("width", None)
        kwargs.pop("icon", None)
        return st.button(label, use_container_width=True, **kwargs)


def columns(spec):
    try:
        return st.columns(spec, gap="medium")
    except TypeError:
        return st.columns(spec)


def chart(fig, key=None, selectable=False):
    kwargs = {"width": "stretch", "theme": None}
    if selectable:
        kwargs["on_select"] = "rerun"
        kwargs["key"] = key
    try:
        return st.altair_chart(fig, **kwargs)
    except TypeError:
        kwargs.pop("width", None)
        kwargs.pop("on_select", None)
        return st.altair_chart(fig, use_container_width=True, **kwargs)


def jload(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(show_spinner="Loading map…")
def geo(path, tol, mtime):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    from shapely.geometry import shape, mapping
    for feat in data.get("features") or []:
        geom = feat.get("geometry")
        if geom:
            feat["geometry"] = mapping(shape(geom).simplify(tol, preserve_topology=True))
    return json.dumps(data)


def layer(path, tol=0.0002):
    if not os.path.exists(path):
        return None
    return geo(path, tol, os.path.getmtime(path))


def short_date(iso):
    dt = datetime.strptime(iso, "%Y-%m-%d")
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{months[dt.month - 1].upper()} {dt.day}"


def label_for(iso, dates):
    """Slider and chart label. Adds the year when two samples share a month and day."""
    text = short_date(iso)
    if any(other != iso and other[5:10] == iso[5:10] for other in dates):
        text = f"{text} {iso[:4]}"
    return text


def long_date(iso):
    dt = datetime.strptime(iso, "%Y-%m-%d")
    months = "January February March April May June July August September October November December".split()
    return f"{months[dt.month - 1]} {dt.day}, {dt.year}"


def pretty_name(name):
    return " ".join(w.capitalize() for w in name.replace("(", " ").replace(")", " ").split())


def km(value):
    return f"{float(value):.1f}"


def fmt_m(metres):
    if metres is None:
        return "—"
    metres = float(metres)
    if metres >= 1000:
        return f"{metres / 1000:.1f} km"
    return f"{int(round(metres))} m"


def status_for(dist_m):
    if dist_m is None:
        return "no_data"
    if dist_m <= RED_M:
        return "red"
    if dist_m <= YELLOW_M:
        return "yellow"
    return "green"


def phase_of(scene, normal_date):
    if scene.get("baseline") or scene["date"] == normal_date:
        return ("Normal baseline", "#2f6fad")
    if (scene.get("ice") or {}).get("jam_risk"):
        return ("Ice-jam pattern", "#d7301f")
    return ("Flood date", "#e06a12")


def near_vals(ice):
    if not ice:
        return []
    return [v["pct_frozen"] for v in ice.get("near_towns", {}).values() if v.get("pct_frozen") is not None]


def pct_text(value):
    if value is None:
        return "—"
    number = float(value)
    if number.is_integer():
        return f"{int(number)}%"
    return f"{number:.0f}%"


def near_range(ice):
    """Per-town ice, e.g. 'Kashechewan 30% · Fort Albany 0%' (no ranges: they read as unsure)."""
    towns = []
    for key, val in (ice or {}).get("near_towns", {}).items():
        pct = val.get("pct_frozen") if isinstance(val, dict) else None
        if pct is not None:
            towns.append(f"{key.split(' (')[0]} {pct_text(pct)}")
    return " · ".join(towns) if towns else None


def near_tile(ice):
    """Short tile version: value '99% · 97%', label 'Frozen near Kashechewan · Fort Albany'."""
    vals, names = [], []
    for key, val in (ice or {}).get("near_towns", {}).items():
        pct = val.get("pct_frozen") if isinstance(val, dict) else None
        if pct is not None:
            vals.append(pct_text(pct)); names.append(key.split(" (")[0])
    if not vals:
        return "—", "Frozen near the communities"
    return " · ".join(vals), "Frozen near " + " · ".join(names)


def ice_rows(ice):
    rows = []
    for key, val in (ice or {}).get("near_towns", {}).items():
        rows.append((key.split(" (")[0], val.get("pct_frozen")))
    rows.sort(key=lambda row: (0 if row[0].startswith("Fort Albany") else 1 if row[0].startswith("Kashechewan") else 2, row[0]))
    if ice and ice.get("upstream_pct_frozen") is not None:
        rows.append(("Upstream", ice["upstream_pct_frozen"]))
    return rows


def closest(lifelines):
    ranked = [line for line in lifelines if line.get("dist_flood_m") is not None]
    return sorted(ranked, key=lambda line: line["dist_flood_m"])


def load_flood(date):
    folder = os.path.join(REAL, date)
    lifelines = jload(os.path.join(folder, "lifelines_status.json")) or []
    return {
        "date": date,
        "baseline": False,
        "stats": jload(os.path.join(folder, "stats.json")) or {},
        "lifelines": lifelines,
        "alert": jload(os.path.join(folder, "alert.json")),
        "ice": jload(os.path.join(folder, "ice_stats.json")),
        "extra": os.path.join(folder, "flood_extra.geojson"),
        "water": os.path.join(REAL, f"flood_{date}_water.geojson"),
        "ice_path": os.path.join(folder, "river_ice.geojson"),
    }


def load_baseline(normal_date, normal_km, sample_lifelines):
    lifelines = []
    for line in sample_lifelines:
        dist = line.get("dist_normal_m")
        lifelines.append({
            **line,
            "dist_flood_m": dist,
            "status": status_for(dist),
            "closer_by_m": 0,
        })
    return {
        "date": normal_date,
        "baseline": True,
        "stats": {
            "extra_water_km2": 0,
            "normal_water_km2": normal_km,
            "flood_water_km2": normal_km,
            "normal_date": normal_date,
            "flood_date": normal_date,
        },
        "lifelines": lifelines,
        "alert": None,
        "ice": None,
        "extra": None,
        "water": None,
        "ice_path": None,
    }


def answer_question(kind, current, scenes, free_text=""):
    """Answer from the loaded radar files.

    Replace this function when the model endpoint is ready. `current` and
    `scenes` contain only stats, ice, lifelines, and alerts read from data/real.
    """
    if kind == "overview" or kind is None:
        spring = answer_question("change", current, scenes)
        today = answer_question("what", current, scenes)
        return f"{spring} On the date shown now: {today}"

    stats = current["stats"]
    ice = current["ice"]
    when = long_date(current["date"])

    if kind == "what":
        if current["baseline"]:
            return (f"{when} is the summer baseline. Mapped water that day is "
                    f"{km(stats['normal_water_km2'])} km². Flood dates are compared "
                    "with this scene, so additional water is zero here.")
        parts = [f"On {when}, radar shows {km(stats['extra_water_km2'])} km² of water "
                 f"that was not water on {long_date(stats['normal_date'])}."]
        if stats.get("flood_water_km2") is not None and stats["flood_water_km2"] < stats.get("normal_water_km2", 0):
            parts.append(f"Open water is {km(stats['flood_water_km2'])} km², under the baseline "
                         f"{km(stats['normal_water_km2'])} km², because ice-covered river is mapped as ice rather than water.")
        if ice and ice.get("jam_risk"):
            parts.append(f"River frozen near the communities: {near_range(ice)}, against "
                         f"{pct_text(ice['upstream_pct_frozen'])} upstream. That contrast is flagged as an ice-jam pattern.")
        elif ice:
            parts.append(f"River frozen near the communities: {near_range(ice)}; upstream "
                         f"{pct_text(ice['upstream_pct_frozen'])}. No ice-jam pattern is flagged.")
        near = closest(current["lifelines"])
        if near:
            top = near[0]
            parts.append(f"Closest lifeline: {top['name']}, {fmt_m(top['dist_flood_m'])} from water or river ice "
                         f"(normally {fmt_m(top['dist_normal_m'])}).")
        return " ".join(parts)

    if kind == "closest":
        ranked = closest(current["lifelines"])
        if not ranked:
            return "No lifeline distances are available for this scene."
        word = "summer water" if current["baseline"] else "detected water"
        bits = []
        for line in ranked:
            extra = "" if current["baseline"] else f", normally {fmt_m(line['dist_normal_m'])}"
            bits.append(f"{line['name']} at {fmt_m(line['dist_flood_m'])} ({EXPOSURE[line['status']].lower()}{extra})")
        return f"Distance to {word}, closest first: " + "; ".join(bits) + "."

    if kind == "change":
        bits = []
        for scene in scenes:
            label = long_date(scene["date"])
            extra = km(scene["stats"]["extra_water_km2"])
            if scene["baseline"]:
                bits.append(f"{label} is the baseline, so additional water is {extra} km².")
                continue
            frozen = near_range(scene["ice"])
            ice_bit = f" Ice near the communities was {frozen}." if frozen else ""
            bits.append(f"{label}: {extra} km² of additional water.{ice_bit}")
        return " ".join(bits)

    # ice
    jam = next((scene for scene in scenes if scene["ice"] and scene["ice"].get("jam_risk")), None)
    if not jam:
        return "None of the loaded dates is flagged as an ice-jam pattern."
    rows = ", ".join(f"{name} {pct_text(pct)}" for name, pct in ice_rows(jam["ice"]) if name != "Upstream")
    up = pct_text(jam["ice"]["upstream_pct_frozen"])
    rule = jam["ice"].get("rule")
    text = (f"On {long_date(jam['date'])} the river was frozen near the communities ({rows}) "
            f"while upstream was {up} frozen. Water coming downstream has little open channel, "
            "which is the ice-jam pattern.")
    if rule:
        text += f" Rule stored with the result: {rule}."
    if current["date"] != jam["date"] and current["ice"]:
        text += (f" On {long_date(current['date'])} the river near the communities is frozen: {near_range(current['ice'])}; "
                 f"upstream {pct_text(current['ice']['upstream_pct_frozen'])}.")
    elif current["baseline"]:
        text += f" {long_date(current['date'])} is the summer baseline, so river ice was not measured."
    return text


def add_pulse(m):
    # {% raw %} keeps the CSS braces out of Folium's template.
    css = """
    {% raw %}
    <style>
    .ping { width: 18px; height: 18px; margin: 0; }
    .ping::after {
      content: "";
      display: block;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      border: 2px solid var(--c, #d7301f);
      animation: ping 1.6s ease-out infinite;
    }
    @keyframes ping {
      0% { transform: scale(0.7); opacity: 0.85; }
      100% { transform: scale(2.4); opacity: 0; }
    }
    </style>
    {% endraw %}
    """
    m.get_root().html.add_child(folium.Element(css))


def add_water(m, data, name, style, show_layer=True):
    if not data:
        return
    folium.GeoJson(data, name=name, show=show_layer, style_function=lambda f, style=style: style).add_to(m)


class PinLayers(folium.MacroElement):
    """Keep the basemap list open after a click, instead of closing when the pointer leaves."""

    _template = Template("{% macro script(this, kwargs) %}\n{{ this.code }}\n{% endmacro %}")

    def __init__(self):
        super().__init__()
        self._name = "PinLayers"
        self.code = """
        (function () {
          var box = document.querySelector('.leaflet-control-layers');
          if (!box || box.getAttribute('data-pin')) return;
          box.setAttribute('data-pin', '1');
          box.setAttribute('data-open', '0');
          var link = box.querySelector('.leaflet-control-layers-toggle');
          if (link) {
            link.addEventListener('click', function (e) {
              e.preventDefault();
              e.stopImmediatePropagation();
              var open = box.getAttribute('data-open') === '1';
              box.setAttribute('data-open', open ? '0' : '1');
              box.classList.toggle('leaflet-control-layers-expanded', !open);
            }, true);
          }
          new MutationObserver(function () {
            var want = box.getAttribute('data-open') === '1';
            var has = box.classList.contains('leaflet-control-layers-expanded');
            if (want && !has) box.classList.add('leaflet-control-layers-expanded');
            if (!want && has) box.classList.remove('leaflet-control-layers-expanded');
          }).observe(box, { attributes: true, attributeFilter: ['class'] });
        })();
        """


def fit_screen(m, date_count):
    # The map iframe is stretched to the window. This makes the drawing inside fill it,
    # and lets the side panels be dragged wider from their edges.
    m.get_root().html.add_child(folium.Element("""
    {% raw %}
    <style>
      html, body { height: 100% !important; width: 100% !important; margin: 0; }
      body > div,
      .folium-map,
      .float-container,
      .float-child,
      .leaflet-container { height: 100% !important; width: 100% !important; }
      /* Sit beside the date slider instead of under the corner panels. */
      .leaflet-top.leaflet-left {
        top: 18px !important;
        left: max(300px, calc(50% - DOCK_HALF - 78px)) !important;
        right: auto !important;
      }
      .leaflet-top.leaflet-right {
        top: 22px !important;
        left: auto !important;
        right: calc(50% - DOCK_HALF - 68px) !important;
      }
      .leaflet-top.leaflet-right .leaflet-control-layers-expanded {
        background: transparent;
        border: none;
        box-shadow: none;
        color: #0f172a;
      }
      .leaflet-control-layers-expanded .leaflet-control-layers-toggle {
        display: block !important;
      }
      .leaflet-top.leaflet-right .leaflet-control-layers-expanded::after {
        content: "";
        position: absolute;
        top: 100%;
        right: 0;
        width: 240px;
        height: 12px;
      }
      .leaflet-control-layers-expanded .leaflet-control-layers-list {
        position: absolute;
        top: calc(100% + 8px);
        right: 0;
        width: max-content;
        background: #fff;
        border-radius: 10px;
        padding: 6px 10px 6px 6px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
      }
      .leaflet-control-zoom.leaflet-bar {
        display: flex;
        border: none;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
      }
      .leaflet-control-zoom.leaflet-bar a {
        width: 32px;
        height: 32px;
        line-height: 32px;
        border-bottom: 1px solid rgba(15, 23, 42, 0.12);
      }
      .leaflet-control-zoom.leaflet-bar a:first-child { border-radius: 10px 0 0 10px; }
      .leaflet-control-zoom.leaflet-bar a:last-child { border-radius: 0 10px 10px 0; }
      .leaflet-control-layers {
        border-radius: 10px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
      }
    </style>
    <script>
    (function () {
      function fill() {
        document.querySelectorAll('.leaflet-container').forEach(function (box) {
          box.style.height = '100%';
          box.style.width = '100%';
        });
        window.dispatchEvent(new Event('resize'));
      }
      fill();
      window.addEventListener('load', function () {
        setTimeout(fill, 60);
        setTimeout(fill, 400);
      });
    })();
    </script>
    {% endraw %}
    """.replace("DOCK_HALF", f"min((100vw - 620px) / 2, max(240px, {max(date_count, 1) * 48}px))")))


def build_map(scene, normal_path, normal_date, selected_id, center, zoom, date_count):
    chosen = next((line for line in scene["lifelines"] if line["id"] == selected_id), None)
    m = folium.Map(location=center, zoom_start=zoom, tiles=None)
    if chosen:
        add_pulse(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite").add_to(m)
    folium.TileLayer("OpenStreetMap", name="Street map").add_to(m)
    add_water(m, layer(normal_path), f"Normal water ({normal_date})",
              {"color": "#4a90d9", "fillColor": "#9ecae1", "weight": 0.6, "fillOpacity": 0.65})
    if scene["water"]:
        add_water(m, layer(scene["water"]), f"All water on {scene['date']}",
                  {"color": "#08306b", "fillColor": "#08306b", "weight": 0.4, "fillOpacity": 0.45}, False)
    if scene["extra"]:
        add_water(m, layer(scene["extra"]), "Additional water",
                  {"color": "#d7301f", "fillColor": "#d7301f", "weight": 0.4, "fillOpacity": 0.62})
    if scene["ice_path"]:
        add_water(m, layer(scene["ice_path"], 0.0001), "River ice",
                  {"color": "#0b7c93", "fillColor": "#dff6fb", "weight": 1.3, "fillOpacity": 0.9})
    for line in scene["lifelines"]:
        dist = line.get("dist_flood_m")
        tip = f"{line['name']}: {fmt_m(dist)}" if dist is not None else line["name"]
        selected = line["id"] == selected_id
        folium.CircleMarker(
            [line["lat"], line["lon"]],
            radius=13 if selected else 8,
            color="#102033" if selected else "#111",
            weight=3 if selected else 1,
            fill=True,
            fill_color=STATUS_COLOR[line["status"]],
            fill_opacity=0.95,
            tooltip=folium.Tooltip(tip, permanent=selected),
        ).add_to(m)
        if selected:
            folium.Circle(
                [line["lat"], line["lon"]], radius=1000,
                color="#e09a2b", weight=1.5, fill=True, fill_color="#fe9929", fill_opacity=0.05,
            ).add_to(m)
            folium.Circle(
                [line["lat"], line["lon"]], radius=200,
                color="#d7301f", weight=2, fill=True, fill_color="#d7301f", fill_opacity=0.12,
            ).add_to(m)
            folium.Marker(
                [line["lat"], line["lon"]],
                icon=folium.DivIcon(
                    html=f'<div class="ping" style="--c:{STATUS_COLOR[line["status"]]}"></div>',
                    icon_size=(18, 18),
                    icon_anchor=(9, 9),
                ),
            ).add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    # The layers button stays open on click. Hover was closing it before a choice could be made.
    PinLayers().add_to(m)
    fit_screen(m, date_count)
    return m


def summary_card(scene):
    stats, ice = scene["stats"], scene["ice"]
    if scene["baseline"]:
        tag, tone = "SUMMER BASELINE", "calm"
        metrics = [
            (f"{km(stats['normal_water_km2'])} km²", "Normal water"),
            (f"{km(stats['extra_water_km2'])} km²", "Additional water"),
            ("Not measured", "River ice"),
        ]
        sentence = "This summer scene is the comparison day. Flood dates are measured against it."
        caption = ""
    else:
        if ice and ice.get("jam_risk"):
            tag, tone = "ICE-JAM PATTERN", "danger"
            sentence = "River conditions show substantially greater ice coverage near the communities than upstream."
        else:
            tag, tone = phase_of(scene, scene["stats"].get("normal_date", scene["date"]))[0].upper(), "warn"
            sentence = "No ice-jam pattern is flagged for this date." if ice else "River ice was not measured for this scene."
        metrics = [(f"{km(stats['extra_water_km2'])} km²", "Additional water")]
        if ice:
            metrics.append(near_tile(ice))
            metrics.append((pct_text(ice.get("upstream_pct_frozen")), "Frozen upstream"))
        caption = (f"Open water this date {km(stats['flood_water_km2'])} km² · "
                   f"normal open water {km(stats['normal_water_km2'])} km².")
        if stats.get("flood_water_km2", 0) < stats.get("normal_water_km2", 0):
            caption += " Ice-covered channel is mapped as ice, not as open water."

    accent = phase_of(scene, scene["stats"].get("normal_date", scene["date"]))[1]
    blocks = "".join(
        f"<div class='metric' style='animation-delay:{i * 0.06:.2f}s'><b>{html.escape(value)}</b><span>{html.escape(label)}</span></div>"
        for i, (value, label) in enumerate(metrics)
    )
    cap = f"<p class='note'>{html.escape(caption)}</p>" if caption else ""
    show(f"""
    <div class="card rise" style="border-top: 3px solid {accent}">
      <div class="date">{html.escape(long_date(scene['date']))}</div>
      <div class="tag {tone}">{html.escape(tag)}</div>
      {blocks}
      <p class="note">{html.escape(sentence)}</p>
      {cap}
    </div>
    """)


def lifeline_card(line, selected, baseline, index=0):
    cls = f"ll {line['status']}" + (" on" if selected else "")
    where = "from summer water" if baseline else "from water or river ice"
    normal = ""
    if not baseline and line.get("dist_normal_m") is not None:
        text = f"Normal: {fmt_m(line['dist_normal_m'])}"
        closer = line.get("closer_by_m") or 0
        if closer >= 50:
            text += f" · {fmt_m(closer)} closer"
        normal = f"<div class='sub'>{html.escape(text)}</div>"
    approx = "" if line.get("verified", True) else "<div class='sub'>Approximate location</div>"
    show(f"""
    <div class="{cls}" style="animation-delay:{index * 0.05:.2f}s">
      <div class="name">{html.escape(pretty_name(line['name']))}</div>
      <div class="dist">{html.escape(fmt_m(line.get('dist_flood_m')))}</div>
      <div class="sub">{where}</div>
      {normal}
      {approx}
      <div class="exp">{EXPOSURE[line['status']]}</div>
    </div>
    """)


def ice_card(scene):
    ice = scene["ice"]
    if not ice:
        message = ("Ice was not measured on the summer baseline." if scene["baseline"]
                   else "River ice was not measured for this scene.")
        show(f"<div class='card'><p class='note'>{message}</p></div>")
        return
    rows = []
    for name, pct in ice_rows(ice):
        width = 0 if pct is None else max(0, min(100, float(pct)))
        tone = "#0e7490" if width >= 70 else "#7eb8c9"
        rows.append(
            f"<div class='ice-row'><span>{html.escape(name)}</span>"
            f"<div class='track'><div class='fill' style='width:{width:.0f}%;background:{tone}'></div></div>"
            f"<b>{html.escape(pct_text(pct))}</b></div>"
        )
    if ice.get("jam_risk"):
        flag = "<p class='jam'>Potential ice-jam pattern</p>"
    else:
        flag = "<p class='ok'>No ice-jam pattern on this date.</p>"
    rule = f"<p class='rule'>{html.escape(ice['rule'])}</p>" if ice.get("rule") else ""
    seen = ice.get("pct_frozen_overall")
    overall = f"<p class='note'>Across the river in view: {html.escape(pct_text(seen))} frozen.</p>" if seen is not None else ""
    show(f"<div class='card rise'>{''.join(rows)}{flag}{overall}{rule}</div>")


def finish_chart(figure):
    return (
        figure.configure(background="#0f172a")
        .configure_view(stroke=None, fill="#0f172a")
        .configure_axis(
            labelColor="#cbd5e1", titleColor="#cbd5e1", gridColor="#1e293b",
            domainColor="#334155", labelFont="Segoe UI", titleFont="Segoe UI",
        )
        .configure_legend(labelColor="#e2e8f0", labelFont="Segoe UI")
    )


def draw_charts(scenes, selected, height=240):
    dates = [scene["date"] for scene in scenes]
    order = [label_for(scene["date"], dates) for scene in scenes]
    angle = 0 if len(order) <= 6 else -35
    water = pd.DataFrame({
        "label": order,
        "km2": [scene["stats"]["extra_water_km2"] for scene in scenes],
    })
    pick = alt.selection_point(name="pick", fields=["label"])
    water_chart = finish_chart(
        alt.Chart(water)
        .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, cursor="pointer")
        .encode(
            x=alt.X("label:N", sort=order, title=None, axis=alt.Axis(labelAngle=angle)),
            y=alt.Y("km2:Q", title="km²"),
            color=alt.condition(alt.datum.label == label_for(selected, dates), alt.value("#d7301f"), alt.value("#e7b2aa")),
            tooltip=[alt.Tooltip("label:N", title="Date"), alt.Tooltip("km2:Q", title="Additional water (km²)", format=".1f")],
        )
        .add_params(pick)
        .properties(height=height)
    )

    ice_rows_long = []
    for scene in scenes:
        if not scene["ice"]:
            continue
        for name, pct in ice_rows(scene["ice"]):
            if name == "Upstream" or pct is None:
                continue
            ice_rows_long.append({"label": label_for(scene["date"], dates), "place": name, "pct": pct})
    ice_df = pd.DataFrame(ice_rows_long)
    ice_chart = None
    if len(ice_df):
        labels = list(dict.fromkeys(ice_df["label"]))
        opacity = (alt.condition(alt.datum.label == label_for(selected, dates), alt.value(1), alt.value(0.4))
                   if label_for(selected, dates) in labels else alt.value(1))
        places = list(dict.fromkeys(ice_df["place"]))
        ice_palette = ["#7dd3fc", "#38bdf8", "#0284c7", "#0369a1", "#bae6fd", "#0ea5e9"]
        ice_chart = finish_chart(
            alt.Chart(ice_df)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("label:N", sort=labels, title=None, axis=alt.Axis(labelAngle=angle)),
                xOffset="place:N",
                y=alt.Y("pct:Q", title="Percent frozen", scale=alt.Scale(domain=[0, 100])),
                color=alt.Color(
                    "place:N",
                    scale=alt.Scale(domain=places, range=[ice_palette[i % len(ice_palette)] for i in range(len(places))]),
                    legend=alt.Legend(orient="top", title=None),
                ),
                opacity=opacity,
                tooltip=["label", "place", alt.Tooltip("pct:Q", title="Frozen (%)", format=".0f")],
            )
            .properties(height=height)
        )
    left, right = columns(2)
    state = None
    with left:
        show("<div class='h'>Additional water detected</div>")
        state = chart(water_chart, key="water-chart", selectable=True)
        st.caption("Click a bar to open that day. The map takes a moment to load.")
    with right:
        show("<div class='h'>River ice near communities</div>")
        if ice_chart is not None:
            chart(ice_chart)
        else:
            st.caption("No river-ice measurements in the loaded files.")
    return picked_label(state)


def picked_label(state):
    if not state:
        return None
    try:
        rows = state.selection["pick"]
    except Exception:
        return None
    if not rows:
        return None
    row = rows[0]
    return row.get("label") if isinstance(row, dict) else None


def metric_strip(scene):
    stats, ice = scene["stats"], scene["ice"]
    if scene["baseline"]:
        tiles = [
            ("base", f"{km(stats['normal_water_km2'])} km²", "Normal summer water"),
            ("water", f"{km(stats['extra_water_km2'])} km²", "Additional water"),
            ("ice", "Not measured", "River ice"),
        ]
    else:
        tiles = [("water", f"{km(stats['extra_water_km2'])} km²", "Additional water")]
        if ice:
            tiles.append(("ice", *near_tile(ice)))
            tiles.append(("up", pct_text(ice.get("upstream_pct_frozen")), "Frozen upstream"))
        else:
            tiles.append(("ice", "—", "River ice"))
            tiles.append(("up", "—", "Frozen upstream"))
    cols = columns(len(tiles))
    for col, (kind, value, label), wait in zip(cols, tiles, (0, 0.05, 0.1)):
        with col:
            show(
                f"<div class='tile {kind}' style='animation-delay:{wait}s'>"
                f"<b>{html.escape(value)}</b><span>{html.escape(label)}</span></div>"
            )


def story_line(scene, normal_date):
    label, color = phase_of(scene, normal_date)
    stats = scene["stats"]
    near = closest(scene["lifelines"])
    top = near[0] if near else None
    if scene["baseline"]:
        headline = f"{km(stats['normal_water_km2'])} km² of summer river"
        detail = "The normal day. Flood dates are measured against this water."
    elif top:
        headline = f"{fmt_m(top['dist_flood_m'])} to {pretty_name(top['name'])}"
        detail = f"{km(stats['extra_water_km2'])} km² of additional water."
        if scene["ice"] and scene["ice"].get("jam_risk"):
            detail = (f"Ice jam. River frozen near the communities: {near_range(scene['ice'])}; "
                      f"upstream {pct_text(scene['ice']['upstream_pct_frozen'])}. " + detail)
        elif scene["ice"]:
            detail += f" River frozen: {near_range(scene['ice'])}."
    else:
        headline = f"{km(stats['extra_water_km2'])} km² of additional water"
        detail = label
    return label, color, headline, detail


def scene_named_in(question, scenes):
    """If the question names one of the radar dates, answer about that day."""
    clean = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in question.lower())
    tokens = set(clean.split())
    for scene in scenes:
        month, day = short_date(scene["date"]).lower().split()
        if month[:3] in clean and str(int(day)) in tokens:
            return scene
    return None


def radar_brief(scenes, showing):
    """Compact numbers already loaded for this page, so Guide does not look them up one by one."""
    lines = [f"Map is showing {showing}."]
    for scene in scenes:
        stats = scene["stats"]
        ice = scene.get("ice") or {}
        kind = "summer baseline" if scene["baseline"] else "flood date"
        ice_bit = "no ice measurement"
        if ice:
            near = []
            for name, val in (ice.get("near_towns") or {}).items():
                pct = val.get("pct_frozen") if isinstance(val, dict) else None
                if pct is not None:
                    near.append(f"{name.split(' (')[0]} {pct}% frozen within 5 km")
            ice_bit = (
                f"overall {ice.get('pct_frozen_overall')}% frozen, "
                f"upstream {ice.get('upstream_pct_frozen')}% frozen, "
                f"jam risk {bool(ice.get('jam_risk'))}"
            )
            if near:
                ice_bit += "; " + "; ".join(near)
        places = []
        for line in scene["lifelines"]:
            where = "verified" if line.get("verified") else "approximate location"
            dist = line.get("dist_flood_m")
            if dist is None:
                places.append(f"{line['name']}: not assessed ({where})")
            else:
                places.append(
                    f"{line['name']}: {dist} m from water, normally {line.get('dist_normal_m')} m, "
                    f"{line.get('status')} ({where})"
                )
        lines.append(
            f"{scene['date']} ({kind}): extra water {stats.get('extra_water_km2')} km², "
            f"open water {stats.get('flood_water_km2')} km², "
            f"normal river {stats.get('normal_water_km2')} km². Ice: {ice_bit}. "
            + " ".join(places)
        )
    return "\n".join(lines)


def respond(question, scene, scenes, history):
    """Answer from the radar numbers on this page. One model call when a Groq key is set."""
    if ask_with_data is not None and os.environ.get("GROQ_API_KEY"):
        result = ask_with_data(question, radar_brief(scenes, scene["date"]), history)
        if result and result.get("answer"):
            return result
    target = scene_named_in(question, scenes) or scene
    kind = route_question(question) or "overview"
    return {
        "answer": answer_question(kind, target, scenes, question),
        "tools_used": [],
        "dates_cited": [target["date"]],
    }


def remember_answer(question, scene, scenes):
    history = [{"role": item["role"], "content": item["content"]} for item in st.session_state.chat][-8:]
    if history and history[-1]["content"] == question:
        history = history[:-1]
    with st.spinner("Reading the radar results…"):
        result = respond(question, scene, scenes, history)
    tools = [tool.get("name", "") for tool in result.get("tools_used") or [] if isinstance(tool, dict)]
    st.session_state.chat.append({
        "role": "assistant",
        "content": result.get("answer") or "No answer came back.",
        "tools": tools,
        "dates": result.get("dates_cited") or [],
    })


@st.fragment
def chat_panel(scene, scenes):
    pending = st.session_state.pop("pending_q", "")
    if pending:
        remember_answer(pending, scene, scenes)

    configured = bool(os.environ.get("GROQ_API_KEY")) and ask_model is not None
    intro = ("Answers use only the radar results. A reply can take a moment."
             if configured else
             "Answers use the radar results on this page. A reply can take a moment.")
    show("<div class='grip grip-left' title='Drag this edge to widen'></div>")
    show(f"<div class='drawer-title guide-name'><b>Guide</b><span>{html.escape(intro)}</span></div>")
    show("<div class='guide-close'><div class='guide-hide' role='button' tabindex='0'>Close</div></div>")
    if st.session_state.chat:
        bits = ["<div class='thread'>"]
        for message in st.session_state.chat:
            role = message["role"]
            body = html.escape(message["content"]).replace("\n", "<br>")
            chips = ""
            if role == "assistant":
                chips = "".join(f"<i>{html.escape(name)}</i>" for name in message.get("tools") or [])
                chips += "".join(f"<i class='when'>{html.escape(date)}</i>" for date in message.get("dates") or [])
                if chips:
                    chips = f"<div class='chips'>{chips}</div>"
            bits.append(f"<div class='bubble {role}'>{body}{chips}</div>")
        bits.append("</div>")
        show("".join(bits))
    else:
        show("<p class='note'>Ask Guide about the water, the ice, or a lifeline.</p>")

    with st.form("ask-form", clear_on_submit=True):
        typed = st.text_input("Ask about this flood", placeholder="Ask about this flood", label_visibility="collapsed")
        submitted = st.form_submit_button("Send")
    if submitted and typed.strip():
        st.session_state.chat.append({"role": "user", "content": typed.strip()})
        st.session_state.pending_q = typed.strip()
        st.rerun(scope="fragment")

    show("<div class='drawer-title'><b>Alert for this date</b></div>")
    labels = [label for _key, label in AUDIENCES]
    picked = st.radio("Audience", labels, horizontal=True, label_visibility="collapsed", key="audience-label")
    audience = next(key for key, label in AUDIENCES if label == picked)
    if scene["baseline"]:
        normal = next((item["date"] for item in scenes if item["baseline"]), "")
        show(f"<p class='note'>Pick a flood date for an alert. {html.escape(long_date(normal))} is the normal river.</p>")
    elif generate_alert is None:
        alert = scene.get("alert") or {}
        if alert.get("text"):
            show(f"<div class='alert-copy'>{html.escape(alert['text'])}</div>")
    else:
        cache_key = f"{scene['date']}:{audience}"
        if cache_key not in st.session_state.alerts:
            with st.spinner("Writing the alert…"):
                st.session_state.alerts[cache_key] = generate_alert(scene["date"], audience)
        cached = st.session_state.alerts.get(cache_key)
        if cached:
            source = "AI" if cached.get("source") == "llm" else "template"
            show(f"<div class='alert-copy'>{html.escape(cached.get('text') or '')}"
                 f"<span>source: {html.escape(source)}</span></div>")

    if situation_report is not None and button("Download situation report", key="report-build"):
        with st.spinner("Preparing the report…"):
            st.session_state.report_text = situation_report()
    if st.session_state.get("report_text"):
        st.download_button(
            "Save report",
            data=st.session_state.report_text,
            file_name="cut-off-situation-report.md",
            mime="text/markdown",
        )


def arm_panels():
    # Runs beside the map, not inside it, so the edge grips can be dragged.
    components.html(
        """
        <script>
        const doc = window.parent.document;
        function restore(sel, key) {
          const col = doc.querySelector(sel);
          if (!col) return;
          const saved = localStorage.getItem(key);
          if (saved) col.style.setProperty('width', saved, 'important');
        }
        function stretch(grip) {
          const col = grip && grip.closest('[data-testid="stColumn"]');
          const zone = grip && (grip.closest('[data-testid="stElementContainer"]') || grip);
          if (!col || !zone || zone.getAttribute('data-fit')) return;
          zone.setAttribute('data-fit', '1');
          function fit() {
            zone.style.setProperty('height', '0px', 'important');
            const h = Math.max(col.clientHeight, col.scrollHeight);
            zone.style.setProperty('height', h + 'px', 'important');
          }
          fit();
          const watch = new ResizeObserver(fit);
          watch.observe(col);
          const inner = col.querySelector('[data-testid="stVerticalBlock"]');
          if (inner) watch.observe(inner);
        }
        function drag(grip, key, growRight) {
          if (!grip) return;
          const col = grip.closest('[data-testid="stColumn"]');
          const zone = grip.closest('[data-testid="stElementContainer"]') || grip;
          if (!col || zone.getAttribute('data-arm')) return;
          zone.setAttribute('data-arm', '1');
          zone.addEventListener('pointerdown', function (e) {
            e.preventDefault();
            e.stopPropagation();
            try { zone.setPointerCapture(e.pointerId); } catch (err) {}
            const startX = e.clientX;
            const startW = col.getBoundingClientRect().width;
            function move(ev) {
              const delta = ev.clientX - startX;
              let w = growRight ? startW + delta : startW - delta;
              w = Math.max(260, Math.min(820, w));
              col.style.setProperty('width', w + 'px', 'important');
              col.style.setProperty('max-width', w + 'px', 'important');
              col.style.setProperty('flex', 'none', 'important');
              localStorage.setItem(key, String(Math.round(w)) + 'px');
            }
            function up(ev) {
              zone.removeEventListener('pointermove', move);
              zone.removeEventListener('pointerup', up);
              try { zone.releasePointerCapture(ev.pointerId); } catch (err) {}
            }
            zone.addEventListener('pointermove', move);
            zone.addEventListener('pointerup', up);
          });
        }
        restore('[data-testid="stColumn"]:has(.panel-left)', 'cutoff-left');
        restore('[data-testid="stColumn"]:has(.drawer-title)', 'cutoff-right');
        drag(doc.querySelector('.grip-right'), 'cutoff-left', true);
        drag(doc.querySelector('.grip-left'), 'cutoff-right', false);
        stretch(doc.querySelector('.grip-right'));
        stretch(doc.querySelector('.grip-left'));
        function setGuide(open) {
          doc.body.classList.toggle('guide-shut', !open);
          localStorage.setItem('cutoff-guide', open ? '1' : '0');
        }
        function armClick(sel, open) {
          doc.querySelectorAll(sel).forEach(function (node) {
            if (node.getAttribute('data-arm')) return;
            node.setAttribute('data-arm', '1');
            node.addEventListener('click', function (e) {
              e.preventDefault();
              e.stopPropagation();
              setGuide(open);
            });
          });
        }
        if (localStorage.getItem('cutoff-guide') === '0') setGuide(false);
        armClick('.guide-hide', false);
        armClick('.guide-show', true);
        </script>
        """,
        height=0,
        width=0,
    )


def show_map(scene, normal_path, normal_date, date_count):
    with st.spinner("Loading the map…"):
        fmap = build_map(
            scene, normal_path, normal_date, st.session_state.lifeline,
            st.session_state.map_center, st.session_state.map_zoom, date_count,
        )
        st_folium(
            fmap, height=900, use_container_width=True, returned_objects=[],
            center=tuple(st.session_state.map_center), zoom=int(st.session_state.map_zoom),
            key="cutoff-map",
        )
    show("""
    <div class="legend">
      <span><i class="sw-water"></i>Normal water</span>
      <span><i class="sw-flood"></i>Additional water</span>
      <span><i class="sw-ice"></i>River ice</span>
      <span><i class="sw-red"></i>Lifeline ≤200 m from water</span>
      <span><i class="sw-yellow"></i>Lifeline ≤1 km</span>
      <span><i class="sw-green"></i>Lower exposure</span>
      <span><i class="sw-ring"></i>200 m ring</span>
      <span><i class="sw-ring far"></i>1 km ring</span>
    </div>
    """)
    if scene["baseline"]:
        st.caption("Summer baseline. Additional water and river ice are drawn on the flood dates.")


def main():
    normal_files = sorted(glob.glob(os.path.join(REAL, "normal_*_water.geojson")))
    dates = sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(REAL, "*", "stats.json")))
    if not dates or not normal_files:
        st.error("No processed dates in data/real. Run the pipeline first (see README).")
        st.stop()

    normal_path = normal_files[0]
    normal_date = os.path.basename(normal_path).split("_")[1]
    floods = [load_flood(date) for date in dates]
    normal_km = floods[0]["stats"].get("normal_water_km2")
    scenes = floods + [load_baseline(normal_date, normal_km, floods[0]["lifelines"])]
    timeline = [scene["date"] for scene in scenes]

    if st.session_state.get("date") not in timeline:
        st.session_state.date = timeline[0]
    st.session_state.setdefault("lifeline", None)
    st.session_state.setdefault("map_center", [52.24, -81.70])
    st.session_state.setdefault("map_zoom", 12)
    st.session_state.setdefault("ai_open", True)
    st.session_state.setdefault("chat", [])
    st.session_state.setdefault("alerts", {})

    years = sorted({date[:4] for date in timeline})
    year_span = years[0] if len(years) == 1 else f"{years[0]}–{years[-1]}"
    show(f"""
    <style>
    div[data-testid="stHorizontalBlock"]:has(.date-dock) {{
      width: min(calc(100vw - 620px), max(480px, {len(timeline) * 96}px)) !important;
    }}
    </style>
    <div class="top">
      <div>
        <div class="brand">CUT OFF</div>
        <div class="title">Albany River</div>
      </div>
      <div class="badge">RCM · {html.escape(year_span)}</div>
    </div>
    """)

    scene = next(item for item in scenes if item["date"] == st.session_state.date)
    phase_label, accent, headline, detail = story_line(scene, normal_date)
    live = html.escape(phase_label.upper())
    labels = [label_for(date, timeline) for date in timeline]
    label_to_date = dict(zip(labels, timeline))
    synced = st.session_state.pop("sync_slider", None)
    if synced in label_to_date:
        st.session_state.date_label = synced
    elif "date_label" not in st.session_state or st.session_state.date_label not in label_to_date:
        st.session_state.date_label = label_for(st.session_state.date, timeline)

    dock = columns([1])
    with dock[0]:
        show("<div class='date-dock'></div>")
        show("<div class='ticks'>" + "".join(f"<span>{html.escape(label)}</span>" for label in labels) + "</div>")
        picked_label = st.select_slider("Date", options=labels, key="date_label", label_visibility="collapsed")
    chosen = label_to_date[picked_label]
    if chosen != st.session_state.date:
        st.session_state.date = chosen
        st.rerun()

    ask = columns([1])
    with ask[0]:
        show("<div class='ask-fab'><div class='guide-show' role='button' tabindex='0'>Ask Guide</div></div>")

    side, chat_col = columns([1, 1])
    with side:
        show("<div class='panel-left'></div><div class='grip grip-right' title='Drag this edge to widen'></div>")
        show(f"""
        <div class="stage" style="--c:{accent}">
          <div class="kicker">{live}</div>
          <b>{html.escape(headline)}</b>
          <p>{html.escape(detail)}</p>
        </div>
        """)
        metric_strip(scene)
        show("<div class='h'>Closest to the water</div>")
        show("<p class='guide'>Red is within 200 m. Yellow is within 1 km.</p>")
        lines = closest(scene["lifelines"]) or scene["lifelines"]
        for index, line in enumerate(lines):
            lifeline_card(line, line["id"] == st.session_state.lifeline, scene["baseline"], index)
            viewing = line["id"] == st.session_state.lifeline
            if button("On map" if viewing else "View on map", key=f"ll-{line['id']}", primary=viewing):
                if viewing:
                    st.session_state.lifeline = None
                else:
                    st.session_state.lifeline = line["id"]
                    st.session_state.map_center = [line["lat"], line["lon"]]
                    st.session_state.map_zoom = 14
                st.rerun()
        show("<div class='h'>River ice</div>")
        show("<p class='guide'>Frozen beside the towns and open upstream is the jam pattern.</p>")
        ice_card(scene)
        show("<div class='h'>Across the spring</div>")
        show("<p class='guide'>Click a bar to open that day.</p>")
        picked = draw_charts(scenes, scene["date"], height=180)
        by_label = {label_for(item["date"], timeline): item["date"] for item in scenes}
        if picked in by_label and by_label[picked] != st.session_state.date:
            st.session_state.date = by_label[picked]
            st.session_state.sync_slider = picked
            st.rerun()
        show(f"<p class='note'>Flood dates are measured against the normal water on {html.escape(long_date(normal_date))}. Ice-covered river is not counted as open water.</p>")
    with chat_col:
        chat_panel(scene, scenes)

    show_map(scene, normal_path, normal_date, len(timeline))
    arm_panels()


def route_question(text):
    words = text.lower()
    if any(word in words for word in ("ice", "jam", "frozen")):
        return "ice"
    if any(word in words for word in ("lifeline", "airstrip", "causeway", "closest", "infrastructure")):
        return "closest"
    if any(word in words for word in ("change", "since", "evolved", "compared", "trend", "over time")):
        return "change"
    if any(word in words for word in ("explain", "data", "overview", "describe", "about", "mean", "tell")):
        return "overview"
    if any(word in words for word in ("happen", "summary", "status", "flood", "water", "condition", "what")):
        return "what"
    return "overview"


main()
