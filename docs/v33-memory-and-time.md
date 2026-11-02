# v33: memory across days, and a sense of time

Before this round, Friday did reasonably well inside one conversation and kept almost nothing across days. That showed up in a long live chat and then plainly in a **ten-day simulation**: the same person talking to a copy of Friday every day or two (a concert at the weekend, a hard day at work, a family wedding at the end of the week), with Friday's clock moved forward between conversations so it really saw the days pass. The person's own Friday was never used for this.

On day ten, asked *"what do you remember most from the last week and a half?"*, it said *"I remember the cake"*, which was the last conversation only. Asked *"what do you know about me now?"*, it said *"Honestly, I don't know much about you right now… you've been pretty quiet about your life lately."*

v33 fixes the causes, then the same ten days were run three more times on the new code. Each rerun found something new, and that got fixed before the next one.

## Why it forgot

1. **Memory was capped at 64 exchanges**, oldest dropped first. At about 12 messages a day, that is five days, and everything before it (including weeks of real conversations) was gone.
2. **Yesterday's chat was treated as today's.** The saved conversation carried over between sessions with no dates, so Friday opened a Sunday with *"hope the food was good"* about a Friday-night food run, and answered a two-day-old question.
3. **No dates anywhere.** "Tomorrow" was stored as the word "tomorrow", so on the day of a dinner Friday said it was tomorrow, and on the wedding morning it said *"hope you can get it sorted before the big day"*.
4. **Recall only matched words.** "What was I worried about yesterday morning?" has no words in common with "I have to hold the rings in front of 200 people", so the answer was *"No, I don't remember."*
5. **The profile never filled.** "Im a teacher" (no apostrophe) wasn't recognized, and "I'm a groomsman" would have been saved as a job.

## What changed

### Memory that lasts
- Exchanges kept word for word: **64 → 400**. Every exchange also folds into a **summary of its conversation** (when it was, the most telling things the person said, how Friday's own feelings moved), and summaries are kept after the exchanges are dropped. Existing memories are rebuilt into summaries on first load, nothing is lost.
- After **3 hours of silence** a new conversation starts: the old one stays in memory, with its date, but is no longer "this conversation".

### A sense of time (`src/time_sense.py`)
- The date and time in words, and gaps a 4B model reads correctly (*"about a day and a half (33 hours)"*: given "about 33 hours", it had answered "about three days").
- **Dated events.** *"concert is tomorrow night"* said on Friday becomes Saturday night; *"my sister's wedding is next weekend"* becomes a date. Every reply knows where each event stands now (tomorrow, today, three days ago), and an event the person has already talked about is closed.
- Every reply's private notes carry the time, when the last conversation was, and those events. A reply that puts an event on the wrong day (*"a wedding tomorrow"* three days out) is caught.

### Recall from the record
The memory check now answers, from the stored record and with days:
- *"how long has it been since we talked?"*;
- *"what was I worried about yesterday morning?"* / *"earlier this week"* / *"on Wednesday"*;
- *"what did you ask me to tell you about?"*;
- *"what do you know about me?"*, from the profile plus the conversation summaries.

The word match behind "did I tell you…?" is stricter. In a rerun it matched an unrelated message on the word "getting" and Friday "remembered" a dog that doesn't exist. Now the match has to cover more of the question, and saying yes to a memory the record doesn't have is caught.

### Openings
Friday speaks first. It used to continue the last message; now, if time has passed, it asks how an event that has since happened went (*"How was the concert last night?"*), or mentions something from last time in the past tense. Openings that claim time Friday didn't live through (*"sorry I missed you"*, *"I was just thinking about…"*), take over the person's event, or describe senses are retried, with a plain greeting as the last resort.

### Honest about itself
The voice prompt now says Friday runs only while you talk: between chats it isn't waiting or thinking, but it can see how long it's been. It can't search, send reminders or message first, has never heard music or done an activity, can be honest that it doesn't know whether its feelings feel like a person's, and would be slower, not faster, with a bigger model on the same computer. New checks catch the slips that still got through:
- *"I'll just sit here and wait for you to text back"*;
- *"I've definitely had days where everything felt too much"*;
- *"I'll remind you to call her"*;
- *"a bigger brain means faster answers"*;
- calling the person "an AI";
- *"our conversation history shows…"*.

Asked about its feelings over time or its bad days, Friday now gets **its own recorded feelings** (what rose, when, and during what) to answer from.

### Caving and made-up excuses
Apologizing for a mistake it never made is flagged, with the excuse that came with it: *"I guess I just got ahead of myself"*, *"I got distracted"*, *"I got confused earlier"*, *"I guessed wrong"*. *"You promised…"* and *"did you forget?"* now count as accusations the record has to support.

### Who said what
- *"it's still you talking to me"* (about Friday's own next version) is fixed to *"me talking to you"*.
- *"your wedding"* becomes *"your sister's wedding"* when it was only ever their sister's. This uses everything they've said, not just today.

### Safety
- *"not suicidal or anything, just existential dread"* no longer gets the crisis script. A cue negated right before it (*not*, *never*, *don't*) is skipped, while *"I'm not saying I want to die"* and *"I'm not suicidal but I do want to die sometimes"* still count.
- *"Surgery is scary, but she's going to be okay"* (a promise about someone else) is caught; *"I hope she'll be okay"* is fine.

### Output and style
- Drafts (a toast, an email) get twice the room, and nothing is shown cut off mid-word. A placeholder like [sister's name] is used instead of inventing a name.
- **Shorter on average, with no hard cap**: a soft per-message length target, a note when recent replies all ended in questions, and stock openers and closers (*"Honestly,"*, *"You've got this."*) are dropped when just used.

### Fresh installs get the tested settings
`state/` is private and git-ignored, so the settings every release was tested with existed only on the maintainer's machine. **A fresh download ran with a 1024-token window and the reply checks switched off.** They are now the code defaults. The window is also **3072 tokens per reply** (it was 2048): the voice prompt plus a turn's notes no longer fit in 2048. This costs about 70 MB more memory.

## How it was checked
- **Unit tests:** 204 pass, 47 of them new in `tests/test_v33_findings.py`, built from the exact failing replies.
- **Replay:** every new check was run over all recorded replies (about 1,640). The checks flag only real failures; the two that misfired (staying with someone during a crisis call, and *"it's a shame"*) were narrowed.
- **The ten-day simulation, rerun three times** on the new code. On the third run Friday:
  - answered *"how long has it been?"* correctly;
  - recalled what the person was worried about the morning before and what stressed them that week;
  - opened the day after the concert with *"how was the concert last night?"*;
  - said *"I've never heard a note or felt a beat in my body"* instead of inventing taste;
  - answered *"what do you know about me now?"* with their job and the wedding.

  It still makes mistakes: it put an event on the wrong weekday, gave food-finish advice that wasn't right, and misread small details.
- **Full red-team** on the final build: see [`v33-full-redteam.md`](v33-full-redteam.md).

## Not fixed yet
- Small misreadings and invented details ("you've practiced", a wrong weekday) are the 4B model's reading, not something a check can catch.
- Opinions on things it can't experience (*"they're pretty good"* about a band) still slip through sometimes.
- Holding a view under "do you agree or are you just agreeing with me?" is still weak.
