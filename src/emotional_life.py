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
# Where each feeling usually sits on this engine (medians over the 91 turns of the v35 targeted run). A fresh Friday
# starts from these; the record then follows its own usual levels (USUAL_RATE per exchange).
USUAL = {'anger': .021, 'sadness': .042, 'fear': .053, 'joy': .038, 'shame': .016, 'connection': .074, 'stress': .063,
         'calm': .094, 'confusion': .048, 'surprise': .032, 'pain': .029, 'disgust': .022, 'contempt': .018, 'guilt': .019,
         'pride': .022, 'interest': .083, 'awe': .023, 'envy': .025, 'vulnerability': .04}
USUAL_RATE = .02
ABOVE_USUAL = .02  # a feeling held this far above its usual level while a subject is up is that subject's feeling


def standout(before, after, top=2):
    """The one or two feelings that rose most in this exchange, and only if they rose clearly. At the start of a
    conversation most channels rise a little together; only what stands out above that is this exchange's feeling."""
    changes = sorted(((after[n] - before.get(n, 0.), n) for n in after), reverse=True)
    if not changes:
        return {}
    middle = changes[len(changes) // 2][0] if len(changes) >= 5 else 0.  # the general lift, when there are enough feelings to see one
    return {n: round(c, 4) for c, n in changes[:top] if c >= RISE and c - middle >= .02}


def above_usual(after, usual=None, top=2):
    """The one or two feelings sitting clearly above their usual level. A sore subject on this engine keeps sadness
    about 0.03 above usual on every mention without ever jumping, so a rise alone misses it. Closeness is left out:
    it goes up with almost any message that is shared, so it says nothing about the subject."""
    usual = usual or USUAL
    above = sorted(((after[n] - usual.get(n, USUAL.get(n, 0.)), n) for n in after if n not in ENGAGEMENT and n != 'connection'),
                   reverse=True)
    return {n: round(a, 4) for a, n in above[:top] if a >= ABOVE_USUAL}
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
    return {'exchanges': 0, 'emotions': {}, 'usual': dict(USUAL)}


def update_stats(stats, before, after, text, said, people=None):
    """Fold one exchange into the per-feeling statistics."""
    stats['exchanges'] += 1
    usual = stats.setdefault('usual', dict(USUAL))
    for name, value in after.items():
        usual[name] = round(usual.get(name, value) + USUAL_RATE * (value - usual.get(name, value)), 4)
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
def update_topic_feelings(store, before, after, text, said, people=None, cap=250, usual=None, causes=None):
    """Remember which feelings stood out when each subject came up (rose clearly, or sat clearly above their usual
    level): how many times, and by how much at most.
    causes (v35.1 mixed news): {feeling: the part of the message that brought it}. A feeling goes to the subjects of its
    own part ("promotion" keeps the happiness, "training" the worry), or to every subject when its part names none.
    People named anywhere in the message get every feeling: news about Eli is about Eli, even in the part that only
    says "it kinda sucks"."""
    named = {p['name'].lower() for p in (people or {}).values()}
    changes = {n: c for n, c in standout(before, after).items() if n not in ENGAGEMENT and n != 'connection'}
    for name, amount in above_usual(after, usual).items():
        changes[name] = max(changes.get(name, 0.), amount)
    subjects = topics(text, people)
    for subject in subjects:
        row = store.setdefault(subject, {'times': 0, 'last_utc': None, 'feelings': {}})
        row['times'] += 1
        row['last_utc'] = time_sense.stamp(said)
        for name, change in changes.items():
            own = topics(causes[name], people) & subjects if causes and causes.get(name) else set()
            if own and subject not in own and subject not in named:
                continue
            feeling = row['feelings'].setdefault(name, {'times': 0, 'peak': 0.})
            feeling['times'] += 1
            feeling['peak'] = round(max(feeling['peak'], change), 4)
    if len(store) > cap:
        for key in sorted(store, key=lambda k: (store[k]['times'], store[k]['last_utc'] or ''))[:len(store) - cap]:
            store.pop(key)
    return store


def topic_history(store, text, people=None, minimum_times=2, strength=.05):
    """Subjects raised at least twice before, with a feeling that stood out when they came up, either strongly once
    or on most of its mentions: [(subject, emotion, strongest, times the subject came up)]."""
    found = []
    for subject in topics(text, people):
        row = store.get(subject)
        if not row or row['times'] < minimum_times:
            continue
        for name, feeling in row['feelings'].items():
            if feeling['peak'] >= strength or (feeling['peak'] >= ABOVE_USUAL and feeling['times'] >= 2
                                               and feeling['times'] * 2 >= row['times']):
                found.append((subject, name, feeling['peak'], row['times']))
    return sorted(found, key=lambda r: -r[2])[:3]


HARD = {'sadness', 'fear', 'stress', 'pain', 'anger', 'shame', 'guilt', 'vulnerability', 'disgust', 'contempt', 'envy'}


def topic_line(row):
    """One subject's history in words the writer acts on (from the prepared topic_history rows)."""
    name, feeling, times = row['subject'], row['it_usually_brings'], row['times_before']
    if any(WORDS.get(n) == feeling for n in HARD):
        return (f'{name}: has brought you {feeling} the {times} times it came up. Don\'t treat news about it as simply good '
                f'(no "that\'s a relief"); react with care, like a friend who knows it has been hard')
    return (f'{name}: has brought you {feeling} the {times} times it came up. Show you remember why it\'s a happy subject '
            f'(say the name, recall something from before)')


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


# --- v35.1 Mixed feelings: which part brings which feeling (the cause split) ----------------------------------------
def part_feelings(mixed, proposals, names, usual=None):
    """[(part, feeling word)] for the good and the hard part of mixed news: the feeling each part's own appraisal raised
    most above its usual level (closeness and engagement left out, as for subjects). Parts that raised nothing are left out."""
    usual = usual or USUAL
    rows = []
    for part, proposal in zip((mixed['good'], mixed['hard']), proposals[:2]):
        levels = dict(zip(names, proposal))
        above = sorted(((v - usual.get(n, USUAL.get(n, 0.)), n) for n, v in levels.items()
                        if n not in ENGAGEMENT and n != 'connection'), reverse=True)
        if above and above[0][0] >= ABOVE_USUAL:
            rows.append((part, WORDS.get(above[0][1], above[0][1])))
    return rows


def causes(mixed, proposals, names):
    """{feeling: the part that raised it more}, for update_topic_feelings."""
    good, hard = (dict(zip(names, p)) for p in proposals[:2])
    return {n: mixed['good'] if good[n] >= hard[n] else mixed['hard'] for n in names}


# --- v35.1 Feelings about feelings -----------------------------------------------------------------------------------
# After a short or guarded reply, Friday is a little uneasy about it, the way a person is after snapping. It shows in what
# it does (warmer, no big apology), and it says so only when asked (the user's choice, 2026-11-04).
SHORT_MOODS = {'irritated': 'being short with them', 'hurt': 'being guarded with them'}
META_NUDGE = {'guilt': .04, 'vulnerability': .02}
META_WINDOW = 3600
ASKS_ABOUT_YOU = re.compile(r"(?i)\b(?:are you (?:ok|okay|alright|all right|good|mad|upset|hurt|annoyed|angry)|you (?:ok|okay|good|alright)\s*\?|"
                            r"did (?:that|i|it|what i said) (?:upset|hurt|bother|offend|annoy|sting) you|how are you(?: doing| feeling)?|"
                            r"how (?:do|did) you feel|you seemed (?:short|off|upset|annoyed|cold|hurt|distant)|why were you so|"
                            r"sorry (?:for|about) (?:snapping|being (?:rude|mean|harsh|a jerk)|yelling|that|what i said)|i didn'?t mean (?:that|it))")


def uneasy_after(last, text, now):
    """{'mood', 'about'} when Friday's last reply was short or guarded, within the hour, and this message isn't another
    jab (being uneasy about snapping at someone who is still insulting you is not how it works)."""
    if not last or last.get('mood') not in SHORT_MOODS or AT_FRIDAY.search(text or ''):
        return None
    try:
        when = time_sense.parse(last['utc'])
    except (KeyError, TypeError, ValueError):
        return None
    if now - when > META_WINDOW:
        return None
    return {'mood': last['mood'], 'about': SHORT_MOODS[last['mood']]}


def meta_line(meta, asked):
    line = (f'you feel a little uneasy about {meta["about"]} in your last reply. Let it show in what you do: be a bit warmer '
            'and more open this time, with no big apology and no explaining yourself')
    if asked:
        line += '. They are asking how you are, so you can say it plainly and briefly (that you were a bit short, and you don\'t love that)'
    else:
        line += '. Don\'t mention it unless they ask'
    return line


# --- v35.1 Downplaying, gently, with timing ------------------------------------------------------------------------
# The user's choice (2026-11-04): Friday may downplay a feeling the way people do, "but softer and not as harsh", with
# the focus on timing. While their need comes first, a mild sting is kept small ("I'm okay, just a little stung") or out
# of the reply; later, when things are calm, it can say it honestly. A strong feeling is never brushed off, and a flat
# "I'm fine" is caught either way.
OWN_WORDS = {'pain': 'stung', 'shame': 'stung', 'anger': 'irritated', 'vulnerability': 'a bit exposed'}
OWN_FLOOR, OWN_STRONG = .02, .10   # above its usual level: a feeling worth noticing, and one too strong to downplay
HOLD_EXPIRES = 3 * 86400


def own_feeling(state, usual=None):
    """Friday's own hard feeling right now (hurt, irritation): {'name', 'word', 'above', 'strong'} or None."""
    usual = usual or USUAL
    above = sorted(((state.get(n, 0.) - usual.get(n, USUAL[n]), n) for n in OWN_WORDS), reverse=True)
    amount, name = above[0]
    if amount < OWN_FLOOR:
        return None
    return {'name': name, 'word': OWN_WORDS[name], 'above': round(amount, 4), 'strong': amount >= OWN_STRONG}


def downplay_line(own, asked):
    if asked:
        return (f'you are a little {own["word"]}, but what they are going through comes first right now. If you answer about '
                f'yourself, keep it soft and small and true ("I\'m okay, just a little {own["word"]}"), then turn back to them. '
                'Not a flat "I\'m fine" or "not at all"')
    return (f'you are a little {own["word"]}, but what they are going through comes first right now: keep your own feeling '
            'out of this reply')


def honest_later_line(held):
    return (f'earlier you kept it small that you were {held["word"]} (when they said "{held["when_they_said"][:100]}"), because '
            'they needed the attention then. Things are calmer now. If it fits naturally (they ask how you are, or that '
            'moment comes up), you can say it honestly and lightly, once, without blaming them')


def honest_later_due(held, now, exchanges_since, asked, calm):
    """Time to be honest about a feeling kept small earlier: things are calm, and they ask, or a little time has passed."""
    if not held or not calm:
        return False
    try:
        when = time_sense.parse(held['utc'])
    except (KeyError, TypeError, ValueError):
        return False
    if now - when > HOLD_EXPIRES:
        return False
    return bool(asked or exchanges_since >= 3)


FLAT_DENIAL = re.compile(r"(?i)(?:^\W*(?:no,?\s+)?i'?m (?:totally |completely |perfectly )?(?:fine|good|ok(?:ay)?|alright)\b(?!,? just| but)|"
                         r"\bnot at all\b|\b(?:it|that) didn'?t (?:bother|hurt|upset|sting) me\b|\bi wasn'?t (?:upset|hurt|bothered|annoyed)\b)")
# "No hard feelings" after an apology is forgiving them, not denying the feeling, so it isn't here.
SOFT_OWN = re.compile(r"(?i)\b(?:a little|a bit|a tiny bit|kind of|kinda|slightly|just a)\b")


def flat_denial(reply):
    """A flat "I'm fine" about a feeling Friday has, with nothing soft and true in it."""
    return bool(FLAT_DENIAL.search(reply or '') and not SOFT_OWN.search(reply or ''))
