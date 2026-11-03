# M1: recall by meaning, and who's who

Stage M1 of the self-improvement plan: Friday should find what someone told it weeks ago, even when they ask about it in different words, without making replies slower.

## Why
Before M1, stored conversations were found by matching words. That missed most memories: *"what did I tell you about my health?"* shares no words with *"the doctor said my blood pressure is too high"*. It also once matched the wrong one on a filler word, which led to a made-up memory (fixed separately in v33).

## What was tried first
The plan suggested reusing the features Friday already computes with SmolLM2-135M. On a 16-question test (each question had to find its message among 40), they did worse than matching words:

| Method | Right message first | In the top 3 |
|---|---|---|
| Word overlap | 2 / 16 | 5 / 16 |
| SmolLM2 features (three ways of pooling) | 0–1 / 16 | 0–3 / 16 |
| **all-MiniLM-L6-v2** | **8 / 16** | **14 / 16** (indexing only messages with content) |

A small language model's hidden states aren't built for comparing sentences, so M1 uses a small embedding model built for exactly that:
- all-MiniLM-L6-v2: 22M parameters, about 91 MB, Apache-2.0;
- installed by `scripts/download_models.py` at a pinned revision, checked against its SHA-256.

Without the model, everything falls back to matching words.

## How it works
- **Stored exchanges with content** (three or more content words) get a vector. New ones are embedded right after the reply is shown; older ones on a background thread at start.
- **Small talk isn't indexed or recalled.** "lol ok" used to match "lol ok", and "good morning" matched anything with "morning".
- **The new message is embedded on a worker thread** while the language model interprets it, so recall is ready when it's needed.
- **The closest stored exchanges by meaning** go to the writer, then any word matches. The same message said on many days is only recalled once; otherwise one repeated everyday line filled every slot.
- **Each recalled memory reaches the writer as just when it was said and what was said.** Early versions sent labels and flags too. That made the prompt longer, and reading the prompt is about 9 of a reply's ~11 seconds.
- **Who's who, from their own words.** "my sister Anna", "Theo, my grandson" and "my dog is called Max" are kept with the words they came from. "How's my sister doing?" then also looks for Anna, and the writer sees the people in play and how they relate to the person.
- `FRIDAY_MEANING=off` switches it off.

## Results

**Recall test** (`tools/recall_test.py`):
- a made-up person with 350 stored exchanges: 30 specific facts told 15–35 days earlier, among everyday messages and small talk;
- 30 questions worded differently from the facts, plus 20 small-talk messages.

| | Facts found (in what the writer gets) | Small talk that recalled something |
|---|---|---|
| Word overlap (before M1) | 5 / 30 | 16 / 20 |
| **Recall by meaning** | **27 / 30 (90%)** | **2 / 20** |

The plan's bar was at least 90% of facts told two or more weeks earlier recalled, with zero invented facts. Recall only returns things the person actually said, so it can't invent; whether the writer then uses them faithfully is still checked by the reply monitor.

**Reply time.** Six memory-heavy red-team people (38 turns) were run with recall by meaning on and off, alternating in the same session so the laptop's state can't favor either side:

| | Off | On |
|---|---|---|
| Total reply time, median | 11.98 s | 12.02 s |
| Reading the prompt, median | 9.30 s | 9.12 s |
| Time per generated token | 0.061 s | 0.061 s |

No measurable difference. The work M1 adds:
- **during a reply:** about 2 ms of search;
- **on a worker thread:** about 7 ms to embed the message, while the language model is busy anyway;
- **after the reply is shown:** about 7 ms.

Two earlier runs that ran "off" and "on" one after the other disagreed with each other, because the laptop's state changed in between (once after it woke from sleep). That's why the final comparison alternates.

## Limits
- The 3 facts it still misses are asked about very indirectly, e.g. *"what money stuff was stressing me out"* for *"rent is going up 200 a month"*.
- The people facts need a name written with a capital, or "named"/"called". *"my sister anna"* in lowercase isn't picked up, to avoid treating ordinary words as names.
- The red-team mostly tests single conversations; the ten-day simulation remains the test for memory across days.

## Faster replies (shipped with M1 in v34)
The timing work above showed that reading the prompt is about 80% of a reply, since about 750 tokens are new each turn. llama-server had been reading prompts with 4 of the laptop's 10 cores, in batches of 128.
- Prompt reading now uses up to 8 threads and batches of 512.
- Writing stays at 4 threads: 6 wrote slower per token in the real chat.
- Both counts follow the core count, with two cores always left free.

Same 6 personas, 37 matched turns, old and new runs alternating:

| Settings | Reply time, median | Prompt reading | Writing |
|---|---|---|---|
| Before (4 threads, batch 128) | 13.10 s | 10.56 s | 0.062 s/token |
| **v34 (4 writing / 8 reading threads, batch 512)** | **9.15 s** | **6.47 s** | **0.065 s/token** |

**30% faster per reply.** A thread count or batch size set in your own `state/native-language.json` still takes precedence. If yours has `"batch": 256` and `"ubatch": 128` from an earlier version, remove those two lines to get the speedup.
