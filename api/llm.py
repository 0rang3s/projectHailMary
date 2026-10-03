"""Groq tool-use for questions, audience alerts, and the situation report."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Iterable

from alert.generate_alert import template_alert
from api.data import (
    DataError,
    compare,
    get_ice,
    get_lifelines,
    get_stats,
    list_dates,
    normalize_date,
    revision,
)

ASK_SYSTEM = (
    "You answer questions about the spring 2025 Albany River ice-jam flood at Fort Albany "
    "and Kashechewan using RADARSAT Constellation Mission radar results. Use ONLY numbers "
    "returned by tools — never invent numbers, places, dates or causes. Cite the radar date "
    "for every number. If a river channel is ice-covered, say open water can't be seen under "
    "ice. If a lifeline location is marked verified=false, say its location is approximate. "
    "If asked anything outside this flood data, say you can only answer about this radar "
    "analysis. Plain language, no citation brackets, max ~120 words. "
    "Call tools before you state a number. Pass dates as the user wrote them "
    "(for example april 30 or 2025-04-30). If a tool returns an error, say so and do not guess."
)

BRIEF_SYSTEM = (
    "You explain the spring 2025 Albany River ice-jam flood at Fort Albany and Kashechewan. "
    "The data message already has every radar number. Use only those numbers. "
    "Never invent numbers, places, dates, or causes. Cite the radar date for every number. "
    "If a channel is ice-covered, say open water can't be seen under the ice. "
    "Open water can be smaller than the normal river for that reason. "
    "Do not say open water is above normal unless its number is larger. "
    "If a location is approximate, say so. Red means within 200 m of water, yellow within 1 km. "
    "April 30 is a different uncalibrated radar product. August 7 is the summer baseline, so extra water is 0. "
    "Plain language, no markdown, under 120 words. "
    "If the question is outside this flood data, say you can only answer about this radar analysis."
)

REPORT_SYSTEM = (
    "You write a markdown situation report on the spring 2025 Albany River ice-jam flood "
    "at Fort Albany and Kashechewan from RADARSAT Constellation Mission results. "
    "Use ONLY numbers returned by tools. Cite the radar date for every number. "
    "Call tools for every flood date before writing. "
    "Sections, in order: What happened, Timeline, Lifelines, River ice, Limitations. "
    "If a channel is ice-covered, say open water can't be seen under ice. "
    "If verified is false, say that location is approximate. "
    "Limitations you may state, without adding measurements of your own: "
    "the April 30 scene is a different uncalibrated product and was shifted about 40 m to line up; "
    "the normal day is the summer after the flood because the free archive starts in spring 2025; "
    "distances are to the nearest detected water at about 20 m resolution; "
    "bright river ice is not counted as open water; "
    "patches of red away from the river can be meltwater, wet snow, or radar noise. "
    "Do not invent other limitations, places, or causes. Plain language."
)

# Albany is the default story. set_project() swaps the place and the Albany-only notes
# when the dashboard opens a different uploaded project.
ALBANY_PLACE = "the spring 2025 Albany River ice-jam flood at Fort Albany and Kashechewan"
_ALBANY_BRIEF_NOTE = "April 30 is a different uncalibrated radar product. August 7 is the summer baseline, so extra water is 0. "
_ALBANY_REPORT_NOTE = ("the April 30 scene is a different uncalibrated product and was shifted about 40 m to line up; "
                       "the normal day is the summer after the flood because the free archive starts in spring 2025; ")
_BASE_PROMPTS = {"ASK_SYSTEM": ASK_SYSTEM, "BRIEF_SYSTEM": BRIEF_SYSTEM, "REPORT_SYSTEM": REPORT_SYSTEM}
PLACE = ALBANY_PLACE


def set_project(place=None, normal_date=None):
    """Point the prompts at a project. place=None means the original Albany story."""
    global ASK_SYSTEM, BRIEF_SYSTEM, REPORT_SYSTEM, PLACE
    PLACE = place or ALBANY_PLACE
    albany = PLACE == ALBANY_PLACE
    out = {}
    for key, text in _BASE_PROMPTS.items():
        text = text.replace(ALBANY_PLACE, PLACE)
        if not albany:
            base = f"{normal_date} is the normal baseline, so extra water is 0. " if normal_date else ""
            text = text.replace(_ALBANY_BRIEF_NOTE, base).replace(_ALBANY_REPORT_NOTE, "")
        out[key] = text
    ASK_SYSTEM, BRIEF_SYSTEM, REPORT_SYSTEM = out["ASK_SYSTEM"], out["BRIEF_SYSTEM"], out["REPORT_SYSTEM"]


AUDIENCE = {
    "coordinator": (
        "Write for an emergency coordinator. Lead with an ice-jam warning when jam_risk is true, "
        "including the percent frozen near each town and upstream. Then give extra water, each "
        "lifeline's status and distance now versus normal, and the radar dates. Plain words."
    ),
    "community": (
        "Write for people in the community. No jargon. At most 3 sentences. Say what the day "
        "means for getting in and out: the airstrips and the causeway. Use only the numbers given."
    ),
    "pilots": (
        "Write for pilots. Airstrips only: name, distance to water on this radar date, and the "
        "normal distance. No other lifelines. Plain words."
    ),
}

SUGGESTED = (
    "how close did water get to the fort albany airstrip?",
    "was there an ice jam on may 7?",
    "what changed between apr 30 and may 19?",
)

_DATE_PARAM = {
    "type": "string",
    "description": "A flood date. Accepts 2025-04-30, Apr 30, april 30, or Apr 30 2025.",
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_dates",
            "description": "List the flood dates and the normal baseline date in this radar analysis.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stats",
            "description": (
                "Flood summary for one date: normal and flood open-water area in km², "
                "extra water beyond the normal river, and how many lifelines are red, yellow, or no_data."
            ),
            "parameters": {
                "type": "object",
                "properties": {"date": _DATE_PARAM},
                "required": ["date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lifelines",
            "description": (
                "Each lifeline (airstrip, causeway, community): distance in metres to flood-day water "
                "and to the normal river, status, and whether the mapped location is verified."
            ),
            "parameters": {
                "type": "object",
                "properties": {"date": _DATE_PARAM},
                "required": ["date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ice",
            "description": (
                "River ice for one date: percent frozen overall, within 5 km of each town, "
                "and upstream, plus jam_risk. Open water under ice is not visible."
            ),
            "parameters": {
                "type": "object",
                "properties": {"date": _DATE_PARAM},
                "required": ["date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare",
            "description": (
                "Difference between two flood dates: extra water, each lifeline's distance, "
                "and percent of river frozen near the towns and upstream."
            ),
            "parameters": {
                "type": "object",
                "properties": {"date_a": _DATE_PARAM, "date_b": _DATE_PARAM},
                "required": ["date_a", "date_b"],
                "additionalProperties": False,
            },
        },
    },
]

_RUNNERS = {
    "list_dates": lambda args: list_dates(),
    "get_stats": lambda args: get_stats(args["date"]),
    "get_lifelines": lambda args: get_lifelines(args["date"]),
    "get_ice": lambda args: get_ice(args["date"]),
    "compare": lambda args: compare(args["date_a"], args["date_b"]),
}

_ask_cache: dict[tuple, dict] = {}
_alert_cache: dict[tuple, dict] = {}
_report_cache: dict[str, str] = {}


def ask(question: str, history: list[dict] | None = None) -> dict:
    if not os.environ.get("GROQ_API_KEY"):
        return {
            "answer": "AI not configured. Add GROQ_API_KEY to the .env file to ask questions about this radar analysis.",
            "tools_used": [],
            "dates_cited": [],
        }
    history = history or []
    key = _suggested_key(question)
    if key in _ask_cache:
        return _ask_cache[key]
    try:
        result = _complete_with_fallback(
            ASK_SYSTEM,
            _history_messages(history) + [{"role": "user", "content": question.strip()}],
            tools=TOOLS,
            max_tokens=700,
        )
    except Exception as exc:
        print("ask failed:", exc)
        return {
            "answer": "The AI service couldn't answer just now. Try again in a moment.",
            "tools_used": [],
            "dates_cited": [],
        }
    if key:
        _ask_cache[key] = result
    return result


def ask_with_data(question: str, data_text: str, history: list[dict] | None = None) -> dict | None:
    """One model call. The dashboard already loaded the radar files, so no tool round trips."""
    if not os.environ.get("GROQ_API_KEY"):
        return None
    model = os.environ.get("LLM_FAST_MODEL") or os.environ.get("LLM_FALLBACK_MODEL") or "openai/gpt-oss-20b"
    messages = _history_messages(history or []) + [{
        "role": "user",
        "content": f"Radar data:\n{data_text.strip()}\n\nQuestion: {question.strip()}",
    }]
    try:
        return _tool_loop(
            model, BRIEF_SYSTEM, messages, tools=None, max_tokens=380,
            reasoning="low", timeout=22.0,
        )
    except Exception as exc:
        print("ask failed:", exc)
        return None


def generate_alert(date: str, audience: str) -> dict:
    from api.data import resolve_flood_date

    iso = resolve_flood_date(date)
    stats = get_stats(iso)
    lifelines = get_lifelines(iso)
    ice = get_ice(iso)
    key = (revision(), iso, audience)
    if key in _alert_cache:
        return _alert_cache[key]

    fallback = {"text": template_for_audience(audience, stats, lifelines, ice), "source": "template"}
    if not os.environ.get("GROQ_API_KEY"):
        _alert_cache[key] = fallback
        return fallback
    payload = json.dumps({"stats": stats, "lifelines": lifelines, "river_ice": ice}, indent=2)
    messages = [{
        "role": "user",
        "content": (
            f"Audience: {audience}.\n{AUDIENCE[audience]}\n\n"
            "Use ONLY the numbers in this data. Never invent places, numbers, dates, or causes. "
            "If a lifeline status is no_data, say it could not be assessed from this radar scene. "
            "If jam_risk is true, the river is ice-covered near those towns and open water can't be seen under the ice. "
            "If verified is false, say the location is approximate. No greeting, no markdown.\n\n"
            f"Data:\n{payload}"
        ),
    }]
    try:
        text = _complete_with_fallback(
            "You phrase radar flood results. You do not calculate new numbers.",
            messages,
            tools=None,
            max_tokens=500,
        )["answer"]
        if not text:
            raise RuntimeError("empty alert")
        result = {"text": text, "source": "llm"}
    except Exception as exc:
        print("alert failed, using template:", exc)
        result = fallback
    _alert_cache[key] = result
    return result


def situation_report() -> str:
    key = revision()
    if key in _report_cache:
        return _report_cache[key]
    if not os.environ.get("GROQ_API_KEY"):
        text = template_report()
        _report_cache[key] = text
        return text
    try:
        text = _complete_with_fallback(
            REPORT_SYSTEM,
            [{"role": "user", "content": "Write the situation report. Read every flood date with tools first."}],
            tools=TOOLS,
            max_tokens=1800,
        )["answer"]
        if len(text) < 80:
            raise RuntimeError("report was empty")
    except Exception as exc:
        print("report failed, using template:", exc)
        text = template_report()
    _report_cache[key] = text
    return text


def template_for_audience(audience: str, stats: dict, lifelines: list, ice) -> str:
    if audience == "community":
        return _community_template(stats, lifelines, ice)
    if audience == "pilots":
        return _pilots_template(stats, lifelines)
    lines = [template_alert(stats, lifelines, ice)]
    for item in sorted(lifelines, key=lambda row: (row.get("dist_flood_m") is None, row.get("dist_flood_m") or 0)):
        if item.get("dist_flood_m") is None or item.get("status") == "no_data":
            lines.append(f"{item['name']}: not assessed from this radar scene.")
            continue
        approx = "" if item.get("verified") else " Location is approximate."
        lines.append(
            f"{item['name']}: {item['status']}, {item['dist_flood_m']} m from flood-day water "
            f"(normally {item['dist_normal_m']} m).{approx}"
        )
    return " ".join(lines)


def template_report() -> str:
    info = list_dates()
    normal = info["normal_date"]
    dates = info["flood_dates"]
    packs = [(iso, get_stats(iso), get_lifelines(iso), get_ice(iso)) for iso in dates]
    first, last = packs[0], packs[-1]
    lines = [
        "# Cut Off situation report",
        "",
        f"Radar view of {PLACE}. "
        "Every figure below is from a RADARSAT Constellation Mission scene.",
        "",
        "## What happened",
        "",
        _what_happened(first, last, normal),
        "",
        "## Timeline",
        "",
    ]
    for iso, stats, _lifelines, ice in packs:
        lines.append(f"### {iso}")
        lines.append("")
        lines.append(
            f"Extra water beyond the normal river: {stats['extra_water_km2']} km². "
            f"Open water on this scene: {stats['flood_water_km2']} km². "
            f"Normal river on {stats['normal_date']}: {stats['normal_water_km2']} km²."
        )
        if ice:
            lines.append("")
            lines.append(_ice_line(iso, ice))
        lines.append("")
    lines.extend(["## Lifelines", ""])
    lines.append(
        "Status is the distance from the place to the nearest water on that radar date. "
        "Red is 200 m or less, yellow is within 1 km. "
        "A location marked approximate was not verified."
    )
    lines.append("")
    for iso, _stats, lifelines, _ice in packs:
        lines.append(f"### {iso}")
        lines.append("")
        for item in lifelines:
            where = "verified location" if item.get("verified") else "approximate location"
            if item.get("dist_flood_m") is None or item.get("status") == "no_data":
                lines.append(f"- {item['name']} ({where}): not assessed from this radar scene.")
            else:
                lines.append(
                    f"- {item['name']} ({where}): {item['dist_flood_m']} m to water "
                    f"(normally {item['dist_normal_m']} m), status {item['status']}."
                )
        lines.append("")
    lines.extend(["## River ice", ""])
    for iso, _stats, _lifelines, ice in packs:
        lines.append(f"- {_ice_line(iso, ice)}" if ice else f"- {iso}: no ice measurement in this scene.")
    lines.extend([
        "",
        "## Limitations",
        "",
        "- The 30 April scene is a different, uncalibrated radar product. It was shifted about 40 m so it lines up with the other scenes.",
        f"- The normal day is {normal}, the summer after the flood. The free archive used here starts in spring 2025, so there is no pre-flood summer scene.",
        "- Where the river is ice-covered, open water under the ice is not in the water map, so flood extent beside a frozen town can look smaller than it was.",
        "- Distances are to the nearest detected water, at about 20 m resolution.",
        "- Some red patches away from the river can be pooled meltwater, wet snow, or radar noise. The water along the river is the part to use.",
        "- The April 30 picture is grainier, so some ice flagged upstream that night can be noise.",
        "",
    ])
    return "\n".join(lines)


def _complete_with_fallback(system: str, messages: list[dict], tools, max_tokens: int) -> dict:
    primary = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")
    fallback = os.environ.get("LLM_FALLBACK_MODEL", "openai/gpt-oss-20b")
    plan = [primary] if primary == fallback else [primary, fallback, primary]
    last = None
    for index, model in enumerate(plan):
        try:
            return _tool_loop(model, system, messages, tools, max_tokens)
        except Exception as exc:
            last = exc
            retryable = _retryable(exc) or _model_missing(exc)
            if index < len(plan) - 1 and retryable:
                wait = _retry_after_seconds(exc) if _is_rate_limit(exc) else 0
                if wait:
                    time.sleep(wait)
                print(f"{model} failed ({type(exc).__name__}); retrying with {plan[index + 1]}")
                continue
            raise
    raise last or RuntimeError("no model configured")


def _tool_loop(model: str, system: str, messages: list[dict], tools, max_tokens: int,
               reasoning: str | None = None, timeout: float = 45.0) -> dict:
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=timeout, max_retries=0)
    thread = [{"role": "system", "content": system}, *messages]
    tools_used: list[dict] = []
    dates: set[str] = set()
    kwargs = {"model": model, "temperature": 0.2, "max_tokens": max_tokens}
    if reasoning and "gpt-oss" in model:
        kwargs["reasoning_effort"] = reasoning
    rounds = 4 if tools else 1
    for round_index in range(rounds):
        request = dict(kwargs)
        if tools and round_index < rounds:
            request["tools"] = tools
            request["tool_choice"] = "auto"
        response = _create(client, thread, request)
        message = response.choices[0].message
        calls = message.tool_calls or []
        if not calls:
            return {
                "answer": (message.content or "").strip(),
                "tools_used": tools_used,
                "dates_cited": sorted(dates),
            }
        thread.append(_assistant_tool_message(message))
        for call in calls:
            name = call.function.name
            args, parsed_ok = _parse_args(call.function.arguments)
            tools_used.append({"name": name, "input": args if parsed_ok else {"arguments": call.function.arguments}})
            result = _run_tool(name, args) if parsed_ok else {"error": "Could not read tool arguments."}
            if not (isinstance(result, dict) and "error" in result):
                dates.update(_dates_from(name, args, result))
            thread.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            })
    response = _create(client, thread, {**kwargs, "tool_choice": "none"})
    return {
        "answer": (response.choices[0].message.content or "").strip(),
        "tools_used": tools_used,
        "dates_cited": sorted(dates),
    }


def _create(client, thread, request):
    try:
        return client.chat.completions.create(messages=thread, **request)
    except TypeError:
        request.pop("reasoning_effort", None)
        return client.chat.completions.create(messages=thread, **request)
    except Exception as exc:
        if "reasoning_effort" in request and "reasoning" in str(exc).lower():
            request.pop("reasoning_effort", None)
            return client.chat.completions.create(messages=thread, **request)
        raise


def _run_tool(name: str, args: dict):
    runner = _RUNNERS.get(name)
    if runner is None:
        return {"error": f"Unknown tool '{name}'."}
    try:
        return runner(args)
    except DataError as exc:
        return {"error": exc.message}
    except KeyError as exc:
        return {"error": f"Missing argument {exc}."}
    except Exception as exc:
        print(f"tool {name} failed:", exc)
        return {"error": "That lookup failed."}


def _dates_from(name: str, args: dict, result) -> Iterable[str]:
    found = []
    if name == "compare" and isinstance(result, dict):
        found.extend([result.get("date_a"), result.get("date_b")])
    elif name == "get_stats" and isinstance(result, dict) and result.get("flood_date"):
        found.append(result["flood_date"])
    elif name in {"get_lifelines", "get_ice"} and args.get("date"):
        try:
            found.append(normalize_date(str(args["date"])))
        except DataError:
            pass
    return [item for item in found if item]


def _assistant_tool_message(message) -> dict:
    entry = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments
                    if isinstance(call.function.arguments, str)
                    else json.dumps(call.function.arguments),
                },
            }
            for call in message.tool_calls
        ],
    }
    if message.content:
        entry["content"] = message.content
    return entry


def _parse_args(raw) -> tuple[dict, bool]:
    if raw is None or raw == "":
        return {}, True
    if isinstance(raw, dict):
        return raw, True
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}, False
    if not isinstance(parsed, dict):
        return {}, False
    return parsed, True


def _history_messages(history: list[dict]) -> list[dict]:
    cleaned = []
    for turn in history[-8:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            cleaned.append({"role": role, "content": content.strip()})
    return cleaned


def _suggested_key(question: str):
    norm = re.sub(r"\s+", " ", question.strip().lower()).rstrip("?").strip()
    if norm in SUGGESTED:
        return (revision(), norm)
    return None


def _is_rate_limit(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    return type(exc).__name__ == "RateLimitError" or status == 429 or "rate_limit" in str(exc).lower()


def _model_missing(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 404 or "model_not_found" in str(exc).lower()


def _retry_after_seconds(exc: Exception) -> float:
    match = re.search(r"try again in ([0-9.]+)s", str(exc))
    if not match:
        return 4
    return min(float(match.group(1)) + 0.5, 20)


def _retryable(exc: Exception) -> bool:
    if type(exc).__name__ in {"RateLimitError", "APITimeoutError", "APIConnectionError"}:
        return True
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()
    if status == 429 or _model_missing(exc):
        return True
    if status in {400, 422} and "tool" in text:
        return True
    return False


def _pretty(iso: str) -> str:
    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    year, month, day = (int(part) for part in iso.split("-"))
    return f"{months[month - 1]} {day}, {year}"


def _community_template(stats: dict, lifelines: list, ice) -> str:
    when = _pretty(stats["flood_date"])
    if ice and ice.get("jam_risk"):
        first = (
            f"On {when}, the river is still frozen beside the communities while it is more open upstream, "
            "so water coming down may have nowhere to go. Open water can't be seen under that ice."
        )
    else:
        frozen = ""
        if ice and ice.get("pct_frozen_overall") is not None:
            frozen = f" About {ice['pct_frozen_overall']}% of the river still looks frozen."
        first = (
            f"On {when}, radar shows {stats['extra_water_km2']} km² of water beyond the normal river.{frozen}"
        )
    access = [
        item for item in lifelines
        if item.get("type") in {"airstrip", "causeway"} and item.get("dist_flood_m") is not None
    ]
    access.sort(key=lambda item: item["dist_flood_m"])
    if access:
        bits = [f"the {item['name']} is {item['dist_flood_m']} m from the water" for item in access]
        second = "For getting in and out, " + ", ".join(bits) + "."
    else:
        second = "The airstrips and causeway could not be assessed from this radar scene."
    third = f"This is the {when} radar scene, compared with the normal river on {_pretty(stats['normal_date'])}."
    return " ".join([first, second, third])


def _pilots_template(stats: dict, lifelines: list) -> str:
    when = _pretty(stats["flood_date"])
    lines = [f"Airstrip distances on the {when} radar scene."]
    found = False
    for item in lifelines:
        if item.get("type") != "airstrip":
            continue
        found = True
        if item.get("dist_flood_m") is None or item.get("status") == "no_data":
            lines.append(f"{item['name']} could not be assessed from this radar scene.")
        else:
            lines.append(
                f"{item['name']}: {item['dist_flood_m']} m from water "
                f"(normally {item['dist_normal_m']} m)."
            )
    if not found:
        lines.append("No airstrip was in this radar scene.")
    return " ".join(lines)


def _what_happened(first, last, normal: str) -> str:
    iso_a, stats_a, _lines_a, ice_a = first
    iso_b, stats_b, _lines_b, ice_b = last
    parts = [
        f"On {iso_a}, extra water beyond the normal river was {stats_a['extra_water_km2']} km² "
        f"(normal river on {normal}: {stats_a['normal_water_km2']} km²)."
    ]
    if ice_a and ice_a.get("jam_risk"):
        parts.append(_ice_line(iso_a, ice_a))
    parts.append(
        f"On {iso_b}, extra water was {stats_b['extra_water_km2']} km²."
    )
    if ice_b:
        parts.append(_ice_line(iso_b, ice_b))
    return " ".join(parts)


def _ice_line(iso: str, ice: dict) -> str:
    if not ice:
        return f"On {iso}, no ice measurement was available."
    bits = []
    for name, value in (ice.get("near_towns") or {}).items():
        pct = value.get("pct_frozen") if isinstance(value, dict) else None
        if pct is not None:
            bits.append(f"{name.split(' (')[0]} {pct}% frozen within 5 km")
    near = ", ".join(bits) if bits else "town readings unavailable"
    upstream = ice.get("upstream_pct_frozen")
    risk = "Ice-jam pattern detected." if ice.get("jam_risk") else "No ice-jam pattern detected."
    covered = " Open water can't be seen under the ice." if ice.get("jam_risk") else ""
    return (
        f"On {iso}, the river was {ice.get('pct_frozen_overall')}% frozen overall "
        f"({near}; upstream {upstream}%). {risk}{covered}"
    )
