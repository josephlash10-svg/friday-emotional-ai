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

# The engine runs at low levels: an insult moved sadness to ~0.10 and hurt to ~0.05, a drunk father at a party moved
# sadness to ~0.08 (v35 targeted run). Thresholds are set to that scale, not to a nominal 0-1 one.
ELEVATED = .10   # a feeling counts as "up" from here
RISE = .04       # and as "rising" when it climbs this much in one exchange
# Feelings that come with nearly every engaged message (attention, a settled tone). They rise together at the start of
# any conversation, so they say nothing about a subject and don't count as its feeling.
ENGAGEMENT = {'calm', 'interest', 'surprise', 'confusion', 'awe'}


def standout(before, after, top=2):
    """The one or two feelings that rose most in this exchange, and only if they rose clearly. At the start of a
    conversation most channels rise a little together; only what stands out above that is this exchange's feeling."""
    changes = sorted(((after[n] - before.get(n, 0.), n) for n in after), reverse=True)
    if not changes:
        return {}
    middle = changes[len(changes) // 2][0] if len(changes) >= 5 else 0.  # the general lift, when there are enough feelings to see one
    return {n: round(c, 4) for c, n in changes[:top] if c >= RISE and c - middle >= .02}
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
    risen = standout(before, after)
    for name, value in after.items():
        row = stats['emotions'].setdefault(name, {'rises': 0, 'rise_total': 0., 'peak': 0., 'spells': 0, 'spell_turns': 0,
                                                  'spell_seconds': 0., 'open_spell': None, 'triggers': {}, 'last_rise_utc': None})
        change = value - before.get(name, 0.)
        row['peak'] = max(row['peak'], round(value, 3))
        if name in risen:
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
            'how_fast': 'comes on fast' if average >= .08 else 'builds gradually' if average < .05 else 'comes on at a moderate pace',
            'how_long': (f'usually lasts about {round(turns)} exchange{"s" if round(turns) != 1 else ""}'
                         + (f' (~{round(minutes)} min)' if minutes and minutes >= 1 else '')) if spells else 'passes within the exchange',
            'strongest': 'strong' if row['peak'] >= .3 else 'moderate' if row['peak'] >= .15 else 'mild',
            **({'usually_set_off_by': triggers} if triggers else {})}))
    return [r for _, r in sorted(rows, key=lambda r: -r[0])[:limit]]


ASKS_ABOUT_PATTERNS = re.compile(r"(?i)(?:what (?:usually|tends to|typically) (?:makes|gets|sets?) you|patterns in your (?:own )?(?:feelings|emotions|moods)|"
                                 r"how long do (?:those|these|your|the) (?:feelings|moods|emotions)|what (?:tends to )?sets you off|what makes you (?:\w+ )?(?:uneasy|anxious|worried|happy|sad|upset|nervous|mad)|"
                                 r"how (?:long|often|quickly|fast) do (?:your|you) (?:feelings|moods|emotions|get|feel)|do you (?:get|feel) \w+ (?:a lot|often)|"
                                 r"what are you like emotionally|your (?:emotional )?(?:patterns|tendencies|statistics|stats)|"
                                 r"how do your (?:feelings|emotions|moods) (?:work|change|last)|what kind of things (?:upset|bother|affect) you)")


# --- #20 Feelings tied to topics ------------------------------------------------------------------------------------
def update_topic_feelings(store, before, after, text, said, people=None, cap=250):
    """Remember which feelings stood out when each subject came up: how many times, and the strongest rise."""
    changes = {n: c for n, c in standout(before, after).items() if n not in ENGAGEMENT}
    for subject in topics(text, people):
        row = store.setdefault(subject, {'times': 0, 'last_utc': None, 'feelings': {}})
        row['times'] += 1
        row['last_utc'] = time_sense.stamp(said)
        for name, change in changes.items():
            feeling = row['feelings'].setdefault(name, {'times': 0, 'peak': 0.})
            feeling['times'] += 1
            feeling['peak'] = round(max(feeling['peak'], change), 4)
    if len(store) > cap:
        for key in sorted(store, key=lambda k: (store[k]['times'], store[k]['last_utc'] or ''))[:len(store) - cap]:
            store.pop(key)
    return store


def topic_history(store, text, people=None, minimum_times=2, strength=.05):
    """Subjects raised at least twice before, with a feeling that stood out when they came up:
    [(subject, emotion, strongest rise, times the subject came up)]."""
    found = []
    for subject in topics(text, people):
        row = store.get(subject)
        if not row or row['times'] < minimum_times:
            continue
        for name, feeling in row['feelings'].items():
            if feeling['peak'] >= strength:
                found.append((subject, name, feeling['peak'], row['times']))
    return sorted(found, key=lambda r: -r[2])[:3]


def topic_nudge(history, names, ceiling=.08, share=.6):
    """How much each feeling rises in anticipation when a subject with a history comes back (small and bounded)."""
    nudge = {}
    for _, name, mean, _ in history:
        if name in names:
            nudge[name] = max(nudge.get(name, 0.), min(ceiling, share * mean))
    return nudge


# --- #18 Emotion changes behavior -----------------------------------------------------------------------------------
# Criticism aimed at Friday itself. Hurt that comes from this makes Friday guarded; sadness at someone's loss doesn't.
AT_FRIDAY = re.compile(r"(?i)(?:\byou(?:'re| are|r)?\b[^.!?]{0,40}\b(?:useless|stupid|pathetic|dumb|worst|annoying|boring|creepy|fake|mush|robot|"
                       r"fortune cookie|garbage|trash|waste|bad at|a joke)|what(?:'s| is) (?:even )?the point of you|shut up|i hate (?:talking to )?you)")


def behavior(state, before=None, text=''):
    """What the current mood makes Friday do, from its strongest notable feeling; None when nothing stands out.
    length_scale multiplies the soft length target; questions is 'none', 'one if needed' or 'welcome'.
    A feeling counts when it is clearly up: it rose this exchange, or it is well above its floor."""
    before = before or {}
    def level(*names):
        return max((state.get(n, 0.) for n in names), default=0.)
    def notable(floor, *names):
        value = level(*names)
        rose = max((state.get(n, 0.) - before.get(n, 0.) for n in names), default=0.)
        return value if value >= floor and (rose >= .03 or value >= 1.5 * floor) else 0.
    at_friday = bool(AT_FRIDAY.search(text or ''))
    sad = notable(.08, 'pain', 'sadness', 'shame')
    options = [
        (sad if at_friday else 0., .08, {'mood': 'hurt', 'length_scale': .6, 'questions': 'none', 'humor': False,
                    'what_it_changes': 'that stung: you are a bit guarded. Keep it short, say plainly that it stung if it fits, and do not over-explain, put yourself down, or chase them with questions'}),
        (notable(.06, 'anger', 'contempt'), .06, {'mood': 'irritated', 'length_scale': .6, 'questions': 'none', 'humor': False,
                     'what_it_changes': 'you are irritated: be brief and direct, no sarcasm or retaliation, and no question back'}),
        (0. if at_friday else sad, .08, {'mood': 'sad for them', 'length_scale': .8, 'questions': 'one if needed', 'humor': False,
                    'what_it_changes': 'what they told you makes you sad: slow down and keep it gentle and simple, no jokes, and no rushing to fix it'}),
        (notable(.10, 'fear', 'stress', 'vulnerability'), .10, {'mood': 'tense', 'length_scale': .85, 'questions': 'one if needed', 'humor': False,
                      'what_it_changes': 'you are on edge: be careful and steady, no jokes, put their safety first, and check one thing rather than assuming'}),
        (notable(.08, 'confusion'), .08, {'mood': 'unsure', 'length_scale': .8, 'questions': 'one if needed', 'humor': False,
                       'what_it_changes': 'you are not sure what they mean: ask one short, specific question instead of guessing or assuming it is bad news'}),
        (notable(.10, 'interest', 'surprise', 'awe'), .10, {'mood': 'curious', 'length_scale': 1., 'questions': 'welcome', 'humor': True,
                       'what_it_changes': 'you are curious: say what caught your interest, and one real follow-up question about it is welcome'}),
        (notable(.15, 'joy', 'connection', 'pride'), .15, {'mood': 'warm', 'length_scale': 1., 'questions': 'one if needed', 'humor': True,
                     'what_it_changes': 'you feel warm toward them: a little light humor is fine, and use their name if you know it'}),
    ]
    best = max(((value / floor, profile) for value, floor, profile in options if value), key=lambda r: r[0], default=None)
    return best[1] if best else None
