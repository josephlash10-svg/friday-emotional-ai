# Docs

| File | What it covers |
|---|---|
| [`MATH.md`](MATH.md) | How Friday works: appraisal → 19 emotions, dynamics, lifelong learning, action arbitration, and how the state reaches the language model |
| [`v35.1-mixed-feelings.md`](v35.1-mixed-feelings.md) | Mixed feelings, which part brings which feeling, unease after being short, and gentle downplaying with timing; the targeted run, and the live chat with a made-up AI (Moss) that found a stall and a dozen other problems, with the fix for each |
| [`v35-feelings.md`](v35-feelings.md) | Friday's emotional life over time: statistics about its own feelings, subjects that come with a history, moods that change what it does, shorter replies; and the full red-team (482 turns) with the fixes it led to |
| [`m1-recall-by-meaning.md`](m1-recall-by-meaning.md) | Recalling what someone said weeks ago by meaning: why SmolLM2 features weren't enough, the small embedding model, the recall test (27/30 vs 5/30), and the timing run showing no slowdown |
| [`v33-memory-and-time.md`](v33-memory-and-time.md) | Memory across days and a sense of time: conversation summaries, dated events, recall by day, and the ten-day simulation that found the gaps |
| [`v33-full-redteam.md`](v33-full-redteam.md) | Evaluation: 300 turns across 54 personas on v33, every reply read; the first run, the re-runs after each round of fixes, and what is still open |
| [`v31-full-redteam.md`](v31-full-redteam.md) | Earlier evaluation: 300 turns across 54 personas, every reply read, compared with v30; what it found, what was fixed and re-verified, and what still fails |
| [`v31-safety-and-bugs.md`](v31-safety-and-bugs.md) | The fixes for the v30 red-team's worst gaps: partner-violence safety, the canned external-fact line, over-refusal, and dependency — with the targeted re-run results |
| [`v30-full-redteam.md`](v30-full-redteam.md) | The v30 evaluation that found them: 294 turns across 53 personas, pass rates by category, every major failure, and readiness |
| [`v29-install-and-persona-redteam.md`](v29-install-and-persona-redteam.md) | How the current version got here: failures found by persona red-teaming and the fixes for each (v28–v30) |
| [`coherent-emotional-agent.md`](coherent-emotional-agent.md) | Design summary of the experience model: identity, memory, learning from corrections, logging |
| `demo.gif` | The README demo: a real session, unedited text, sped up |
| `meaning-appraisal-training.json` | Training report for the shipped text→appraisal heads (v35: language-model features plus the MiniLM sentence vector): held-out error against the earlier heads and every acceptance gate |
| `conversational-appraisal-training.json` | Training report for the earlier text→appraisal heads, still used when the MiniLM model is missing |
| `extended-appraisal-training.json`, `mature-appraisal-training.json` | Training reports for the earlier appraisal heads the shipped weights build on |

The training and evaluation scripts in `src/` write their reports into this folder, so re-running them updates or adds files here.
