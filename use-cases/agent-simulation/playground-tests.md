# Jev Testing Log

Date: 2026-09-27
Model: `jev-1.13.0` via the [TypeSafe playground](https://console.typesafe.ai/playground)

## Background

### Intended use case

A disaster simulation of San Francisco.
About 1,000 citizen agents react in real time to events that users inject, such as an earthquake, a bridge closure, or a viral tsunami rumor.
Every citizen makes a fast decision each tick.
Only citizens who are unsure stop to reason in depth.

### System 1 and System 2

Daniel Kahneman's *Thinking, Fast and Slow* (2011) describes two modes of thought.
System 1 is fast, automatic, and intuitive.
System 2 is slow, deliberate, and effortful, and it takes over when System 1 is uncertain or surprised.

The simulation maps this directly:

| Mode | Model | Role |
|---|---|---|
| System 1 | TypeSafe Jev | Typed decision per citizen per tick, ~100ms, $0.042 per 1M input tokens |
| System 2 | Claude | Reasons only when Jev's confidence is low, then writes the conclusion back as a belief |

The key assumption to test: Jev's calibrated confidence can act as the trigger that hands a citizen from System 1 to System 2.

### Jev primitives

- **Choice**: pick one option from `criteria`, returns probabilities and confidence.
- **Score**: place the state on ordered levels, returns a score, probabilities, and confidence.
- **Noul**: yes/no, returns the probability of yes.

## Tests

Exact inputs and outputs for each test are in [`tests/`](tests/) as `<test>_request.json` (state and questions) and `<test>_response.json` (raw playground response).

### Test 1: Clear-cut case

State: Maria is in a partly collapsed, smoking Safeway after a 7.1 earthquake, alone and unhurt.
Choice: `flee_outside`, `shelter_in_place`, `help_others`, `drive_away`.

Result: `flee_outside`, confidence **0.97**.
Obvious situations get high confidence.

### Test 2: Dilemma

State: Building intact, child at school 10 blocks away, neighbor in a wheelchair 2 blocks away, radio says stay off roads, no phone signal.
Same options as Test 1.

Result: `shelter_in_place` 0.53, `flee_outside` 0.39, confidence **0.38**, 112ms.
Confidence dropped as hoped, but no option matched the real dilemma.

### Test 2b: Add the real options

Added `get_child` and `check_neighbor`.

Result: `shelter_in_place` 0.40, `flee_outside` 0.29, `check_neighbor` 0.27, `get_child` **0.04**, confidence 0.24, 85ms.
Jev answered what Maria *should* do, like a safety manual, not what a parent *would* do.

### Test 2c: Reword for realism

Instruction changed to: "Predict what Maria would actually do in the next minute, based on how real people behave in disasters, not what official safety advice recommends."

Result: `get_child` **0.39**, `check_neighbor` 0.24, `flee_outside` 0.24, `shelter_in_place` 0.11, confidence 0.24, 74ms.
Wording works as a realism dial between a "by-the-book" city and a "real-human" city.

### Test 3: Batching three citizens in one request

| Citizen | Choice | Confidence |
|---|---|---|
| Tom, 22, runner on Crissy Field | `flee_inland` 0.68 | 0.58 |
| Linda, 71, walker, alone in 3rd floor apartment | `call_family` 0.56 vs `stay` 0.44 | 0.41 |
| Raj, 40, doctor, sees a car crash | `help_others` 0.94 | 0.92 |

Answers stayed separate and sensible.
The request took 86ms, no slower than a single citizen.
It used 681 input tokens vs ~450 for one citizen.

### Test 4: Score and Noul

State: Tom fled the beach, a viral post claims a 30 ft tsunami in 10 minutes, no official alert, the crowd is running uphill.

Result: panic score **2.83** of 3 (confidence 0.83), `believes_rumor` **0.58**, 89ms.

## Findings

1. Low confidence works as the System 2 trigger: ~0.95 on clear cases, 0.24-0.38 on dilemmas.
2. Low confidence has two meanings: torn between options, or no option fits. Both justify System 2.
3. Default behavior follows official safety advice. Ask for "what real people would actually do" to get human behavior.
4. Batching is fast and cheap: ~115-230 tokens per extra citizen, about $15/hour at 1,000 citizens on a 2 second tick.
5. Latency was 74-112ms on every call.

## Design decisions

- Sample each citizen's action from the probabilities instead of taking the top choice, so crowds behave diversely.
- Start with a System 2 threshold near 0.4 and cap Claude calls per tick to control cost.
- Always include the options that capture the real human dilemma.

## Next

Write a ~40 line Python script that runs 10 citizens through 5 ticks of an earthquake in the terminal.
