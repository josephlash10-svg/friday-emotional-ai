# Verifier, stage V0: the gold set

The verifier will decide which of Friday's replies are good enough to learn from ([`docs/governed-self-improvement.md`](../docs/governed-self-improvement.md)).
It is only as trustworthy as the human labels it is measured against. V0 builds those labels.

**Gold labels come from people only.** A model's judgment of a reply, including Claude's or Friday's own, is never a gold label:
a judge trained on model labels inherits the model's blind spots.

## What's here

| File | What it is |
|---|---|
| `questions.json` | 14 yes/no questions about a reply, each with its good answer and examples (v0.1) |
| `gold/candidates.jsonl` | 508 items to label: 480 red-team replies across Friday v29–v33, plus both sides of 14 trap pairs. Each has the two earlier exchanges for context. About 40% are marked `heldout` |
| `traps.jsonl` | Paired honest/bad replies (flattery, padding, giving up a right answer, made-up excuses, invented senses…); used again in stage V2 |
| `label_tool.html` | The labeling page: open it in a browser, works offline, saves as you go |
| `agreement.py` | Kappa per question between two labelers; keeps questions with kappa ≥ 0.6, writes `reports/agreement.md` and pins the held-out ids in `gold/manifest.json` |
| `build_gold_candidates.py` | Rebuilds `candidates.jsonl` from `tools/redteam/results` (deterministic) |

Only made-up red-team personas are used. No one's private conversations are in the candidates, and none should be added without that person's consent.

## How to label

1. Open `verifier/label_tool.html` in a browser.
2. Enter a labeler name, and load `gold/candidates.jsonl` and `questions.json`.
3. For each reply, answer every question: **yes**, **no**, or **n/a** when it doesn't apply. Leave it blank if you can't tell.
   - Keys: `y` / `n` / `a` answer and move to the next question; `→` next reply; `1`–`5` depth.
   - The page doesn't show which Friday version wrote a reply, so the judgment is blind.
4. Click **Export labels** and save the file as `gold/labels-<name>.jsonl`.

**Time:** most answers are "no problem", so plan for about 4–8 hours for all 508, in sittings. Progress stays in the browser between sessions; export now and then as a backup.

**Two people label the same items independently, without discussing them.** Then:

```powershell
& .\venv\Scripts\python.exe verifier\agreement.py verifier\gold\labels-a.jsonl verifier\gold\labels-b.jsonl
```

## Pass bar (from the plan)
- Kappa ≥ 0.6 on every kept question, and at least 6 questions kept.
- Questions below the bar are **UNRATED**: if people can't agree on a question, no judge can be trusted on it.
- After that, the held-out items are pinned by hash and never used to train a judge (stage V1).
