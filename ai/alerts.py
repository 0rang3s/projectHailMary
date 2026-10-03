"""
Cut Off - AI alert (owned by the AI person).

Reads the analysis outputs and writes a short plain-language alert.
The LLM only PHRASES the numbers; it is told to use nothing else.

Usage:
  python alert/generate_alert.py data/mock        # writes data/mock/alert.json
Needs GROQ_API_KEY in the environment (or a .env file) for the LLM version;
without it, a template alert is written so the app still works.
Model comes from LLM_MODEL (default openai/gpt-oss-120b), with
LLM_FALLBACK_MODEL (default openai/gpt-oss-20b) on failure.
"""
import json, os, sys
from pathlib import Path

SYSTEM = (
    "You write flood situation alerts for emergency planners serving remote First Nations "
    "communities. Use ONLY the numbers in the data provided. Never invent places, numbers, "
    "dates or causes. If a lifeline has status no_data, say it could not be assessed from this "
    "radar scene. Max 3 sentences, plain words, no greeting, no markdown. "
    "If river_ice.jam_risk is true, lead with an ice-jam warning naming the towns and the % frozen. "
    "End with the radar dates used."
)


def ice_sentence(ice):
    if not ice:
        return ""
    if ice.get("jam_risk"):
        towns = ", ".join(t.split(" (")[0] for t in ice["jam_towns"])
        near = "; ".join(f"{k.split(' (')[0]} {v['pct_frozen']}%" for k, v in ice["near_towns"].items() if v["pct_frozen"] is not None)
        return (f"ICE-JAM WARNING: river still frozen near {towns} ({near} frozen) while only "
                f"{ice['upstream_pct_frozen']}% frozen upstream, so water arriving from upstream may back up.")
    return f"River ice: {ice['pct_frozen_overall']}% of the river frozen; no ice-jam pattern detected."


def template_alert(stats, lifelines, ice=None):
    worst = sorted([l for l in lifelines if l["dist_flood_m"] is not None], key=lambda l: l["dist_flood_m"])
    parts = [ice_sentence(ice)] if ice and ice.get("jam_risk") else []
    parts.append(f"Radar shows {stats['extra_water_km2']} km² of water beyond normal river extent.")
    if worst:
        w = worst[0]
        parts.append(f"Closest lifeline: {w['name']}, {w['dist_flood_m']} m from flood-day water ({w['status']}).")
    nd = [l["name"] for l in lifelines if l["status"] == "no_data"]
    if nd:
        parts.append("Not assessed (outside scene): " + ", ".join(nd) + ".")
    parts.append(f"Radar dates: normal {stats['normal_date']}, flood {stats['flood_date']}.")
    return " ".join(parts)


def llm_alert(stats, lifelines, ice=None):
    from groq import Groq
    data = json.dumps({"stats": stats, "lifelines": lifelines, "river_ice": ice}, indent=2)
    primary = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")
    fallback = os.environ.get("LLM_FALLBACK_MODEL", "openai/gpt-oss-20b")
    client = Groq(timeout=60.0, max_retries=0)
    last = None
    for model in [primary] if primary == fallback else [primary, fallback]:
        try:
            msg = client.chat.completions.create(
                model=model,
                temperature=0.2,
                max_tokens=300,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Data:\n{data}\n\nWrite the alert."},
                ],
            )
            text = (msg.choices[0].message.content or "").strip()
            if text:
                return text
            last = RuntimeError("empty alert")
        except Exception as exc:
            last = exc
            print(f"{model} failed, trying fallback:", exc)
    raise last


def main(data_dir):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    stats = json.load(open(f"{data_dir}/stats.json"))
    lifelines = json.load(open(f"{data_dir}/lifelines_status.json"))
    ice_p = f"{data_dir}/ice_stats.json"
    ice = json.load(open(ice_p)) if os.path.exists(ice_p) else None
    source = "template"
    text = template_alert(stats, lifelines, ice)
    if os.environ.get("GROQ_API_KEY"):
        try:
            text = llm_alert(stats, lifelines, ice); source = "llm"
        except Exception as e:
            print("LLM failed, using template:", e)
    out = {"text": text, "source": source, "mock": stats.get("mock", False)}
    json.dump(out, open(f"{data_dir}/alert.json", "w"), indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/mock")
