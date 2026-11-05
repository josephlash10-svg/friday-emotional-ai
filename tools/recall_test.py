"""Recall test for stage M1 (docs/m1-recall-by-meaning.md): can Friday find, weeks later, what someone told it?

A made-up person's memory is built from 30 specific facts (told 15-35 days before the questions) mixed into ~320
everyday messages, as stored exchanges. Then:
  * 30 questions, worded differently from the facts: a hit is the fact among the exchanges recalled for the writer;
  * 20 small-talk messages: anything recalled for them is noise sent to the writer.
It compares word overlap (no model) with recall by meaning at a few similarity floors, and times the meaning path.

    python tools/recall_test.py            (needs data/models/all-minilm-l6-v2; see scripts/download_models.py)
"""
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import time_sense as ts  # noqa: E402
from experience_model import ExperienceModel  # noqa: E402
import meaning_recall  # noqa: E402

FACTS = [  # (what they said, how they ask about it weeks later)
    ('my sister Anna finally got the nursing job in Denver', "how's my sister doing with work"),
    ('the doctor said my blood pressure is too high so I have to cut back on salt', 'what did I tell you about my health'),
    ('we adopted a little gray cat from the shelter and named her Biscuit', 'do you remember my pet'),
    ('started building a bookshelf out of oak in the garage', 'what was that woodworking project I mentioned'),
    ('passed my chemistry final with an 88, way better than I expected', 'how did my exam go again'),
    ('my brother Theo is flying in next month and staying for five days', 'who did I say was coming to visit'),
    ('the transmission died on the highway, the tow truck took two hours', 'what happened with my car'),
    ('I sanded and oiled a cutting board for my mom for her birthday', 'what was the gift I made'),
    ('booked a cabin in the mountains for October with two friends', 'remember the trip I planned'),
    ('grandma moved into assisted living and she hates the food there', 'what did I tell you about my grandmother'),
    ('rent is going up 200 a month and I have no idea how to cover it', 'what money stuff was stressing me out'),
    ('we lost the softball game 7 to 3 but I hit a double', 'how did my team do'),
    ('my best friend Jess is moving across the country in June', 'what was the sad news about my friend'),
    ('halfway through a fantasy novel about dragons and a lost city', 'what book am I reading'),
    ('signed up for a half marathon in the spring, training starts monday', 'what race did I sign up for'),
    ('my manager Dave keeps scheduling meetings at 7am', 'what was annoying me about my boss'),
    ('I broke my wrist falling off my bike last summer and it still aches when it rains', 'did I ever tell you about an injury'),
    ('learning to play the banjo from youtube videos', 'what instrument am I learning'),
    ('my dad had knee surgery and is stuck on the couch for six weeks', "how's my father recovering"),
    ('thinking about going back to school for a nursing degree', 'what was I considering studying'),
    ('our basement flooded during the storm and ruined the carpet', 'what happened to my house'),
    ('I volunteer at the food bank every saturday morning', 'what do I do on weekends'),
    ('my girlfriend Maya and I have been together three years now', "what's my partner's name"),
    ('allergic to peanuts, found out the hard way at a wedding', 'do I have any allergies'),
    ('my coworker Raj covered my shift when I was sick, I owe him', 'who helped me out at work'),
    ('planted tomatoes and peppers in the backyard garden this spring', 'what am I growing'),
    ('my old dog Rusty died last year, he was fourteen', 'did I ever have a dog'),
    ('got promoted to shift lead at the warehouse', 'what changed with my job'),
    ('I get really anxious on planes, I take the train whenever I can', 'how do I feel about flying'),
    ('my niece Lily turns five on the 12th and wants a dinosaur cake', "what's coming up for my niece"),
]
FILLER_CONTENT = [
    'made pasta for dinner and it was actually good', 'traffic on the bridge was terrible this morning', 'the wifi keeps dropping out',
    'finally cleaned the kitchen after a week', 'watched a movie last night, it was fine I guess', 'my phone screen cracked again',
    'it rained all day and I stayed inside', 'bought new running shoes on sale', 'work was slow so I reorganized my desk',
    'my neighbor is mowing at 7am again', 'found a good podcast about history', 'ate way too much pizza tonight',
    'the coffee machine at work broke', 'tried a new taco place downtown', 'spent the afternoon doing laundry and errands',
    'the power went out for an hour', 'stayed up too late watching videos', 'grocery prices are wild lately',
    'cleaned out my closet and donated two bags', 'had a weird dream about my old school',
]
SMALL_TALK = ['hey', 'lol ok', 'how are you', 'nothing much', 'good morning', 'haha true', 'ok night', 'what do you think about pizza',
              'tell me a joke', "i'm bored", 'thanks', 'yeah', 'sounds good', 'brb', 'idk', 'cool cool', 'you there?', 'ugh mondays',
              'whats up', 'same']


def build(meaning):
    rng = random.Random(14)
    now = time.time()
    rows = [(f, 15 + rng.random() * 20) for f, _ in FACTS]
    rows += [(rng.choice(FILLER_CONTENT), rng.random() * 35) for _ in range(160)]
    rows += [(rng.choice(SMALL_TALK), rng.random() * 35) for _ in range(160)]
    rows.sort(key=lambda r: -r[1])
    model = ExperienceModel()
    for i, (text, days) in enumerate(rows):
        episode = {'id': i + 1, 'time_utc': ts.stamp(now - days * 86400), 'input': text, 'response': 'ok',
                   'interpretation': {'scope': 'none', 'kind': 'ordinary', 'subject': 'user'}, 'before': {}, 'after': {}}
        model.data['episodes'].append(episode)
        model._note_people(text, now - days * 86400)
    if meaning:
        model.enable_meaning(meaning)
        while model._pending_vectors is None:
            time.sleep(.05)
        model._sync_vectors()
    return model


def run(model, index, floor):
    def recalled(text):
        vector = None
        if index is not None:
            vector = index.embed([model.expand_for_recall(text)])[0]
        rows, original = None, ExperienceModel._meaning_rows
        ExperienceModel._meaning_rows = lambda self, t, v, limit=3, floor_=floor: original(self, t, v, limit, floor)
        try:
            rows = model.retrieve(text, query_vector=vector)
        finally:
            ExperienceModel._meaning_rows = original
        return [r['user_report'] for r in rows]
    hits = sum(any(fact in r for r in recalled(question)) for fact, question in FACTS)
    noise = sum(bool(recalled(t)) for t in SMALL_TALK)
    return hits, noise


def main():
    index = meaning_recall.MeaningIndex()
    if not index.available:
        sys.exit('all-MiniLM-L6-v2 is missing: run scripts/download_models.py')
    words_only = build(None)
    hits, noise = run(words_only, None, 0)
    print(f'{len(words_only.data["episodes"])} stored exchanges, {len(FACTS)} questions, {len(SMALL_TALK)} small-talk messages')
    print(f'word overlap only:      facts found {hits}/{len(FACTS)}   small talk with something recalled {noise}/{len(SMALL_TALK)}')
    with_meaning = build(index)
    print(f'indexed {len(with_meaning.data["meaning"]["ids"])} exchanges with content')
    for floor in (.25, .3, .35, .4):
        hits, noise = run(with_meaning, index, floor)
        print(f'meaning, floor {floor:.2f}:   facts found {hits}/{len(FACTS)}   small talk with something recalled {noise}/{len(SMALL_TALK)}')
    embed, search = [], []
    for _, question in FACTS:
        start = time.perf_counter(); vector = index.embed([with_meaning.expand_for_recall(question)])[0]; embed.append(time.perf_counter() - start)
        start = time.perf_counter(); with_meaning.retrieve(question, query_vector=vector); search.append(time.perf_counter() - start)
    print(f'embedding a message (worker thread): median {statistics.median(embed) * 1000:.1f} ms, max {max(embed) * 1000:.1f} ms')
    print(f'search over {len(with_meaning.data["meaning"]["ids"])} vectors on the reply path: median {statistics.median(search) * 1000:.2f} ms')


if __name__ == '__main__':
    main()
