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

LIFELINE_TYPES = ["community", "airstrip", "road", "bridge", "other"]
WRONG_BAND = re.compile(r"(^|[_\-.])(rl|rrrl|xc|ch|cv|local_inc_angle|inc|data_mask|mask|hh)([_\-.]|$)", re.I)

LANDING_CSS = """
<style>
[data-testid="stAppViewContainer"], [data-testid="stMain"], .stApp { height: auto !important; overflow: auto !important; }
.stApp { color: #e2e8f0; }
.block-container { max-width: 1100px !important; padding: 2.2rem 1.4rem 4rem !important; pointer-events: auto !important; margin: 0 auto; }
.land-top { display: flex; align-items: baseline; gap: 14px; margin-bottom: 4px; }
.land-top .brand { font-size: 1.9rem; font-weight: 800; letter-spacing: .08em; color: #f8fafc; }
.land-top .sub { color: #94a3b8; }
.land-intro { color: #cbd5e1; max-width: 760px; margin: 2px 0 18px; line-height: 1.5; }
.land-h { margin: 22px 0 8px; font-size: .78rem; font-weight: 700; letter-spacing: .12em; color: #7dd3fc; text-transform: uppercase; }
.pcard { border: 1px solid rgba(125, 211, 252, .25); background: rgba(15, 23, 42, .85); border-radius: 14px; padding: 14px 16px 10px; margin-bottom: 6px; }
.pcard b { font-size: 1.05rem; color: #f8fafc; }
.pcard .meta { color: #94a3b8; font-size: .85rem; margin-top: 3px; }
.pcard .desc { color: #cbd5e1; font-size: .9rem; margin-top: 6px; }
.pill { display: inline-block; font-size: .7rem; font-weight: 700; letter-spacing: .06em; padding: 2px 8px; border-radius: 999px; margin-left: 8px; vertical-align: middle; }
.pill.done { background: rgba(49, 163, 84, .2); color: #86efac; }
.pill.running, .pill.new { background: rgba(250, 204, 21, .18); color: #fde68a; }
.pill.error { background: rgba(215, 48, 31, .22); color: #fca5a5; }
.pcard .warn { color: #fbbf24; font-size: .8rem; margin-top: 6px; }
.pcard .err { color: #fca5a5; font-size: .85rem; margin-top: 6px; }
.howto { color: #94a3b8; font-size: .88rem; line-height: 1.5; }
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
    if proj.get("res_m"):
        meta += f" · {proj['res_m']} m pixels"
    warn = proj.get("warnings") or []
    body = f"""
    <div class="pcard">
      <b>{html.escape(proj.get('name', slug))}</b><span class="pill {html.escape(status)}">{html.escape(status.upper())}</span>
      <div class="meta">{html.escape(meta)}</div>
      {f'<div class="desc">{html.escape(proj["description"])}</div>' if proj.get('description') else ''}
      {f'<div class="warn">⚠ {len(warn)} warning{"s" if len(warn) != 1 else ""}: {html.escape(warn[0][:140])}</div>' if warn else ''}
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
    show("""<div class='howto'>Upload one <b>normal-day</b> image and one or more <b>flood-day</b> images of the same place.
    Works with RCM analysis-ready files from AWS (the <code>rr.tif</code> band) or EODMS GRD orders (the <code>HV.tif</code> file).
    Pick a summer day with no flood as the normal day. Same pass direction for all images works best.</div>""")
    name = st.text_input("Project name", placeholder="e.g. Red River, spring 2025")
    description = st.text_input("Short description (optional)", placeholder="What happened, where")
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
        box = c2.text_input("Area box: west, south, east, north (degrees)", placeholder="-82.40, 52.00, -81.45, 52.45",
                            help="Empty = wherever all images overlap.")
        coast = c1.number_input("Ignore everything east of this UTM x (m)", min_value=0, value=0, step=1000,
                                help="For coasts: sea ice and waves are not river. 0 = off.")

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
    <div class="land-top"><div class="brand">CUT OFF</div><div class="sub">Flood &amp; river-ice lifeline maps from RADARSAT radar</div></div>
    <div class="land-intro">Upload radar images of any place in Canada. Cut Off finds the water, compares each flood day to a
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
