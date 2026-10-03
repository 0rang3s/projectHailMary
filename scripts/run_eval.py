"""Run the demo questions against /api/infer and print a pass/fail line for each.

Usage (API must be running):
    python3 scripts/run_eval.py
    python3 scripts/run_eval.py --delay 25 --show

--delay  seconds to wait between questions (keeps you under the Groq per-minute limit)
--show   also print each summary and claim
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

CASES = [
    {"q": "Which lifeline is in the most trouble?", "expect": "answer",
     "mention": ["fort albany"]},
    {"q": "What changed between Apr 30 and May 19?", "expect": "answer",
     "mention": ["kashechewan"], "avoid": ["in volume"]},
    {"q": "Is the Fort Albany airstrip getting better or worse?", "expect": "answer",
     "mention": ["airstrip", "yellow"], "avoid": ["threat has lessened"]},
    {"q": "Which places got worse between May 7 and May 19?", "expect": "answer",
     "mention": ["kashechewan"]},
    {"q": "Is Kashechewan safe to get in and out of right now?", "expect": "answer",
     "mention": ["airstrip"]},
    {"q": "Why does the Kashechewan community matter in a flood?", "expect": "answer",
     "mention": ["dike"]},
    {"q": "Will the Fort Albany airstrip flood next year?", "expect": "refuse"},
    {"q": "Did climate change cause this flood?", "expect": "refuse"},
    {"q": "What's the best pizza in Toronto?", "expect": "refuse"},
]


def ask(url, question):
    body = json.dumps({"question": question, "history": []}).encode()
    req = urllib.request.Request(
        f"{url}/api/infer", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.load(res)


SERVICE_ERROR = "couldn't answer just now"


def ask_with_retry(url, question, retries=2):
    data = {}
    for attempt in range(retries + 1):
        data = ask(url, question)
        if SERVICE_ERROR not in data.get("summary", ""):
            return data
        if attempt < retries:
            print("        rate limited, waiting 65s before retrying...")
            time.sleep(65)
    return data


def check(case, data):
    problems = []
    claims = data.get("claims") or []
    text = " ".join([data.get("summary", "")] + [c.get("claim", "") for c in claims]).lower()
    if "couldn't answer just now" in text:
        problems.append("service error (rate limit?)")
    if case["expect"] == "refuse":
        if claims:
            problems.append(f"should refuse but returned {len(claims)} claim(s)")
    else:
        if not claims:
            problems.append("no claims returned")
        if data.get("dropped_claims"):
            problems.append(f"{data['dropped_claims']} claim(s) dropped")
        if data.get("unverified_numbers"):
            problems.append(f"unverified numbers: {data['unverified_numbers']}")
        for word in case.get("mention", []):
            if word not in text:
                problems.append(f"missing '{word}'")
    for word in case.get("avoid", []):
        if word in text:
            problems.append(f"contains '{word}'")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--delay", type=float, default=30)
    parser.add_argument("--only", default="", help="comma-separated question numbers, e.g. 1,3,7")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()

    picked = {int(x) for x in args.only.split(",") if x.strip()}
    cases = [c for n, c in enumerate(CASES, 1) if not picked or n in picked]
    failed = 0
    for i, case in enumerate(cases):
        start = time.time()
        try:
            data = ask_with_retry(args.url, case["q"])
            problems = check(case, data)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            data, problems = {}, [f"request failed: {exc}"]
        took = time.time() - start
        status = "PASS" if not problems else "FAIL"
        failed += bool(problems)
        print(f"[{status}] {took:4.1f}s  {case['q']}")
        for p in problems:
            print(f"        - {p}")
        if args.show and data:
            print(f"        summary: {data.get('summary', '')}")
            for c in data.get("claims") or []:
                print(f"        claim ({c.get('confidence')}): {c.get('claim')}")
        if i < len(cases) - 1 and took > 2:     # fast answers came from the cache
            time.sleep(args.delay)

    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()