# Coherent emotional agent experiment

> **Historical (v1–v27, 2026-10-06/07).** This describes the experience model as Codex built it. The "experiment directory" and
> "release report" it mentions are kept locally and are not in this repository. Later versions changed several of the details here
> (memory limits, recall, the writer's notes); for the current design see [`MATH.md`](MATH.md) and the version write-ups in [`README.md`](README.md).

The system maintains its own modeled reactions to conversational events, uses them in appraisal and decisions, remembers sourced experiences, and learns from ordinary corrections. Its language model expresses those reactions. A working emotional controller is not evidence of subjective consciousness, biological maturity, or human-indistinguishable conversation.

## What changes through experience

The state has 19 continuous emotion channels. Meaning is mapped to estimated effects on Friday's goals: relevance, progress, certainty, control, novelty, safety, support, effort, and responsibility. These are estimates, not physiological measurements. Current state affects processing, regulation, memory salience, and the language context. Own responsibility for a mistake supports guilt; uncertain self-evaluation is separated from responsibility rather than turning every mistake into shame.

Outcomes update expectations, perceived control, baseline, persistence, and regulation preferences at bounded, nonzero learning rates. Verbal corrections update scoped conversational lessons and interpretations. An ambiguous correction prompts clarification. User-reported outside-world facts are recorded as reports and are not automatically accepted as true. A user's revised belief remains the user's belief.

Emotional differentiation starts coarse and becomes finer with varied evidence. Repeating one topic cannot mature every domain. The candidate includes 64 disclosed simulated educational events across eight domains. Its differentiation index is an internal design variable, not a measured developmental age. This curriculum does not give Friday a fictional childhood, adult biography, or memories of meeting the user physically. There is no scientific conversion from its index to 24 years of human emotional development.

## Identity and continuity

Friday, the user's explicitly supplied profile, and the recorded relationship are separate persistent records. Aliases and relationship descriptions can be revised. Quoted names and fictional examples do not become the user's identity. Source-labelled episode retrieval favors topic relevance, with a smaller affect-salience contribution. Missing memories remain missing; a model-generated statement is not evidence that an event happened.

Time recovery is analytic and occurs before cognition. Long pauses do not cause the interpreter to act on a stale emotional state. Recovery is not evidence of continuous thought while offline. `:state` shows current recovered values; `:reflect` describes the last processed appraisal. Baseline and persistence can still change with subsequent outcomes.

## Replies and logging

The native Qwen language model receives grounded identity, relevant conversation, lessons, and qualitative affect context. Ordinary chat omits numerical diagnostics. Introspection can describe mild tension, curiosity, relief, and mixed reactions in first-person language without inventing a physical body or an unsupported cause. Numbers appear when explicitly requested.

A bounded pre-display monitor checks particular contradictions, including bodily memories, false memory incapacity, blanket emotion denial, quoted-name confusion, unsupported strong emotion, invented topic bans, and false arithmetic concessions. One repair is attempted; continued violations use a grounded fallback. These checks do not detect every hallucination or establish general factual reliability. Validated replies are buffered until reviewed, so first displayed text can take longer than the first model token.

Completed native conversation turns are saved atomically. `state/logs/chat-YYYY-MM-DD.jsonl` records inputs, displayed outputs, appraisal and actual before/after affect. `state/logs/reply-review.jsonl` records rejected drafts and repairs. Logs contain conversation text. `:trace on` enables controller details; `:trace off` returns to ordinary display. `:save` and `:quit` also save. `:reset` clears recent conversation and temporary state while retaining long-term learning.

## What was trained

The wider meaning classifier and own-event head were trained on 700 synthetic examples with 20 separately phrased held-out examples: 19/20 classification, normalized event error about 0.00574. The appraiser was trained against declared design targets. Qwen and the frozen language feature model were not fine-tuned by this run. These small synthetic scores do not measure conversational maturity.

The experiment directory preserves every source copy, checkpoint manifest, failure, raw conversation, and validation result. Classification matches are reported separately from conversation failures. Final speed, memory, restart, and adversarial results belong in the release report; earlier laptop measurements do not describe this larger candidate.
