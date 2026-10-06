"""Tsunami-rumor agent society on Claude only, Jev only, or the confidence-gated hybrid.

Usage: python sim.py --mode hybrid --agents 100 --seed 1
Needs ANTHROPIC_API_KEY and TYPESAFE_API_KEY. Writes runs/<mode>-n<agents>-s<seed>.jsonl.
"""
import argparse
import asyncio
import json
import math
import random
import time
from pathlib import Path

import anthropic
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul

JEV_MODEL = "jev-1.13.0"
CLAUDE_MODEL = "claude-opus-5-5"
PRICE = {"jev_in": 0.042e-6, "claude_in": 4e-6, "claude_out": 20e-6}
TICKS = 8
OFFICIAL_TICK = 3
RUMOR = '"TSUNAMI COMING IN 20 MIN, 30 FT WAVE, GET TO HIGH GROUND NOW"'
OFFICIAL = '"No tsunami threat to San Francisco. This earthquake was on land." (National Tsunami Warning Center)'

ACTIONS = {
    "share_warning": "Repost or forward the tsunami warning to friends and family",
    "debunk": "Tell friends the tsunami warning is false",
    "check_official": "Look for official alerts or news before doing anything else",
    "evacuate": "Leave now for higher ground",
    "stay_put": "Stay where they are and keep dealing with the earthquake",
}
INSTRUCTIONS = (
    "Predict the main thing this person would actually do in the next 10 minutes, "
    "based on how real people behave in disasters, not what official safety advice recommends."
)
BELIEF_Q = "Does this person currently believe a tsunami is about to hit San Francisco?"

SYSTEM = (
    "You simulate one resident in a disaster simulation of San Francisco.\n"
    f"{INSTRUCTIONS}\n\nOptions for `action`:\n"
    + "\n".join(f"- {k}: {v}" for k, v in ACTIONS.items())
    + f"\n\n`believes_tsunami` answers: {BELIEF_Q}\n"
    "`note` is one short third-person sentence on what this person now believes or has decided."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "note": {"type": "string"},
        "believes_tsunami": {"type": "boolean"},
        "action": {"type": "string", "enum": list(ACTIONS)},
    },
    "required": ["note", "believes_tsunami", "action"],
    "additionalProperties": False,
}

NAMES = ["Maria", "Tom", "Linda", "Raj", "Wei", "Aisha", "Carlos", "Grace", "Daniel", "Mei", "Jamal", "Sofia",
         "Kenji", "Olivia", "Luis", "Fatima", "Ethan", "Priya", "Marcus", "Hannah", "Diego", "Nora", "Sam", "Ana"]
COASTAL = ["the Marina", "Ocean Beach in the Outer Sunset", "the Embarcadero", "the Outer Richmond", "Crissy Field"]
INLAND = ["the Mission", "Noe Valley", "Twin Peaks", "Bernal Heights", "the Castro", "Nob Hill"]
JOBS = ["nurse", "software engineer", "student", "retired teacher", "barista", "contractor", "lawyer",
        "rideshare driver", "shop owner", "line cook", "accountant", "artist"]
HOUSEHOLD = ["lives alone", "lives with young kids", "lives with an elderly parent", "lives with roommates",
             "lives with a partner"]
SOCIAL = ["rarely uses social media", "checks social media a few times a day", "is on social media constantly"]


def make_agent(i, rng):
    coastal = rng.random() < 0.4
    job = rng.choice(JOBS)
    age = rng.randint(18, 26) if job == "student" else rng.randint(62, 85) if job.startswith("retired") else rng.randint(22, 70)
    a = {
        "id": i, "name": rng.choice(NAMES), "age": age, "job": job,
        "household": rng.choice(HOUSEHOLD), "coastal": coastal,
        "place": rng.choice(COASTAL if coastal else INLAND), "trust": rng.choice(["low", "medium", "high"]),
        "social": rng.choice(SOCIAL), "temper": rng.choice(["anxious", "calm", "skeptical", "impulsive"]),
    }
    where = "near the water, low-lying" if coastal else "inland, on higher ground"
    a["persona"] = (f"{a['name']}, {a['age']}, {a['job']}, {a['household']}, currently in {a['place']} ({where}). "
                    f"Trust in officials: {a['trust']}. {a['name']} {a['social']} and is {a['temper']} by temperament.")
    a.update(saw_rumor=False, knows_official=False, checked_early=False, last=None, note=None)
    return a


def small_world(n, k, p, rng):
    """Watts-Strogatz ring with k neighbors and rewiring probability p."""
    nbrs = [set() for _ in range(n)]
    for i in range(n):
        for j in range(1, k // 2 + 1):
            b = (i + j) % n
            if rng.random() < p:
                b = rng.randrange(n)
                while b == i or b in nbrs[i]:
                    b = rng.randrange(n)
            nbrs[i].add(b)
            nbrs[b].add(i)
    return [sorted(s) for s in nbrs]


def describe(a, t, friends_last):
    count = lambda act: sum(x == act for x in friends_last)
    shares, debunks, evacs = count("share_warning"), count("debunk"), count("evacuate")
    lines = [f"Person: {a['persona']}",
             f"Time: {10 * t + 5} minutes after a magnitude 6.9 earthquake struck San Francisco on land. "
             "The shaking has stopped. Some power and cell service is out."]
    if shares:
        lines.append(f"In the last 10 minutes, {shares} of their {len(friends_last)} close contacts shared this post: {RUMOR}")
    elif a["saw_rumor"]:
        lines.append(f"Earlier they saw a viral post: {RUMOR}")
    if debunks:
        lines.append(f"{debunks} close contact(s) said the tsunami post is fake"
                     + (" and passed on the official statement." if t - 1 >= OFFICIAL_TICK else "."))
    if evacs:
        lines.append(f"{evacs} close contact(s) are heading to higher ground.")
    if a["knows_official"]:
        lines.append(f"They have seen the official statement: {OFFICIAL}")
    elif a["checked_early"]:
        lines.append("When they last checked official sources, there was no tsunami information yet.")
    if not (shares or debunks or a["saw_rumor"] or a["knows_official"]):
        lines.append("They have not seen anything about a tsunami.")
    if a["last"]:
        lines.append(f"What they did in the last 10 minutes: {ACTIONS[a['last']]}.")
    if a["note"]:
        lines.append(f"What they concluded earlier: {a['note']}")
    return "\n".join(lines), shares > 0, debunks > 0 and t - 1 >= OFFICIAL_TICK


class Spend:
    def __init__(self, cap):
        self.cap, self.jev_in, self.claude_in, self.claude_out, self.claude_calls, self.jev_calls = cap, 0, 0, 0, 0, 0

    @property
    def claude_usd(self):
        return self.claude_in * PRICE["claude_in"] + self.claude_out * PRICE["claude_out"]

    @property
    def jev_usd(self):
        return self.jev_in * PRICE["jev_in"]


async def ask_jev(client, sem, spend, state):
    async with sem:
        r = await client.system_one(state, {
            "action": Choice(instructions=INSTRUCTIONS, criteria=ACTIONS),
            "believes": Noul(instructions=BELIEF_Q),
        })
    spend.jev_in += r.usage.input_tokens
    spend.jev_calls += 1
    a = r.choices["action"]
    return {"probs": dict(a.probabilities), "conf": a.confidence, "p_believe": r.nouls["believes"].noul,
            "in": r.usage.input_tokens}


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
    world = random.Random(0)
    agents = [make_agent(i, world) for i in range(n)]
    nbrs = small_world(n, 6, 0.1, world)
    seeds = set(world.sample(range(n), max(1, n // 20)))
    for i in seeds:
        agents[i].update(last="share_warning", saw_rumor=True)
    rng = random.Random(seed)
    spend = Spend(max_usd)
    jev = AsyncTypeSafeClient(model=JEV_MODEL)
    claude = anthropic.AsyncAnthropic(max_retries=6)
    jsem, csem = asyncio.Semaphore(30), asyncio.Semaphore(16)
    cap = min(math.ceil(cap_frac * n), cap_abs)
    with open(out, "w") as f:
        f.write(json.dumps({"meta": {"mode": mode, "agents": n, "seed": seed, "threshold": threshold,
                                     "cap_frac": cap_frac, "cap_abs": cap_abs, "jev": JEV_MODEL, "claude": CLAUDE_MODEL,
                                     "seeds": sorted(seeds)}}) + "\n")
        for t in range(TICKS):
            t0 = time.time()
            last = [a["last"] for a in agents]
            described = [describe(a, t, [last[j] for j in nbrs[a["id"]]]) for a in agents]
            states = [d[0] for d in described]
            jres = [None] * n
            if mode != "claude":
                jres = await asyncio.gather(*(ask_jev(jev, jsem, spend, s) for s in states))
            if mode == "claude":
                esc = list(range(n))
            elif mode == "hybrid":
                low = sorted((r["conf"], i) for i, r in enumerate(jres) if r["conf"] < threshold)
                esc = [i for _, i in low[:cap]]
            else:
                esc = []
            cres = dict(zip(esc, await asyncio.gather(*(ask_claude(claude, csem, spend, states[i]) for i in esc))))
            for i, a in enumerate(agents):
                c, j = cres.get(i), jres[i]
                if c and "failed" not in c:
                    act, believes, note, src = c["action"], c["believes_tsunami"], c["note"], "claude"
                elif j:
                    act = rng.choices(list(j["probs"]), weights=list(j["probs"].values()))[0]
                    believes, note, src = rng.random() < j["p_believe"], a["note"], "jev"
                else:
                    act, believes, note, src = a["last"] or "stay_put", None, a["note"], "failed"
                saw, official_via_friend = described[i][1], described[i][2]
                f.write(json.dumps({"t": t, "id": i, "src": src, "action": act, "believes": believes,
                                    "note": note if src == "claude" else None, "jev": j, "claude": c,
                                    "state": states[i]}) + "\n")
                a["saw_rumor"] |= saw
                a["knows_official"] |= official_via_friend or (act == "check_official" and t >= OFFICIAL_TICK)
                a["checked_early"] |= act == "check_official" and t < OFFICIAL_TICK
                a["last"], a["note"] = act, note
            acts = [a["last"] for a in agents]
            print(f"t={t} {time.time() - t0:5.1f}s esc={len(esc):5d} "
                  + " ".join(f"{k}={acts.count(k) / n:.2f}" for k in ACTIONS)
                  + f" | claude ${spend.claude_usd:.3f} ({spend.claude_calls}) jev ${spend.jev_usd:.4f} ({spend.jev_calls})",
                  flush=True)
        f.write(json.dumps({"spend": {"claude_usd": spend.claude_usd, "jev_usd": spend.jev_usd,
                                      "claude_calls": spend.claude_calls, "jev_calls": spend.jev_calls,
                                      "claude_in": spend.claude_in, "claude_out": spend.claude_out,
                                      "jev_in": spend.jev_in}}) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["claude", "jev", "hybrid"], required=True)
    p.add_argument("--agents", type=int, default=100)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--threshold", type=float, default=0.4)
    p.add_argument("--cap", type=float, default=0.1, help="max fraction of agents escalated per tick")
    p.add_argument("--cap-abs", type=int, default=100, help="max agents escalated per tick")
    p.add_argument("--max-usd", type=float, default=8.0, help="abort once this run's Claude spend passes this")
    p.add_argument("--ticks", type=int, default=TICKS)
    p.add_argument("--out")
    args = p.parse_args()
    TICKS = args.ticks
    Path("runs").mkdir(exist_ok=True)
    out = args.out or f"runs/{args.mode}-n{args.agents}-s{args.seed}.jsonl"
    asyncio.run(run(args.mode, args.agents, args.seed, args.threshold, args.cap, args.cap_abs, args.max_usd, out))
