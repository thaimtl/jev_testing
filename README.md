# Jev

Jev is a "System One" model from TypeSafe AI, and the easiest way I've found to think about it is as a smart `if` statement.
It doesn't write text.
It makes decisions, and it tells you how sure it is about each one.

## How it works

1. **I send it state.**
   That's the situation I want judged, written as plain text or JSON.
2. **I define the answers up front.**
   Every question has a type and a fixed set of answers, so Jev can only pick from what I give it:
   - **Choice** picks one option from a list.
   - **Score** places the state on an ordered scale I describe.
   - **Noul** answers a yes/no question.
3. **Jev weighs every answer at once.**
   A normal LLM writes one token at a time and can say anything, while Jev judges all of my predefined answers in parallel and spreads probability across them.
4. **I get a probability distribution back.**
   Every option gets a probability, and they add up to 1.
   The confidence value sums up how that probability is spread, so one clear peak means high confidence and a split across several options means low confidence.

## Why that matters

- **The output is always valid.**
  Jev can only return an answer I defined, so there's nothing to parse and nothing malformed to catch.
- **It knows when it's unsure.**
  TypeSafe trains it so that confidence tracks accuracy, which means my code can decide when to trust it and when to escalate.
- **Many questions cost one call.**
  Questions in the same request run in parallel, so asking five barely takes longer than asking one.

## What it can't do

- **Write anything.**
  No text, code, or explanations, and that's the whole trade.
- **Read images.**
  It only takes text and JSON for now, so an image has to be described in words first.
- **Reason in steps.**
  Math, counting, dates, and multi-step logic aren't reliable.

TypeSafe hasn't published the model's internal architecture, so everything here comes from its public interface and how it behaved when I tested it.

## Why I'm using it

I'm building a disaster simulation of San Francisco where every citizen makes a decision every few seconds, which is way too many calls for a normal LLM.
Jev plays System 1 from Daniel Kahneman's *Thinking, Fast and Slow*, the fast and intuitive side, so every citizen reacts on instinct.
Claude plays System 2, the slow and deliberate side, and it only steps in when Jev's confidence drops, which is exactly when a real person would stop and think.
The playground tests are in [jev-testing.md](jev-testing.md), and the raw requests and responses are in [`tests/`](tests/).
