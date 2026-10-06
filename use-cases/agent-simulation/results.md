# Experiment Results

Date: 2026-10-06
Models: `jev-1.13.0` (TypeSafe API), `claude-sonnet-5-5` (hurricane), `claude-opus-5-5` (tsunami pilot)

## Summary

- **Cost: yes.**
  The hybrid ran 1,000 agents for $0.85, while Claude alone cost $1.69 for 100 agents.
  That is 10x the agents for half the price, and 21x cheaper per agent-day.
- **Fidelity: about the same as Claude alone, and both trail the paper.**
  Against real Hurricane Dorian mobility data, Claude alone missed by 0.132 (mean absolute error on the normalized daily curve), the hybrid by 0.140, and Jev alone by 0.147 to 0.168.
  AgentSociety's own full simulator missed by 0.076, so my one-decision-per-day setup is the weaker part, not the model mix.
- **The confidence gate works as a dial.**
  Escalating more of the low-confidence decisions moves the hybrid's behavior toward Claude's, from a Jensen-Shannon divergence of 0.15 at 4% escalation to 0.02 at 32%.
- **Jev and Claude are different crowds.**
  Claude is nearly deterministic (two seeds differ by JSD 0.003) and nobody ever stays home.
  Jev spreads its answers more, which is closer to how a real population varies, but it also under-reacts to the storm.

## Main experiment: replicating AgentSociety's Hurricane Dorian study

### The paper

[AgentSociety](https://arxiv.org/abs/2502.08691) (Piao et al., 2025, Tsinghua) section 7.5 simulates 1,000 residents of Columbia, South Carolina through Hurricane Dorian (Aug 28 to Sep 5, 2019).
It checks the simulated daily trips against real SafeGraph mobility data and reports that the simulation tracks the real drop and recovery.
Agents run on DeepSeek-V3 inside a full city simulator with maps, schedules, and needs.

I picked it because it is my base paper, it is a disaster scenario like my San Francisco use case, every agent makes a typed travel decision that Jev can make, and it publishes a real-world yardstick.

### What I copied and what I simplified

Copied from the paper and its [public code](https://github.com/tsinghua-fib-lab/agentsociety/blob/main/examples/hurricane_impact/hurricane.py):

- The 1,000 census-based Columbia resident profiles from the [benchmark dataset](https://huggingface.co/datasets/tsinghua-fib-lab/hurricane-mobility-generation-benchmark), saved in [`data/columbia_profiles.json`](data/columbia_profiles.json).
- The 9-day timeline: 3 normal days, 3 days after the landfall message, 3 normal days.
- The weather messages, word for word: "Hurricane Dorian has made landfall in other cities, travel is slightly affected, and winds can be felt." and "The weather is normal and does not affect travel."

Simplified:

- Each agent makes one decision per day, picking one of five plans from stay home to several outings, instead of re-planning every 30 minutes on a map.
- There is no map, no needs model, and no social network.
- The real data is digitized from the paper's Figure 23 ([`data/agentsociety_fig23.png`](data/agentsociety_fig23.png)), accurate to about 0.01.
  The benchmark's ground-truth file is not published, so I could not use its official scorer.

Every arm gets the same persona, weather, yesterday's plan, and the same instruction: "Predict how this person would actually spend today, based on how real people behave, not what official safety advice recommends."
Jev answers a Choice question and I sample the plan from its probabilities.
In the hybrid, agents with Jev confidence below 0.4 go to Claude, which picks the plan and writes a one-sentence note that the agent remembers on later days.
Escalations are capped at 10% of agents and 100 calls per day.

Code: [`hurricane.py`](hurricane.py).
Raw per-agent decisions: `runs/hurricane-*.jsonl`.

### Normalized daily visits

Each curve is divided by its own maximum, the same way as the paper's Figure 23.

| Run | Aug 28 | Aug 29 | Aug 30 | Aug 31 | Sep 1 | Sep 2 | Sep 3 | Sep 4 | Sep 5 | MAE vs real | Drop during | Change after |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Real (SafeGraph)** | 0.94 | 0.96 | 0.90 | 0.53 | 0.45 | 0.47 | 0.92 | 1.00 | 0.91 | 0 | -48% | +1% |
| AgentSociety, DeepSeek-V3 | 1.00 | 0.94 | 0.98 | 0.34 | 0.37 | 0.32 | 0.95 | 0.95 | 0.89 | 0.076 | -65% | -4% |
| Claude only, 100, seed 1 | 0.99 | 0.99 | 1.00 | 0.80 | 0.79 | 0.78 | 0.91 | 0.95 | 0.96 | 0.132 | -20% | -5% |
| Claude only, 100, seed 2 | 0.99 | 0.99 | 1.00 | 0.82 | 0.76 | 0.76 | 0.90 | 0.93 | 0.94 | 0.133 | -21% | -7% |
| Hybrid, 100, seed 1 | 0.90 | 0.96 | 1.00 | 0.81 | 0.76 | 0.79 | 0.87 | 0.87 | 0.88 | 0.140 | -17% | -8% |
| Hybrid, 100, seed 2 | 0.92 | 0.96 | 1.00 | 0.85 | 0.77 | 0.81 | 0.90 | 0.92 | 0.96 | 0.140 | -15% | -4% |
| Jev only, 100, seed 1 | 0.91 | 0.99 | 1.00 | 0.90 | 0.78 | 0.72 | 0.84 | 0.90 | 0.95 | 0.147 | -18% | -7% |
| Jev only, 100, seed 2 | 0.90 | 0.95 | 1.00 | 0.91 | 0.89 | 0.84 | 0.90 | 0.93 | 0.98 | 0.168 | -7% | -1% |
| Hybrid, 1,000 (paper scale) | 0.92 | 0.97 | 1.00 | 0.85 | 0.80 | 0.76 | 0.86 | 0.90 | 0.93 | 0.140 | -17% | -7% |
| Jev only, 1,000 | 0.92 | 0.97 | 1.00 | 0.88 | 0.82 | 0.79 | 0.91 | 0.96 | 1.00 | 0.146 | -14% | -1% |
| Hybrid, 10,000 | 0.93 | 0.97 | 1.00 | 0.88 | 0.82 | 0.79 | 0.89 | 0.94 | 0.97 | 0.146 | -14% | -3% |

Every arm sees the storm and recovers afterwards, but none of them drops as far as real people did.
The paper's simulator overshoots the drop (-65%), and mine undershoots it (-7% to -21%).
The landfall message says travel is only "slightly affected", and a single daily plan has no way to cancel the extra errands and trips that the paper's half-hourly planner drops.

### Activity level

This is the share of agents who leave home at all.
The paper reports 70% to 90% before landfall and about 30% at landfall.

| Run | Before | Landfall (3 days) | After |
|---|---|---|---|
| Claude only, 100 | 100% | 99% to 100% | 100% |
| Hybrid, 100 | 100% | 89% to 97% | 100% |
| Jev only, 1,000 | 100% | 92% to 95% | 97% to 100% |

Claude keeps every single agent going to work through the storm.
Jev lets 5% to 10% stay home, which is the right direction but still far from the paper's 30%.

### Cost

| Run | Agent-days | Claude calls | Claude $ | Jev $ | $ per agent-day | Escalated |
|---|---|---|---|---|---|---|
| Claude only, 100 | 900 | 900 | 1.69 | 0 | 0.00188 | 100% |
| Hybrid, 100 | 900 | 33 | 0.06 | 0.02 | 0.00009 | 3.7% |
| Jev only, 100 | 900 | 0 | 0 | 0.02 | 0.00002 | 0% |
| Hybrid, 1,000 | 9,000 | 360 | 0.66 | 0.19 | 0.00009 | 4.0% |
| Hybrid, 10,000 | 90,000 | 900 | 1.65 | 1.93 | 0.00004 | 1.0% (cap hit every day) |

Costs are computed from token counts at list prices, $2 and $10 per million input and output tokens for Sonnet 5.5 and $0.042 per million input tokens for Jev.

### How close is the hybrid to Claude?

Jensen-Shannon divergence between the plan distributions, pooled over all 9 days, at 100 agents.
0 means identical and 1 means no overlap.

| Comparison | JSD |
|---|---|
| Claude seed 1 vs Claude seed 2 (noise floor) | 0.003 |
| Jev seed 1 vs Jev seed 2 (noise floor) | 0.010 |
| Claude vs Jev only | 0.17 to 0.22 |
| Claude vs hybrid, threshold 0.4, 4% escalated | 0.13 to 0.17 |
| Claude vs hybrid, threshold 0.6, 17% escalated | 0.05 |
| Claude vs hybrid, threshold 0.8, 32% escalated | 0.02 |

| Plan | Claude only | Hybrid (0.4) | Hybrid (0.8) | Jev only |
|---|---|---|---|---|
| Stay home | 0% | 1% | 1% | 1% to 4% |
| One errand | 0% | 1% | 1% | 0% |
| Work only | 73% to 76% | 32% to 34% | 62% | 25% to 31% |
| Work and one more trip | 23% to 27% | 58% to 59% | 35% | 57% to 64% |
| Several outings | 0% | 5% to 7% | 1% | 8% to 11% |

The threshold is a real dial between Jev's crowd and Claude's crowd.
At 0.8 the hybrid is nearly indistinguishable from Claude and still costs a third as much ($0.00062 per agent-day).
Turning the dial toward Claude did not improve the match to real data (MAE 0.140 at 0.4, 0.179 at 0.6, 0.148 at 0.8), because Claude is not closer to the real curve than Jev in this setup.

When Claude was called, it agreed with Jev's top pick only 35% to 44% of the time at threshold 0.4, and 72% of the time at 0.8.
So the lowest-confidence cases are exactly where the two models disagree, which is what the System 2 trigger should catch.

## Pilot: San Francisco tsunami rumor

Before switching to the paper replication, I ran my own scenario: 100 citizens on a small-world network after a 6.9 earthquake, with a viral "30 ft tsunami" post seeded on 5% of them and an official denial at tick 3.
Each tick every citizen picks one of share, debunk, check official sources, evacuate, or stay put, and says whether they believe the rumor.
Code: [`sim.py`](sim.py) and [`analyze.py`](analyze.py).
This pilot used Claude Opus 5.5, and there is no ground truth, so it only compares the models with each other.

| Run | Claude $ | Jev $ | $ per agent-tick | Believe rumor at t7 | Rumor reach at t7 | Pooled JSD vs Claude |
|---|---|---|---|---|---|---|
| Claude only, 100 | 3.98 | 0 | 0.00497 | 4% | 47% | - |
| Hybrid, 100 (8% escalated) | 0.32 to 0.33 | 0.02 | 0.00043 | 19% | 72% | 0.07 |
| Jev only, 100 | 0 | 0.02 | 0.00002 | 27% to 33% | 68% to 81% | 0.10 |
| Jev only, 1,000 | 0 | 0.20 | 0.00002 | 29% | 77% | - |
| Jev only, 10,000 | 0 | 1.97 | 0.00002 | 29% | 77% | - |

Claude citizens mostly stay put and stop sharing once the official denial lands, so the rumor stalls at 47% of the network.
Jev citizens keep 3% to 12% sharing every tick, so it keeps spreading.
The hybrid sits in between and costs 11x less than Claude alone.
Jev-only rumor dynamics are the same at 1,000 and 10,000 agents (77% reach and 29% belief at t7 for both), and 100 agents is just noisier (68% to 81%).
So on this network over 8 ticks I see no scale effect of the kind Wu and Xiao warn about.

## What this says about the hypothesis

The cost half holds.
A confidence-gated Jev and Claude society runs about 20x cheaper per agent than Claude alone, and 10x the agents for the same budget is easy.
The 1,000-agent run at paper scale cost $0.85, and the 10,000-agent run cost $3.58 and took about 12 minutes.

The fidelity half holds relative to Claude, not relative to reality.
The hybrid stays within 0.01 MAE of Claude alone on the real Dorian curve, and the threshold controls how Claude-like it is.
But both trail AgentSociety's full simulator by a wide margin, so a cheap decision model does not fix a thin environment.
The next gain comes from a richer harness (half-hourly plans, needs, a social network) rather than a different model mix.

## Caveats

- The real curve and AgentSociety's simulated curve are read off a figure, not from raw data.
- One decision per day is much simpler than the paper's mobility engine, so the comparison with the paper is about the outcome, not the mechanism.
- Two seeds per arm at 100 agents, and one seed at 1,000 and 10,000.
- The 10,000-agent hurricane hybrid hit the 100-calls-per-day cap every day, so only 1% of decisions escalated there and it behaves like Jev alone (MAE 0.146).
- The killed second Claude seed of the tsunami pilot spent up to $0.44 that is not in any run file.
- Spend is computed from token counts and list prices, not read from the billing dashboards.

## Spend

| Bucket | Claude | Jev |
|---|---|---|
| Tsunami pilot (Opus 5.5) | $4.6 to $5.1 | $2.25 |
| Hurricane replication (Sonnet 5.5) | $6.63 | $2.47 |
| **Total** | **about $11.5 of $25** | **about $4.7 of $25** |
