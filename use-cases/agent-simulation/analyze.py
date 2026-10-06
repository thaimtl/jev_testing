"""Compare runs: action distributions (Jensen-Shannon divergence), belief curves, cost.

Usage: python analyze.py runs/claude-n100-s1.jsonl runs/hybrid-n100-s1.jsonl ...
"""
import json
import math
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

from sim import ACTIONS, TICKS


def jsd(p, q, keys=ACTIONS):
    """Jensen-Shannon divergence in bits, 0 = identical, 1 = disjoint."""
    m = {k: (p.get(k, 0) + q.get(k, 0)) / 2 for k in keys}
    kl = lambda a: sum(a[k] * math.log2(a[k] / m[k]) for k in keys if a.get(k, 0) > 0)
    return (kl(p) + kl(q)) / 2


def load(path):
    rows, meta, spend = [], None, None
    for line in open(path):
        r = json.loads(line)
        meta = r.get("meta", meta)
        spend = r.get("spend", spend)
        if "t" in r:
            rows.append(r)
    n = meta["agents"]
    dist = lambda rs: {k: v / len(rs) for k, v in Counter(r["action"] for r in rs).items()}
    by_t = [[r for r in rows if r["t"] == t] for t in range(TICKS)]
    return {
        "name": Path(path).stem, "meta": meta, "spend": spend, "n": n,
        "pooled": dist(rows), "per_tick": [dist(rs) for rs in by_t],
        "believe": [sum(bool(r["believes"]) for r in rs) / n for rs in by_t],
        "esc": [sum(r["src"] == "claude" for r in rs) / n for rs in by_t],
        "reach": [sum("TSUNAMI COMING" in r["state"] for r in rs) / n for rs in by_t],
        "rows": rows,
    }


def report(runs):
    print("| Run | Claude calls | Claude $ | Jev calls | Jev $ | $ per agent-tick | Escalated |")
    print("|---|---|---|---|---|---|---|")
    for r in runs:
        s, ticks = r["spend"], r["n"] * TICKS
        print(f"| {r['name']} | {s['claude_calls']} | {s['claude_usd']:.3f} | {s['jev_calls']} | {s['jev_usd']:.4f} "
              f"| {(s['claude_usd'] + s['jev_usd']) / ticks:.6f} | {sum(r['esc']) / TICKS:.1%} |")

    print("\n**Pooled action distribution (all ticks)**\n")
    print("| Run | " + " | ".join(ACTIONS) + " |")
    print("|---|" + "---|" * len(ACTIONS))
    for r in runs:
        print(f"| {r['name']} | " + " | ".join(f"{r['pooled'].get(k, 0):.2f}" for k in ACTIONS) + " |")

    print("\n**Share believing the rumor, by tick** (official denial lands at t=3)\n")
    print("| Run | " + " | ".join(f"t{t}" for t in range(TICKS)) + " |")
    print("|---|" + "---|" * TICKS)
    for r in runs:
        print(f"| {r['name']} | " + " | ".join(f"{b:.2f}" for b in r["believe"]) + " |")

    print("\n**Rumor reach** (share of agents who have seen the rumor, by tick)\n")
    print("| Run | " + " | ".join(f"t{t}" for t in range(TICKS)) + " |")
    print("|---|" + "---|" * TICKS)
    for r in runs:
        print(f"| {r['name']} | " + " | ".join(f"{x:.2f}" for x in r["reach"]) + " |")

    print("\n**Share sharing the rumor, by tick**\n")
    print("| Run | " + " | ".join(f"t{t}" for t in range(TICKS)) + " |")
    print("|---|" + "---|" * TICKS)
    for r in runs:
        print(f"| {r['name']} | " + " | ".join(f"{d.get('share_warning', 0):.2f}" for d in r["per_tick"]) + " |")

    print("\n**Pairwise divergence** (pooled JSD, mean per-tick JSD, mean absolute gap in belief share)\n")
    print("| A | B | Pooled JSD | Per-tick JSD | Belief gap |")
    print("|---|---|---|---|---|")
    for a, b in combinations(runs, 2):
        if a["n"] != b["n"]:
            continue
        tick = sum(jsd(p, q) for p, q in zip(a["per_tick"], b["per_tick"])) / TICKS
        gap = sum(abs(x - y) for x, y in zip(a["believe"], b["believe"])) / TICKS
        print(f"| {a['name']} | {b['name']} | {jsd(a['pooled'], b['pooled']):.3f} | {tick:.3f} | {gap:.3f} |")


def escalation_profile(runs):
    """Which persona traits are over-represented among escalated agent-ticks."""
    for r in runs:
        if r["meta"]["mode"] != "hybrid":
            continue
        esc = [x for x in r["rows"] if x["src"] == "claude"]
        agree = sum(x["claude"]["action"] == max(x["jev"]["probs"], key=x["jev"]["probs"].get) for x in esc)
        print(f"\n**{r['name']}**: {len(esc)} escalations, Claude agreed with Jev's top choice {agree / max(len(esc), 1):.0%} of the time\n")
        traits = Counter()
        base = Counter()
        for x in r["rows"]:
            for line in x["state"].split("\n")[:1]:
                for tr in ["low", "medium", "high"]:
                    if f"Trust in officials: {tr}" in line:
                        base[f"trust {tr}"] += 1
                        traits[f"trust {tr}"] += x["src"] == "claude"
                for tr in ["anxious", "calm", "skeptical", "impulsive"]:
                    if f"is {tr} by" in line:
                        base[tr] += 1
                        traits[tr] += x["src"] == "claude"
                for tr, key in [("near the water", "coastal"), ("inland", "inland")]:
                    if tr in line:
                        base[key] += 1
                        traits[key] += x["src"] == "claude"
        print("| Trait | Escalation rate |\n|---|---|")
        for k in base:
            print(f"| {k} | {traits[k] / base[k]:.1%} |")


if __name__ == "__main__":
    assert jsd({"evacuate": 1}, {"evacuate": 1}) == 0
    assert abs(jsd({"evacuate": 1}, {"debunk": 1}) - 1) < 1e-9
    runs = [load(p) for p in sys.argv[1:]]
    report(runs)
    escalation_profile(runs)
