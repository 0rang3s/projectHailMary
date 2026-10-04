"""
Landing page: saved projects + upload a new one.

A project is a folder in data/projects/<slug>/ (see pipeline/run_project.py).
Opening a project sets ?project=<slug> in the URL, and app.py draws the map from that folder.
"""
import html
import json
import math
import os
import re
import shutil
import sys
import textwrap
from datetime import date, datetime

import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(ROOT, "data", "projects")
STAGING = os.path.join(PROJECTS, "_staging")
if os.path.join(ROOT, "pipeline") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "pipeline"))

ARCHIVE = "Find radar for a place"
UPLOAD = "Upload my own files"
LIFELINE_TYPES = ["community", "airstrip", "road", "bridge", "other"]
WRONG_BAND = re.compile(r"(^|[_\-.])(rl|rrrl|xc|ch|cv|local_inc_angle|inc|data_mask|mask|hh)([_\-.]|$)", re.I)

LANDING_CSS = """
<style>
[data-testid="stAppViewContainer"], [data-testid="stMain"], .stApp { height: auto !important; overflow: auto !important; }
.stApp { color: #e2e8f0; }
.block-container { max-width: 1100px !important; padding: 2.2rem 1.4rem 4rem !important; pointer-events: auto !important; margin: 0 auto; }
.land-top { display: flex; align-items: baseline; gap: 14px; margin-bottom: 4px; }
.land-top .brand { font-size: 1.55rem; font-weight: 800; letter-spacing: 0; color: #f8fafc; }
.land-top .sub { color: #94a3b8; }
.land-intro { color: #cbd5e1; max-width: 760px; margin: 2px 0 18px; line-height: 1.5; }
.land-h { margin: 22px 0 8px; font-size: .78rem; font-weight: 700; letter-spacing: .12em; color: #7dd3fc; text-transform: uppercase; }
.pcard { border: 1px solid rgba(125, 211, 252, .25); background: rgba(15, 23, 42, .85); border-radius: 14px; padding: 14px 16px 10px; margin-bottom: 6px; }
.pcard b { font-size: 1.05rem; color: #f8fafc; }
.pcard .meta { color: #94a3b8; font-size: .85rem; margin-top: 3px; }
.pill { display: inline-block; font-size: .7rem; font-weight: 700; letter-spacing: .06em; padding: 2px 8px; border-radius: 999px; margin-left: 8px; vertical-align: middle; }
.pill.done { background: rgba(49, 163, 84, .2); color: #86efac; }
.pill.running, .pill.new { background: rgba(250, 204, 21, .18); color: #fde68a; }
.pill.error { background: rgba(215, 48, 31, .22); color: #fca5a5; }
.pcard .err { color: #fca5a5; font-size: .85rem; margin-top: 6px; }
.howto { color: #94a3b8; font-size: .88rem; line-height: 1.5; }
/* The map page pins every map iframe full-screen. Undo that for the small picker map here. */
[data-testid="stElementContainer"]:has(iframe) { height: auto !important; min-height: 0 !important; overflow: visible !important; }
iframe[data-testid="stCustomComponentV1"]:not([height="0"]) { position: static !important; inset: auto !important;
  width: 100% !important; height: 340px !important; z-index: auto !important; border-radius: 12px !important; }
</style>
"""


def show(fragment):
    st.markdown(textwrap.dedent(fragment).strip(), unsafe_allow_html=True)


# ---------------------------------------------------------------- files
def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "project"
    base, n = slug, 2
    while os.path.exists(os.path.join(PROJECTS, slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def read_project(slug):
    path = os.path.join(PROJECTS, slug, "project.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def list_projects():
    out = []
    if not os.path.isdir(PROJECTS):
        return out
    for slug in sorted(os.listdir(PROJECTS)):
        if slug.startswith("_"):
            continue
        proj = read_project(slug)
        if proj is None:
            continue
        stamp = proj.get("finished") or proj.get("created") or ""
        out.append((slug, proj, stamp))
    # Newest first, but Albany (our tuned reference) always on top.
    out.sort(key=lambda x: x[2], reverse=True)
    out.sort(key=lambda x: 0 if x[0] == "albany-2025" else 1)
    return [(slug, proj) for slug, proj, _ in out]


def has_inputs(slug, proj):
    return all(os.path.exists(os.path.join(PROJECTS, slug, im["file"])) for im in proj.get("images", []))


def guess_date(filename, path):
    """Date from the file name (2025-05-07 / 20250507), else from the TIFF tag."""
    m = re.search(r"(20\d{2})-?([01]\d)-?([0-3]\d)", filename)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            pass
    try:
        from run_project import date_of
        iso = date_of(path)
        return date.fromisoformat(iso) if iso else None
    except Exception:
        return None


def describe_file(path):
    """(kind, problem) for an uploaded file, without running anything heavy."""
    try:
        from run_project import detect_kind
        return detect_kind(path), None
    except Exception as e:
        return None, str(e) or "Could not read this file as a GeoTIFF."


def stage_uploads(files):
    """Write uploads to a staging folder once, so dates/kinds can be read from the real file."""
    os.makedirs(STAGING, exist_ok=True)
    staged = st.session_state.setdefault("staged", {})
    rows = []
    for f in files:
        key = f"{f.name}:{f.size}"
        if key not in staged:
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f.name)
            path = os.path.join(STAGING, f"{len(staged):03d}_{safe}")
            with open(path, "wb") as out:
                shutil.copyfileobj(f, out, length=16 * 1024 * 1024)
            kind, problem = describe_file(path)
            staged[key] = {"path": path, "name": f.name, "kind": kind, "problem": problem,
                           "date": guess_date(f.name, path)}
        rows.append(staged[key])
    return rows


def create_project(name, description, rows, lifelines, advanced):
    slug = slugify(name)
    pdir = os.path.join(PROJECTS, slug)
    os.makedirs(os.path.join(pdir, "inputs"))
    images = []
    for r in rows:
        iso = r["date"].isoformat()
        rel = f"inputs/{iso}.tif"
        shutil.move(r["path"], os.path.join(pdir, rel))
        im = {"date": iso, "role": r["role"], "file": rel}
        if r.get("threshold_db") is not None and not pd.isna(r["threshold_db"]):
            im["threshold_db"] = float(r["threshold_db"])
        images.append(im)
    proj = {"name": name, "description": description or "", "created": datetime.now().isoformat(timespec="seconds"),
            "status": "new", "images": images}
    proj.update({k: v for k, v in advanced.items() if v not in (None, "", [])})
    with open(os.path.join(pdir, "project.json"), "w", encoding="utf-8") as f:
        json.dump(proj, f, indent=2)
    with open(os.path.join(pdir, "lifelines.json"), "w", encoding="utf-8") as f:
        json.dump(lifelines, f, indent=2)
    st.session_state.staged = {}
    return slug


def run_with_status(slug, label):
    from run_project import run_project
    with st.status(label, expanded=True) as box:
        proj = run_project(slug, log=box.write)
        if proj.get("status") == "done":
            box.update(label="Done. Opening the map…", state="complete")
        else:
            box.update(label="It stopped with an error", state="error")
    return proj


def open_project(slug):
    st.query_params["project"] = slug
    st.rerun()


# ---------------------------------------------------------------- page parts
def project_card(slug, proj):
    status = proj.get("status") or "new"
    floods = proj.get("flood_dates") or sorted(im["date"] for im in proj.get("images", []) if im.get("role") == "flood")
    normal = proj.get("normal_date") or next((im["date"] for im in proj.get("images", []) if im.get("role") == "normal"), "?")
    meta = f"{len(floods)} flood date{'s' if len(floods) != 1 else ''}: {', '.join(floods) or '—'} · normal day {normal}"
    body = f"""
    <div class="pcard">
      <b>{html.escape(proj.get('name', slug))}</b><span class="pill {html.escape(status)}">{html.escape(status.upper())}</span>
      <div class="meta">{html.escape(meta)}</div>
      {f'<div class="err">{html.escape(str(proj.get("error")))}</div>' if status == "error" and proj.get("error") else ''}
    </div>
    """
    show(body)
    a, b, _ = st.columns([1, 1, 3])
    if a.button("Open map", key=f"open-{slug}", type="primary", disabled=status != "done", use_container_width=True):
        open_project(slug)
    can_rerun = has_inputs(slug, proj)
    if b.button("Run again", key=f"rerun-{slug}", disabled=not can_rerun, use_container_width=True,
                help=None if can_rerun else "The radar files for this project aren't on this computer."):
        proj = run_with_status(slug, f"Processing {proj.get('name', slug)}…")
        if proj.get("status") == "done":
            open_project(slug)
        else:
            st.error(proj.get("error"))


def lifelines_from(df):
    out, used = [], set()
    for i, row in df.iterrows():
        if pd.isna(row.get("lat")) or pd.isna(row.get("lon")) or not str(row.get("name") or "").strip():
            continue
        lid = re.sub(r"[^a-z0-9]+", "_", str(row["name"]).lower()).strip("_") or f"p{i}"
        while lid in used:
            lid += "_2"
        used.add(lid)
        kind = str(row.get("type") or "other").lower()
        out.append({"id": lid, "name": str(row["name"]).strip(), "type": kind if kind in LIFELINE_TYPES else "other",
                    "lat": float(row["lat"]), "lon": float(row["lon"]),
                    "verified": bool(row.get("exact", True)) if not pd.isna(row.get("exact", True)) else True})
    return out


def new_project_form():
    show("<div class='land-h'>New project</div>")
    name = st.text_input("Project name", placeholder="e.g. Red River, spring 2025")
    description = st.text_input("Short description (optional)", placeholder="What happened, where")
    source = st.radio("Radar images", [ARCHIVE, UPLOAD], horizontal=True, key="source")
    files, picks = None, None
    if source == ARCHIVE:
        picks = archive_section()
    else:
        show("""<div class='howto'>Upload one <b>normal-day</b> image and one or more <b>flood-day</b> images of the same place.
        Works with RCM analysis-ready files from AWS (the <code>rr.tif</code> band) or EODMS GRD orders (the <code>HV.tif</code> file).
        Pick a summer day with no flood as the normal day. Same pass direction for all images works best.</div>""")
        files = st.file_uploader("Radar images (.tif)", type=["tif", "tiff"], accept_multiple_files=True)

    rows = stage_uploads(files) if files else []
    table = None
    if rows:
        for r in rows:
            if r["problem"]:
                st.error(f"{r['name']}: {r['problem']}")
            elif WRONG_BAND.search(os.path.splitext(r["name"])[0]):
                st.warning(f"{r['name']}: this looks like the wrong band. Use the rr file (AWS) or HV (EODMS).")
        good = [r for r in rows if not r["problem"]]
        if good:
            # A Jul-Oct image is the likely normal day; the rest default to flood. The user can change it.
            summer = [r for r in good if r["date"] and r["date"].month in (7, 8, 9, 10)]
            normal_name = (summer[0] if summer else good[-1])["name"]
            df = pd.DataFrame([{
                "file": r["name"], "kind": (r["kind"] or "").upper(), "date": r["date"],
                "role": "normal" if r["name"] == normal_name else "flood", "threshold_db": None,
            } for r in good])
            show("<div class='howto'>Check the dates and pick which image is the normal day. "
                 "Leave the water cutoff empty to have it picked automatically.</div>")
            table = st.data_editor(
                df, hide_index=True, use_container_width=True, key=f"files-{len(good)}",
                disabled=["file", "kind"],
                column_config={
                    "file": st.column_config.TextColumn("File"),
                    "kind": st.column_config.TextColumn("Type", help="ARD = analysis-ready (AWS). GRD = EODMS order."),
                    "date": st.column_config.DateColumn("Date", required=True),
                    "role": st.column_config.SelectboxColumn("Role", options=["normal", "flood"], required=True),
                    "threshold_db": st.column_config.NumberColumn("Water cutoff (dB)", help="Optional. Empty = automatic."),
                })

    show("<div class='land-h'>Lifelines to watch (optional)</div>")
    show("<div class='howto'>Places that matter: towns, airstrips, roads, bridges. Right-click a spot in Google Maps to copy its lat, lon. "
         "Towns (type <b>community</b>) also turn on the ice-jam check.</div>")
    csv = st.file_uploader("…or upload a CSV with columns name, type, lat, lon", type=["csv"], key="ll-csv")
    base = pd.DataFrame({"name": pd.Series(dtype="str"), "type": pd.Series(dtype="str"),
                         "lat": pd.Series(dtype="float"), "lon": pd.Series(dtype="float"), "exact": pd.Series(dtype="bool")})
    if csv is not None:
        try:
            got = pd.read_csv(csv)
            got.columns = [c.strip().lower() for c in got.columns]
            base = pd.concat([base, got[[c for c in base.columns if c in got.columns]]], ignore_index=True)
            base["exact"] = base["exact"].fillna(True)
        except Exception as e:
            st.error(f"Couldn't read that CSV: {e}")
    lifeline_df = st.data_editor(
        base, num_rows="dynamic", hide_index=True, use_container_width=True, key="ll-editor",
        column_config={
            "name": st.column_config.TextColumn("Name"),
            "type": st.column_config.SelectboxColumn("Type", options=LIFELINE_TYPES, default="community"),
            "lat": st.column_config.NumberColumn("Lat", format="%.5f", min_value=-90, max_value=90),
            "lon": st.column_config.NumberColumn("Lon", format="%.5f", min_value=-180, max_value=180),
            "exact": st.column_config.CheckboxColumn("Exact spot?", default=True,
                                                     help="Untick if the location is a rough guess."),
        })

    with st.expander("Advanced (leave empty for automatic)"):
        c1, c2 = st.columns(2)
        res = c1.number_input("Pixel size (m)", min_value=0, value=0, step=10, help="0 = automatic (20 m, larger for big areas)")
        box = "" if source == ARCHIVE else c2.text_input(
            "Area box: west, south, east, north (degrees)", placeholder="-82.40, 52.00, -81.45, 52.45",
            help="Empty = wherever all images overlap.")
        coast = c1.number_input("Ignore everything east of this UTM x (m)", min_value=0, value=0, step=1000,
                                help="For coasts: sea ice and waves are not river. 0 = off.")

    if source == ARCHIVE:
        if st.button("Download and process", type="primary", disabled=picks is None):
            process_archive(name, description, picks, lifelines_from(lifeline_df),
                            {"res_m": int(res) or None, "coast_x": int(coast) or None})
        return
    if st.button("Process images", type="primary", disabled=table is None):
        problems = []
        if not name.strip():
            problems.append("Give the project a name.")
        recs = table.to_dict("records") if table is not None else []
        if sum(r["role"] == "normal" for r in recs) != 1:
            problems.append("Pick exactly one image as the normal day.")
        if not any(r["role"] == "flood" for r in recs):
            problems.append("Add at least one flood-day image.")
        if any(r["date"] is None or (isinstance(r["date"], float) and math.isnan(r["date"])) for r in recs):
            problems.append("Every image needs a date.")
        else:
            isos = [pd.Timestamp(r["date"]).date().isoformat() for r in recs]
            if len(set(isos)) != len(isos):
                problems.append("Two images have the same date.")
        aoi = None
        if box.strip():
            try:
                aoi = [float(v) for v in box.split(",")]
                assert len(aoi) == 4 and aoi[0] < aoi[2] and aoi[1] < aoi[3]
            except Exception:
                problems.append("Area box should be four numbers: west, south, east, north.")
        if problems:
            for p in problems:
                st.error(p)
            return
        by_name = {r["name"]: r for r in rows}
        chosen = [{**by_name[r["file"]], "role": r["role"], "date": pd.Timestamp(r["date"]).date(),
                   "threshold_db": r["threshold_db"]} for r in recs]
        advanced = {"res_m": int(res) or None, "aoi_lonlat": aoi, "coast_x": int(coast) or None}
        slug = create_project(name.strip(), description.strip(), chosen, lifelines_from(lifeline_df), advanced)
        proj = run_with_status(slug, "Processing… (about 30 s to a few minutes)")
        if proj.get("status") == "done":
            open_project(slug)
        else:
            st.error(f"{proj.get('error')}  The project is saved below, so you can fix it and run again.")


def landing():
    show(LANDING_CSS)
    show("""
    <div class="land-top"><div class="brand">RCM FloodScope</div><div class="sub">Flood &amp; river-ice lifeline maps from RADARSAT radar</div></div>
    <div class="land-intro">Pick any place in Canada (or upload your own radar images). RCM FloodScope finds the water, compares each flood day to a
    normal day, spots river ice and ice-jam patterns, and measures how close the water gets to the places you care about.</div>
    """)
    left, right = st.columns([1.15, 1], gap="large")
    with left:
        show("<div class='land-h'>Saved projects</div>")
        projects = list_projects()
        if not projects:
            st.info("No projects yet. Make one on the right.")
        for slug, proj in projects:
            project_card(slug, proj)
    with right:
        new_project_form()


# ---------------------------------------------------------------- find radar for a place
def _set_point(lat, lon):
    st.session_state.arc_lat, st.session_state.arc_lon = round(lat, 5), round(lon, 5)
    st.session_state.pop("arc_results", None)


def archive_section():
    """Pick a place + dates, search the RCM archive, tick the scenes to use. Returns the picks or None."""
    import archive
    import folium
    from streamlit_folium import st_folium

    st.session_state.setdefault("arc_lat", 52.24)
    st.session_state.setdefault("arc_lon", -81.70)
    st.session_state.setdefault("arc_km", 40)
    show("""<div class='howto'>Pick a spot: type a place, click the map, or type coordinates. RCM FloodScope searches Canada's
    free RCM radar archive (2025 onward) for that box, and downloads only that box.</div>""")

    c1, c2 = st.columns([3, 1])
    place = c1.text_input("Place name", placeholder="e.g. Peguis First Nation, Manitoba", label_visibility="collapsed")
    if c2.button("Find place", use_container_width=True) and place.strip():
        try:
            hit = archive.geocode(place.strip())
            if hit:
                _set_point(hit[0], hit[1])
                st.session_state.arc_place = hit[2]
                st.rerun()
            st.warning("No match in Canada. Try a nearby town, or click the map.")
        except Exception as e:
            if type(e).__name__ in ("RerunException", "StopException"):
                raise
            st.error(f"Couldn't look that up ({e}). Type the coordinates instead.")
    if st.session_state.get("arc_place"):
        st.caption(st.session_state.arc_place)

    lat, lon, km = st.session_state.arc_lat, st.session_state.arc_lon, st.session_state.arc_km
    bbox = archive.box_around(lat, lon, km)
    m = folium.Map(location=[lat, lon], zoom_start=max(5, min(12, int(round(10 - math.log2(max(km, 5) / 20))))),
                   tiles="OpenStreetMap")
    folium.Rectangle([[bbox[1], bbox[0]], [bbox[3], bbox[2]]], color="#38bdf8", weight=2, fill=True,
                     fill_opacity=0.08).add_to(m)
    folium.Marker([lat, lon]).add_to(m)
    got = st_folium(m, height=340, use_container_width=True, returned_objects=["last_clicked"], key="arc-map")
    click = (got or {}).get("last_clicked")
    if click and click != st.session_state.get("arc_last_click"):
        st.session_state.arc_last_click = click
        _set_point(click["lat"], click["lng"])
        st.session_state.pop("arc_place", None)
        st.rerun()

    c1, c2, c3 = st.columns(3)
    c1.number_input("Latitude", min_value=41.0, max_value=84.0, step=0.01, format="%.5f", key="arc_lat")
    c2.number_input("Longitude", min_value=-141.0, max_value=-52.0, step=0.01, format="%.5f", key="arc_lon")
    c3.slider("Box size (km)", 10, 100, step=5, key="arc_km")
    st.caption(f"Box: {bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]} (west, south, east, north)")

    c1, c2 = st.columns(2)
    normal_win = c1.date_input("Normal day: search between", (date(2025, 7, 1), date(2025, 9, 30)),
                               min_value=date(2025, 1, 1), key="arc_normal_win",
                               help="Summer or fall, no flood, no snow.")
    flood_win = c2.date_input("Flood days: search between", (date(2025, 4, 15), date(2025, 5, 31)),
                              min_value=date(2025, 1, 1), key="arc_flood_win")

    if st.button("Search the archive", use_container_width=True):
        if len(normal_win) != 2 or len(flood_win) != 2:
            st.error("Pick a start and an end date for both searches.")
        else:
            try:
                with st.spinner("Searching the RCM archive…"):
                    normal = archive.search(bbox, normal_win[0].isoformat(), normal_win[1].isoformat())
                    flood = archive.search(bbox, flood_win[0].isoformat(), flood_win[1].isoformat())
                st.session_state.arc_results = {"bbox": list(bbox), "normal": normal, "flood": flood}
            except Exception as e:
                st.error(f"Search failed: {e}")

    res = st.session_state.get("arc_results")
    if not res:
        return None
    if list(res["bbox"]) != list(bbox):
        st.info("You moved the box. Search again to update the list.")
        return None
    if not res["normal"] or not res["flood"]:
        which = "normal-day" if not res["normal"] else "flood-day"
        st.warning(f"No {which} scenes cover this box in those dates. Try wider dates (the archive starts in 2025).")
        return None

    # Pre-pick: the best-covering normal scene (ascending if possible), then flood scenes from the same
    # pass direction that cover most of the box. The user can change any of it.
    def score(sc):
        return (sc["coverage"] >= 90, sc["orbit"] == "ascending", sc["coverage"])
    best = max(res["normal"], key=score)
    floods = [sc for sc in res["flood"] if sc["coverage"] >= 90 and sc["orbit"] == best["orbit"]][:4]
    rows = []
    for role, scenes in (("normal", res["normal"]), ("flood", res["flood"])):
        for sc in scenes:
            rows.append({"use": sc is best or sc in floods, "role": role, "when (UTC)": sc["when"],
                         "pass": sc["orbit"], "covers %": sc["coverage"], "id": sc["id"]})
    show(f"<div class='howto'>Found {len(res['normal'])} normal-day and {len(res['flood'])} flood-day scenes. "
         "Tick one normal day and the flood days you want. Pick scenes that cover more than 90% of the box, "
         "with the same pass for all of them.</div>")
    table = st.data_editor(
        pd.DataFrame(rows), hide_index=True, use_container_width=True, key=f"arc-table-{len(rows)}",
        disabled=["when (UTC)", "pass", "covers %", "id"], column_order=["use", "role", "when (UTC)", "pass", "covers %"],
        column_config={
            "use": st.column_config.CheckboxColumn("Use"),
            "role": st.column_config.SelectboxColumn("Role", options=["normal", "flood"], required=True),
            "covers %": st.column_config.ProgressColumn("Covers box", min_value=0, max_value=100, format="%.0f%%"),
        })
    by_id = {sc["id"]: sc for sc in res["normal"] + res["flood"]}
    return {"bbox": res["bbox"], "picks": [{**by_id[r["id"]], "role": r["role"]}
                                           for r in table.to_dict("records") if r["use"]]}


def process_archive(name, description, picks, lifelines, advanced):
    import archive
    chosen = picks["picks"]
    problems = []
    if not name.strip():
        problems.append("Give the project a name.")
    if sum(sc["role"] == "normal" for sc in chosen) != 1:
        problems.append("Tick exactly one normal-day scene.")
    if not any(sc["role"] == "flood" for sc in chosen):
        problems.append("Tick at least one flood-day scene.")
    dates = [sc["date"] for sc in chosen]
    if len(set(dates)) != len(dates):
        problems.append("Two ticked scenes are on the same day. Keep the one that covers more.")
    if len({sc["orbit"] for sc in chosen}) > 1:
        st.warning("You mixed ascending and descending passes. It will run, but the water edges may not line up as well.")
    if problems:
        for p in problems:
            st.error(p)
        return
    slug = slugify(name.strip())
    pdir = os.path.join(PROJECTS, slug)
    os.makedirs(os.path.join(pdir, "inputs"))
    images = []
    with st.status("Downloading radar…", expanded=True) as box:
        try:
            for sc in sorted(chosen, key=lambda x: x["date"]):
                rel = f"inputs/{sc['date']}.tif"
                box.write(f"Downloading {sc['date']} ({sc['role']})…")
                filled = archive.download(sc, picks["bbox"], os.path.join(pdir, rel))
                if filled < 0.5:
                    st.warning(f"{sc['date']} only has data over {filled:.0%} of the box.")
                images.append({"date": sc["date"], "role": sc["role"], "file": rel, "scene_id": sc["id"]})
            box.update(label="Downloaded", state="complete")
        except Exception as e:
            box.update(label="Download failed", state="error")
            st.error(f"Download failed: {e}")
            shutil.rmtree(pdir, ignore_errors=True)
            return
    proj = {"name": name.strip(), "description": description or "", "source": "RCM ARD archive (AWS)",
            "created": datetime.now().isoformat(timespec="seconds"), "status": "new",
            "aoi_lonlat": picks["bbox"], "images": images}
    proj.update({k: v for k, v in advanced.items() if v not in (None, "", [])})
    with open(os.path.join(pdir, "project.json"), "w", encoding="utf-8") as f:
        json.dump(proj, f, indent=2)
    with open(os.path.join(pdir, "lifelines.json"), "w", encoding="utf-8") as f:
        json.dump(lifelines, f, indent=2)
    st.session_state.pop("arc_results", None)
    proj = run_with_status(slug, "Processing… (about 30 s to a few minutes)")
    if proj.get("status") == "done":
        open_project(slug)
    else:
        st.error(f"{proj.get('error')}  The project is saved on the left, so you can fix it and run again.")
