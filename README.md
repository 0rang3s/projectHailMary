# Cut Off

Our project for Mission Accepted (Challenge 3). Basically, we use Canada's RADARSAT Constellation Mission (RCM) radar to map the spring 2025 Albany River flood and check how close the water got to Fort Albany and Kashechewan's lifelines: the airstrips, the causeway and the towns themselves.

## Why this matters

Fort Albany and Kashechewan are fly-in First Nations on James Bay. Every spring the river ice breaks up, jams, and the water backs up into the communities. In 2025 Kashechewan evacuated in mid-April and Fort Albany declared an emergency on April 29–30. Normal satellite photos are useless here because of cloud, darkness and snow. Radar sees through all of that.

## How it works

We take radar pictures of the same area on different days and turn each one into a water map. Water is smooth so it shows up dark on radar, and anything darker than a cutoff counts as water. Then we compare each flood-season day against a normal summer day. Water that's there during the flood but not on the normal day is the flood. Then we measure how far that water is from each lifeline.

We also built an ice-jam detector. Ice jams are what actually cause these floods. Open water looks dark on radar and ice looks bright, so inside the river's normal channels anything that isn't water on a flood date is most likely ice. If the river is mostly frozen right by the towns while it's mostly open upstream, that's the warning sign, because the water coming down has nowhere to go.

## The data

- Apr 30, 2025: the night Fort Albany declared the emergency (EODMS order, 12.5 m)
- May 7, 2025: one week later (RCM analysis-ready data from AWS, 20 m)
- May 19, 2025: water draining (same source)
- Aug 7, 2025: our normal day (same source)

The free AWS archive only starts in spring 2025, so our normal day is the summer after the flood, not before it.

## What we found

Extra water compared to normal was about 66.6 km² on Apr 30, 67.0 km² on May 7 and 20.1 km² on May 19. On the emergency night, water got within roughly 60–200 m of Fort Albany's airstrip and causeway area, when normally it's 370–490 m away. That lines up with the news saying the causeway was less than a foot from overflowing.

The ice result is the big one. On Apr 30 the river was 97–99% frozen within 5 km of both towns while only about 11% frozen upstream, which is the classic ice-jam setup. By May 7 it was fully open at Fort Albany and only 30% frozen at Kashechewan, and by May 19 it was basically all open. We tested different cutoffs and smoothing and the near-town number stays at 93–100% no matter what, so it's not a fluke of one setting.

## Run it

```bash
pip install -r requirements.txt
streamlit run frontend/app.py
```

`frontend/app.py` is the dashboard (timeline, map, lifelines, ice, charts, and Ask Cut Off). `streamlit run app/app.py` opens the earlier view of the same files.

Ask Cut Off answers from these radar files on its own. For the fuller assistant that looks up any date, copy `.env.example` to `.env` and add a `GROQ_API_KEY`. Alerts for coordinators, the community, and pilots, plus the situation report, work either way.

Use the slider at the top to move between dates. Blue is where water normally is, red is extra water on that date, and the dots are lifelines coloured by how close the water is (red means 200 m or less, yellow means within 1 km).

The Streamlit app stays available as a backup demo. The main interface is the web app below.

## Run the web app

Backend, from the repo root:

```bash
pip install -r requirements.txt && cp .env.example .env
```

Add your Groq key to `.env`, then:

```bash
uvicorn api.main:app --reload
```

Frontend:

```bash
cd web && npm install && npm run dev
```

Open http://localhost:5173. The page talks to the API at http://localhost:8000 through the Vite proxy. API docs are at http://localhost:8000/docs.

## What's in the repo

- `pipeline/water_mask.py` turns a radar picture into a water map
- `pipeline/analyze.py` compares a flood date to normal and checks the lifelines
- `pipeline/ice.py` is the ice-jam detector
- `pipeline/get_ard_baseline.py` downloads RCM pictures from AWS (no ordering needed)
- `alert/generate_alert.py` writes a short plain-language alert from the numbers
- `api/` is the FastAPI backend (dates, map layers, questions, alerts, situation report)
- `web/` is the map and chat frontend
- `app/app.py` is the Streamlit backup demo
- `data/real/` holds all the processed results
- `outputs/flood_story.png` is the before/after image for the slides
- `outputs/ice_jam.png` shows the frozen river on Apr 30 vs open on May 7

The raw radar files aren't in the repo because they're too big. Run `get_ard_baseline.py` to grab them again.

## Rerun after changing lifeline locations

```bash
for d in 2025-04-30 2025-05-07 2025-05-19; do
  python pipeline/analyze.py data/real/normal_2025-08-07_water.geojson data/real/flood_${d}_water.geojson \
         data/real/flood_${d}_mask.tif data/lifelines.json data/real/$d
done
python pipeline/ice.py data/real/normal_2025-08-07_mask.tif data/real/flood_2025-04-30_mask.tif data/lifelines.json data/real/2025-04-30 \
       --db data/real/flood_2025-04-30_db.tif --ice-threshold 49.5 --median 7
for d in 2025-05-07 2025-05-19; do
  python pipeline/ice.py data/real/normal_2025-08-07_mask.tif data/real/flood_${d}_mask.tif data/lifelines.json data/real/$d
done
for d in 2025-04-30 2025-05-07 2025-05-19; do python alert/generate_alert.py data/real/$d; done
```

The `_db.tif` files aren't in the repo, so to rerun the Apr 30 ice step you need to regenerate them first with `pipeline/water_mask.py` (Apr 30 uses `--band HV --threshold 47.5 --shift-px 2,0`).

## Things to keep in mind

The Apr 30 picture is a different product from the others and isn't calibrated, so compare it with some care. It was also sitting about 40 m off from the other pictures, so we nudge it back into place (`--shift-px 2,0`). On Apr 30 a lot of the river near the towns was still iced over, and ice doesn't show up as water, so Kashechewan's flood is probably under-counted that day. The ice detector catches that instead. Some of the upstream ice it flags on Apr 30 could just be noise, since that picture is grainier. Some of the red patches away from the river could be pooled meltwater, wet snow or just radar noise, so the red right along the river is what to focus on. The causeway and town centre locations are approximate for now. Distances are to the nearest water we detected at 20 m resolution.

