"""
Cut Off - web app.

Run:  streamlit run app/app.py
Reads only the data-contract files in data/real (no numbers are hard-coded here):
  data/real/normal_<date>_water.geojson         normal-day water (baseline)
  data/real/flood_<date>_water.geojson          water on each flood-season date
  data/real/<date>/flood_extra.geojson          new water vs normal
  data/real/<date>/lifelines_status.json        distances + status
  data/real/<date>/stats.json, alert.json
"""
import json, os, glob
import pandas as pd
import streamlit as st
import folium
import geopandas as gpd
from streamlit_folium import st_folium

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = os.path.join(ROOT, "data", "real")
st.set_page_config(page_title="Cut Off", layout="wide")


@st.cache_data
def geo(path, tol=0.0002):
    if not os.path.exists(path):
        return None
    g = gpd.read_file(path)
    g["geometry"] = g.simplify(tol)          # lighter for the browser
    return g.to_json()


def jload(path):
    return json.load(open(path)) if os.path.exists(path) else None


dates = sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(REAL, "*", "stats.json")))
if not dates:
    st.error("No processed dates in data/real. Run the pipeline first (see README).")
    st.stop()
normal_path = sorted(glob.glob(os.path.join(REAL, "normal_*_water.geojson")))[0]
normal_date = os.path.basename(normal_path).split("_")[1]

# ---------- header ----------
st.title("Cut Off: Albany River flood lifelines")
st.caption("Fort Albany & Kashechewan First Nations · RADARSAT Constellation Mission radar · "
           f"normal day = {normal_date}")

date = st.select_slider("Flood-season date", options=dates, value=dates[0])
D = os.path.join(REAL, date)
stats, lifelines, alert = jload(f"{D}/stats.json"), jload(f"{D}/lifelines_status.json") or [], jload(f"{D}/alert.json")
ice = jload(f"{D}/ice_stats.json")
if ice and ice.get("jam_risk"):
    st.error("⚠️ ICE-JAM PATTERN: river frozen near " + ", ".join(t.split(" (")[0] for t in ice["jam_towns"]) +
             f" while only {ice['upstream_pct_frozen']}% frozen upstream. Water coming downstream has nowhere to go.")

COLORS = {"red": "#d7301f", "yellow": "#fe9929", "green": "#31a354", "no_data": "#969696"}
ICON = {"red": "🔴", "yellow": "🟡", "green": "🟢", "no_data": "⚪"}
left, right = st.columns([3, 1])

# ---------- map ----------
with left:
    m = folium.Map(location=[52.215, -81.80], zoom_start=11, tiles="OpenStreetMap")
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="Satellite").add_to(m)
    folium.GeoJson(geo(normal_path), name=f"Normal water ({normal_date})",
                   style_function=lambda f: {"color": "#4a90d9", "fillColor": "#9ecae1",
                                             "weight": 0.6, "fillOpacity": 0.7}).add_to(m)
    folium.GeoJson(geo(os.path.join(REAL, f"flood_{date}_water.geojson")), name=f"All water on {date}", show=False,
                   style_function=lambda f: {"color": "#08306b", "fillColor": "#08306b",
                                             "weight": 0.4, "fillOpacity": 0.5}).add_to(m)
    folium.GeoJson(geo(f"{D}/flood_extra.geojson"), name=f"New water on {date} (vs normal)",
                   style_function=lambda f: {"color": "#d7301f", "fillColor": "#d7301f",
                                             "weight": 0.4, "fillOpacity": 0.6}).add_to(m)
    folium.GeoJson(geo(f"{D}/river_ice.geojson", tol=0.0001), name=f"River ice on {date}",
                   style_function=lambda f: {"color": "#00e5ff", "fillColor": "#ffffff",
                                             "weight": 1.2, "fillOpacity": 0.9}).add_to(m)
    for L in lifelines:
        d = L.get("dist_flood_m")
        tip = f"{L['name']}: {d} m to water (normally {L['dist_normal_m']} m)" if d is not None else f"{L['name']}: not covered"
        folium.CircleMarker([L["lat"], L["lon"]], radius=9, color="black", weight=1, fill=True,
                            fill_color=COLORS[L["status"]], fill_opacity=0.95, tooltip=tip).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, height=620, use_container_width=True, key=f"map-{date}")
    st.caption("Blue = where water normally is. Red = extra water on the selected date. "
               "White with cyan outline = river still frozen. "
               "Dots = lifelines, coloured by distance to water (red ≤ 200 m, yellow ≤ 1 km).")

# ---------- side panel ----------
with right:
    st.subheader("Lifeline status")
    for L in sorted(lifelines, key=lambda l: (l["dist_flood_m"] is None, l["dist_flood_m"] or 0)):
        tag = "" if L.get("verified") else " ·  _location approx._"
        if L["dist_flood_m"] is None:
            st.markdown(f"{ICON['no_data']} **{L['name']}**  \nnot covered by this scene{tag}")
        else:
            st.markdown(f"{ICON[L['status']]} **{L['name']}**  \n{L['dist_flood_m']} m from water "
                        f"(normally {L['dist_normal_m']} m){tag}")
    if ice:
        st.divider()
        st.subheader("River ice")
        for k, v in ice["near_towns"].items():
            if v["pct_frozen"] is not None:
                st.markdown(f"**{k.split(' (')[0]}** (5 km): {v['pct_frozen']}% frozen")
        st.markdown(f"**Upstream** (15+ km away): {ice['upstream_pct_frozen']}% frozen")
    st.divider()
    st.metric("Extra water vs normal", f"{stats['extra_water_km2']} km²")
    st.caption(f"Normal {stats['normal_water_km2']} km² · this date {stats['flood_water_km2']} km² of open water")
    st.divider()
    st.subheader("Alert")
    if alert:
        st.info(alert["text"])
        st.caption(f"generated by: {alert['source']}")

# ---------- timeline ----------
st.subheader("How the flood changed")
rows = []
for d in dates:
    s = jload(os.path.join(REAL, d, "stats.json"))
    i = jload(os.path.join(REAL, d, "ice_stats.json")) or {}
    near = [v["pct_frozen"] for v in i.get("near_towns", {}).values() if v["pct_frozen"] is not None]
    rows.append({"date": d, "extra water vs normal (km²)": s["extra_water_km2"],
                 "river frozen near towns (%)": max(near) if near else None})
df = pd.DataFrame(rows).set_index("date")
c1, c2 = st.columns(2)
c1.bar_chart(df[["extra water vs normal (km²)"]])
c2.bar_chart(df[["river frozen near towns (%)"]], color="#7fd3e6")
st.caption("Apr 30 comes from a different RCM product (EODMS order, uncalibrated) than May/Aug (analysis-ready data), "
           "and much of the river was still ice-covered that night, so compare it with care.")
