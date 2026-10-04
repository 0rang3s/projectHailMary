# RCM FloodScope

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

The free AWS archive only starts in 2025 (we checked year by year, nothing for 2019–2024 anywhere in Canada), so our normal day is the summer after the flood, not before it.

We also grabbed Apr 1, 2025 (same satellite pass as May 7, May 19 and Aug 7). It's an ice-only reference date: the river is frozen everywhere, upstream too, so no jam. We don't compute flood numbers for it because in early April wet snow and frozen bogs look dark on radar and get mistaken for water. Those same dark patches show up on Apr 30, which tells us most of the Apr 30 red patches away from the river aren't flood. There's also a gap in the archive over our area from Apr 8 to May 6, right during breakup, so Apr 30 only exists because of our EODMS order.

## What we found

Extra water compared to normal, along the river, was about 66.5 km² on Apr 30, 20.7 km² on May 7 and 13.0 km² on May 19. We leave out the James Bay shoreline east of the river mouth, because the tidal flats and breaking sea ice there aren't river flooding (with the shore included it was 67.0 km² on May 7 and 20.1 km² on May 19, and both numbers are saved in `stats.json`). Apr 30 is a different, uncalibrated product and a lot of the river was hidden under ice, so don't compare it straight against the May numbers. On the emergency night, water got within roughly 60–200 m of Fort Albany's airstrip and causeway area, when normally it's 370–490 m away. That lines up with the news saying the causeway was less than a foot from overflowing.

The ice result is the big one (see `outputs/ice_timeline.png`). On Apr 1 the river was 97–99% frozen everywhere, upstream too. On Apr 30 the river was 97–99% frozen within 5 km of both towns while only about 11% frozen upstream, which is the classic ice-jam setup. By May 7 it was fully open at Fort Albany and only 30% frozen at Kashechewan, and by May 19 it was basically all open. We tested different cutoffs and smoothing and the near-town number stays at 93–100% no matter what, so it's not a fluke of one setting.

## Run it

```bash
pip install -r requirements.txt
streamlit run frontend/app.py
```

`frontend/app.py` is the dashboard (timeline, map, lifelines, ice, charts, and Ask RCM FloodScope).

Ask RCM FloodScope answers from these radar files on its own. For the fuller assistant that looks up any date, copy `.env.example` to `.env` and add a `GROQ_API_KEY`. Alerts for coordinators, the community, and pilots, plus the situation report, work either way.

Use the slider at the top to move between dates. Blue is where water normally is, red is extra water on that date, and the dots are lifelines coloured by how close the water is (red means 200 m or less, yellow means within 1 km).

## Upload your own radar images

The dashboard now opens on a landing page. On the left are saved projects, on the right you make a new one. Albany is saved project #1, so clicking Open map on it gives the same results as before.

To make a new project:

1. Give it a name.
2. Pick where the radar comes from:
   - **Find radar for a place** (easiest): type a place name and hit Find place, click the map, or type lat/lon. Set the box size. Pick a date range for the normal day (summer, no flood) and one for the flood. Hit Search the archive. It lists every RCM scene over that box from the free AWS archive (2025 onward) and pre-ticks the best ones. Untick or change roles if you want.
   - **Upload my own files**: one normal-day image and one or more flood-day images of the same place. Use the `rr.tif` file for AWS analysis-ready data, or `HV.tif` for an EODMS order. Check the dates in the table and pick the normal day.
3. Optional: add lifelines (name, type, lat, lon), or upload a CSV. Towns should be type `community`, since that's what turns on the ice-jam check.
4. Click Download and process (or Process images). It downloads only your box, then takes about 30 seconds to a few minutes and opens the map.

Everything it figures out by itself (the area, the projection, the water cutoff, how much to shift an image to line it up) gets written to `data/projects/<name>/project.json`. You can edit any of it there and hit Run again. You can also run a project without the app: `python pipeline/run_project.py <name>`.

Things to know:

- The raw radar files and the big `.tif` files aren't in git. So a saved project opens fine from its results, but Run again only works on the computer that has the inputs.
- Images from Nov to Apr get a snow warning. Wet snow looks like water, so extra water can come out too high. The ice check still works.
- With no towns in the lifelines there's no jam check, just how much of the river is frozen.
- The Albany project has its cutoffs set by hand (checked against the news). A fully automatic run on the same files lands close, but not exact: about 41 km² extra water on Apr 30 instead of 66.5, and the same ice-jam result.

## What's in the repo

- `pipeline/water_mask.py` turns a radar picture into a water map
- `pipeline/analyze.py` compares a flood date to normal and checks the lifelines
- `pipeline/ice.py` is the ice-jam detector
- `pipeline/get_ard_baseline.py` downloads RCM pictures from AWS (no ordering needed)
- `pipeline/run_project.py` runs everything for one project (any place, any images)
- `pipeline/archive.py` searches and downloads RCM radar for any box from the free AWS archive
- `ai/` is the assistant: questions, alerts for each audience, the situation report (`ai/alerts.py` writes the plain-language alert)
- `frontend/app.py` is the dashboard, `frontend/projects.py` is the landing page (saved projects + new project)
- `data/projects/` holds each saved project's results (Albany is `albany-2025`)
- `data/real/` holds all the processed results
- `outputs/flood_story.png` is the before/after image for the slides
- `outputs/ice_jam.png` shows the frozen river on Apr 30 vs open on May 7
- `outputs/ice_timeline.png` shows the whole breakup: Apr 1, Apr 30, May 7, May 19

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

The Apr 30 picture is a different product from the others and isn't calibrated, so compare it with some care. It was also sitting about 40 m off from the other pictures, so we nudge it back into place (`--shift-px 2,0`). On Apr 30 a lot of the river near the towns was still iced over, and ice doesn't show up as water, so Kashechewan's flood is probably under-counted that day. The ice detector catches that instead. Some of the upstream ice it flags on Apr 30 could just be noise, since that picture is grainier. Some of the red patches away from the river could be pooled meltwater, wet snow or just radar noise, so the red right along the river is what to focus on. The causeway and town centre locations are approximate for now. Distances count open water, river ice and the river's normal channel, because a frozen river is still the river and the river doesn't disappear during a flood. That's why Kashechewan never shows up as farther than normal anymore. The open-water-only distance is still saved as `dist_open_water_m`. Run `pipeline/ice.py` before `pipeline/analyze.py`, since the distance step uses the ice map.

