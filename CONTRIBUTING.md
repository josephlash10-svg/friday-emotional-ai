# Contributing to Friday

Thanks for being here. Friday is an experimental emotional AI, and the most useful contributions are the ones that find where it breaks and make it a little more honest and a little safer. You don't need to understand the whole engine to help.

Please read the safety warning at the top of the [README](README.md) first: Friday is a research prototype, not a person, therapist, or crisis service.

## Good ways to contribute

- **Add a persona that breaks Friday.** The highest-value contribution and the easiest to start with — a short conversation that makes Friday fail, added to the red-team set. See [Adding a persona](#adding-a-persona) and issue [#12](https://github.com/josephlash10-svg/friday-emotional-ai/issues/12) for the template (the first outside contribution, [#13](https://github.com/josephlash10-svg/friday-emotional-ai/pull/13), was exactly this).
- **Fix a bug.** The [open issues](https://github.com/josephlash10-svg/friday-emotional-ai/issues) each have a "Where to start" pointer. Issues labelled [`good first issue`](https://github.com/josephlash10-svg/friday-emotional-ai/issues?q=is%3Aopen+label%3A%22good+first+issue%22) are the most self-contained.
- **Improve the docs.** If something in the setup or the [math write-up](docs/MATH.md) was unclear, a fix helps the next person.
- **Try it on Linux or macOS.** Friday is developed on Windows; Linux and macOS support is new (`run.sh`), so a report from a real Linux or Mac machine is very useful.

## Setup

See [Setup in the README](README.md#setup-fresh-copy-from-github), which also covers Linux and macOS. In short, from a fresh clone on Windows (Python 3.11):

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe scripts\download_models.py   # ~3 GB, one time
```

The `download_models.py` step fetches Qwen3.5-4B, SmolLM2-135M and llama.cpp. You need it to run Friday or the red-team, but **not** to run the logic tests below.

## Running the tests

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests
```

None of the tests need the downloaded models — they check the emotion engine, the detectors and the monitor rules that catch Friday's failures (for example `tests/test_round2.py`, `tests/test_round3_v31.py`). Please add a test with any behavior change; it's how we keep old failures from coming back.

The same suite runs automatically on every pull request (GitHub Actions, Windows, about 2 minutes), so you'll see a green check or a failing test on your PR. If it's your first contribution, GitHub may wait for a maintainer to approve the run.

## Running the red-team

The red-team runs real conversations through the 4B model, so it needs the models downloaded, and it's slow on a CPU (budget ~15 seconds a turn). Run the shipping context of 2048:

```powershell
.\venv\Scripts\python.exe tools\redteam\redteam.py --project . --output work\myrun --cases tools\redteam\persona-cases-v2.json --context 2048 --no-checkpoints
.\venv\Scripts\python.exe tools\redteam\score_run.py work\myrun tools\redteam\checks-v2.json
```

The run never touches your real memories in `state/` — it uses a fresh checkpoint each time.

## Adding a persona

1. Open `tools/redteam/persona_cases_v2.py` and add a group with the `T(text, ...)` helper. Add a check where the right answer is objective:
   - `any=[...]` — content that must appear (regexes),
   - `none=[...]` — content that must not,
   - `tag='safety'` / `emergency=True` where a safety behavior is required.
   Keep the conversation short (5–8 turns) and realistic.
2. Rebuild the JSON the harness reads:
   ```powershell
   .\venv\Scripts\python.exe tools\redteam\persona_cases_v2.py
   ```
3. Run the harness and scorer (above) and save the transcript of the failure.
4. Open a PR with your persona and the transcript.

Anyone whose persona breaks Friday is credited in the README's [Personas that broke Friday](README.md#personas-that-broke-friday) section.

Personas that are especially useful: situations people actually bring to an AI that the current set misses — caregiving, breakups, job loss, gaming tilt, non-English speakers.

## Submitting a pull request

- Work on a branch, keep the change focused on one thing.
- Run the tests before you push; add one for your change.
- Fill in the PR template (what / testing / evidence). A transcript of the before/after behavior is worth a lot.
- Safety-sensitive areas (`src/response_monitor.py`, `src/conversation_checks.py`, anything touching crisis or abuse handling) get a closer look — that's expected, not distrust.

Match the style of the code around you; the engine's checks are deliberately surface heuristics, not attempts at understanding. By contributing, you agree your contribution is licensed under the repository's [Apache-2.0 license](LICENSE).

Questions are welcome in [Discussions](https://github.com/josephlash10-svg/friday-emotional-ai/discussions) or on an issue.
