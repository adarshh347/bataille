# Skill — Granular verification

*A meta-process skill: how to verify generated work against the volume problem.
Learned 2026-05-22, from the agent run that produced this dossier.*

## Purpose

Counteract the LLM failure mode where large volumes of generated content pass
without real verification. Replace surface approval ("looks good?") with
verification at small, specific, load-bearing units, placed *inside* the flow of
work — not bolted on at the end.

## The failure mode (named)

When a lot is generated at once — long documents, multi-file output, fan-out
across agents — verification quietly disappears. Three mechanisms:

1. **Fluency masks uncertainty.** Generated text reads as equally confident
   whether a sentence is solid or invented. The surface carries no signal about
   which claims are load-bearing guesses.
   
2. **Volume defeats review.** A human cannot truly verify a wall of text. Faced
   with 2,000 words or 18 candidates, they check the *surface* — tone, shape,
   plausibility — and wave it through. Errors ride underneath, unread.

3. **Verification is dumped at the wrong end.** Asking "does this look right?"
   *after* the structure is built pushes the whole verification burden onto the
   user, at the worst moment, at the wrong granularity.

Result: unverified content becomes load-bearing. Later work is built on top of
it. The error propagates and compounds silently.

## Why "a few surface questions" fails

- "Does this look good?" / "Any feedback?" — the user can only rubber-stamp or
  redo the work themselves. No real information passes.
- It asks about the *whole* when error lives in the *parts*.
- It asks at the *end*, when changing the framing is most expensive.
- It seeks *approval*, not *information*. A real verification question must be
  answerable *wrong* — otherwise it tests nothing.

The fix is not "more questions." It is **fewer, smaller, sharper** ones — aimed
at the right units, asked at the right time.

## The principle

**Verify small, verify specific, verify in-flow.** The unit of verification is
not the deliverable — it is the atomic decision or claim that can independently
be right or wrong. Surface those units, ranked by leverage, as diagnostic
checkpoints *while* the work is being built.

## The method

1. **Decompose into capture units.** Break the work into atoms: one factual
   claim, one interpretive move, one framing/scoping decision, one citation, one
   design choice. The atom is the thing with its own truth value.

2. **Triage — leverage × confidence.** Do not verify everything (that is just
   volume again). For each unit, score two things:
   - *Load-bearing?* Will other work be built on top of it? Does an error
     propagate downstream?
   - *Confident?* Verified against a source, or inference / judgment / memory?
   **High-leverage × low-confidence → verify now.** Everything else → tag and
   move on. This is how you reach "the right few" instead of "a vague few" or
   "an exhausting fifty."

3. **Verify framing before volume.** The single highest-leverage checkpoint is
   the *scoping / framing decision*, surfaced *before* generation fans out. One
   wrong framing silently corrupts everything downstream. Always surface the
   framing as its own checkpoint first — especially before any multi-agent or
   multi-file fan-out.

4. **Make checkpoints diagnostic, not approval-seeking.** A good checkpoint:
   - States the specific assumption or decision ("I am treating X as Y").
   - Shows the rejected alternative ("I chose A over B because C").
   - Has a *detectable wrong answer*.
   - If answered, *changes what happens next*. If the answer changes nothing,
     it is not a checkpoint — it is noise; cut it.

5. **Expose uncertainty, ranked — don't make the user hunt.** Tag claims:
   - `[verified]` — checked against a source
   - `[inferred]` — reasoned, not directly sourced
   - `[uncertain]` — extrapolated, or a judgment call
   - `[from-memory]` — from training knowledge, not the provided material
   The user verifies `[uncertain]` and `[from-memory]` first. Honest flagging is
   the *correct* behavior — e.g. an agent saying "this PDF is a scan I could not
   read, so this section is reconstructed" is good practice, not failure.

6. **Checkpoint at the seams.** Place verification at the joints where one stage
   feeds the next. Verify a stage *before* building the next stage on it.
   Verification is a sequence of small gates, not one final gate.

7. **Propagate corrections.** When the user corrects one unit, ask whether the
   correction *generalizes*. One correction should be applied everywhere it
   bears, not only at the spot it was raised.

## Concrete artifact — the verification ledger

When delivering substantial generated content, attach a short **verification
ledger** — not the content restated, but its spine:

- The 3–7 load-bearing decisions / claims, each with a confidence tag.
- For each low-confidence one: the *specific* thing for the user to confirm or
  reject, phrased so a wrong answer is detectable.

This lets the user verify the *skeleton* in a minute without reading the wall —
and tells them exactly where their attention is worth most.

## Anti-patterns

- Ending a deliverable with "let me know if you want changes."
- "Does this look right?" over a wall of text.
- Making the user the proofreader of volume the model generated.
- Surfacing questions only after the full structure is built.
- Treating silence, or a quick "ok," as verification.
- Asking many vague questions instead of few sharp ones.

## Worked example — the modern-context misfire (this project)

A sub-agent was asked to generate "modern-context candidates" mapping Bataille
onto 2026. It returned 18, fluent and plausible. The user then corrected: the
candidates over-indexed on *non-living digital objects* (datacenters, crypto,
LLMs) when Bataille's concepts — eroticism, the sacred, sacrifice, the gift —
are an *anthropology* and bite hardest on *lived human dynamics*.

Root cause: a single **framing decision** — "modern context = digital systems /
2026 technology" — was never verified. It was baked into the agent's prompt and
silently propagated into all 18 candidates. The wall of plausible output hid the
error; it surfaced only after delivery, at cost ~18 instead of ~1.

What the method prescribes: before launching that agent, surface one framing
checkpoint —

> "The agent will map Bataille onto these object classes: AI infrastructure,
> crypto, climate, the attention economy. Is the object class right — or should
> it be *lived human dynamics* (intimacy, desire, grief, status, the hunt for
> intensity), with the digital present as backdrop, not subject?"

A diagnostic question, asked before the volume, catches it for free.

## When to apply

Any substantial generation — long documents, multi-file output, fan-out /
multi-agent work — and *especially* when one early decision (framing, scope, a
source, a definition) will propagate. The bigger the fan-out, the earlier and
harder the framing checkpoint.

## One-line operational checklist

- **Before generating:** what is the framing — and is it verified?
- **While generating:** what are the load-bearing, low-confidence units?
- **When delivering:** attach the ledger; ask the few diagnostic questions;
  never close with "looks good?"
