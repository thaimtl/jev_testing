# Agent Simulation

Can Jev and Claude together run agent societies 10x bigger for the same cost?
I think they can, because most decisions a simulated person makes are fast and obvious, and only a few need real reasoning.

## System 1 and System 2

Daniel Kahneman's *Thinking, Fast and Slow* (2011) splits thinking into two modes.
System 1 is fast, automatic, and intuitive.
System 2 is slow, deliberate, and effortful, and it takes over when System 1 is unsure.

I map that directly onto two models:

| Mode | Model | Role |
|---|---|---|
| System 1 | Jev | Every agent makes a typed decision every tick |
| System 2 | Claude | Only agents with low Jev confidence stop and reason, and the conclusion is written back as a belief |

## Research background

Agent societies are expensive, so most recent work cuts cost by removing real decisions.

- **[AgentSociety](https://arxiv.org/abs/2502.08691)** (Piao et al., 2025) simulated over 10,000 LLM agents and 5 million interactions.
  It ran experiments on hurricanes, the spread of inflammatory messages, polarization, and universal basic income.
  This is my base paper, since its hurricane and inflammatory-message experiments are close to my earthquake and tsunami rumor scenarios.
- **[APS](https://arxiv.org/abs/2605.27419)** (Zheng et al., 2026) reached 10 million agents by querying a few prototype agents and approximating everyone else from them.
  Its errors cluster in unusual, heterogeneous agents.
- **[Poor Man's Agentic Modeling](https://arxiv.org/abs/2608.11215)** (Itkin, 2026) replaces each LLM agent with a small statistical model fitted from a few thousand LLM answers, so the society runs on a laptop.
- **[Scale limits of social mechanisms](https://arxiv.org/abs/2608.22884)** (Wu and Xiao, 2026) shows that gossip, consensus, and punishment can behave differently at thousands of agents than in small groups.
  It calls testing that directly prohibitively expensive.
- **[DPT-Agent](https://arxiv.org/abs/2502.11882)** (2025) gives a single agent a System 1 and a System 2, but nobody has applied that to a whole society.

## My take

APS copies prototypes and Poor Man's swaps in a fitted formula, so in both cases most agents stop making real decisions.
I want every agent to keep a real model decision and spend expensive reasoning only where it's needed.

**Confidence-gated dual-process agents:** every agent decides with Jev, and an agent escalates to Claude only when Jev's confidence is low.

The low-confidence agents should be the same unusual agents where APS makes its errors, so Claude's attention lands where approximation breaks.

## Experiment plan

1. **Baseline.** Run a published agent-society experiment on Claude only.
   I used AgentSociety's Hurricane Dorian mobility study, because it publishes real mobility data to check against.
2. **Hybrid.** Run the same agents with Jev and Claude, then compare plan distributions with Jensen-Shannon divergence, the daily curve against real data, and cost.
3. **Scale.** Run the hybrid at 1,000 and 10,000 agents.

A tsunami rumor scenario in San Francisco served as the pilot.

## Progress

- [Playground tests](playground-tests.md): confidence works as the System 2 trigger, wording controls realism, and batching stays cheap.
  Raw requests and responses are in [`tests/`](tests/).
- [Experiment results](results.md): the hybrid runs 1,000 agents for half the cost of 100 Claude-only agents and matches Claude's fit to real Hurricane Dorian data (MAE 0.140 vs 0.132).
  Both trail AgentSociety's full simulator (0.076), so the environment, not the model mix, is now the bottleneck.

## Running it

```
pip install anthropic typesafe-sdk
export ANTHROPIC_API_KEY=... TYPESAFE_API_KEY=...
python hurricane.py run --mode hybrid --agents 100 --seed 1
python hurricane.py report runs/hurricane-*.jsonl
python sim.py --mode hybrid --agents 100 --seed 1      # tsunami pilot
python analyze.py runs/*-n100-*.jsonl
```

Runs at 1,000 agents and up are gitignored because of their size.
