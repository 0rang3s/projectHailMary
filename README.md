
Our project for Mission Accepted (Challenge 3). Basically, we use Canada's RADARSAT Constellation Mission (RCM) radar to map the spring 2025 Albany River flood and check how close the water got to Fort Albany and Kashechewan's lifelines: the airstrips, the causeway and the towns themselves.

Why this matters

Fort Albany and Kashechewan are fly-in First Nations on James Bay. Every spring the river ice breaks up, jams, and the water backs up into the communities. In 2025 Kashechewan evacuated in mid-April and Fort Albany declared an emergency on April 29–30. Normal satellite photos are useless here because of cloud, darkness and snow. Radar sees through all of that.

How it works

We take radar pictures of the same area on different days and turn each one into a water map. Water is smooth so it shows up dark on radar, and anything darker than a cutoff counts as water. Then we compare each flood-season day against a normal summer day. Water that's there during the flood but not on the normal day is the flood. Last, we measure how far that water is from each lifeline.

The data
Apr 30, 2025: the night Fort Albany declared the emergency (EODMS order, 12.5 m)
May 7, 2025: one week later (RCM analysis-ready data from AWS, 20 m)
May 19, 2025: water draining (same source)
Aug 7, 2025: our normal day (same source)

The free AWS archive only starts in spring 2025, so our normal day is the summer after the flood, not before it.

What we found

Extra water compared to normal was about 68.6 km² on Apr 30, 67.0 km² on May 7 and 20.1 km² on May 19. On the emergency night, water got within roughly 100–160 m of Fort Albany's airstrip and causeway area, when normally it's 370–490 m away. That lines up with the news saying the causeway was less than a foot from overflowing.

pip install -r requirements.txt
streamlit run app/app.py

Use the slider at the top to move between dates. Blue is where water normally is, red is extra water on that date, and the dots are lifelines coloured by how close the water is (red means 200 m or less, yellow means within 1 km).

What's in the repo
pipeline/water_mask.py turns a radar picture into a water map
pipeline/analyze.py compares a flood date to normal and checks the lifelines
pipeline/get_ard_baseline.py downloads RCM pictures from AWS (no ordering needed)
alert/generate_alert.py writes a short plain-language alert from the numbers
app/app.py is the web app
data/real/ holds all the processed results
outputs/flood_story.png is the before/after image for the slides

The raw radar files aren't in the repo because they're too big. Run get_ard_baseline.py to grab them again.

Rerun after changing lifeline locations
bash
for d in 2025-04-30 2025-05-07 2025-05-19; do
  python pipeline/analyze.py data/real/normal_2025-08-07_water.geojson data/real/flood_${d}_water.geojson \
         data/real/flood_${d}_mask.tif data/lifelines.json data/real/$d
  python alert/generate_alert.py data/real/$d
done
Things to keep in mind

The Apr 30 picture is a different product from the others and isn't calibrated, so compare it with some care. On Apr 30 a lot of the river near the towns was still iced over, and ice doesn't show up as water, so Kashechewan is probably under-counted that day. Some of the red patches away from the river could be pooled meltwater, wet snow or just radar noise, so the red right along the river is what to focus on. The causeway and town centre locations are approximate for now. Distances are to the nearest water we detected at 20 m resolution.