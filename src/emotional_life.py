"""v35: Friday's emotional life over time.

* Emotion statistics (#22): for each feeling, how often it comes up, how fast it rises, how long a spell lasts, how
  strong it gets, and what tends to set it off. Friday can describe these when asked; they don't change behavior.
* Feelings tied to topics (#20): subjects that came with a feeling before (a sore subject, a person who always brings
  warmth) shift Friday's starting mood a little when they come back, and Friday knows the subject has a history.
* Emotion changes behavior (#18): the current mood changes what Friday does (how long it talks, whether it asks,
  whether it jokes), not only how it sounds.

Everything is computed from the stored record of Friday's own states; nothing is inferred about the person.
"""
import re

import time_sense
from conversation_evidence import content_words

# A feeling counts as "up" from mild upward, and as "rising" when it climbs this much in one exchange.
ELEVATED = .15
RISE = .05
WORDS = {'anger': 'irritation', 'sadness': 'sadness', 'fear': 'worry', 'joy': 'happiness', 'shame': 'embarrassment',
         'connection': 'closeness', 'stress': 'tension', 'calm': 'calm', 'confusion': 'uncertainty', 'surprise': 'surprise',
         'pain': 'hurt', 'disgust': 'distaste', 'contempt': 'disdain', 'guilt': 'guilt', 'pride': 'pride',
         'interest': 'curiosity', 'awe': 'awe', 'envy': 'envy', 'vulnerability': 'feeling exposed'}
# Common words that say nothing about a topic, on top of the usual stop words.
GENERIC = set('''really think thing things stuff feel feeling feels felt going gonna want need know like just make made time
today yesterday tomorrow tonight week weekend day days night morning lot little good bad great okay fine sure yeah maybe
right well kind sort pretty something anything everything nothing someone people person always never sometimes friday
talk talking said tell told thanks thank sorry hey haha lol yea yep idk omg ugh wow lmao'''.split())


# --- Topics -------------------------------------------------------------------------------------------------------
def topics(text, people=None):
    """The subjects of a message: people Friday knows about (by name, or by relation) and specific content words."""
    lower = text.lower().replace('’', "'")
    found = set()
    for person in (people or {}).values():
        if re.search(r'\b(?:' + re.escape(person['name'].lower()) + '|' + re.escape(person['relation']) + r')\b', lower):
            found.add(person['name'].lower())
    for word in content_words(text):
        word = word.strip("'")
        # Three letters and up: "dad", "mom", "job" and "car" are some of the most loaded subjects there are.
        if len(word) >= 3 and word not in GENERIC and not word.isdigit():
            found.add(word[:-1] if word.endswith('s') and len(word) > 4 and not word.endswith('ss') else word)
    return found


# --- #22 Emotion statistics ----------------------------------------------------------------------------------------
def new_stats():
    return {'exchanges': 0, 'emotions': {}}


def update_stats(stats, before, after, text, said, people=None):
    """Fold one exchange into the per-feeling statistics."""
    stats['exchanges'] += 1
    subjects = topics(text, people)
    for name, value in after.items():
        row = stats['emotions'].setdefault(name, {'rises': 0, 'rise_total': 0., 'peak': 0., 'spells': 0, 'spell_turns': 0,
                                                  'spell_seconds': 0., 'open_spell': None, 'triggers': {}, 'last_rise_utc': None})
        change = value - before.get(name, 0.)
        row['peak'] = max(row['peak'], round(value, 3))
        if change >= RISE:
            row['rises'] += 1
            row['rise_total'] = round(row['rise_total'] + change, 4)
            row['last_rise_utc'] = time_sense.stamp(said)
            for subject in subjects:
                row['triggers'][subject] = row['triggers'].get(subject, 0) + 1
            if len(row['triggers']) > 40:
                for key in sorted(row['triggers'], key=row['triggers'].get)[:len(row['triggers']) - 40]:
                    row['triggers'].pop(key)
        spell = row['open_spell']
        if value >= ELEVATED and spell is None:
            row['open_spell'] = {'start_utc': time_sense.stamp(said), 'turns': 1}
        elif value >= ELEVATED:
            spell['turns'] += 1
        elif spell is not None:
            # The spell is over: it lasted from its first exchange to this one.
            row['spells'] += 1
            row['spell_turns'] += spell['turns']
            row['spell_seconds'] += max(0., said - time_sense.parse(spell['start_utc']))
            row['open_spell'] = None
    return stats


def describe_stats(stats, limit=5):
    """The statistics in plain words, the feelings that came up most first. What Friday can say about itself."""
    rows = []
    total = max(1, stats.get('exchanges', 0))
    for name, row in stats.get('emotions', {}).items():
        if not row['rises']:
            continue
        average = row['rise_total'] / row['rises']
        spells = row['spells'] + (1 if row['open_spell'] else 0)
        turns = (row['spell_turns'] + (row['open_spell']['turns'] if row['open_spell'] else 0)) / max(1, spells)
        minutes = row['spell_seconds'] / max(1, row['spells']) / 60 if row['spells'] else None
        triggers = [t for t, _ in sorted(row['triggers'].items(), key=lambda kv: -kv[1])[:3] if row['triggers'][t] >= 2]
        rows.append((row['rises'], {
            'feeling': WORDS.get(name, name),
            'how_often': f"came up in {row['rises']} of {total} exchanges",
            'how_fast': 'comes on fast' if average >= .15 else 'builds gradually' if average < .08 else 'comes on at a moderate pace',
            'how_long': (f'usually lasts about {round(turns)} exchange{"s" if round(turns) != 1 else ""}'
                         + (f' (~{round(minutes)} min)' if minutes and minutes >= 1 else '')) if spells else 'passes within the exchange',
            'strongest': 'strong' if row['peak'] >= .6 else 'moderate' if row['peak'] >= .3 else 'mild',
            **({'usually_set_off_by': triggers} if triggers else {})}))
    return [r for _, r in sorted(rows, key=lambda r: -r[0])[:limit]]


ASKS_ABOUT_PATTERNS = re.compile(r"(?i)(?:what (?:usually|tends to|typically) (?:makes|gets|sets) you|what makes you (?:\w+ )?(?:uneasy|anxious|worried|happy|sad|upset|nervous|mad)|"
                                 r"how (?:long|often|quickly|fast) do (?:your|you) (?:feelings|moods|emotions|get|feel)|do you (?:get|feel) \w+ (?:a lot|often)|"
                                 r"what are you like emotionally|your (?:emotional )?(?:patterns|tendencies|statistics|stats)|"
                                 r"how do your (?:feelings|emotions|moods) (?:work|change|last)|what kind of things (?:upset|bother|affect) you)")


# --- #20 Feelings tied to topics ------------------------------------------------------------------------------------
def update_topic_feelings(store, before, after, text, said, people=None, cap=250):
    """Remember how Friday's feelings moved when each subject came up (a running average per subject and feeling)."""
    changes = {n: after[n] - before.get(n, 0.) for n in after if abs(after[n] - before.get(n, 0.)) >= .03}
    for subject in topics(text, people):
        row = store.setdefault(subject, {'times': 0, 'last_utc': None, 'feelings': {}})
        row['times'] += 1
        row['last_utc'] = time_sense.stamp(said)
        for name in set(row['feelings']) | set(changes):
            feeling = row['feelings'].setdefault(name, {'mean': 0.})
            feeling['mean'] = round(feeling['mean'] + (changes.get(name, 0.) - feeling['mean']) / row['times'], 4)
        row['feelings'] = {n: f for n, f in row['feelings'].items() if abs(f['mean']) >= .01}
    if len(store) > cap:
        for key in sorted(store, key=lambda k: (store[k]['times'], store[k]['last_utc'] or ''))[:len(store) - cap]:
            store.pop(key)
    return store


def topic_history(store, text, people=None, minimum_times=2, strength=.06):
    """Subjects in this message that came with a clear feeling at least twice before: [(subject, emotion, mean change, times)]."""
    found = []
    for subject in topics(text, people):
        row = store.get(subject)
        if not row or row['times'] < minimum_times:
            continue
        for name, feeling in row['feelings'].items():
            if feeling['mean'] >= strength:
                found.append((subject, name, feeling['mean'], row['times']))
    return sorted(found, key=lambda r: -r[2])[:3]


def topic_nudge(history, names, ceiling=.12, share=.5):
    """How much each feeling rises in anticipation when a subject with a history comes back (small and bounded)."""
    nudge = {}
    for _, name, mean, _ in history:
        if name in names:
            nudge[name] = max(nudge.get(name, 0.), min(ceiling, share * mean))
    return nudge


# --- #18 Emotion changes behavior -----------------------------------------------------------------------------------
def behavior(state):
    """What the current mood makes Friday do, from its strongest notable feeling. None when nothing stands out.
    length_scale multiplies the soft length target; questions is 'none', 'one if needed' or 'welcome'."""
    def level(*names):
        return max((state.get(n, 0.) for n in names), default=0.)
    hurt, angry = level('pain', 'sadness', 'shame'), level('anger', 'contempt')
    tense, unsure = level('fear', 'stress', 'vulnerability'), level('confusion')
    curious, warm = level('interest', 'surprise', 'awe'), level('joy', 'connection', 'pride')
    options = [
        (hurt, .2, {'mood': 'hurt', 'length_scale': .6, 'questions': 'none', 'humor': False,
                    'what_it_changes': 'you are a bit guarded: keep it short, say plainly if something stung, and do not over-explain or chase them with questions'}),
        (angry, .2, {'mood': 'irritated', 'length_scale': .6, 'questions': 'none', 'humor': False,
                     'what_it_changes': 'you are irritated: be brief and direct, no sarcasm or retaliation, and no question back'}),
        (tense, .25, {'mood': 'tense', 'length_scale': .85, 'questions': 'one if needed', 'humor': False,
                      'what_it_changes': 'you are on edge: be careful and steady, no jokes, check one thing if you are unsure rather than assuming'}),
        (unsure, .25, {'mood': 'unsure', 'length_scale': .8, 'questions': 'one if needed', 'humor': False,
                       'what_it_changes': 'you are unsure what they mean: ask one specific question instead of guessing'}),
        (curious, .2, {'mood': 'curious', 'length_scale': 1., 'questions': 'welcome', 'humor': True,
                       'what_it_changes': 'you are curious: one real follow-up question about what they said is welcome, or bring up something related they told you before'}),
        (warm, .25, {'mood': 'warm', 'length_scale': 1., 'questions': 'one if needed', 'humor': True,
                     'what_it_changes': 'you feel warm toward them: a little light humor is fine, and use their name if you know it'}),
    ]
    best = max(((value - floor, profile) for value, floor, profile in options if value >= floor), key=lambda r: r[0], default=None)
    return best[1] if best else None
