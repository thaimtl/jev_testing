"""Replicates AgentSociety's Hurricane Dorian mobility experiment on Claude only, Jev only, or the hybrid.

Run:    python hurricane.py run --mode hybrid --agents 100 --seed 1
Report: python hurricane.py report runs/hurricane-*.jsonl
Needs ANTHROPIC_API_KEY and TYPESAFE_API_KEY. Protocol follows AgentSociety (Piao et al. 2025, arXiv 2502.08691)
section 7.5 and examples/hurricane_impact/hurricane.py: 9 days, weather message changes after day 3 and day 6.
"""
import argparse
import asyncio
import json
import math
import random
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

import anthropic
from typesafe_sdk import AsyncTypeSafeClient, Choice

from analyze import jsd

JEV_MODEL = "jev-1.13.0"
CLAUDE_MODEL = "claude-sonnet-5-5"
PRICE = {"jev_in": 0.042e-6, "claude_in": 2e-6, "claude_out": 10e-6}
HERE = Path(__file__).parent
PROFILES = json.loads((HERE / "data/columbia_profiles.json").read_text())

# Weather messages copied verbatim from AgentSociety's hurricane example.
NORMAL = "The weather is normal and does not affect travel."
LANDFALL = "Hurricane Dorian has made landfall in other cities, travel is slightly affected, and winds can be felt."
WEATHER = [NORMAL] * 3 + [LANDFALL] * 3 + [NORMAL] * 3
DATES = ["Aug 28", "Aug 29", "Aug 30", "Aug 31", "Sep 1", "Sep 2", "Sep 3", "Sep 4", "Sep 5"]

# Normalized daily visits in Columbia, SC, digitized from AgentSociety Figure 23 (data/agentsociety_fig23.png), +-0.01.
REAL = [0.94, 0.96, 0.90, 0.53, 0.45, 0.47, 0.92, 1.00, 0.91]
AGENTSOCIETY_SIM = [1.00, 0.94, 0.98, 0.34, 0.37, 0.32, 0.95, 0.95, 0.89]

PLANS = {
    "stay_home": "Stays home all day",
    "one_errand": "Makes one short trip (groceries, pharmacy, or gas) and comes back",
    "work_only": "Goes to work and comes back",
    "work_and_more": "Goes to work plus one errand, meal out, or social visit",
    "many_outings": "Makes several trips: work, errands, eating out, or social visits",
}
OUTINGS = {"stay_home": 0, "one_errand": 1, "work_only": 1, "work_and_more": 2, "many_outings": 3}
INSTRUCTIONS = ("Predict how this person would actually spend today, "
                "based on how real people behave, not what official safety advice recommends.")
SYSTEM = (f"You simulate one resident of Columbia, South Carolina in a city mobility simulation.\n{INSTRUCTIONS}\n\n"
          "Options for `plan`:\n" + "\n".join(f"- {k}: {v}" for k, v in PLANS.items())
          + "\n\n`note` is one short third-person sentence on what this person has decided and why.")
SCHEMA = {
    "type": "object",
    "properties": {"note": {"type": "string"}, "plan": {"type": "string", "enum": list(PLANS)}},
    "required": ["note", "plan"],
    "additionalProperties": False,
}


def persona(p):
    return (f"{p['age']}-year-old {p['race']} {'woman' if p['gender'] == 'female' else 'man'} living in Columbia, "
            f"South Carolina, with a job to commute to. Education: {p['education']}. "
            f"Household income: ${p['income']:,} a year. Spending level: {p['consumption']}.")


def describe(a, day):
    lines = [f"Person: {a['persona']}", f"Today: day {day + 1} of the simulation.", f"Weather: {WEATHER[day]}"]
    if a["last"]:
        lines.append(f"Yesterday's plan: {PLANS[a['last']]}.")
    if a["note"]:
        lines.append(f"What they concluded earlier: {a['note']}")
    return "\n".join(lines)


class Spend:
    def __init__(self, cap):
        self.cap = cap
        self.jev_in = self.claude_in = self.claude_out = self.claude_calls = self.jev_calls = 0

    @property
    def claude_usd(self):
        return self.claude_in * PRICE["claude_in"] + self.claude_out * PRICE["claude_out"]

    @property
    def jev_usd(self):
        return self.jev_in * PRICE["jev_in"]


async def ask_jev(client, sem, spend, state):
    async with sem:
        r = await client.system_one(state, {"plan": Choice(instructions=INSTRUCTIONS, criteria=PLANS)})
    spend.jev_in += r.usage.input_tokens
    spend.jev_calls += 1
    a = r.choices["plan"]
    return {"probs": dict(a.probabilities), "conf": a.confidence, "in": r.usage.input_tokens}


async def ask_claude(client, sem, spend, state):
    if spend.claude_usd > spend.cap:
        raise SystemExit(f"Claude spend ${spend.claude_usd:.2f} passed the ${spend.cap} cap")
    async with sem:
        m = await client.messages.create(
            model=CLAUDE_MODEL, max_tokens=2000, system=SYSTEM,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": state}],
        )
    spend.claude_in += m.usage.input_tokens
    spend.claude_out += m.usage.output_tokens
    spend.claude_calls += 1
    usage = {"in": m.usage.input_tokens, "out": m.usage.output_tokens}
    if m.stop_reason != "end_turn":
        return {"failed": m.stop_reason, **usage}
    return {**json.loads(next(b.text for b in m.content if b.type == "text")), **usage}


async def run(mode, n, seed, threshold, cap_frac, cap_abs, max_usd, out):
    profiles = PROFILES if n <= len(PROFILES) else random.Random(0).choices(PROFILES, k=n)
    agents = [{"id": i, "persona": persona(p), "last": None, "note": None} for i, p in enumerate(profiles[:n])]
    rng = random.Random(seed)
    spend = Spend(max_usd)
    jev = AsyncTypeSafeClient(model=JEV_MODEL)
    claude = anthropic.AsyncAnthropic(max_retries=6)
    jsem, csem = asyncio.Semaphore(30), asyncio.Semaphore(16)
    cap = min(math.ceil(cap_frac * n), cap_abs)
    with open(out, "w") as f:
        f.write(json.dumps({"meta": {"mode": mode, "agents": n, "seed": seed, "threshold": threshold, "cap": cap,
                                     "jev": JEV_MODEL, "claude": CLAUDE_MODEL}}) + "\n")
        for day in range(len(WEATHER)):
            t0 = time.time()
            states = [describe(a, day) for a in agents]
            jres = [None] * n
            if mode != "claude":
                jres = await asyncio.gather(*(ask_jev(jev, jsem, spend, s) for s in states))
            if mode == "claude":
                esc = list(range(n))
            elif mode == "hybrid":
                esc = [i for _, i in sorted((r["conf"], i) for i, r in enumerate(jres) if r["conf"] < threshold)[:cap]]
            else:
                esc = []
            cres = dict(zip(esc, await asyncio.gather(*(ask_claude(claude, csem, spend, states[i]) for i in esc))))
            for i, a in enumerate(agents):
                c, j = cres.get(i), jres[i]
                if c and "failed" not in c:
                    plan, note, src = c["plan"], c["note"], "claude"
                elif j:
                    plan, note, src = rng.choices(list(j["probs"]), weights=list(j["probs"].values()))[0], a["note"], "jev"
                else:
                    plan, note, src = a["last"] or "work_only", a["note"], "failed"
                f.write(json.dumps({"day": day, "id": i, "src": src, "plan": plan, "jev": j, "claude": c,
                                    "state": states[i]}) + "\n")
                a["last"], a["note"] = plan, note
            plans = Counter(a["last"] for a in agents)
            print(f"day={day} {time.time() - t0:5.1f}s esc={len(esc):5d} "
                  + " ".join(f"{k}={plans[k] / n:.2f}" for k in PLANS)
                  + f" | claude ${spend.claude_usd:.3f} ({spend.claude_calls}) jev ${spend.jev_usd:.4f} ({spend.jev_calls})",
                  flush=True)
        f.write(json.dumps({"spend": {"claude_usd": spend.claude_usd, "jev_usd": spend.jev_usd,
                                      "claude_calls": spend.claude_calls, "jev_calls": spend.jev_calls,
                                      "claude_in": spend.claude_in, "claude_out": spend.claude_out,
                                      "jev_in": spend.jev_in}}) + "\n")


def load(path):
    rows, meta, spend = [], None, None
    for line in open(path):
        r = json.loads(line)
        meta, spend = r.get("meta", meta), r.get("spend", spend)
        if "day" in r:
            rows.append(r)
    days = [[r for r in rows if r["day"] == d] for d in range(len(WEATHER))]
    trips = [sum(OUTINGS[r["plan"]] for r in rs) for rs in days]
    return {
        "name": Path(path).stem.removeprefix("hurricane-"), "meta": meta, "spend": spend, "n": meta["agents"],
        "rows": rows, "norm": [t / max(trips) for t in trips],
        "active": [sum(OUTINGS[r["plan"]] > 0 for r in rs) / len(rs) for rs in days],
        "dist": [{k: v / len(rs) for k, v in Counter(r["plan"] for r in rs).items()} for rs in days],
        "pooled": {k: v / len(rows) for k, v in Counter(r["plan"] for r in rows).items()},
        "esc": sum(r["src"] == "claude" for r in rows) / len(rows),
    }


def phase_change(curve):
    before = sum(curve[:3]) / 3
    return sum(curve[3:6]) / 3 / before - 1, sum(curve[6:]) / 3 / before - 1


def report(runs):
    curves = [("Real (SafeGraph)", REAL), ("AgentSociety sim (DeepSeek-V3)", AGENTSOCIETY_SIM)] + \
             [(r["name"], r["norm"]) for r in runs]
    print("**Normalized daily visits** (each curve divided by its own max, as in AgentSociety Fig. 23)\n")
    print("| Run | " + " | ".join(DATES) + " | MAE vs real | Drop during | Change after |")
    print("|---|" + "---|" * (len(DATES) + 3))
    for name, c in curves:
        mae = sum(abs(x - y) for x, y in zip(c, REAL)) / len(REAL)
        during, after = phase_change(c)
        print(f"| {name} | " + " | ".join(f"{x:.2f}" for x in c) + f" | {mae:.3f} | {during:+.0%} | {after:+.0%} |")

    print("\n**Activity level** (share of agents leaving home; AgentSociety reports 70-90% before and ~30% at landfall)\n")
    print("| Run | " + " | ".join(DATES) + " |")
    print("|---|" + "---|" * len(DATES))
    for r in runs:
        print(f"| {r['name']} | " + " | ".join(f"{x:.2f}" for x in r["active"]) + " |")

    print("\n**Cost**\n")
    print("| Run | Agent-days | Claude calls | Claude $ | Jev calls | Jev $ | $ per agent-day | Escalated |")
    print("|---|---|---|---|---|---|---|---|")
    for r in runs:
        s, ad = r["spend"], len(r["rows"])
        print(f"| {r['name']} | {ad} | {s['claude_calls']} | {s['claude_usd']:.3f} | {s['jev_calls']} | {s['jev_usd']:.4f} "
              f"| {(s['claude_usd'] + s['jev_usd']) / ad:.6f} | {r['esc']:.1%} |")

    print("\n**Plan distribution divergence** (Jensen-Shannon, bits, same agent count only)\n")
    print("| A | B | Pooled JSD | Mean per-day JSD | Curve MAE |")
    print("|---|---|---|---|---|")
    for a, b in combinations(runs, 2):
        if a["n"] == b["n"]:
            day = sum(jsd(p, q, PLANS) for p, q in zip(a["dist"], b["dist"])) / len(WEATHER)
            mae = sum(abs(x - y) for x, y in zip(a["norm"], b["norm"])) / len(WEATHER)
            print(f"| {a['name']} | {b['name']} | {jsd(a['pooled'], b['pooled'], PLANS):.3f} | {day:.3f} | {mae:.3f} |")

    print("\n**Pooled plan distribution**\n")
    print("| Run | " + " | ".join(PLANS) + " |")
    print("|---|" + "---|" * len(PLANS))
    for r in runs:
        print(f"| {r['name']} | " + " | ".join(f"{r['pooled'].get(k, 0):.2f}" for k in PLANS) + " |")

    for r in runs:
        esc = [x for x in r["rows"] if x["src"] == "claude" and x["jev"]]
        if esc:
            agree = sum(x["claude"]["plan"] == max(x["jev"]["probs"], key=x["jev"]["probs"].get) for x in esc)
            print(f"\n{r['name']}: {len(esc)} escalations, Claude matched Jev's top plan {agree / len(esc):.0%} of the time.")


if __name__ == "__main__":
    if sys.argv[1:2] == ["report"]:
        report([load(p) for p in sys.argv[2:]])
        sys.exit()
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run"])
    p.add_argument("--mode", choices=["claude", "jev", "hybrid"], required=True)
    p.add_argument("--agents", type=int, default=100)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--threshold", type=float, default=0.4)
    p.add_argument("--cap", type=float, default=0.1, help="max fraction of agents escalated per day")
    p.add_argument("--cap-abs", type=int, default=100, help="max agents escalated per day")
    p.add_argument("--tag", default="", help="suffix for the output file name")
    p.add_argument("--max-usd", type=float, default=5.0, help="abort once this run's Claude spend passes this")
    args = p.parse_args()
    (HERE / "runs").mkdir(exist_ok=True)
    out = HERE / f"runs/hurricane-{args.mode}-n{args.agents}-s{args.seed}{args.tag}.jsonl"
    asyncio.run(run(args.mode, args.agents, args.seed, args.threshold, args.cap, args.cap_abs, args.max_usd, out))
