"""
Cut Off - AI alert (owned by the AI person).

Reads the analysis outputs and writes a short plain-language alert.
The LLM only PHRASES the numbers; it is told to use nothing else.

Usage:
  python alert/generate_alert.py data/mock        # writes data/mock/alert.json
Needs ANTHROPIC_API_KEY in the environment for the LLM version;
without it, a template alert is written so the app still works.
"""
import json, os, sys

SYSTEM = (
    "You write flood situation alerts for emergency planners serving remote First Nations "
    "communities. Use ONLY the numbers in the data provided. Never invent places, numbers, "
    "dates or causes. If a lifeline has status no_data, say it could not be assessed from this "
    "radar scene. Max 3 sentences, plain words, no greeting, no markdown. "
    "End with the radar dates used."
)


def template_alert(stats, lifelines):
    worst = sorted([l for l in lifelines if l["dist_flood_m"] is not None], key=lambda l: l["dist_flood_m"])
    parts = [f"Radar shows {stats['extra_water_km2']} km² of water beyond normal river extent."]
    if worst:
        w = worst[0]
        parts.append(f"Closest lifeline: {w['name']}, {w['dist_flood_m']} m from flood-day water ({w['status']}).")
    nd = [l["name"] for l in lifelines if l["status"] == "no_data"]
    if nd:
        parts.append("Not assessed (outside scene): " + ", ".join(nd) + ".")
    parts.append(f"Radar dates: normal {stats['normal_date']}, flood {stats['flood_date']}.")
    return " ".join(parts)


def llm_alert(stats, lifelines):
    import anthropic
    client = anthropic.Anthropic()
    data = json.dumps({"stats": stats, "lifelines": lifelines}, indent=2)
    msg = client.messages.create(
        model=os.environ.get("ALERT_MODEL", "claude-sonnet-5-5"),
        max_tokens=300,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Data:\n{data}\n\nWrite the alert."}],
    )
    return msg.content[0].text.strip()


def main(data_dir):
    stats = json.load(open(f"{data_dir}/stats.json"))
    lifelines = json.load(open(f"{data_dir}/lifelines_status.json"))
    source = "template"
    text = template_alert(stats, lifelines)
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            text = llm_alert(stats, lifelines); source = "llm"
        except Exception as e:
            print("LLM failed, using template:", e)
    out = {"text": text, "source": source, "mock": stats.get("mock", False)}
    json.dump(out, open(f"{data_dir}/alert.json", "w"), indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/mock")
